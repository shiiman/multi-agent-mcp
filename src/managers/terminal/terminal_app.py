"""macOS Terminal.app ターミナル実装。"""

import logging

from .base import TerminalExecutor

logger = logging.getLogger(__name__)


class TerminalAppExecutor(TerminalExecutor):
    """macOS Terminal.app でスクリプトを実行するクラス。"""

    @property
    def name(self) -> str:
        return "Terminal.app"

    async def is_available(self) -> bool:
        """Terminal.app が利用可能か確認する。

        macOS では常に利用可能。
        """
        return True

    async def execute_script(
        self, working_dir: str, script: str, script_path: str
    ) -> tuple[bool, str]:
        """Terminal.app でスクリプトを実行する。

        既存のウィンドウがある場合は新しいタブとして開く。
        """
        try:
            escaped_script_path = self._escape_applescript_string(script_path)
            # 既存ウィンドウがあればタブ、なければ新規ウィンドウ
            applescript = f'''
tell application "Terminal"
    activate
    if (count of windows) > 0 then
        -- 既存ウィンドウに新しいタブを作成
        tell front window
            set newTab to do script "{escaped_script_path}"
        end tell
        return "tab"
    else
        -- 新しいウィンドウを作成
        do script "{escaped_script_path}"
        return "window"
    end if
end tell
'''
            code, stdout, stderr = await self._run_osascript(applescript)

            if code == 0:
                if "tab" in stdout.lower():
                    return True, "Terminal.app の新しいタブでワークスペースを開きました"
                return True, "Terminal.app でワークスペースを開きました"
            else:
                error_msg = stderr.strip() if stderr else "不明なエラー"
                return False, f"Terminal.app の起動に失敗しました: {error_msg}"

        except Exception as e:
            logger.error(f"Terminal.app 起動エラー: {e}")
            return False, f"Terminal.app 起動エラー: {e}"
