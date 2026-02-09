"""server.py ライフサイクルのテスト（異常終了シナリオ）。"""

import json

from src.server import _save_shutdown_state


class TestSaveShutdownState:
    """_save_shutdown_state のテスト。"""

    def test_saves_state_on_shutdown(self, app_ctx, temp_dir, settings):
        """T16: シャットダウン時に状態がファイルに保存されること。"""
        mcp_dir = temp_dir / settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        app_ctx.project_root = str(temp_dir)

        result = _save_shutdown_state(app_ctx)
        assert result is True

        shutdown_file = mcp_dir / "shutdown_state.json"
        assert shutdown_file.exists()

        with open(shutdown_file) as f:
            state = json.load(f)

        assert state["session_id"] == app_ctx.session_id
        assert state["agent_count"] == len(app_ctx.agents)
        assert isinstance(state["agent_ids"], list)

    def test_returns_false_when_no_project_root(self, app_ctx):
        """project_root が未設定の場合 False を返すこと。"""
        app_ctx.project_root = None
        result = _save_shutdown_state(app_ctx)
        assert result is False

    def test_returns_false_when_no_mcp_dir(self, app_ctx, temp_dir):
        """MCP ディレクトリが存在しない場合 False を返すこと。"""
        app_ctx.project_root = str(temp_dir)
        # MCP ディレクトリを作成しない
        result = _save_shutdown_state(app_ctx)
        assert result is False

    def test_saves_correct_agent_ids(self, app_ctx, temp_dir, settings):
        """保存されたエージェントIDが正しいこと。"""
        mcp_dir = temp_dir / settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        app_ctx.project_root = str(temp_dir)

        result = _save_shutdown_state(app_ctx)
        assert result is True

        shutdown_file = mcp_dir / "shutdown_state.json"
        with open(shutdown_file) as f:
            state = json.load(f)

        expected_ids = sorted(app_ctx.agents.keys())
        assert sorted(state["agent_ids"]) == expected_ids
