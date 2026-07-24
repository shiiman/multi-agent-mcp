"""AiCliManagerのテスト。"""

from unittest.mock import patch

import pytest

from src.config.settings import AICli, ModelDefaults, resolve_model_for_cli


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
        assert default == ai_cli_manager.settings.get_active_profile_cli()

    def test_get_command(self, ai_cli_manager):
        """CLIコマンドを取得できることをテスト。"""
        cmd = ai_cli_manager.get_command(AICli.CLAUDE)
        assert cmd == "claude"

        cmd = ai_cli_manager.get_command(AICli.CODEX)
        assert cmd == "codex"

        cmd = ai_cli_manager.get_command(AICli.AGY)
        assert cmd == "agy"

        cmd = ai_cli_manager.get_command(AICli.CURSOR)
        assert cmd == "agent"

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
        assert info["is_default"] == (ai_cli_manager.get_default_cli() == AICli.CLAUDE)

    def test_get_all_cli_info(self, ai_cli_manager):
        """全CLI情報を取得できることをテスト。"""
        all_info = ai_cli_manager.get_all_cli_info()
        assert len(all_info) == 4  # claude, codex, agy, cursor

    def test_refresh_availability(self, ai_cli_manager):
        """利用可能性を再検出できることをテスト。"""
        result = ai_cli_manager.refresh_availability()
        assert isinstance(result, dict)
        # 全CLIについて結果があること
        for cli in AICli:
            assert cli in result

    def test_refresh_availability_cursor_fallback(self, ai_cli_manager):
        """Cursor は agent 未検出時に cursor-agent へフォールバックできることをテスト。"""
        with patch("src.managers.ai_cli_manager.shutil.which") as mock_which:
            mock_which.side_effect = lambda command: (
                None
                if command == "agent"
                else "/usr/local/bin/cursor-agent" if command == "cursor-agent" else None
            )
            result = ai_cli_manager.refresh_availability()

        assert result[AICli.CURSOR] is True


