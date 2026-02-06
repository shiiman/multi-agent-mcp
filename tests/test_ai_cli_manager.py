"""AiCliManagerのテスト。"""

from unittest.mock import AsyncMock, patch

import pytest

from src.config.settings import AICli, ModelDefaults, TerminalApp, resolve_model_for_cli


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


class TestBuildStdinCommand:
    """build_stdin_command のテスト。"""

    def test_build_stdin_command_claude(self, ai_cli_manager):
        """Claude Code のコマンドが正しく構築されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CLAUDE, "/tmp/task.md", "/path/to/worktree"
        )
        assert "claude" in cmd
        assert "--dangerously-skip-permissions" in cmd
        # Claude CLI は --directory オプションがないため、cd で移動する
        assert "cd" in cmd
        assert "/path/to/worktree" in cmd
        assert "/tmp/task.md" in cmd

    def test_build_stdin_command_codex(self, ai_cli_manager):
        """Codex のコマンドが正しく構築されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CODEX, "/tmp/task.md", "/path/to/worktree"
        )
        assert "codex exec" in cmd
        assert " - < /tmp/task.md" in cmd
        # 全 CLI で cd && command 形式
        assert "cd" in cmd
        assert "/path/to/worktree" in cmd
        assert "/tmp/task.md" in cmd

    def test_build_stdin_command_gemini(self, ai_cli_manager):
        """Gemini のコマンドが正しく構築されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.GEMINI, "/tmp/task.md", "/path/to/worktree"
        )
        assert "gemini" in cmd
        assert "--yolo" in cmd
        # 全 CLI で cd && command 形式
        assert "cd" in cmd
        assert "/path/to/worktree" in cmd
        assert "/tmp/task.md" in cmd

    def test_build_stdin_command_claude_without_worktree(self, ai_cli_manager):
        """worktree なしで Claude Code コマンドが構築されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(AICli.CLAUDE, "/tmp/task.md")
        assert "claude" in cmd
        assert "--dangerously-skip-permissions" in cmd
        # worktree なしの場合は cd も含まれない
        assert "cd" not in cmd

    def test_build_stdin_command_codex_without_worktree(self, ai_cli_manager):
        """worktree なしで Codex コマンドが構築されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(AICli.CODEX, "/tmp/task.md")
        assert "codex exec" in cmd
        assert " - < /tmp/task.md" in cmd
        # worktree なしの場合は cd も含まれない
        assert "cd" not in cmd

    def test_build_stdin_command_gemini_without_worktree(self, ai_cli_manager):
        """worktree なしで Gemini コマンドが構築されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(AICli.GEMINI, "/tmp/task.md")
        assert "gemini" in cmd
        assert "--yolo" in cmd
        # worktree なしの場合は cd も含まれない
        assert "cd" not in cmd


class TestBuildStdinCommandWithModel:
    """build_stdin_command のモデル指定テスト。"""

    def test_build_stdin_command_codex_with_model(self, ai_cli_manager):
        """Codex で --model フラグが含まれることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CODEX, "/tmp/task.md", "/path/to/worktree",
            model="gpt-5.3-codex",
        )
        assert "--model" in cmd
        assert "gpt-5.3-codex" in cmd
        assert "codex exec" in cmd

    def test_build_stdin_command_gemini_with_model(self, ai_cli_manager):
        """Gemini で --model フラグが含まれることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.GEMINI, "/tmp/task.md", "/path/to/worktree",
            model="gemini-3-pro",
        )
        assert "--model" in cmd
        assert "gemini-3-pro" in cmd
        assert "--yolo" in cmd

    def test_build_stdin_command_codex_claude_alias_resolved(self, ai_cli_manager):
        """Codex で Claude 固有モデル名が CLI デフォルトに解決されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CODEX, "/tmp/task.md", "/path/to/worktree",
            model="opus", role="admin",
        )
        assert "--model" in cmd
        assert ModelDefaults.CODEX_DEFAULT in cmd

    def test_build_stdin_command_gemini_claude_alias_resolved(self, ai_cli_manager):
        """Gemini で Claude 固有モデル名が CLI デフォルトに解決されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.GEMINI, "/tmp/task.md", "/path/to/worktree",
            model="sonnet", role="worker",
        )
        assert "--model" in cmd
        assert ModelDefaults.GEMINI_LIGHT in cmd

    def test_build_stdin_command_claude_model_passthrough(self, ai_cli_manager):
        """Claude で model がそのまま渡されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CLAUDE, "/tmp/task.md", "/path/to/worktree",
            model="opus",
        )
        assert "--model" in cmd
        assert "opus" in cmd

    def test_build_stdin_command_no_model(self, ai_cli_manager):
        """model=None の場合 --model が含まれないことをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CODEX, "/tmp/task.md", "/path/to/worktree",
        )
        assert "--model" not in cmd


