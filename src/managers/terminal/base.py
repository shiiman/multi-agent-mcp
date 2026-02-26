"""ターミナル実行の基底クラス。"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from src.config.constants import KILL_WAIT_TIMEOUT_SECONDS, SUBPROCESS_TIMEOUT_SECONDS
from src.managers.subprocess_utils import (
    build_subprocess_error,
    cleanup_timed_out_process,
)

logger = logging.getLogger(__name__)


class TerminalExecutor(ABC):
    """ターミナルアプリでスクリプトを実行する基底クラス。"""

    def __init__(self) -> None:
        self.last_subprocess_error: dict[str, Any] | None = None

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

    def _set_subprocess_error(
        self,
        *,
        kind: str,
        message: str,
        timeout_seconds: float | None = None,
        cwd: str | None = None,
    ) -> str:
        """構造化された subprocess エラー情報を設定し JSON 文字列を返す。"""
        json_str, error_info = build_subprocess_error(
            kind=kind,
            command="",
            message=message,
            timeout_seconds=timeout_seconds,
            cwd=cwd,
        )
        self.last_subprocess_error = error_info
        return json_str

    async def _run_shell(self, command: str) -> tuple[int, str, str]:
        """シェルコマンドを実行する。

        Args:
            command: 実行するシェルコマンド

        Returns:
            (リターンコード, stdout, stderr) のタプル
        """
        self.last_subprocess_error = None
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
            return proc.returncode or 0, stdout.decode(), stderr.decode()
        except asyncio.TimeoutError:
            await cleanup_timed_out_process(proc, KILL_WAIT_TIMEOUT_SECONDS)
            return 124, "", self._set_subprocess_error(
                kind="timeout",
                message="サブプロセス実行がタイムアウトしました",
                timeout_seconds=SUBPROCESS_TIMEOUT_SECONDS,
            )
        except Exception as e:
            logger.error(f"シェルコマンド実行エラー: {e}")
            return 1, "", self._set_subprocess_error(
                kind="spawn_error",
                message=str(e),
            )

    async def _run_exec(self, *args: str) -> tuple[int, str, str]:
        """コマンドを引数分離で実行する。

        Args:
            *args: 実行コマンドと引数

        Returns:
            (リターンコード, stdout, stderr) のタプル
        """
        self.last_subprocess_error = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
            return proc.returncode or 0, stdout.decode(), stderr.decode()
        except asyncio.TimeoutError:
            await cleanup_timed_out_process(proc, KILL_WAIT_TIMEOUT_SECONDS)
            return 124, "", self._set_subprocess_error(
                kind="timeout",
                message="コマンド実行がタイムアウトしました",
                timeout_seconds=SUBPROCESS_TIMEOUT_SECONDS,
            )
        except Exception as e:
            logger.error(f"コマンド実行エラー: {e}")
            return 1, "", self._set_subprocess_error(
                kind="spawn_error",
                message=str(e),
            )

    async def _run_osascript(self, script: str) -> tuple[int, str, str]:
        """AppleScript を安全に実行する。"""
        return await self._run_exec("osascript", "-e", script)

    def _escape_applescript_string(self, value: str) -> str:
        """AppleScript 文字列用にエスケープする。"""
        return value.replace("\\", "\\\\").replace('"', '\\"')

    async def close_workspace(self, session_name: str) -> bool:
        """セッション名に対応するターミナル workspace を閉じる。

        デフォルトは何もしない（no-op）。
        ターミナル固有の実装でオーバーライドする。

        Args:
            session_name: tmux セッション名（ウィンドウタイトルのマッチングに使用）

        Returns:
            workspace を閉じた場合 True
        """
        return False

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
