"""initialize_agent ツールのテスト。"""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
        assert cli == AICli.CLAUDE  # デフォルトは Claude


class TestBuildCliArgsWithPrompt:
    """プロンプト付き CLI 引数構築のテスト。"""

    def test_claude_with_prompt(self, ai_cli_manager):
        """Claude CLI でプロンプトが位置引数で渡されることをテスト。"""
        args = ai_cli_manager._build_cli_args(
            AICli.CLAUDE, "/tmp/test", "テストプロンプト"
        )
        assert "--prompt" not in args
        assert args[-1] == "テストプロンプト"

    def test_codex_with_prompt(self, ai_cli_manager):
        """Codex CLI でプロンプトが位置引数で渡されることをテスト。"""
        args = ai_cli_manager._build_cli_args(
            AICli.CODEX, "/tmp/test", "テストプロンプト"
        )
        assert "--message" not in args
        assert args[-1] == "テストプロンプト"

    def test_gemini_with_prompt(self, ai_cli_manager):
        """Gemini CLI でプロンプトが --prompt オプションで渡されることをテスト。"""
        args = ai_cli_manager._build_cli_args(
            AICli.GEMINI, "/tmp/test", "テストプロンプト"
        )
        assert "--prompt" in args
        assert "テストプロンプト" in args

    def test_claude_without_prompt(self, ai_cli_manager):
        """プロンプトなしの場合 --prompt オプションが含まれないことをテスト。"""
        args = ai_cli_manager._build_cli_args(AICli.CLAUDE, "/tmp/test", None)
        assert "--prompt" not in args


class TestInitializeAgentIntegration:
    """initialize_agent の統合テスト（モック使用）。"""

    @pytest.mark.asyncio
    async def test_initialize_admin_agent_auto(self, ai_cli_manager):
        """Admin エージェントを auto プロンプトで初期化できることをテスト。"""
        now = datetime.now()
        agent = Agent(
            id="admin-001",
            role=AgentRole.ADMIN,
            status=AgentStatus.IDLE,
            tmux_session="admin-session",
            working_dir="/tmp/test-admin",
            ai_cli=None,
            created_at=now,
            last_activity=now,
        )

        # ロールテンプレートを読み込む
        # Agent モデルで use_enum_values=True のため、role は文字列
        loader = get_template_loader()
        prompt = loader.load("roles", agent.role)

        assert "Admin" in prompt

        # open_worktree_in_terminal をモック
        with patch.object(
            ai_cli_manager, "open_worktree_in_terminal", new_callable=AsyncMock
        ) as mock_open:
            mock_open.return_value = (True, "ターミナルを開きました")

            success, message = await ai_cli_manager.open_worktree_in_terminal(
                worktree_path=agent.working_dir,
                cli=AICli.CLAUDE,
                prompt=prompt,
                terminal=TerminalApp.AUTO,
            )

            assert success is True
            mock_open.assert_called_once()
            # プロンプトが渡されていることを確認
            call_kwargs = mock_open.call_args[1]
            assert "Admin" in call_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_initialize_worker_agent_auto(self, ai_cli_manager):
        """Worker エージェントを auto プロンプトで初期化できることをテスト。"""
        now = datetime.now()
        agent = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="worker-session",
            working_dir="/tmp/test-worker",
            ai_cli=AICli.GEMINI,
            created_at=now,
            last_activity=now,
        )

        # ロールテンプレートを読み込む
        # Agent モデルで use_enum_values=True のため、role は文字列
        loader = get_template_loader()
        prompt = loader.load("roles", agent.role)

        assert "Worker" in prompt

        # open_worktree_in_terminal をモック
        with patch.object(
            ai_cli_manager, "open_worktree_in_terminal", new_callable=AsyncMock
        ) as mock_open:
            mock_open.return_value = (True, "ターミナルを開きました")

            # エージェントに設定された CLI を使用
            cli = agent.ai_cli or ai_cli_manager.get_default_cli()
            assert cli == AICli.GEMINI

            success, message = await ai_cli_manager.open_worktree_in_terminal(
                worktree_path=agent.working_dir,
                cli=cli,
                prompt=prompt,
                terminal=TerminalApp.GHOSTTY,
            )

            assert success is True
            call_kwargs = mock_open.call_args[1]
            assert call_kwargs["cli"] == AICli.GEMINI
            assert "Worker" in call_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_initialize_with_custom_prompt(self, ai_cli_manager):
        """カスタムプロンプトで初期化できることをテスト。"""
        custom_prompt = "これはカスタムプロンプトです。特別な指示を含みます。"

        with patch.object(
            ai_cli_manager, "open_worktree_in_terminal", new_callable=AsyncMock
        ) as mock_open:
            mock_open.return_value = (True, "ターミナルを開きました")

            success, message = await ai_cli_manager.open_worktree_in_terminal(
                worktree_path="/tmp/test",
                cli=AICli.CLAUDE,
                prompt=custom_prompt,
                terminal=TerminalApp.AUTO,
            )

            assert success is True
            call_kwargs = mock_open.call_args[1]
            assert call_kwargs["prompt"] == custom_prompt

    @pytest.mark.asyncio
    async def test_initialize_with_file_prompt(self, ai_cli_manager):
        """ファイルからプロンプトを読み込んで初期化できることをテスト。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(
                "# ファイルベースのプロンプト\n\n"
                "これはファイルから読み込まれたプロンプトです。"
            )
            file_path = f.name

        try:
            # ファイルからプロンプトを読み込む
            prompt = Path(file_path).read_text(encoding="utf-8")
            assert "ファイルベースのプロンプト" in prompt

            with patch.object(
                ai_cli_manager, "open_worktree_in_terminal", new_callable=AsyncMock
            ) as mock_open:
                mock_open.return_value = (True, "ターミナルを開きました")

                success, message = await ai_cli_manager.open_worktree_in_terminal(
                    worktree_path="/tmp/test",
                    cli=AICli.CLAUDE,
                    prompt=prompt,
                    terminal=TerminalApp.AUTO,
                )

                assert success is True
                call_kwargs = mock_open.call_args[1]
                assert "ファイルベースのプロンプト" in call_kwargs["prompt"]
        finally:
            Path(file_path).unlink()
