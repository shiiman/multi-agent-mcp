"""iTerm2 ターミナル実装。"""

import logging

from .base import TerminalExecutor

logger = logging.getLogger(__name__)


class ITerm2Executor(TerminalExecutor):
    """iTerm2 でスクリプトを実行するクラス。"""

    @property
    def name(self) -> str:
        return "iTerm2"

    async def is_available(self) -> bool:
        """iTerm2 が利用可能か確認する。"""
        code, _, _ = await self._run_shell(
            "osascript -e 'application \"iTerm\" exists'"
        )
        return code == 0

    async def execute_script(
        self, working_dir: str, script: str, script_path: str
    ) -> tuple[bool, str]:
        """iTerm2 でスクリプトを実行する。

        既存のウィンドウがある場合は新しいタブとして開く。
        """
        if not await self.is_available():
            return False, "iTerm2 が見つかりません"

        try:
            # 既存ウィンドウがあればタブ、なければ新規ウィンドウ
            applescript = f'''
tell application "iTerm"
    activate
    if (count of windows) > 0 then
        -- 既存ウィンドウに新しいタブを作成
        tell current window
            create tab with default profile
            tell current session
                write text "{script_path}"
            end tell
        end tell
        return "tab"
    else
        -- 新しいウィンドウを作成
        create window with default profile
        tell current session of current window
            write text "{script_path}"
        end tell
        return "window"
    end if
end tell
'''
            code, stdout, stderr = await self._run_shell(
                f"osascript -e '{applescript}'"
            )

            if code == 0:
                if "tab" in stdout.lower():
                    return True, "iTerm2 の新しいタブでワークスペースを開きました"
                return True, "iTerm2 でワークスペースを開きました"
            else:
                error_msg = stderr.strip() if stderr else "不明なエラー"
                return False, f"iTerm2 の起動に失敗しました: {error_msg}"

        except Exception as e:
            logger.error(f"iTerm2 起動エラー: {e}")
            return False, f"iTerm2 起動エラー: {e}"
