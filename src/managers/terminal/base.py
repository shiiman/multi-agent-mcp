"""ターミナル実行の基底クラス。"""

import asyncio
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class TerminalExecutor(ABC):
    """ターミナルアプリでスクリプトを実行する基底クラス。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """ターミナルアプリの名前。"""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """ターミナルアプリが利用可能か確認する。"""
        ...

    @abstractmethod
    async def execute_script(
        self, working_dir: str, script: str, script_path: str
    ) -> tuple[bool, str]:
        """スクリプトを実行する。

        Args:
            working_dir: 作業ディレクトリのパス
            script: 実行するシェルスクリプト（セッション名抽出用）
            script_path: スクリプトファイルのパス

        Returns:
            (成功したかどうか, メッセージ) のタプル
        """
        ...

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

    async def _run_exec(self, *args: str) -> tuple[int, str, str]:
        """コマンドを引数分離で実行する。

        Args:
            *args: 実行コマンドと引数

        Returns:
            (リターンコード, stdout, stderr) のタプル
        """
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

    async def _run_osascript(self, script: str) -> tuple[int, str, str]:
        """AppleScript を安全に実行する。"""
        return await self._run_exec("osascript", "-e", script)

    def _escape_applescript_string(self, value: str) -> str:
        """AppleScript 文字列用にエスケープする。"""
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _extract_session_name(self, script: str) -> str:
        """スクリプトからセッション名を抽出する。

        Args:
            script: シェルスクリプト

        Returns:
            セッション名（見つからない場合は "MCP Workspace"）
        """
        for line in script.split("\n"):
            if line.startswith("SESSION="):
                return line.split("=")[1].strip('"')
        return "MCP Workspace"
