"""Ghostty ターミナル実装。"""

import asyncio
import logging
import shutil
from pathlib import Path

from .base import TerminalExecutor

logger = logging.getLogger(__name__)


class GhosttyExecutor(TerminalExecutor):
    """Ghostty でスクリプトを実行するクラス。"""

    @property
    def name(self) -> str:
        return "Ghostty"

    def _get_ghostty_path(self) -> str | None:
        """Ghostty の実行パスを取得する。"""
        ghostty_path = shutil.which("ghostty")
        if not ghostty_path:
            macos_ghostty = Path("/Applications/Ghostty.app/Contents/MacOS/ghostty")
            if macos_ghostty.exists():
                ghostty_path = str(macos_ghostty)
        return ghostty_path

    async def is_available(self) -> bool:
        """Ghostty が利用可能か確認する。"""
        return self._get_ghostty_path() is not None

    async def execute_script(
        self, working_dir: str, script: str, script_path: str
    ) -> tuple[bool, str]:
        """Ghostty でスクリプトを実行する。

        既存のウィンドウがある場合は新しいタブとして開く。
        """
        ghostty_path = self._get_ghostty_path()
        if not ghostty_path:
            return False, "Ghostty が見つかりません"

        session_name = self._extract_session_name(script)

        try:
            # 既存の Ghostty プロセスがある場合はタブ追加を試みる
            if await self._is_running():
                success = await self._open_in_tab(f'exec bash "{script_path}"')
                if success:
                    return True, "Ghostty の新しいタブでワークスペースを開きました"
                # タブ追加に失敗した場合は新しいウィンドウで開く

            # 新しいウィンドウで開く
            proc = await asyncio.create_subprocess_exec(
                ghostty_path,
                f"--working-directory={working_dir}",
                f"--title={session_name}",
                "-e",
                script_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

            # プロセス起動を確認するために少し待つ
            await asyncio.sleep(0.5)

            # プロセスがまだ動いていれば成功（tmux attach で待機中）
            if proc.returncode is None:
                # ウィンドウを画面サイズに合わせる（fill arrange）
                await self._maximize_window()
                return True, "Ghostty でワークスペースを開きました"
            else:
                return False, f"Ghostty の起動に失敗しました (code: {proc.returncode})"

        except Exception as e:
            logger.error(f"Ghostty 起動エラー: {e}")
            return False, f"Ghostty 起動エラー: {e}"

    async def _is_running(self) -> bool:
        """Ghostty が起動中かを確認する。"""
        applescript = """
        if application "Ghostty" is running then
            return "true"
        else
            return "false"
        end if
        """
        try:
            code, stdout, _ = await self._run_osascript(applescript)
            if code == 0:
                return "true" in stdout.lower()

            # AppleScript 判定が失敗する環境向けフォールバック
            code, _, _ = await self._run_exec("pgrep", "-x", "Ghostty")
            if code == 0:
                return True
            code, _, _ = await self._run_exec("pgrep", "-x", "ghostty")
            return code == 0
        except Exception as e:
            logger.debug(f"Ghostty 実行チェックをスキップ: {e}")
            return False

    async def _open_in_tab(self, command: str) -> bool:
        """既存の Ghostty ウィンドウに新しいタブを開いてコマンドを実行する。"""
        escaped_command = self._escape_applescript_string(command)
        applescript = f'''
-- コマンドをクリップボードに設定
set the clipboard to "{escaped_command}"

tell application "Ghostty"
    activate
end tell

tell application "System Events"
    if exists process "Ghostty" then
        tell process "Ghostty"
            -- locale 非依存で新しいタブを開く
            keystroke "t" using command down
            delay 0.5

            -- クリップボードから貼り付け（Cmd+V）
            keystroke "v" using command down
            delay 0.1
            keystroke return
        end tell
    else if exists process "ghostty" then
        tell process "ghostty"
            -- locale 非依存で新しいタブを開く
            keystroke "t" using command down
            delay 0.5

            -- クリップボードから貼り付け（Cmd+V）
            keystroke "v" using command down
            delay 0.1
            keystroke return
        end tell
    else
        error "Ghostty process not found"
    end if
end tell
'''
        try:
            code, _, _ = await self._run_osascript(applescript)
            if code == 0:
                await asyncio.sleep(0.5)
                return True
            return False
        except Exception as e:
            logger.warning(f"Ghostty タブ追加に失敗: {e}")
            return False

    async def _maximize_window(self) -> None:
        """Ghostty ウィンドウを画面サイズに合わせる（fill arrange）。"""
        applescript = '''
tell application "System Events"
    tell process "Ghostty"
        if exists window 1 then
            -- メイン画面のサイズを取得
            set screenWidth to 1920
            set screenHeight to 1080
            try
                tell application "Finder"
                    set desktopBounds to bounds of window of desktop
                    set screenWidth to (item 3 of desktopBounds) - (item 1 of desktopBounds)
                    set screenHeight to (item 4 of desktopBounds) - (item 2 of desktopBounds)
                end tell
            end try

            -- ウィンドウを画面左上に配置し、画面サイズに合わせる
            -- メニューバー(25px)とDock(70px程度)を考慮
            set position of window 1 to {0, 25}
            set size of window 1 to {screenWidth, screenHeight - 95}
        end if
    end tell
end tell
'''
        try:
            await self._run_osascript(applescript)
        except Exception as e:
            logger.warning(f"ウィンドウ最大化に失敗: {e}")