class TestBuildStdinCommand:
    """build_stdin_command のテスト。"""

    def test_build_stdin_command_claude(self, ai_cli_manager):
        """Claude Code のコマンドが正しく構築されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CLAUDE, "/tmp/task.md", "/path/to/worktree"
        )
        assert "claude" in cmd
        assert "--dangerously-skip-permissions" in cmd
        assert "--prompt" not in cmd
        # Claude CLI は --directory オプションがないため、cd で移動する
        assert "cd" in cmd
        assert "/path/to/worktree" in cmd
        assert "/tmp/task.md" in cmd
        assert "あなたの役割は" in cmd
        assert "< /tmp/task.md" not in cmd

    def test_build_stdin_command_codex(self, ai_cli_manager):
        """Codex のコマンドが正しく構築されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CODEX,
            "/tmp/task.md",
            "/path/to/worktree",
            role_template_path="/repo/templates/roles/admin.md",
        )
        assert "codex " in cmd
        assert "codex exec" not in cmd
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd
        assert "--message" not in cmd
        # 全 CLI で cd && command 形式
        assert "cd" in cmd
        assert "/path/to/worktree" in cmd
        assert "/tmp/task.md" in cmd
        assert "/repo/templates/roles/admin.md" in cmd
        assert "$(cat " not in cmd

    def test_build_stdin_command_agy(self, ai_cli_manager):
        """agy のコマンドが正しく構築されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.AGY, "/tmp/task.md", "/path/to/worktree"
        )
        assert "agy" in cmd
        assert "--dangerously-skip-permissions" in cmd
        assert "--prompt-interactive" in cmd
        assert "--yolo" not in cmd
        # 全 CLI で cd && command 形式
        assert "cd" in cmd
        assert "/path/to/worktree" in cmd
        assert "/tmp/task.md" in cmd
        assert "< /tmp/task.md" not in cmd

    def test_build_stdin_command_agy_effort_mapping(self, ai_cli_manager):
        """agy の effort が low/medium/high 透過・xhigh→high・none→省略になること。"""
        low = ai_cli_manager.build_stdin_command(
            AICli.AGY, "/tmp/task.md", reasoning_effort="low"
        )
        assert "--effort low" in low

        medium = ai_cli_manager.build_stdin_command(
            AICli.AGY, "/tmp/task.md", reasoning_effort="medium"
        )
        assert "--effort medium" in medium

        high = ai_cli_manager.build_stdin_command(
            AICli.AGY, "/tmp/task.md", reasoning_effort="high"
        )
        assert "--effort high" in high

        xhigh = ai_cli_manager.build_stdin_command(
            AICli.AGY, "/tmp/task.md", reasoning_effort="xhigh"
        )
        assert "--effort high" in xhigh  # xhigh は high に丸める

        none = ai_cli_manager.build_stdin_command(
            AICli.AGY, "/tmp/task.md", reasoning_effort="none"
        )
        assert "--effort" not in none

    def test_build_stdin_command_cursor(self, ai_cli_manager):
        """Cursor は print モードを使わず通常起動コマンドを構築することをテスト。"""
        with patch("src.managers.ai_cli_manager.shutil.which") as mock_which:
            mock_which.side_effect = lambda command: (
                "/usr/local/bin/agent" if command == "agent" else None
            )
            cmd = ai_cli_manager.build_stdin_command(
                AICli.CURSOR, "/tmp/task.md", "/path/to/worktree"
            )

        assert "agent " in cmd
        assert "cursor-agent" not in cmd
        assert "--model" not in cmd
        assert "--prompt" not in cmd
        assert "--print" not in cmd
        assert "--force" in cmd
        assert "/tmp/task.md" in cmd

    def test_build_stdin_command_cursor_with_model_and_fallback(self, ai_cli_manager):
        """Cursor は model 指定時のみ --model を付与し、必要ならコマンドをフォールバックする。"""
        with patch("src.managers.ai_cli_manager.shutil.which") as mock_which:
            mock_which.side_effect = lambda command: (
                None
                if command == "agent"
                else "/usr/local/bin/cursor-agent" if command == "cursor-agent" else None
            )
            cmd = ai_cli_manager.build_stdin_command(
                AICli.CURSOR, "/tmp/task.md", "/path/to/worktree",
                model="opus",
            )

        assert "cursor-agent " in cmd
        assert "--model" in cmd
        assert ModelDefaults.CURSOR_DEFAULT in cmd
        assert "--force" in cmd
        assert "--print" not in cmd

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
        assert "codex " in cmd
        assert "codex exec" not in cmd
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd
        assert "--message" not in cmd
        # worktree なしの場合は cd も含まれない
        assert "cd" not in cmd

    def test_build_stdin_command_agy_without_worktree(self, ai_cli_manager):
        """worktree なしで agy コマンドが構築されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(AICli.AGY, "/tmp/task.md")
        assert "agy" in cmd
        assert "--dangerously-skip-permissions" in cmd
        # worktree なしの場合は cd も含まれない
        assert "cd" not in cmd

    def test_build_stdin_command_claude_ignores_reasoning_effort(self, ai_cli_manager):
        """Claude では reasoning_effort を渡しても CLI オプションに含めない。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CLAUDE,
            "/tmp/task.md",
            "/path/to/worktree",
            reasoning_effort="high",
        )
        assert "--effort" not in cmd
        assert "--reasoning-effort" not in cmd

    def test_build_stdin_command_codex_uses_reasoning_effort(self, ai_cli_manager):
        """Codex では reasoning_effort を -c reasoning.effort 形式で付与する。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CODEX,
            "/tmp/task.md",
            "/path/to/worktree",
            reasoning_effort="xhigh",
        )
        assert "-c 'reasoning.effort=\"xhigh\"'" in cmd


