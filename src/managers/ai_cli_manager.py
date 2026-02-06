"""AI CLI管理マネージャー。

複数のAI CLIツール（Claude Code, Codex, Gemini）を管理する。
"""

import asyncio
import logging
import shlex
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from src.config.settings import DEFAULT_AI_CLI_COMMANDS, AICli, TerminalApp, resolve_model_for_cli

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = logging.getLogger(__name__)


class AiCliManager:
    """複数のAI CLIツールを管理するマネージャー。"""

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
            cmd = self._cli_commands.get(cli, cli.value)
            self._available_clis[cli] = shutil.which(cmd) is not None
            if self._available_clis[cli]:
                logger.info(f"AI CLI '{cli.value}' が利用可能です")
            else:
                logger.debug(f"AI CLI '{cli.value}' は見つかりませんでした")

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
        self._available_clis[cli] = shutil.which(command) is not None

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

    def build_stdin_command(
        self,
        cli: AICli | str,
        task_file_path: str,
        worktree_path: str | None = None,
        project_root: str | None = None,
        model: str | None = None,
        role: str = "worker",
        thinking_tokens: int | None = None,
    ) -> str:
        """AI CLIでstdinからタスクを読み込むコマンドを構築する。

        Args:
            cli: AI CLI（文字列も受け付ける）
            task_file_path: タスクファイルのパス
            worktree_path: 作業ディレクトリのパス（オプション）
            project_root: プロジェクトルートパス（MCP_PROJECT_ROOT 環境変数用）
            model: 使用するモデル（オプション）
            role: エージェントのロール（"admin" or "worker"、モデル解決に使用）
            thinking_tokens: Extended Thinking のトークン数（0 で無効、None で省略）

        Returns:
            実行コマンド文字列
        """
        # 文字列が渡された場合は enum に変換
        if isinstance(cli, str):
            cli = AICli(cli)
        cmd = self.get_command(cli)

        # Settings から CLI 別デフォルトモデルを構築
        cli_defaults = {
            "codex": {
                "admin": self.settings.cli_default_codex_admin_model,
                "worker": self.settings.cli_default_codex_worker_model,
            },
            "gemini": {
                "admin": self.settings.cli_default_gemini_admin_model,
                "worker": self.settings.cli_default_gemini_worker_model,
            },
        }

        # CLI に応じてモデル名を解決
        resolved_model = resolve_model_for_cli(cli.value, model, role, cli_defaults)

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

        if cli == AICli.CLAUDE:
            # export MCP_PROJECT_ROOT=... && cd <path> && claude --model <model> --dangerously-skip-permissions < task.md
            parts = [cmd]
            if resolved_model:
                parts.extend(["--model", resolved_model])
            parts.append("--dangerously-skip-permissions")
            parts.append(f"< {shlex.quote(task_file_path)}")
            command = " ".join(parts)
            if working_dir:
                return f"{env_prefix}cd {shlex.quote(working_dir)} && {command}"
            return f"{env_prefix}{command}"

        elif cli == AICli.CODEX:
            # export MCP_PROJECT_ROOT=... && cd <path> && cat task.md | codex --model <model> -a never
            parts = ["cat", shlex.quote(task_file_path), "|", cmd]
            if resolved_model:
                parts.extend(["--model", resolved_model])
            parts.extend(["-a", "never"])
            command = " ".join(parts)
            if working_dir:
                return f"{env_prefix}cd {shlex.quote(working_dir)} && {command}"
            return f"{env_prefix}{command}"

        else:  # AICli.GEMINI
            # export MCP_PROJECT_ROOT=... && cd <path> && gemini --model <model> --yolo < task.md
            parts = [cmd]
            if resolved_model:
                parts.extend(["--model", resolved_model])
            parts.append("--yolo")
            parts.append(f"< {shlex.quote(task_file_path)}")
            command = " ".join(parts)
            if working_dir:
                return f"{env_prefix}cd {shlex.quote(working_dir)} && {command}"
            return f"{env_prefix}{command}"

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
        cmd = self.get_command(cli)
        args = [cmd]

        # CLI固有のオプション（worktree_path は呼び出し側で cwd として使用）
        if cli == AICli.CLAUDE:
            if prompt:
                args.extend(["--prompt", prompt])
        elif cli == AICli.CODEX:
            if prompt:
                args.extend(["--message", prompt])
        elif cli == AICli.GEMINI:
            if prompt:
                args.extend(["--prompt", prompt])

        return args

    async def open_worktree(
        self,
        worktree_path: str,
        cli: AICli | str | None = None,
        prompt: str | None = None,
        detach: bool = True,
    ) -> tuple[bool, str]:
        """AI CLIでworktreeを開く。

        Args:
            worktree_path: worktreeのパス
            cli: 使用するAI CLI（Noneでデフォルト、文字列も受け付ける）
            prompt: 初期プロンプト（オプション）
            detach: バックグラウンドで実行するか

        Returns:
            (成功したかどうか, メッセージ) のタプル
        """
        # 文字列が渡された場合は enum に変換
        if isinstance(cli, str):
            cli = AICli(cli)
        cli = cli or self.get_default_cli()

        if not self.is_available(cli):
            return False, f"{cli.value} は利用できません"

        args = self._build_cli_args(cli, worktree_path, prompt)

        # 全 CLI で cwd を使用して作業ディレクトリを指定
        cwd = worktree_path

        try:
            if detach:
                # バックグラウンドで起動
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                    cwd=cwd,
                )
                return True, f"{cli.value} を起動しました（PID: {proc.pid}）"
            else:
                # フォアグラウンドで実行（完了を待つ）
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )
                stdout, stderr = await proc.communicate()

                if proc.returncode == 0:
                    return True, f"{cli.value} が正常に終了しました"
                else:
                    return False, f"{cli.value} がエラーで終了しました: {stderr.decode()}"

        except FileNotFoundError:
            return False, f"{cli.value} コマンドが見つかりません"
        except Exception as e:
            logger.error(f"AI CLI起動エラー: {e}")
            return False, f"AI CLI起動エラー: {e}"

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

    async def open_worktree_in_terminal(
        self,
        worktree_path: str,
        cli: AICli | str | None = None,
        prompt: str | None = None,
        terminal: TerminalApp = TerminalApp.AUTO,
    ) -> tuple[bool, str]:
        """ターミナルアプリを開いてAI CLIを起動する。

        Args:
            worktree_path: worktreeのパス
            cli: 使用するAI CLI（Noneでデフォルト、文字列も受け付ける）
            prompt: 初期プロンプト（オプション）
            terminal: 使用するターミナルアプリ

        Returns:
            (成功したかどうか, メッセージ) のタプル
        """
        # 文字列が渡された場合は enum に変換
        if isinstance(cli, str):
            cli = AICli(cli)
        cli = cli or self.get_default_cli()

        if not self.is_available(cli):
            return False, f"{cli.value} は利用できません"

        # CLI コマンドを構築
        args = self._build_cli_args(cli, worktree_path, prompt)
        command = " ".join(shlex.quote(arg) for arg in args)

        # ターミナルを検出/選択
        if terminal == TerminalApp.AUTO:
            terminal = await self._detect_terminal()

        # ターミナルで開く
        if terminal == TerminalApp.GHOSTTY:
            return await self._open_in_ghostty(worktree_path, command)
        elif terminal == TerminalApp.ITERM2:
            return await self._open_in_iterm2(worktree_path, command)
        elif terminal == TerminalApp.TERMINAL:
            return await self._open_in_terminal_app(worktree_path, command)
        else:
            return False, f"未対応のターミナル: {terminal}"

    async def _detect_terminal(self) -> TerminalApp:
        """利用可能なターミナルアプリを検出する。

        優先順位: Ghostty → iTerm2 → Terminal.app

        Returns:
            検出されたターミナルアプリ
        """
        # Ghostty を確認
        ghostty_app = Path("/Applications/Ghostty.app")
        if ghostty_app.exists():
            return TerminalApp.GHOSTTY

        # iTerm2 を確認
        iterm_app = Path("/Applications/iTerm.app")
        if iterm_app.exists():
            return TerminalApp.ITERM2

        # デフォルトは Terminal.app
        return TerminalApp.TERMINAL

    async def _open_in_ghostty(
        self, worktree_path: str, command: str
    ) -> tuple[bool, str]:
        """Ghostty で新しいウィンドウを開いてコマンドを実行する。

        Args:
            worktree_path: 作業ディレクトリのパス
            command: 実行するコマンド

        Returns:
            (成功したかどうか, メッセージ) のタプル
        """
        try:
            # open -na Ghostty.app --args --working-directory={path} -e {command}
            proc = await asyncio.create_subprocess_exec(
                "open", "-na", "Ghostty.app",
                "--args",
                f"--working-directory={worktree_path}",
                "-e", command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode == 0:
                return True, "Ghostty でターミナルを開きました"
            else:
                error_msg = stderr.decode().strip() if stderr else "不明なエラー"
                return False, f"Ghostty の起動に失敗しました: {error_msg}"

        except Exception as e:
            logger.error(f"Ghostty 起動エラー: {e}")
            return False, f"Ghostty 起動エラー: {e}"

    async def _open_in_iterm2(
        self, worktree_path: str, command: str
    ) -> tuple[bool, str]:
        """iTerm2 で新しいウィンドウを開いてコマンドを実行する。

        Args:
            worktree_path: 作業ディレクトリのパス
            command: 実行するコマンド

        Returns:
            (成功したかどうか, メッセージ) のタプル
        """
        try:
            # AppleScript で iTerm2 を制御
            # shlex.quote でパスをエスケープしてからさらに AppleScript 用にエスケープ
            escaped_path = worktree_path.replace("\\", "\\\\").replace('"', '\\"')
            escaped_command = command.replace("\\", "\\\\").replace('"', '\\"')

            applescript = f'''
            tell application "iTerm"
                activate
                create window with default profile
                tell current session of current window
                    write text "cd {shlex.quote(escaped_path)} && {escaped_command}"
                end tell
            end tell
            '''

            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", applescript,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode == 0:
                return True, "iTerm2 でターミナルを開きました"
            else:
                error_msg = stderr.decode().strip() if stderr else "不明なエラー"
                return False, f"iTerm2 の起動に失敗しました: {error_msg}"

        except Exception as e:
            logger.error(f"iTerm2 起動エラー: {e}")
            return False, f"iTerm2 起動エラー: {e}"

    async def _open_in_terminal_app(
        self, worktree_path: str, command: str
    ) -> tuple[bool, str]:
        """macOS Terminal.app で新しいウィンドウを開いてコマンドを実行する。

        Args:
            worktree_path: 作業ディレクトリのパス
            command: 実行するコマンド

        Returns:
            (成功したかどうか, メッセージ) のタプル
        """
        try:
            # AppleScript で Terminal.app を制御
            escaped_path = worktree_path.replace("\\", "\\\\").replace('"', '\\"')
            escaped_command = command.replace("\\", "\\\\").replace('"', '\\"')

            applescript = f'''
            tell application "Terminal"
                activate
                do script "cd {shlex.quote(escaped_path)} && {escaped_command}"
            end tell
            '''

            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", applescript,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode == 0:
                return True, "Terminal.app でターミナルを開きました"
            else:
                error_msg = stderr.decode().strip() if stderr else "不明なエラー"
                return False, f"Terminal.app の起動に失敗しました: {error_msg}"

        except Exception as e:
            logger.error(f"Terminal.app 起動エラー: {e}")
            return False, f"Terminal.app 起動エラー: {e}"
