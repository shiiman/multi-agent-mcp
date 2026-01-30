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
