"""AI CLI管理マネージャー。

複数のAI CLIツール（Claude Code, Codex, Gemini）を管理する。
"""

import asyncio
import logging
import shutil
from typing import TYPE_CHECKING

from src.config.settings import AICli, DEFAULT_AI_CLI_COMMANDS

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

    def is_available(self, cli: AICli) -> bool:
        """指定のAI CLIが利用可能か確認する。

        Args:
            cli: 確認するAI CLI

        Returns:
            利用可能な場合True
        """
        return self._available_clis.get(cli, False)

    def get_available_clis(self) -> list[AICli]:
        """利用可能なAI CLI一覧を取得する。

        Returns:
            利用可能なAI CLIのリスト
        """
        return [cli for cli, available in self._available_clis.items() if available]

    def get_command(self, cli: AICli) -> str:
        """AI CLIのコマンドを取得する。

        Args:
            cli: AI CLI

        Returns:
            コマンド文字列
        """
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

        Returns:
            デフォルトのAI CLI
        """
        return self.settings.default_ai_cli

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

        # CLI固有のオプション
        if cli == AICli.CLAUDE:
            args.extend(["--directory", worktree_path])
            if prompt:
                args.extend(["--prompt", prompt])
        elif cli == AICli.CODEX:
            args.extend(["--cwd", worktree_path])
            if prompt:
                args.extend(["--message", prompt])
        elif cli == AICli.GEMINI:
            args.extend(["--dir", worktree_path])
            if prompt:
                args.extend(["--prompt", prompt])

        return args

    async def open_worktree(
        self,
        worktree_path: str,
        cli: AICli | None = None,
        prompt: str | None = None,
        detach: bool = True,
    ) -> tuple[bool, str]:
        """AI CLIでworktreeを開く。

        Args:
            worktree_path: worktreeのパス
            cli: 使用するAI CLI（Noneでデフォルト）
            prompt: 初期プロンプト（オプション）
            detach: バックグラウンドで実行するか

        Returns:
            (成功したかどうか, メッセージ) のタプル
        """
        cli = cli or self.get_default_cli()

        if not self.is_available(cli):
            return False, f"{cli.value} は利用できません（インストールされていないか、パスが通っていません）"

        args = self._build_cli_args(cli, worktree_path, prompt)

        try:
            if detach:
                # バックグラウンドで起動
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                )
                return True, f"{cli.value} を起動しました（PID: {proc.pid}）"
            else:
                # フォアグラウンドで実行（完了を待つ）
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
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
