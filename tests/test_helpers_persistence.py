"""helpers_persistence.py のユニットテスト。"""

import json
from unittest.mock import patch

from src.tools.helpers_persistence import delete_agents_file


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

    def test_returns_false_when_no_project_root(self, app_ctx):
        """project_root 未設定で False が返ること。"""
        app_ctx.project_root = None

        with patch(
            "src.tools.helpers_persistence.get_project_root_from_config",
            return_value=None,
        ):
            result = delete_agents_file(app_ctx)

        assert result is False
