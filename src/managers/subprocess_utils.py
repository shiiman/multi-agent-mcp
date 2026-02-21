"""サブプロセス共通ユーティリティ。

タイムアウト処理、エラー構築など、複数マネージャーで共通のサブプロセス操作を提供する。
"""

import asyncio
import json
import logging
from typing import Any

from src.config.constants import KILL_WAIT_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


async def cleanup_timed_out_process(
    proc: asyncio.subprocess.Process,
    kill_wait_timeout: float = KILL_WAIT_TIMEOUT_SECONDS,
) -> None:
    """タイムアウトしたプロセスを確実に終了する。"""
    try:
        if proc.returncode is None:
            proc.kill()
        await asyncio.wait_for(proc.wait(), timeout=kill_wait_timeout)
    except asyncio.TimeoutError:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=1.0)
        except Exception as cleanup_error:
            logger.warning("タイムアウト後のプロセス終了に失敗: %s", cleanup_error)
    except Exception as cleanup_error:
        logger.warning("タイムアウト後のクリーンアップに失敗: %s", cleanup_error)


def build_subprocess_error(
    *,
    kind: str,
    command: str,
    message: str,
    timeout_seconds: float | None = None,
    cwd: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """構造化された subprocess エラー情報を構築する。

    Returns:
        (JSON 文字列, エラー情報 dict) のタプル
    """
    error_info: dict[str, Any] = {
        "kind": kind,
        "message": message,
    }
    if timeout_seconds is not None:
        error_info["timeout_seconds"] = timeout_seconds
    if cwd is not None:
        error_info["cwd"] = cwd
    return json.dumps(error_info, ensure_ascii=False), error_info