class TestResolveModelForCli:
    """resolve_model_for_cli() のテスト。"""

    def test_claude_passthrough(self):
        """Claude は変換なしでそのまま返すことをテスト。"""
        assert resolve_model_for_cli("claude", "opus", "admin") == "opus"
        assert resolve_model_for_cli("claude", "sonnet", "worker") == "sonnet"

    def test_codex_fallback_admin(self):
        """Codex で opus → gpt-5.3-codex に解決されることをテスト。"""
        result = resolve_model_for_cli("codex", "opus", "admin")
        assert result == ModelDefaults.CODEX_DEFAULT

    def test_codex_fallback_worker(self):
        """Codex で sonnet → gpt-5.3-codex に解決されることをテスト。"""
        result = resolve_model_for_cli("codex", "sonnet", "worker")
        assert result == ModelDefaults.CODEX_DEFAULT

    def test_gemini_fallback_admin(self):
        """Gemini で opus → gemini-3-pro に解決されることをテスト。"""
        result = resolve_model_for_cli("gemini", "opus", "admin")
        assert result == ModelDefaults.GEMINI_DEFAULT

    def test_gemini_fallback_worker(self):
        """Gemini で sonnet → gemini-3-flash に解決されることをテスト。"""
        result = resolve_model_for_cli("gemini", "sonnet", "worker")
        assert result == ModelDefaults.GEMINI_LIGHT

    def test_explicit_model_not_converted(self):
        """明示指定されたモデル名は変換されないことをテスト。"""
        assert resolve_model_for_cli("codex", "gpt-5.3-codex", "worker") == "gpt-5.3-codex"
        assert resolve_model_for_cli("gemini", "gemini-3-pro", "admin") == "gemini-3-pro"

    def test_none_model_returns_none(self):
        """model=None の場合 None を返すことをテスト。"""
        assert resolve_model_for_cli("claude", None) is None
        assert resolve_model_for_cli("codex", None) is None
        assert resolve_model_for_cli("gemini", None) is None

    def test_custom_cli_defaults_override(self):
        """cli_defaults を渡すとハードコード値を上書きできることをテスト。"""
        custom = {
            "codex": {"admin": "custom-codex-model", "worker": "custom-codex-worker"},
        }
        result = resolve_model_for_cli("codex", "opus", "admin", cli_defaults=custom)
        assert result == "custom-codex-model"

        result = resolve_model_for_cli("codex", "sonnet", "worker", cli_defaults=custom)
        assert result == "custom-codex-worker"


class TestBuildStdinCommandWithThinkingTokens:
    """build_stdin_command の thinking_tokens テスト。"""

    def test_thinking_tokens_included_in_claude(self, ai_cli_manager):
        """Claude で MAX_THINKING_TOKENS が環境変数に含まれることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CLAUDE, "/tmp/task.md", "/path/to/worktree",
            thinking_tokens=4000,
        )
        assert "MAX_THINKING_TOKENS=4000" in cmd

    def test_thinking_tokens_zero_included_in_claude(self, ai_cli_manager):
        """Claude で thinking_tokens=0 でも明示的に設定されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CLAUDE, "/tmp/task.md", "/path/to/worktree",
            thinking_tokens=0,
        )
        assert "MAX_THINKING_TOKENS=0" in cmd

    def test_thinking_tokens_excluded_from_codex(self, ai_cli_manager):
        """Codex では MAX_THINKING_TOKENS が設定されないことをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CODEX, "/tmp/task.md", "/path/to/worktree",
            thinking_tokens=1000,
        )
        assert "MAX_THINKING_TOKENS" not in cmd

    def test_thinking_tokens_excluded_from_gemini(self, ai_cli_manager):
        """Gemini では MAX_THINKING_TOKENS が設定されないことをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.GEMINI, "/tmp/task.md", "/path/to/worktree",
            thinking_tokens=2000,
        )
        assert "MAX_THINKING_TOKENS" not in cmd

    def test_thinking_tokens_none_excluded(self, ai_cli_manager):
        """thinking_tokens=None の場合 MAX_THINKING_TOKENS が含まれないことをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CLAUDE, "/tmp/task.md", "/path/to/worktree",
            thinking_tokens=None,
        )
        assert "MAX_THINKING_TOKENS" not in cmd

    def test_thinking_tokens_with_project_root(self, ai_cli_manager):
        """thinking_tokens と project_root が両方含まれることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CLAUDE, "/tmp/task.md", "/path/to/worktree",
            project_root="/project",
            thinking_tokens=4000,
        )
        assert "MCP_PROJECT_ROOT" in cmd
        assert "MAX_THINKING_TOKENS=4000" in cmd
        assert "export MCP_PROJECT_ROOT" in cmd
        assert "export MAX_THINKING_TOKENS" in cmd

    def test_thinking_tokens_direct_value(self, ai_cli_manager):
        """プロファイル設定の直接値が正しく渡されることをテスト。"""
        thinking_tokens = 2000
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CLAUDE, "/tmp/task.md", "/path/to/worktree",
            thinking_tokens=thinking_tokens,
        )
        assert "MAX_THINKING_TOKENS=2000" in cmd


