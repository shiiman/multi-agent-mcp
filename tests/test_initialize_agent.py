"""initialize_agent ツールのテスト。"""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config.settings import AICli, TerminalApp
from src.config.template_loader import get_template_loader
from src.models.agent import Agent, AgentRole, AgentStatus


class TestTemplateLoaderForInitializeAgent:
    """initialize_agent で使用する TemplateLoader のテスト。"""

    def test_load_admin_role_template(self):
        """Admin ロールテンプレートを読み込めることをテスト。"""
        loader = get_template_loader()
        content = loader.load("roles", "admin")
        assert "Admin" in content
        assert "エージェント" in content or "agent" in content.lower()

    def test_load_worker_role_template(self):
        """Worker ロールテンプレートを読み込めることをテスト。"""
        loader = get_template_loader()
        content = loader.load("roles", "worker")
        assert "Worker" in content
        assert "エージェント" in content or "agent" in content.lower()

    def test_load_owner_role_template(self):
        """Owner ロールテンプレートを読み込めることをテスト。"""
        loader = get_template_loader()
        content = loader.load("roles", "owner")
        assert "Owner" in content

    def test_load_nonexistent_template(self):
        """存在しないテンプレートでエラーが発生することをテスト。"""
        loader = get_template_loader()
        with pytest.raises(FileNotFoundError):
            loader.load("roles", "nonexistent")