class TestBuildStdinCommandWithModel:
    """build_stdin_command のモデル指定テスト。"""

    def test_build_stdin_command_codex_with_model(self, ai_cli_manager):
        """Codex で --model フラグが含まれることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CODEX, "/tmp/task.md", "/path/to/worktree",
            model="gpt-5.4",
        )
        assert "--model" in cmd
        assert "gpt-5.4" in cmd
        assert "codex exec" not in cmd
        assert "--message" not in cmd

    def test_build_stdin_command_agy_with_model(self, ai_cli_manager):
        """agy で --model フラグが含まれることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.AGY, "/tmp/task.md", "/path/to/worktree",
            model="gemini-3-pro",
        )
        assert "--model" in cmd
        assert "gemini-3-pro" in cmd
        assert "--yolo" not in cmd

    def test_build_stdin_command_codex_claude_alias_resolved(self, ai_cli_manager):
        """Codex で Claude 固有モデル名が CLI デフォルトに解決されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CODEX, "/tmp/task.md", "/path/to/worktree",
            model="opus", role="admin",
        )
        assert "--model" in cmd
        assert ModelDefaults.CODEX_DEFAULT in cmd

    def test_build_stdin_command_agy_model_passthrough_no_validation(self, ai_cli_manager):
        """agy はモデル互換性を検証せず、指定モデルをそのまま渡すことをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.AGY, "/tmp/task.md", "/path/to/worktree",
            model="sonnet", role="worker",
        )
        assert "--model" in cmd
        assert "sonnet" in cmd

    def test_build_stdin_command_claude_model_passthrough(self, ai_cli_manager):
        """Claude で model がそのまま渡されることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CLAUDE, "/tmp/task.md", "/path/to/worktree",
            model="opus",
        )
        assert "--model" in cmd
        assert "opus" in cmd

    def test_build_stdin_command_no_model(self, ai_cli_manager):
        """model=None の場合 CLI デフォルトモデルが使われることをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CODEX, "/tmp/task.md", "/path/to/worktree",
        )
        assert "--model" in cmd
        assert ModelDefaults.CODEX_DEFAULT in cmd

    def test_build_stdin_command_codex_no_exec_even_for_large_task_path(
        self, ai_cli_manager, tmp_path
    ):
        """Codex は常に対話コマンドを使い、exec にフォールバックしないことをテスト。"""
        task_file = tmp_path / "large.md"
        task_file.write_text("A" * 20000, encoding="utf-8")
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CODEX, str(task_file), "/path/to/worktree"
        )
        assert "codex exec" not in cmd
        assert "--message" not in cmd
        assert str(task_file) in cmd


