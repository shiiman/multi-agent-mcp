"""tmuxセッション管理モジュール。"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config.settings import Settings

from src.config.settings import TerminalApp
from src.managers import tmux_shared
from src.managers.tmux_workspace_mixin import TmuxWorkspaceMixin

logger = logging.getLogger(__name__)

# 後方互換: 既存 import 参照のため公開
MAIN_SESSION = tmux_shared.MAIN_SESSION
MAIN_WINDOW_PANE_ADMIN = tmux_shared.MAIN_WINDOW_PANE_ADMIN
MAIN_WINDOW_WORKER_PANES = tmux_shared.MAIN_WINDOW_WORKER_PANES
get_project_name = tmux_shared.get_project_name


class TmuxManager(TmuxWorkspaceMixin):
    """tmuxセッションを管理するクラス。"""

    def __init__(self, settings: "Settings") -> None:
        self.settings = settings

    async def _run(self, *args: str) -> tuple[int, str, str]:
        """tmuxコマンドを実行する。"""
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

    def _get_window_name(self, window_index: int) -> str:
        """ウィンドウインデックスからウィンドウ名を取得する。"""
        if window_index == 0:
            return self.settings.window_name_main
        return f"{self.settings.window_name_worker_prefix}{window_index}"

    def _get_project_name(self, working_dir: str) -> str:
        """作業ディレクトリからプロジェクト名を返す。"""
        return get_project_name(working_dir, enable_git=self.settings.enable_git)

    async def create_session(self, name: str, working_dir: str) -> bool:
        session_name = name
        code, _, stderr = await self._run(
            "new-session", "-d", "-s", session_name, "-c", working_dir
        )
        if code != 0:
            logger.error(f"セッション作成エラー: {stderr}")
        return code == 0

    async def send_keys(self, session: str, command: str, literal: bool = True) -> bool:
        session_name = session
        if literal:
            code, _, stderr = await self._run("send-keys", "-t", session_name, "-l", command)
        else:
            code, _, stderr = await self._run("send-keys", "-t", session_name, command)
        if code != 0:
            logger.error(f"キー送信エラー: {stderr}")
            return False

        code, _, stderr = await self._run("send-keys", "-t", session_name, "Enter")
        if code != 0:
            logger.error(f"Enterキー送信エラー: {stderr}")
        return code == 0

    async def capture_pane(self, session: str, lines: int = 100) -> str:
        session_name = session
        code, stdout, stderr = await self._run(
            "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"
        )
        if code != 0:
            logger.error(f"ペインキャプチャエラー: {stderr}")
            return ""
        return stdout

    async def kill_session(self, session: str) -> bool:
        session_name = session
        code, _, stderr = await self._run("kill-session", "-t", session_name)
        if code != 0:
            logger.warning(f"セッション終了エラー（既に終了している可能性）: {stderr}")
        return code == 0

    async def list_sessions(self) -> list[str]:
        code, stdout, _ = await self._run("list-sessions", "-F", "#{session_name}")
        if code != 0:
            return []
        return [s.strip() for s in stdout.strip().split("\n") if s.strip()]

    async def session_exists(self, session: str) -> bool:
        code, _, _ = await self._run("has-session", "-t", session)
        return code == 0

    async def cleanup_all_sessions(self) -> int:
        sessions = await self.list_sessions()
        return await self.cleanup_sessions(sessions)

    async def cleanup_sessions(self, sessions: list[str]) -> int:
        targets = sorted({s for s in sessions if s})
        count = 0
        for session in targets:
            if await self.kill_session(session):
                count += 1
        return count

    async def cleanup_project_session(self, project_name: str) -> int:
        return await self.cleanup_sessions([project_name])

    async def _run_exec(self, *args: str) -> tuple[int, str, str]:
        """サブプロセスをリスト形式で安全に実行する。"""
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return proc.returncode or 0, stdout.decode(), stderr.decode()
        except Exception as e:
            logger.error(f"コマンド実行エラー: {e}")
            return 1, "", str(e)

    async def open_session_in_terminal(self, session: str) -> bool:
        session_name = session
        attach_cmd = f"tmux attach -t {session_name}"
        openers = {
            TerminalApp.GHOSTTY: self._open_in_ghostty,
            TerminalApp.ITERM2: self._open_in_iterm2,
            TerminalApp.TERMINAL: self._open_in_terminal_app,
        }
        default_terminal = self.settings.default_terminal
        if default_terminal in openers:
            return await openers[default_terminal](attach_cmd)
        for opener in (self._open_in_ghostty, self._open_in_iterm2, self._open_in_terminal_app):
            if await opener(attach_cmd):
                return True
        return False

    async def _open_in_ghostty(self, attach_cmd: str) -> bool:
        import shutil
        from pathlib import Path

        ghostty_path = shutil.which("ghostty")
        if not ghostty_path:
            macos_ghostty = Path("/Applications/Ghostty.app/Contents/MacOS/ghostty")
            if macos_ghostty.exists():
                ghostty_path = str(macos_ghostty)

        if ghostty_path:
            code, _, _ = await self._run_exec(ghostty_path, "-e", attach_cmd)
            return code == 0
        return False

    async def _open_in_iterm2(self, attach_cmd: str) -> bool:
        iterm_check = await self._run_exec(
            "osascript", "-e", 'application "iTerm" exists'
        )
        if iterm_check[0] == 0:
            escaped_cmd = tmux_shared.escape_applescript(attach_cmd)
            applescript = f'''
            tell application "iTerm"
                activate
                create window with default profile
                tell current session of current window
                    write text "{escaped_cmd}"
                end tell
            end tell
            '''
            code, _, _ = await self._run_exec("osascript", "-e", applescript)
            return code == 0
        return False

    async def _open_in_terminal_app(self, attach_cmd: str) -> bool:
        escaped_cmd = tmux_shared.escape_applescript(attach_cmd)
        applescript = f'''
        tell application "Terminal"
            activate
            do script "{escaped_cmd}"
        end tell
        '''
        code, _, _ = await self._run_exec("osascript", "-e", applescript)
        return code == 0
