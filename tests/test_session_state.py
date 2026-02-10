"""session_state.py のユニットテスト。"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.workspace import WorktreeInfo
from src.tools.session_state import (
    _clear_config_session_id,
    _reset_app_context,
    cleanup_session_resources,
    detect_stale_sessions,
)

# cleanup_session_resources 内で resolve_main_repo_root が呼ばれるのをモック
_RESOLVE_PATCH = "src.tools.helpers_persistence.resolve_main_repo_root"
_HEALTHCHECK_PATCH = "src.managers.healthcheck_daemon.stop_healthcheck_daemon"


class TestResetAppContext:
    """_reset_app_context のテスト。"""

    def test_clears_agents(self, app_ctx):
        """T1: agents dict がクリアされること。"""
        assert len(app_ctx.agents) > 0
        _reset_app_context(app_ctx)
        assert len(app_ctx.agents) == 0

    def test_clears_admin_poll_state(self, app_ctx):
        """T2: _admin_poll_state がクリアされること。"""
        app_ctx._admin_poll_state["admin-001"] = {
            "waiting_for_ipc": True,
            "allow_dashboard_until": None,
            "last_poll_blocked_at": None,
        }
        _reset_app_context(app_ctx)
        assert len(app_ctx._admin_poll_state) == 0

    def test_clears_admin_last_healthcheck(self, app_ctx):
        """T3: _admin_last_healthcheck_at がクリアされること。"""
        app_ctx._admin_last_healthcheck_at["admin-001"] = datetime.now()
        _reset_app_context(app_ctx)
        assert len(app_ctx._admin_last_healthcheck_at) == 0

    def test_clears_owner_wait_state(self, app_ctx):
        """Owner 待機ロック状態がクリアされること。"""
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": datetime.now(),
            "unlocked_at": None,
            "unlock_reason": None,
        }
        _reset_app_context(app_ctx)
        assert len(app_ctx._owner_wait_state) == 0


class TestClearConfigSessionId:
    """_clear_config_session_id のテスト。"""

    def test_clears_session_id(self, app_ctx, temp_dir, settings):
        """config.json の session_id をクリアする。"""
        mcp_dir = temp_dir / settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        config_file = mcp_dir / "config.json"
        config_file.write_text(json.dumps({
            "mcp_tool_prefix": "mcp__multi-agent-mcp__",
            "session_id": "test-session",
        }))
        app_ctx.project_root = str(temp_dir)

        result = _clear_config_session_id(app_ctx)
        assert result is True

        with open(config_file) as f:
            config = json.load(f)
        assert "session_id" not in config
        assert config["mcp_tool_prefix"] == "mcp__multi-agent-mcp__"

    def test_returns_false_when_no_project_root(self, app_ctx):
        """project_root 未設定で False を返す。"""
        app_ctx.project_root = None
        result = _clear_config_session_id(app_ctx)
        assert result is False

    def test_returns_false_when_no_config_file(self, app_ctx, temp_dir):
        """config.json 未存在で False を返す。"""
        app_ctx.project_root = str(temp_dir)
        result = _clear_config_session_id(app_ctx)
        assert result is False

    def test_returns_false_when_no_session_id_in_config(
        self, app_ctx, temp_dir, settings
    ):
        """config.json に session_id がない場合 False を返す。"""
        mcp_dir = temp_dir / settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        config_file = mcp_dir / "config.json"
        config_file.write_text(json.dumps({
            "mcp_tool_prefix": "mcp__multi-agent-mcp__",
        }))
        app_ctx.project_root = str(temp_dir)

        result = _clear_config_session_id(app_ctx)
        assert result is False


class TestCleanupSessionResources:
    """cleanup_session_resources のテスト。"""

    @pytest.mark.asyncio
    async def test_calls_ipc_cleanup(self, app_ctx, temp_dir):
        """T4: IPC の cleanup() が呼ばれること。"""
        mock_ipc = MagicMock()
        mock_ipc.cleanup = MagicMock()
        app_ctx.ipc_manager = mock_ipc
        app_ctx.project_root = str(temp_dir)

        with patch(
            _HEALTHCHECK_PATCH, new_callable=AsyncMock,
        ), patch(_RESOLVE_PATCH, return_value=str(temp_dir)):
            results = await cleanup_session_resources(app_ctx)

        # _reset_app_context で ipc_manager は None になるが、
        # 保持していた mock_ipc 経由で呼び出しを確認
        mock_ipc.cleanup.assert_called_once()
        assert results["ipc_cleaned"] is True

    @pytest.mark.asyncio
    async def test_calls_dashboard_cleanup(self, app_ctx, temp_dir):
        """T5: Dashboard の cleanup() が呼ばれること。"""
        mock_dashboard = MagicMock()
        mock_dashboard.cleanup = MagicMock()
        app_ctx.dashboard_manager = mock_dashboard
        app_ctx.project_root = str(temp_dir)

        with patch(
            _HEALTHCHECK_PATCH, new_callable=AsyncMock,
        ), patch(_RESOLVE_PATCH, return_value=str(temp_dir)):
            results = await cleanup_session_resources(app_ctx)

        mock_dashboard.cleanup.assert_called_once()
        assert results["dashboard_cleaned"] is True

    @pytest.mark.asyncio
    async def test_deletes_agents_file(self, app_ctx, temp_dir):
        """T6: agents.json が削除されること。"""
        with patch(
            _HEALTHCHECK_PATCH, new_callable=AsyncMock,
        ), patch(
            "src.tools.helpers_persistence.delete_agents_file",
            return_value=True,
        ) as mock_delete:
            results = await cleanup_session_resources(app_ctx)

        mock_delete.assert_called_once_with(app_ctx)
        assert results["agents_file_deleted"] is True

    @pytest.mark.asyncio
    async def test_clears_config_session_id(self, app_ctx, temp_dir, settings):
        """T7: config.json の session_id がクリアされること。"""
        mcp_dir = temp_dir / settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        config_file = mcp_dir / "config.json"
        config_file.write_text(json.dumps({
            "mcp_tool_prefix": "mcp__multi-agent-mcp__",
            "session_id": "test-session",
        }))
        app_ctx.project_root = str(temp_dir)

        with patch(
            _HEALTHCHECK_PATCH, new_callable=AsyncMock,
        ), patch(_RESOLVE_PATCH, return_value=str(temp_dir)):
            results = await cleanup_session_resources(app_ctx)

        assert results["config_session_cleared"] is True
        with open(config_file) as f:
            config = json.load(f)
        assert "session_id" not in config

    @pytest.mark.asyncio
    async def test_removes_orphan_provisional_dirs(self, app_ctx, temp_dir, settings):
        """cleanup 時に provisional-* 残骸が一括削除されることをテスト。"""
        mcp_dir = temp_dir / settings.mcp_dir
        provisional_a = mcp_dir / "provisional-abcd1234"
        provisional_b = mcp_dir / "provisional-efgh5678"
        provisional_a.mkdir(parents=True, exist_ok=True)
        provisional_b.mkdir(parents=True, exist_ok=True)
        (provisional_a / "agents.json").write_text("{}", encoding="utf-8")
        (provisional_b / "agents.json").write_text("{}", encoding="utf-8")
        app_ctx.project_root = str(temp_dir)
        app_ctx.session_id = "provisional-abcd1234"

        with patch(
            _HEALTHCHECK_PATCH, new_callable=AsyncMock,
        ), patch(_RESOLVE_PATCH, return_value=str(temp_dir)):
            results = await cleanup_session_resources(app_ctx)

        assert results["provisional_cleanup"]["removed_count"] == 2
        assert sorted(results["provisional_cleanup"]["removed_dirs"]) == [
            "provisional-abcd1234",
            "provisional-efgh5678",
        ]
        assert not provisional_a.exists()
        assert not provisional_b.exists()

    @pytest.mark.asyncio
    async def test_removes_registry(self, app_ctx, temp_dir):
        """T8: グローバルレジストリが削除されること。"""
        app_ctx.project_root = str(temp_dir)

        with patch(
            _HEALTHCHECK_PATCH, new_callable=AsyncMock,
        ), patch(
            # cleanup_session_resources は src.tools.helpers から import する
            "src.tools.helpers.remove_agents_by_owner",
            return_value=3,
        ) as mock_remove, patch(
            _RESOLVE_PATCH, return_value=str(temp_dir),
        ):
            results = await cleanup_session_resources(app_ctx)

        mock_remove.assert_called_once()
        assert results["registry_removed"] == 3

    @pytest.mark.asyncio
    async def test_resets_app_context(self, app_ctx, temp_dir):
        """cleanup 後に app_ctx のインメモリ状態がリセットされること。"""
        assert app_ctx.session_id is not None
        app_ctx.project_root = str(temp_dir)

        with patch(
            _HEALTHCHECK_PATCH, new_callable=AsyncMock,
        ), patch(_RESOLVE_PATCH, return_value=str(temp_dir)):
            await cleanup_session_resources(app_ctx)

        assert app_ctx.session_id is None
        assert app_ctx.project_root is None
        assert len(app_ctx.agents) == 0

    @pytest.mark.asyncio
    async def test_removes_dot_worktrees_path(self, app_ctx, temp_dir):
        """`.worktrees/` 配下の worktree が削除対象になることをテスト。"""
        repo_path = temp_dir / "repo"
        repo_path.mkdir(parents=True, exist_ok=True)
        app_ctx.project_root = str(repo_path)
        app_ctx.agents["agent-002"].worktree_path = str(
            repo_path / ".worktrees" / "feature/add-worker-task"
        )
        app_ctx.agents["agent-002"].branch = "feature/add-worker-task"

        mock_worktree_manager = MagicMock()
        mock_worktree_manager.list_worktrees = AsyncMock(
            return_value=[
                WorktreeInfo(
                    path=str(repo_path),
                    branch="main",
                    commit="aaa111",
                    is_bare=False,
                    is_detached=False,
                    locked=False,
                    prunable=False,
                ),
                WorktreeInfo(
                    path=str(repo_path / ".worktrees" / "feature/add-worker-task"),
                    branch="feature/add-worker-task",
                    commit="bbb222",
                    is_bare=False,
                    is_detached=False,
                    locked=False,
                    prunable=False,
                ),
            ]
        )
        mock_worktree_manager.remove_worktree = AsyncMock(
            return_value=(True, "removed")
        )

        with patch(
            _HEALTHCHECK_PATCH, new_callable=AsyncMock
        ), patch(
            "src.tools.helpers.get_worktree_manager",
            return_value=mock_worktree_manager,
        ), patch(
            _RESOLVE_PATCH, return_value=str(repo_path)
        ):
            results = await cleanup_session_resources(
                app_ctx,
                remove_worktrees=True,
                repo_path=str(repo_path),
            )

        assert results["removed_worktrees"] == 1
        mock_worktree_manager.remove_worktree.assert_awaited_once()


class TestDetectStaleSessions:
    """detect_stale_sessions のテスト。"""

    def test_finds_old_data(self, temp_dir, settings):
        """T14: 古い agents.json があるディレクトリを検出すること。"""
        mcp_dir = temp_dir / settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)

        # 古いセッションデータを作成
        old_session = mcp_dir / "old-session-001"
        old_session.mkdir()
        (old_session / "agents.json").write_text("{}")

        another_session = mcp_dir / "old-session-002"
        another_session.mkdir()
        (another_session / "agents.json").write_text("{}")

        # agents.json がないディレクトリ（正常にクリーンアップ済み）
        clean_session = mcp_dir / "clean-session"
        clean_session.mkdir()

        stale = detect_stale_sessions(str(temp_dir))
        assert len(stale) == 2
        assert "old-session-001" in stale
        assert "old-session-002" in stale
        # クリーンなセッションは含まれない
        assert "clean-session" not in stale

    def test_empty_when_clean(self, temp_dir, settings):
        """T15: クリーンな状態で空リストが返ること。"""
        mcp_dir = temp_dir / settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)

        stale = detect_stale_sessions(str(temp_dir))
        assert stale == []

    def test_empty_when_no_mcp_dir(self, temp_dir):
        """MCP ディレクトリが存在しない場合に空リストが返ること。"""
        stale = detect_stale_sessions(str(temp_dir))
        assert stale == []
