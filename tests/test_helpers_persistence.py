"""helpers_persistence.py のユニットテスト。"""

import json
import time
from unittest.mock import patch

from src.models.agent import Agent, AgentRole, AgentStatus
from src.tools.helpers_persistence import (
    delete_agents_file,
    load_agents_from_file,
    reset_sync_cache,
    save_agent_to_file,
    sync_agents_from_file,
)


class TestDeleteAgentsFile:
    """delete_agents_file のテスト。"""

    def test_deletes_existing_file(self, app_ctx, temp_dir, settings):
        """T11: 正常にファイル削除されること。"""
        # agents.json を作成
        session_dir = temp_dir / settings.mcp_dir / "test-session"
        session_dir.mkdir(parents=True, exist_ok=True)
        agents_file = session_dir / "agents.json"
        agents_file.write_text(json.dumps({"agent-001": {"id": "agent-001"}}))

        app_ctx.project_root = str(temp_dir)
        app_ctx.session_id = "test-session"

        with patch(
            "src.tools.helpers_persistence.resolve_main_repo_root",
            return_value=str(temp_dir),
        ):
            result = delete_agents_file(app_ctx)

        assert result is True
        assert not agents_file.exists()

    def test_returns_false_when_not_exists(self, app_ctx, temp_dir):
        """T12: ファイル未存在で False が返ること。"""
        app_ctx.project_root = str(temp_dir)
        app_ctx.session_id = "nonexistent-session"

        with patch(
            "src.tools.helpers_persistence.resolve_main_repo_root",
            return_value=str(temp_dir),
        ):
            result = delete_agents_file(app_ctx)

        assert result is False


class TestSaveAndSyncAgentsFile:
    """save_agent_to_file / sync_agents_from_file のテスト。"""

    def test_save_agent_to_file_writes_snapshot_without_existing_read(
        self, app_ctx, temp_dir, settings, monkeypatch
    ):
        """AppContext スナップショットから agents.json を再構築できること。"""
        now = app_ctx.agents["agent-001"].created_at
        new_agent = Agent(
            id="agent-003",
            role=AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="agent-003",
            working_dir=str(temp_dir),
            created_at=now,
            last_activity=now,
        )
        app_ctx.agents[new_agent.id] = new_agent
        app_ctx.project_root = str(temp_dir)
        app_ctx.session_id = "test-session"

        def _unexpected_json_load(*_args, **_kwargs):
            raise AssertionError("save_agent_to_file should not read agents.json")

        monkeypatch.setattr("src.tools.helpers_persistence.json.load", _unexpected_json_load)
        with patch(
            "src.tools.helpers_persistence.resolve_main_repo_root",
            return_value=str(temp_dir),
        ):
            assert save_agent_to_file(app_ctx, new_agent) is True

        agents_file = temp_dir / settings.mcp_dir / "test-session" / "agents.json"
        payload = json.loads(agents_file.read_text(encoding="utf-8"))
        assert set(payload) >= {"agent-001", "agent-002", "agent-003"}
        assert payload["agent-003"]["status"] == AgentStatus.BUSY.value

    def test_load_agents_from_file_reads_saved_agents(self, app_ctx, temp_dir):
        """保存済みの agents.json を読み戻せること。"""
        app_ctx.project_root = str(temp_dir)
        app_ctx.session_id = "test-session"
        agent = app_ctx.agents["agent-001"]

        with patch(
            "src.tools.helpers_persistence.resolve_main_repo_root",
            return_value=str(temp_dir),
        ):
            assert save_agent_to_file(app_ctx, agent) is True
            loaded = load_agents_from_file(app_ctx)

        assert loaded["agent-001"].id == "agent-001"
        assert loaded["agent-002"].id == "agent-002"

    def test_sync_agents_from_file_invalidates_ttl_when_file_changes(
        self, app_ctx, temp_dir, settings
    ):
        """TTL 内でも mtime 変化時は再同期すること。"""
        reset_sync_cache()
        app_ctx.project_root = str(temp_dir)
        app_ctx.session_id = "test-session"
        agent = app_ctx.agents["agent-001"]

        with patch(
            "src.tools.helpers_persistence.resolve_main_repo_root",
            return_value=str(temp_dir),
        ):
            assert save_agent_to_file(app_ctx, agent) is True
            assert sync_agents_from_file(app_ctx) == 0

            agents_file = temp_dir / settings.mcp_dir / "test-session" / "agents.json"
            payload = json.loads(agents_file.read_text(encoding="utf-8"))
            payload["agent-002"]["status"] = AgentStatus.BUSY.value
            time.sleep(0.001)
            agents_file.write_text(json.dumps(payload), encoding="utf-8")

            synced = sync_agents_from_file(app_ctx)

        assert synced >= 1
        assert app_ctx.agents["agent-002"].status == AgentStatus.BUSY

    def test_returns_false_when_no_project_root(self, app_ctx):
        """project_root 未設定で False が返ること。"""
        app_ctx.project_root = None

        with patch(
            "src.tools.helpers_persistence.get_project_root_from_config",
            return_value=None,
        ):
            result = delete_agents_file(app_ctx)

        assert result is False