class TestResolveModelForCli:
    """resolve_model_for_cli() のテスト。"""

    def test_claude_passthrough(self):
        """Claude は変換なしでそのまま返すことをテスト。"""
        assert resolve_model_for_cli("claude", "opus", "admin") == "opus"
        assert resolve_model_for_cli("claude", "sonnet", "worker") == "sonnet"

    def test_codex_fallback_admin(self):
        """Codex で opus → Codex デフォルトモデルに解決されることをテスト。"""
        result = resolve_model_for_cli("codex", "opus", "admin")
        assert result == ModelDefaults.CODEX_DEFAULT

    def test_codex_fallback_worker(self):
        """Codex で sonnet → Codex デフォルトモデルに解決されることをテスト。"""
        result = resolve_model_for_cli("codex", "sonnet", "worker")
        assert result == ModelDefaults.CODEX_DEFAULT

    def test_agy_model_passthrough_admin(self):
        """agy はモデル互換性を検証せず opus をそのまま返すことをテスト。"""
        result = resolve_model_for_cli("agy", "opus", "admin")
        assert result == "opus"

    def test_agy_model_passthrough_worker(self):
        """agy はモデル互換性を検証せず sonnet をそのまま返すことをテスト。"""
        result = resolve_model_for_cli("agy", "sonnet", "worker")
        assert result == "sonnet"

    def test_explicit_model_not_converted(self):
        """明示指定されたモデル名は変換されないことをテスト。"""
        assert resolve_model_for_cli("codex", "gpt-5.4", "worker") == "gpt-5.4"
        assert resolve_model_for_cli("gemini", "gemini-3-pro", "admin") == "gemini-3-pro"
        assert resolve_model_for_cli("claude", "claude-opus-4-6", "admin") == "claude-opus-4-6"
        assert resolve_model_for_cli("cursor", "composer-1.5", "worker") == "composer-1.5"

    def test_cursor_legacy_model_fallback_to_default(self):
        """Cursor 旧モデル ID は非互換としてデフォルトへフォールバックすることをテスト。"""
        result = resolve_model_for_cli("cursor", "composer1.5", "worker")
        assert result == ModelDefaults.CURSOR_DEFAULT

    def test_explicit_model_mismatch_converted_to_cli_default(self):
        """CLI とモデルが不一致なら CLI デフォルトへ置換される（agy は無検証）ことをテスト。"""
        assert (
            resolve_model_for_cli("codex", "gemini-3-pro", "admin")
            == ModelDefaults.CODEX_DEFAULT
        )
        assert resolve_model_for_cli("agy", "gpt-5.4", "worker") == "gpt-5.4"
        assert resolve_model_for_cli("claude", "gemini-3-pro", "worker") == ModelDefaults.SONNET

    def test_none_model_returns_none(self):
        """model=None の場合 CLI デフォルトを返すことをテスト。"""
        assert resolve_model_for_cli("claude", None) == ModelDefaults.SONNET
        assert resolve_model_for_cli("codex", None) == ModelDefaults.CODEX_DEFAULT
        assert resolve_model_for_cli("agy", None) == ModelDefaults.AGY_LIGHT

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

    def test_thinking_tokens_excluded_from_agy(self, ai_cli_manager):
        """agy では MAX_THINKING_TOKENS が設定されないことをテスト。"""
        cmd = ai_cli_manager.build_stdin_command(
            AICli.AGY, "/tmp/task.md", "/path/to/worktree",
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


class TestBuildStdinCommandWithReasoningEffort:
    """build_stdin_command の reasoning effort テスト。"""

    @pytest.mark.parametrize(
        "cli",
        [AICli.CLAUDE, AICli.CODEX, AICli.AGY, AICli.CURSOR],
    )
    def test_invalid_effort_raises_value_error(self, ai_cli_manager, cli):
        """無効な reasoning_effort は全 CLI で ValueError にする。"""
        with pytest.raises(
            ValueError,
            match="reasoning_effort は low/medium/high/xhigh/none のいずれかを指定してください",
        ):
            ai_cli_manager.build_stdin_command(
                cli,
                "/tmp/task.md",
                "/path/to/worktree",
                reasoning_effort="invalid",
            )

    def test_claude_ignores_high_effort(self, ai_cli_manager):
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CLAUDE, "/tmp/task.md", "/path/to/worktree",
            reasoning_effort="high",
        )
        assert "--effort" not in cmd
        assert "--reasoning-effort" not in cmd

    def test_claude_ignores_xhigh_effort(self, ai_cli_manager):
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CLAUDE, "/tmp/task.md", "/path/to/worktree",
            reasoning_effort="xhigh",
        )
        assert "--effort" not in cmd
        assert "--reasoning-effort" not in cmd

    def test_codex_with_xhigh(self, ai_cli_manager):
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CODEX, "/tmp/task.md", "/path/to/worktree",
            reasoning_effort="xhigh",
        )
        assert "-c 'reasoning.effort=\"xhigh\"'" in cmd

    def test_none_effort_is_omitted(self, ai_cli_manager):
        cmd = ai_cli_manager.build_stdin_command(
            AICli.CODEX, "/tmp/task.md", "/path/to/worktree",
            reasoning_effort="none",
        )
        assert "reasoning.effort" not in cmd
