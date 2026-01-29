"""AiCliManagerのテスト。"""

from src.config.settings import AICli


class TestAiCliManager:
    """AiCliManagerのテスト。"""

    def test_get_available_clis(self, ai_cli_manager):
        """利用可能なCLI一覧を取得できることをテスト。"""
        clis = ai_cli_manager.get_available_clis()
        # 結果はリストであること
        assert isinstance(clis, list)

    def test_get_default_cli(self, ai_cli_manager):
        """デフォルトCLIを取得できることをテスト。"""
        default = ai_cli_manager.get_default_cli()
        assert default == AICli.CLAUDE

    def test_get_command(self, ai_cli_manager):
        """CLIコマンドを取得できることをテスト。"""
        cmd = ai_cli_manager.get_command(AICli.CLAUDE)
        assert cmd == "claude"

        cmd = ai_cli_manager.get_command(AICli.CODEX)
        assert cmd == "codex"

        cmd = ai_cli_manager.get_command(AICli.GEMINI)
        assert cmd == "gemini"

    def test_set_command(self, ai_cli_manager):
        """CLIコマンドを設定できることをテスト。"""
        ai_cli_manager.set_command(AICli.CLAUDE, "/custom/path/claude")
        assert ai_cli_manager.get_command(AICli.CLAUDE) == "/custom/path/claude"

    def test_get_cli_info(self, ai_cli_manager):
        """CLI情報を取得できることをテスト。"""
        info = ai_cli_manager.get_cli_info(AICli.CLAUDE)
        assert info["cli"] == "claude"
        assert info["command"] == "claude"
        assert "available" in info
        assert info["is_default"] is True

    def test_get_all_cli_info(self, ai_cli_manager):
        """全CLI情報を取得できることをテスト。"""
        all_info = ai_cli_manager.get_all_cli_info()
        assert len(all_info) == 3  # claude, codex, gemini

    def test_refresh_availability(self, ai_cli_manager):
        """利用可能性を再検出できることをテスト。"""
        result = ai_cli_manager.refresh_availability()
        assert isinstance(result, dict)
        # 全CLIについて結果があること
        for cli in AICli:
            assert cli in result
