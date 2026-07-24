"""AI CLI管理マネージャー。

複数のAI CLIツール（Claude Code, Codex, Antigravity(agy), Cursor）を管理する。
"""

import logging
import shlex
import shutil
from typing import TYPE_CHECKING

from src.config.settings import DEFAULT_AI_CLI_COMMANDS, AICli, resolve_model_for_cli

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = logging.getLogger(__name__)


class AiCliManager:
    """複数のAI CLIツールを管理するマネージャー。"""

    _CURSOR_FALLBACK_COMMAND = "cursor-agent"

    def __init__(self, settings: "Settings") -> None:
        """AiCliManagerを初期化する。

        Args:
            settings: アプリケーション設定
        """
        self.settings = settings
        self._available_clis: dict[AICli, bool] = {}
        self._cli_commands: dict[AICli, str] = DEFAULT_AI_CLI_COMMANDS.copy()
        self._detect_available_clis()

    def _detect_available_clis(self) -> None:
        """利用可能なAI CLIを検出する。"""
        for cli in AICli:
            cmd, is_available = self._resolve_cli_command(cli)
            self._available_clis[cli] = is_available
            if is_available:
                logger.info("AI CLI '%s' が利用可能です (command: %s)", cli.value, cmd)
            else:
                logger.debug("AI CLI '%s' は見つかりませんでした", cli.value)

    def _resolve_cli_command(self, cli: AICli) -> tuple[str, bool]:
        """実行に利用する CLI コマンドを解決する。

        Args:
            cli: AI CLI

        Returns:
            (解決されたコマンド, 利用可能かどうか)
        """
        configured = self._cli_commands.get(cli, cli.value)

        if cli != AICli.CURSOR:
            return configured, shutil.which(configured) is not None

        # Cursor は agent を第一候補にし、未検出時のみ cursor-agent にフォールバック。
        if shutil.which(configured) is not None:
            return configured, True

        fallback = self._CURSOR_FALLBACK_COMMAND
        if configured != fallback and shutil.which(fallback) is not None:
            return fallback, True

        return configured, False

    def _get_runtime_command(self, cli: AICli) -> str:
        """起動時に実行するコマンド文字列を取得する。"""
        command, _ = self._resolve_cli_command(cli)
        return command

    def is_available(self, cli: AICli | str) -> bool:
        """指定のAI CLIが利用可能か確認する。

        Args:
            cli: 確認するAI CLI（文字列も受け付ける）

        Returns:
            利用可能な場合True
        """
        # 文字列が渡された場合は enum に変換
        if isinstance(cli, str):
            cli = AICli(cli)
        return self._available_clis.get(cli, False)

    def get_available_clis(self) -> list[AICli]:
        """利用可能なAI CLI一覧を取得する。

        Returns:
            利用可能なAI CLIのリスト
        """
        return [cli for cli, available in self._available_clis.items() if available]

    def get_command(self, cli: AICli | str) -> str:
        """AI CLIのコマンドを取得する。

        Args:
            cli: AI CLI（文字列も受け付ける）

        Returns:
            コマンド文字列
        """
        # 文字列が渡された場合は enum に変換
        if isinstance(cli, str):
            cli = AICli(cli)
        return self._cli_commands.get(cli, cli.value)

    def set_command(self, cli: AICli, command: str) -> None:
        """AI CLIのコマンドを設定する。

        Args:
            cli: AI CLI
            command: コマンド文字列
        """
        self._cli_commands[cli] = command
        # 利用可能性を再検出
        _, is_available = self._resolve_cli_command(cli)
        self._available_clis[cli] = is_available

    def get_default_cli(self) -> AICli:
        """デフォルトのAI CLIを取得する。

        アクティブなモデルプロファイルの CLI 設定を返す。

        Returns:
            デフォルトのAI CLI
        """
        from src.config.settings import ModelProfile

        if self.settings.model_profile_active == ModelProfile.STANDARD:
            return self.settings.model_profile_standard_cli
        else:  # PERFORMANCE
            return self.settings.model_profile_performance_cli

    @staticmethod
    def _map_agy_effort(effort: str) -> str | None:
        """本プロジェクトの effort を agy の --effort 値へマッピングする。

        agy は low/medium/high のみ対応。xhigh は high に丸め、none は省略。
        """
        if effort in {"low", "medium", "high"}:
            return effort
        if effort == "xhigh":
            return "high"
        return None  # none → --effort 省略

    def build_stdin_command(
        self,
        cli: AICli | str,
        task_file_path: str,
        worktree_path: str | None = None,
        project_root: str | None = None,
        model: str | None = None,
        role: str = "worker",
        role_template_path: str | None = None,
        thinking_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        """AI CLIでstdinからタスクを読み込むコマンドを構築する。

        Args:
            cli: AI CLI（文字列も受け付ける）
            task_file_path: タスクファイルのパス
            worktree_path: 作業ディレクトリのパス（オプション）
            project_root: プロジェクトルートパス（MCP_PROJECT_ROOT 環境変数用）
            model: 使用するモデル（オプション）
            role: エージェントのロール（"admin" or "worker"、モデル解決に使用）
            role_template_path: ロールテンプレートファイルパス（オプション）
            thinking_tokens: Extended Thinking のトークン数（0 で無効、None で省略）
            reasoning_effort: 推論強度（low/medium/high/xhigh/none）

        Returns:
            実行コマンド文字列
        """
        # 文字列が渡された場合は enum に変換
        if isinstance(cli, str):
            cli = AICli(cli)
        cmd = self._get_runtime_command(cli)

        # Settings から CLI 別デフォルトモデルを構築
        cli_defaults = self.settings.get_cli_default_models()

        # CLI に応じてモデル名を解決
        resolved_model = resolve_model_for_cli(cli.value, model, role, cli_defaults)
        if cli == AICli.CURSOR and model is None:
            resolved_model = None

        effort = (reasoning_effort or "none").lower()
        valid_efforts = {"low", "medium", "high", "xhigh", "none"}
        if effort not in valid_efforts:
            raise ValueError(
                "reasoning_effort は low/medium/high/xhigh/none のいずれかを指定してください"
            )

        # 環境変数設定（プロジェクトルート + thinking tokens）
        env_parts = []
        if project_root:
            env_parts.append(f"export MCP_PROJECT_ROOT={shlex.quote(project_root)}")
        # MAX_THINKING_TOKENS は Claude Code 専用（0 も明示設定する）
        if cli == AICli.CLAUDE and thinking_tokens is not None:
            env_parts.append(f"export MAX_THINKING_TOKENS={thinking_tokens}")
        env_prefix = " && ".join(env_parts) + " && " if env_parts else ""

        # 作業ディレクトリ: worktree_path > project_root > なし
        working_dir = worktree_path or project_root
        role_label = role or "worker"
        launch_prompt = (
            f"あなたの役割は {role_label} です。"
            f"役割テンプレートは {role_template_path or '(未指定)'}、"
            f"タスクは {task_file_path} です。"
            "両方を確認して、役割に従って作業を開始してください。"
        )
        quoted_prompt = shlex.quote(launch_prompt)

        if cli == AICli.CLAUDE:
            # export MCP_PROJECT_ROOT=... && cd <path> &&
            # claude --model <model> --dangerously-skip-permissions "<instruction>"
            parts = [cmd]
            if resolved_model:
                parts.extend(["--model", resolved_model])
            if effort != "none":
                logger.debug(
                    "Claude CLI では reasoning_effort=%s は未対応のため無視します",
                    effort,
                )
            parts.append("--dangerously-skip-permissions")
            # Claude CLI はプロンプトを位置引数で受け取る（--prompt は未対応）。
            parts.append(quoted_prompt)
            command = " ".join(parts)
            if working_dir:
                return f"{env_prefix}cd {shlex.quote(working_dir)} && {command}"
            return f"{env_prefix}{command}"

        elif cli == AICli.CODEX:
            # codex exec は使用しない。常に対話コマンドを起動して指示文を渡す。
            parts = [cmd]
            if resolved_model:
                parts.extend(["--model", resolved_model])
            if effort in {"low", "medium", "high", "xhigh"}:
                # Codex は設定上書き(-c)で reasoning.effort を受け取る。
                parts.extend(["-c", shlex.quote(f'reasoning.effort="{effort}"')])
            # Claude Code の --dangerously-skip-permissions 相当。
            # 外部サンドボックス前提で、Codex 側の確認プロンプトを抑止する。
            parts.append("--dangerously-bypass-approvals-and-sandbox")
            # Codex CLI はプロンプトを位置引数で受け取る（--message は未対応）。
            parts.append(quoted_prompt)
            command = " ".join(parts)
            if working_dir:
                return f"{env_prefix}cd {shlex.quote(working_dir)} && {command}"
            return f"{env_prefix}{command}"

        elif cli == AICli.AGY:
            # export MCP_PROJECT_ROOT=... && cd <path> &&
            # agy --model <model> --dangerously-skip-permissions
            #     [--effort <e>] --prompt-interactive "<instruction>"
            parts = [cmd]
            if resolved_model:
                parts.extend(["--model", resolved_model])
            parts.append("--dangerously-skip-permissions")
            mapped = self._map_agy_effort(effort)
            if mapped:
                parts.extend(["--effort", mapped])
            # --prompt-interactive で初期プロンプト実行後にセッションを継続（tmux 向き）
            parts.extend(["--prompt-interactive", quoted_prompt])
            command = " ".join(parts)
            if working_dir:
                return f"{env_prefix}cd {shlex.quote(working_dir)} && {command}"
            return f"{env_prefix}{command}"

        else:  # AICli.CURSOR
            # Cursor は print モードを使わず、通常起動で対話継続できる形にする。
            parts = [cmd]
            if resolved_model:
                parts.extend(["--model", resolved_model])
            if effort != "none":
                logger.warning(
                    "Cursor CLI では reasoning_effort=%s は未対応のため無視します",
                    effort,
                )
            parts.append("--force")
            parts.append(quoted_prompt)
            command = " ".join(parts)
            if working_dir:
                return f"{env_prefix}cd {shlex.quote(working_dir)} && {command}"
            return f"{env_prefix}{command}"

    def build_stdin_command_or_error(
        self,
        cli: AICli | str,
        task_file_path: str,
        worktree_path: str | None = None,
        project_root: str | None = None,
        model: str | None = None,
        role: str = "worker",
        role_template_path: str | None = None,
        thinking_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> tuple[str | None, str | None]:
        """AI CLI コマンド生成を安全に試行し、失敗をエラー文字列へ変換する。"""
        try:
            command = self.build_stdin_command(
                cli=cli,
                task_file_path=task_file_path,
                worktree_path=worktree_path,
                project_root=project_root,
                model=model,
                role=role,
                role_template_path=role_template_path,
                thinking_tokens=thinking_tokens,
                reasoning_effort=reasoning_effort,
            )
        except Exception as e:
            logger.warning("CLIコマンド生成に失敗: %s", e)
            return None, f"CLIコマンド生成に失敗しました: {e}"
        return command, None

    def _build_cli_args(
        self,
        cli: AICli,
        worktree_path: str,
        prompt: str | None = None,
    ) -> list[str]:
        """AI CLI用のコマンドライン引数を構築する。

        Args:
            cli: AI CLI
            worktree_path: 作業ディレクトリのパス
            prompt: 初期プロンプト（オプション）

        Returns:
            コマンドライン引数のリスト
        """
        cmd = self._get_runtime_command(cli)
        args = [cmd]

        if cli == AICli.CLAUDE:
            # 許可プロンプトを抑止（tmux ペイン内でスタックするのを防止）
            args.append("--dangerously-skip-permissions")
            if prompt:
                args.append(prompt)
        elif cli == AICli.CODEX:
            # 許可プロンプトを抑止（tmux ペイン内でスタックするのを防止）
            args.append("--dangerously-bypass-approvals-and-sandbox")
            if prompt:
                args.append(prompt)
        elif cli == AICli.AGY:
            args.append("--dangerously-skip-permissions")
            if prompt:
                args.extend(["--prompt-interactive", prompt])
        elif cli == AICli.CURSOR:
            # Cursor は print モードを使わず、通常起動でプロンプトを位置引数に渡す。
            args.append("--force")
            if prompt:
                args.append(prompt)

        return args

    def build_interactive_command(
        self,
        cli: AICli | str,
        prompt: str | None = None,
    ) -> str:
        """対話起動用の CLI コマンド文字列を構築する。"""
        if isinstance(cli, str):
            cli = AICli(cli)
        args = self._build_cli_args(cli, "", prompt)
        return " ".join(shlex.quote(arg) for arg in args)

    def refresh_availability(self) -> dict[AICli, bool]:
        """AI CLIの利用可能性を再検出する。

        Returns:
            各AI CLIの利用可能性
        """
        self._detect_available_clis()
        return self._available_clis.copy()

    def get_cli_info(self, cli: AICli) -> dict:
        """指定AI CLIの情報を取得する。

        Args:
            cli: AI CLI

        Returns:
            CLIの情報を含む辞書
        """
        return {
            "cli": cli.value,
            "command": self.get_command(cli),
            "available": self.is_available(cli),
            "is_default": cli == self.get_default_cli(),
        }

    def get_all_cli_info(self) -> list[dict]:
        """全AI CLIの情報を取得する。

        Returns:
            各CLIの情報を含むリスト
        """
        return [self.get_cli_info(cli) for cli in AICli]