class TestAiCliManagerTerminal:
    """ターミナル起動機能のテスト。"""

    @pytest.mark.asyncio
    async def test_detect_terminal_ghostty(self, ai_cli_manager):
        """Ghostty が検出されることをテスト。"""
        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = True
            terminal = await ai_cli_manager._detect_terminal()
            assert terminal == TerminalApp.GHOSTTY

    @pytest.mark.asyncio
    async def test_detect_terminal_iterm2(self, ai_cli_manager):
        """iTerm2 が検出されることをテスト。"""
        with patch("pathlib.Path.exists") as mock_exists:
            def exists_side_effect(self=None):
                # Ghostty がない場合、iTerm2 を返す
                path = str(mock_exists.call_args)
                return "iTerm" in path

            mock_exists.side_effect = lambda: False
            # 最初の呼び出し（Ghostty）は False、2番目（iTerm）は True
            mock_exists.side_effect = [False, True]
            terminal = await ai_cli_manager._detect_terminal()
            assert terminal == TerminalApp.ITERM2

    @pytest.mark.asyncio
    async def test_detect_terminal_fallback(self, ai_cli_manager):
        """Terminal.app にフォールバックすることをテスト。"""
        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = False
            terminal = await ai_cli_manager._detect_terminal()
            assert terminal == TerminalApp.TERMINAL

    @pytest.mark.asyncio
    async def test_open_in_ghostty_success(self, ai_cli_manager):
        """Ghostty でターミナルを開くことをテスト。"""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_proc

            success, message = await ai_cli_manager._open_in_ghostty(
                "/tmp/test", "claude"
            )
            assert success is True
            assert "Ghostty" in message

    @pytest.mark.asyncio
    async def test_open_in_ghostty_failure(self, ai_cli_manager):
        """Ghostty 起動失敗をテスト。"""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))
            mock_exec.return_value = mock_proc

            success, message = await ai_cli_manager._open_in_ghostty(
                "/tmp/test", "claude"
            )
            assert success is False
            assert "失敗" in message

    @pytest.mark.asyncio
    async def test_open_in_iterm2_success(self, ai_cli_manager):
        """iTerm2 でターミナルを開くことをテスト。"""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_proc

            success, message = await ai_cli_manager._open_in_iterm2(
                "/tmp/test", "claude"
            )
            assert success is True
            assert "iTerm2" in message

    @pytest.mark.asyncio
    async def test_open_in_terminal_app_success(self, ai_cli_manager):
        """Terminal.app でターミナルを開くことをテスト。"""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_proc

            success, message = await ai_cli_manager._open_in_terminal_app(
                "/tmp/test", "claude"
            )
            assert success is True
            assert "Terminal.app" in message

    @pytest.mark.asyncio
    async def test_open_worktree_in_terminal_cli_not_available(self, ai_cli_manager):
        """CLI が利用できない場合のテスト。"""
        # 全 CLI を利用不可に
        ai_cli_manager._available_clis = {cli: False for cli in AICli}

        success, message = await ai_cli_manager.open_worktree_in_terminal(
            "/tmp/test", AICli.CLAUDE
        )
        assert success is False
        assert "利用できません" in message

    @pytest.mark.asyncio
    async def test_open_worktree_in_terminal_with_ghostty(self, ai_cli_manager):
        """Ghostty でターミナルを開くことをテスト。"""
        ai_cli_manager._available_clis[AICli.CLAUDE] = True

        with patch.object(
            ai_cli_manager, "_open_in_ghostty", new_callable=AsyncMock
        ) as mock_open:
            mock_open.return_value = (True, "success")

            success, message = await ai_cli_manager.open_worktree_in_terminal(
                "/tmp/test", AICli.CLAUDE, terminal=TerminalApp.GHOSTTY
            )
            assert success is True
            mock_open.assert_called_once()
