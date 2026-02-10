"""server.py ライフサイクルのテスト（異常終了シナリオ）。"""

from src.server import _save_shutdown_state


class TestSaveShutdownState:
    """_save_shutdown_state のテスト。"""

    def test_does_not_create_shutdown_state_file(self, app_ctx, temp_dir, settings):
        """T16: shutdown_state.json が新規生成されないこと。"""
        mcp_dir = temp_dir / settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        app_ctx.project_root = str(temp_dir)

        result = _save_shutdown_state(app_ctx)
        assert result is False

        shutdown_file = mcp_dir / "shutdown_state.json"
        assert not shutdown_file.exists()

    def test_returns_false_when_no_project_root(self, app_ctx):
        """project_root が未設定の場合 False を返すこと。"""
        app_ctx.project_root = None
        result = _save_shutdown_state(app_ctx)
        assert result is False

    def test_returns_false_when_mcp_dir_exists(self, app_ctx, temp_dir, settings):
        """MCP ディレクトリが存在しても False を返すこと。"""
        mcp_dir = temp_dir / settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        app_ctx.project_root = str(temp_dir)
        result = _save_shutdown_state(app_ctx)
        assert result is False
