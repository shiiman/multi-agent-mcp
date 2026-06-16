"""cmux ターミナル実装。"""

import asyncio
import logging
import shutil
from pathlib import Path

from .base import TerminalExecutor

logger = logging.getLogger(__name__)


class CmuxExecutor(TerminalExecutor):
    """cmux でスクリプトを実行するクラス。

    既存の cmux がある場合は Cmd+N で新しい workspace を開く。
    """

    @property
    def name(self) -> str:
        return "cmux"

    def _get_cmux_path(self) -> str | None:
        """cmux の実行パスを取得する。"""
        cmux_path = shutil.which("cmux")
        if not cmux_path:
            macos_cmux = Path("/Applications/cmux.app/Contents/MacOS/cmux")
            if macos_cmux.exists():
                cmux_path = str(macos_cmux)
        return cmux_path

    async def is_available(self) -> bool:
        """cmux が利用可能か確認する。"""
        if self._get_cmux_path() is not None:
            return True
        return Path("/Applications/cmux.app").exists()

    async def execute_script(
        self, working_dir: str, script: str, script_path: str
    ) -> tuple[bool, str]:
        """cmux でスクリプトを実行する。

        既存の cmux がある場合は新しい workspace を開く。
        """
        cmux_path = self._get_cmux_path()
        has_app = Path("/Applications/cmux.app").exists()

        if not cmux_path and not has_app:
            return False, "cmux が見つかりません"

        session_name = self._extract_session_name(script)

        try:
            # 既存の cmux プロセスがある場合は workspace を開く
            if await self._is_running():
                success = await self._open_workspace(
                    f'exec bash "{script_path}"'
                )
                if success:
                    return (
                        True,
                        "cmux の新しい workspace でスクリプトを開きました",
                    )
                # workspace 追加に失敗した場合は新しいウィンドウで開く

            # 新しいウィンドウで開く
            if cmux_path:
                proc = await asyncio.create_subprocess_exec(
                    cmux_path,
                    f"--working-directory={working_dir}",
                    f"--title={session_name}",
                    "-e",
                    script_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            elif has_app:
                proc = await asyncio.create_subprocess_exec(
                    "open",
                    "-na",
                    "cmux.app",
                    "--args",
                    f"--working-directory={working_dir}",
                    f"--title={session_name}",
                    "-e",
                    script_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            else:
                return False, "cmux の実行パスが見つかりません"

            # プロセス起動を確認するために少し待つ
            await asyncio.sleep(0.5)

            # プロセスがまだ動いていれば成功（tmux attach で待機中）
            if proc.returncode is None:
                return True, "cmux でワークスペースを開きました"
            else:
                return False, (
                    f"cmux の起動に失敗しました (code: {proc.returncode})"
                )

        except Exception as e:
            logger.error("cmux 起動エラー: %s", e)
            return False, f"cmux 起動エラー: {e}"

    async def _is_running(self) -> bool:
        """cmux が起動中かを確認する。"""
        applescript = """
        if application "cmux" is running then
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
            code, _, _ = await self._run_exec("pgrep", "-x", "cmux")
            return code == 0
        except Exception as e:
            logger.debug("cmux 実行チェックをスキップ: %s", e)
            return False

    async def close_workspace(self, session_name: str) -> bool:
        """セッション名に対応する cmux workspace を閉じる。

        1. ウィンドウタイトルでセッション名を検索してフォーカス
        2. tmux セッションを kill（タイトルが変わる前に検索済み）
        3. Cmd+W で workspace を閉じる

        Args:
            session_name: tmux セッション名（ウィンドウタイトルのマッチングに使用）

        Returns:
            workspace を閉じた場合 True
        """
        if not await self._is_running():
            return False

        # ① ウィンドウタイトルで対象を検索してフォーカス
        escaped_name = self._escape_applescript_string(session_name)
        find_script = f'''
tell application "System Events"
    if exists process "cmux" then
        tell process "cmux"
            set windowList to windows
            repeat with w in windowList
                if name of w contains "{escaped_name}" then
                    perform action "AXRaise" of w
                    return "found"
                end if
            end repeat
        end tell
    end if
end tell
return "not_found"
'''
        try:
            code, stdout, _ = await self._run_osascript(find_script)
            if code != 0 or stdout.strip().lower() != "found":
                logger.debug(
                    "cmux workspace が見つかりませんでした: %s",
                    session_name,
                )
                return False

            # ② tmux セッションを kill（ウィンドウ特定済みなので安全）
            await self._run_exec(
                "tmux", "kill-session", "-t", session_name
            )
            await asyncio.sleep(0.3)

            # ③ cmux を最前面にして Cmd+W で workspace を閉じる
            close_script = '''
tell application "cmux"
    activate
end tell
delay 0.3

tell application "System Events"
    tell process "cmux"
        -- 最前面ウィンドウを閉じる（②で対象を AXRaise 済み）
        keystroke "w" using command down
        delay 0.3
        return "closed"
    end tell
end tell
'''
            code, stdout, _ = await self._run_osascript(close_script)
            if code == 0 and "closed" in stdout.lower():
                logger.info(
                    "cmux workspace を閉じました: %s", session_name
                )
                return True
            return False
        except Exception as e:
            logger.warning(
                "cmux workspace クローズに失敗: %s (%s)", session_name, e
            )
            return False

    async def _open_workspace(self, command: str) -> bool:
        """既存の cmux で新しい workspace を開いてコマンドを実行する。"""
        escaped_command = self._escape_applescript_string(command)
        applescript = f'''
-- コマンドをクリップボードに設定
set the clipboard to "{escaped_command}"

tell application "cmux"
    activate
end tell

tell application "System Events"
    if exists process "cmux" then
        tell process "cmux"
            -- Cmd+N で新しい workspace を開く
            keystroke "n" using command down
            delay 0.5

            -- クリップボードから貼り付け（Cmd+V）
            keystroke "v" using command down
            delay 0.1
            keystroke return
        end tell
    else
        error "cmux process not found"
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
            logger.warning("cmux workspace 追加に失敗: %s", e)
            return False
