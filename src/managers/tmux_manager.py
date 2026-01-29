"""tmuxセッション管理モジュール。"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config.settings import Settings

from src.config.settings import TerminalApp

logger = logging.getLogger(__name__)


class TmuxManager:
    """tmuxセッションを管理するクラス。"""

    def __init__(self, settings: "Settings") -> None:
        """TmuxManagerを初期化する。

        Args:
            settings: アプリケーション設定
        """
        self.prefix = settings.tmux_prefix
        self.default_terminal = settings.default_terminal

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

    async def send_keys(self, session: str, command: str, literal: bool = True) -> bool:
        """セッションにキー入力を送信する。

        Args:
            session: セッション名（プレフィックスなし）
            command: 実行するコマンド
            literal: Trueの場合、特殊文字をリテラルとして送信（デフォルト: True）

        Returns:
            成功した場合True
        """
        session_name = self._session_name(session)

        # コマンド送信（リテラルモードで特殊文字をエスケープ）
        # multi-agent-shogun の知見: メッセージと Enter は別々に送信する必要がある
        if literal:
            code, _, stderr = await self._run(
                "send-keys", "-t", session_name, "-l", command
            )
        else:
            code, _, stderr = await self._run(
                "send-keys", "-t", session_name, command
            )

        if code != 0:
            logger.error(f"キー送信エラー: {stderr}")
            return False

        # Enter キーを別途送信（重要：multi-agent-shogun の知見）
        code, _, stderr = await self._run("send-keys", "-t", session_name, "Enter")
        if code != 0:
            logger.error(f"Enterキー送信エラー: {stderr}")
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

    async def _run_shell(self, command: str) -> tuple[int, str, str]:
        """シェルコマンドを実行する。

        Args:
            command: 実行するシェルコマンド

        Returns:
            (リターンコード, stdout, stderr) のタプル
        """
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return proc.returncode or 0, stdout.decode(), stderr.decode()
        except Exception as e:
            logger.error(f"シェルコマンド実行エラー: {e}")
            return 1, "", str(e)

    async def open_session_in_terminal(self, session: str) -> bool:
        """tmuxセッションをターミナルアプリで開く。

        環境変数 MCP_DEFAULT_TERMINAL で指定されたターミナルを使用。
        auto の場合は優先順位: ghostty → iTerm2 → Terminal.app

        Args:
            session: セッション名（プレフィックスなし）

        Returns:
            成功した場合True
        """
        session_name = self._session_name(session)
        attach_cmd = f"tmux attach -t {session_name}"

        # 指定されたターミナルを使用
        if self.default_terminal == TerminalApp.GHOSTTY:
            return await self._open_in_ghostty(attach_cmd)
        elif self.default_terminal == TerminalApp.ITERM2:
            return await self._open_in_iterm2(attach_cmd)
        elif self.default_terminal == TerminalApp.TERMINAL:
            return await self._open_in_terminal_app(attach_cmd)

        # auto: 優先順位で試行
        if await self._open_in_ghostty(attach_cmd):
            return True
        if await self._open_in_iterm2(attach_cmd):
            return True
        return await self._open_in_terminal_app(attach_cmd)

    async def _open_in_ghostty(self, attach_cmd: str) -> bool:
        """Ghostty でセッションを開く。"""
        import shutil
        from pathlib import Path

        ghostty_path = shutil.which("ghostty")
        if not ghostty_path:
            macos_ghostty = Path("/Applications/Ghostty.app/Contents/MacOS/ghostty")
            if macos_ghostty.exists():
                ghostty_path = str(macos_ghostty)

        if ghostty_path:
            code, _, _ = await self._run_shell(f'"{ghostty_path}" -e "{attach_cmd}"')
            return code == 0
        return False

    async def _open_in_iterm2(self, attach_cmd: str) -> bool:
        """iTerm2 でセッションを開く。"""
        iterm_check = await self._run_shell(
            "osascript -e 'application \"iTerm\" exists'"
        )
        if iterm_check[0] == 0:
            applescript = f'''
            tell application "iTerm"
                activate
                create window with default profile
                tell current session of current window
                    write text "{attach_cmd}"
                end tell
            end tell
            '''
            code, _, _ = await self._run_shell(f"osascript -e '{applescript}'")
            return code == 0
        return False

    async def _open_in_terminal_app(self, attach_cmd: str) -> bool:
        """macOS Terminal.app でセッションを開く。"""
        applescript = f'''
        tell application "Terminal"
            activate
            do script "{attach_cmd}"
        end tell
        '''
        code, _, _ = await self._run_shell(f"osascript -e '{applescript}'")
        return code == 0