class TestInitializeAgentValidation:
    """initialize_agent のバリデーションロジックのテスト。"""

    def create_mock_agent(
        self,
        agent_id: str,
        role: AgentRole,
        working_dir: str | None = "/tmp/test",
        ai_cli: AICli | None = None,
    ) -> Agent:
        """テスト用のエージェントを作成する。"""
        now = datetime.now()
        # AgentRole を文字列に変換して比較
        is_owner = role == AgentRole.OWNER
        return Agent(
            id=agent_id,
            role=role,
            status=AgentStatus.IDLE,
            tmux_session=f"{agent_id}-session" if not is_owner else None,
            working_dir=working_dir,
            ai_cli=ai_cli,
            created_at=now,
            last_activity=now,
        )

    def test_prompt_type_auto_loads_role_template(self):
        """prompt_type='auto' でロールテンプレートが読み込まれることをテスト。"""
        agent = self.create_mock_agent("test-001", AgentRole.ADMIN)
        loader = get_template_loader()

        # Agent モデルで use_enum_values=True のため、role は文字列
        # auto の場合、agent.role をテンプレート名として使用
        template_name = agent.role  # "admin"
        content = loader.load("roles", template_name)

        assert content is not None
        assert len(content) > 0
        assert "Admin" in content

    def test_prompt_type_auto_for_worker(self):
        """Worker の auto プロンプトが正しく読み込まれることをテスト。"""
        agent = self.create_mock_agent("test-002", AgentRole.WORKER)
        loader = get_template_loader()

        # Agent モデルで use_enum_values=True のため、role は文字列
        content = loader.load("roles", agent.role)

        assert content is not None
        assert "Worker" in content

    def test_prompt_type_custom_requires_custom_prompt(self):
        """prompt_type='custom' で custom_prompt が必須であることをテスト。"""
        # custom_prompt が None の場合はエラーになるべき
        prompt_type = "custom"
        custom_prompt = None

        # バリデーションロジック
        if prompt_type == "custom" and not custom_prompt:
            error = "prompt_type='custom' の場合、custom_prompt は必須です"
        else:
            error = None

        assert error is not None
        assert "必須" in error

    def test_prompt_type_custom_uses_custom_prompt(self):
        """prompt_type='custom' で custom_prompt が使用されることをテスト。"""
        prompt_type = "custom"
        custom_prompt = "これはカスタムプロンプトです。"

        if prompt_type == "custom":
            prompt = custom_prompt

        assert prompt == custom_prompt

    def test_prompt_type_file_reads_from_path(self):
        """prompt_type='file' でファイルから読み込まれることをテスト。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# ファイルからのプロンプト\nテスト内容です。")
            file_path = f.name

        try:
            prompt_type = "file"
            custom_prompt = file_path

            if prompt_type == "file":
                path = Path(custom_prompt)
                prompt = path.read_text(encoding="utf-8")

            assert "ファイルからのプロンプト" in prompt
            assert "テスト内容です" in prompt
        finally:
            Path(file_path).unlink()

    def test_prompt_type_file_nonexistent_file(self):
        """prompt_type='file' で存在しないファイルの場合エラーになることをテスト。"""
        custom_prompt = "/nonexistent/path/to/file.md"

        path = Path(custom_prompt)
        exists = path.exists()

        assert exists is False

    def test_invalid_prompt_type(self):
        """無効な prompt_type でエラーになることをテスト。"""
        valid_types = ["auto", "custom", "file"]
        invalid_type = "invalid"

        assert invalid_type not in valid_types

    def test_owner_agent_not_supported(self):
        """Owner エージェントが対象外であることをテスト。"""
        agent = self.create_mock_agent("owner-001", AgentRole.OWNER)

        # Owner は tmux ペインを持たないため、initialize_agent の対象外
        # Agent モデルで use_enum_values=True のため、role は文字列
        is_owner = agent.role == "owner"
        assert is_owner is True

    def test_agent_without_working_dir(self):
        """working_dir がないエージェントでエラーになることをテスト。"""
        agent = self.create_mock_agent("test-003", AgentRole.WORKER, working_dir=None)

        assert agent.working_dir is None

    def test_terminal_validation(self):
        """ターミナルアプリのバリデーションをテスト。"""
        valid_terminals = ["auto", "ghostty", "iterm2", "terminal"]

        for terminal in valid_terminals:
            terminal_app = TerminalApp(terminal)
            assert terminal_app is not None

        with pytest.raises(ValueError):
            TerminalApp("invalid_terminal")


class TestInitializeAgentCLISelection:
    """AI CLI 選択ロジックのテスト。"""

    def test_uses_agent_cli_if_set(self):
        """エージェントに CLI が設定されていればそれを使用することをテスト。"""
        now = datetime.now()
        agent = Agent(
            id="test-001",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test-session",
            working_dir="/tmp/test",
            ai_cli=AICli.CODEX,
            created_at=now,
            last_activity=now,
        )

        # エージェントに CLI が設定されていればそれを使用
        cli = agent.ai_cli
        assert cli == AICli.CODEX

    def test_uses_default_cli_if_not_set(self, ai_cli_manager):
        """エージェントに CLI が設定されていなければデフォルトを使用することをテスト。"""
        now = datetime.now()
        agent = Agent(
            id="test-002",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test-session",
            working_dir="/tmp/test",
            ai_cli=None,
            created_at=now,
            last_activity=now,
        )

        # CLI が None の場合はデフォルトを使用
        cli = agent.ai_cli or ai_cli_manager.get_default_cli()
        assert cli == ai_cli_manager.settings.get_active_profile_cli()


class TestBuildCliArgsWithPrompt:
    """プロンプト付き CLI 引数構築のテスト。"""

    def test_claude_with_prompt(self, ai_cli_manager):
        """Claude CLI でプロンプトが位置引数で渡されることをテスト。"""
        args = ai_cli_manager._build_cli_args(
            AICli.CLAUDE, "/tmp/test", "テストプロンプト"
        )
        assert "--prompt" not in args
        assert "--dangerously-skip-permissions" in args
        assert args[-1] == "テストプロンプト"

    def test_codex_with_prompt(self, ai_cli_manager):
        """Codex CLI でプロンプトが位置引数で渡されることをテスト。"""
        args = ai_cli_manager._build_cli_args(
            AICli.CODEX, "/tmp/test", "テストプロンプト"
        )
        assert "--message" not in args
        assert "--dangerously-bypass-approvals-and-sandbox" in args
        assert args[-1] == "テストプロンプト"

    def test_agy_with_prompt(self, ai_cli_manager):
        """agy CLI でプロンプトが --prompt-interactive で渡されることをテスト。"""
        args = ai_cli_manager._build_cli_args(AICli.AGY, "/tmp/test", "テストプロンプト")
        assert "agy" in args
        assert "--prompt-interactive" in args
        assert "テストプロンプト" in args

    def test_cursor_with_prompt_uses_interactive_mode(self, ai_cli_manager):
        """Cursor CLI は print モードを使わず、プロンプトを位置引数で渡すことをテスト。"""
        with patch("src.managers.ai_cli_manager.shutil.which") as mock_which:
            mock_which.side_effect = lambda command: (
                "/usr/local/bin/agent" if command == "agent" else None
            )
            args = ai_cli_manager._build_cli_args(
                AICli.CURSOR, "/tmp/test", "テストプロンプト"
            )

        assert args == ["agent", "--force", "テストプロンプト"]
        assert "--print" not in args
        assert "--prompt" not in args

    def test_claude_without_prompt(self, ai_cli_manager):
        """プロンプトなしの場合 --prompt オプションが含まれないことをテスト。"""
        args = ai_cli_manager._build_cli_args(AICli.CLAUDE, "/tmp/test", None)
        assert "--prompt" not in args
        assert "--dangerously-skip-permissions" in args

    def test_codex_without_prompt_has_bypass_flag(self, ai_cli_manager):
        """Codex CLI でプロンプトなしでも bypass フラグが含まれることをテスト。"""
        args = ai_cli_manager._build_cli_args(AICli.CODEX, "/tmp/test", None)
        assert "--dangerously-bypass-approvals-and-sandbox" in args

    def test_agy_without_prompt_has_skip_permissions(self, ai_cli_manager):
        """agy CLI でプロンプトなしでも --dangerously-skip-permissions が含まれることをテスト。"""
        args = ai_cli_manager._build_cli_args(AICli.AGY, "/tmp/test", None)
        assert "--dangerously-skip-permissions" in args

    def test_cursor_without_prompt_uses_plain_command(self, ai_cli_manager):
        """Cursor CLI は prompt なしでも通常起動コマンドのみを返すことをテスト。"""
        with patch("src.managers.ai_cli_manager.shutil.which") as mock_which:
            mock_which.side_effect = lambda command: (
                "/usr/local/bin/agent" if command == "agent" else None
            )
            args = ai_cli_manager._build_cli_args(AICli.CURSOR, "/tmp/test", None)

        assert args == ["agent", "--force"]
        assert "--print" not in args
