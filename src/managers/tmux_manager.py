"""tmuxセッション管理モジュール。"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = logging.getLogger(__name__)


class TmuxManager:
    """tmuxセッションを管理するクラス。"""

    def __init__(self, settings: "Settings") -> None:
        """TmuxManagerを初期化する。

        Args:
            settings: アプリケーション設定
        """
        self.prefix = settings.tmux_prefix

    async def _run(self, *args: str) -> tuple[int, str, str]:
        """tmuxコマンドを実行する。

        Args:
            *args: tmuxコマンドの引数

        Returns:
            (リターンコード, stdout, stderr) のタプル
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "tmux",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return proc.returncode or 0, stdout.decode(), stderr.decode()
        except FileNotFoundError:
            logger.error("tmux がインストールされていません")
            return 1, "", "tmux not found"
        except Exception as e:
            logger.error(f"tmux コマンド実行エラー: {e}")
            return 1, "", str(e)

    def _session_name(self, name: str) -> str:
        """セッション名にプレフィックスを付与する。

        Args:
            name: 元のセッション名

        Returns:
            プレフィックス付きセッション名
        """
        return f"{self.prefix}-{name}"

    async def create_session(self, name: str, working_dir: str) -> bool:
        """新しいtmuxセッションを作成する。

        Args:
            name: セッション名（プレフィックスなし）
            working_dir: 作業ディレクトリのパス

        Returns:
            成功した場合True
        """
        session_name = self._session_name(name)
        code, _, stderr = await self._run(
            "new-session", "-d", "-s", session_name, "-c", working_dir
        )
        if code != 0:
            logger.error(f"セッション作成エラー: {stderr}")
        return code == 0

    async def send_keys(self, session: str, command: str) -> bool:
        """セッションにキー入力を送信する。

        Args:
            session: セッション名（プレフィックスなし）
            command: 実行するコマンド

        Returns:
            成功した場合True
        """
        session_name = self._session_name(session)
        code, _, stderr = await self._run(
            "send-keys", "-t", session_name, command, "Enter"
        )
        if code != 0:
            logger.error(f"キー送信エラー: {stderr}")
        return code == 0

    async def capture_pane(self, session: str, lines: int = 100) -> str:
        """セッションの出力をキャプチャする。

        Args:
            session: セッション名（プレフィックスなし）
            lines: 取得する行数

        Returns:
            キャプチャした出力テキスト
        """
        session_name = self._session_name(session)
        code, stdout, stderr = await self._run(
            "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"
        )
        if code != 0:
            logger.error(f"ペインキャプチャエラー: {stderr}")
            return ""
        return stdout

    async def kill_session(self, session: str) -> bool:
        """セッションを終了する。

        Args:
            session: セッション名（プレフィックスなし）

        Returns:
            成功した場合True
        """
        session_name = self._session_name(session)
        code, _, stderr = await self._run("kill-session", "-t", session_name)
        if code != 0:
            logger.warning(f"セッション終了エラー（既に終了している可能性）: {stderr}")
        return code == 0

    async def list_sessions(self) -> list[str]:
        """管理対象のセッション一覧を取得する。

        Returns:
            セッション名のリスト（プレフィックス付き）
        """
        code, stdout, _ = await self._run("list-sessions", "-F", "#{session_name}")
        if code != 0:
            return []
        sessions = [s.strip() for s in stdout.strip().split("\n") if s.strip()]
        return [s for s in sessions if s.startswith(self.prefix)]

    async def session_exists(self, session: str) -> bool:
        """セッションが存在するか確認する。

        Args:
            session: セッション名（プレフィックスなし）

        Returns:
            存在する場合True
        """
        session_name = self._session_name(session)
        code, _, _ = await self._run("has-session", "-t", session_name)
        return code == 0

    async def cleanup_all_sessions(self) -> int:
        """管理対象の全セッションを終了する。

        Returns:
            終了したセッション数
        """
        sessions = await self.list_sessions()
        count = 0
        for session in sessions:
            # プレフィックスを除去して kill_session を呼び出す
            name = session.replace(f"{self.prefix}-", "", 1)
            if await self.kill_session(name):
                count += 1
        return count
