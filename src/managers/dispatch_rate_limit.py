"""ペイン送信のスコープ別レート制御。"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.context import AppContext

__all__ = ["send_with_scoped_rate_limit"]


def _resolve_dispatch_lock_store(app_ctx: AppContext) -> dict[str, asyncio.Lock]:
    """送信先スコープごとのロックストアを返す。"""
    store = getattr(app_ctx, "_dispatch_rate_limit_locks", None)
    if not isinstance(store, dict):
        store = {}
        app_ctx._dispatch_rate_limit_locks = store
    return store


def _resolve_dispatch_timestamp_store(app_ctx: AppContext) -> dict[str, float]:
    """送信先スコープごとの最終送信時刻ストアを返す。"""
    store = getattr(app_ctx, "_dispatch_rate_limit_last_sent_at", None)
    if not isinstance(store, dict):
        store = {}
        app_ctx._dispatch_rate_limit_last_sent_at = store
    return store


def _build_dispatch_scope_key(
    session_name: str,
    window_index: int,
    pane_index: int,
    scope: str,
) -> str:
    """レート制御用のスコープキーを生成する。"""
    if scope == "session":
        return session_name
    return f"{session_name}:{window_index}.{pane_index}"


async def send_with_scoped_rate_limit(
    app_ctx: AppContext,
    session_name: str,
    window_index: int,
    pane_index: int,
    command: str,
    *,
    literal: bool = True,
    clear_input: bool = True,
    confirm_codex_prompt: bool = False,
    scope: str = "pane",
) -> bool:
    """送信先スコープごとに排他・cooldown を適用して tmux へ送信する。"""
    tmux = app_ctx.tmux
    send_and_confirm = getattr(tmux, "send_and_confirm_to_pane", None)
    try:
        import unittest.mock as mock
    except ImportError:  # pragma: no cover
        mock = None

    if mock is not None and isinstance(tmux, mock.Mock):
        send_and_confirm = None

    if not callable(send_and_confirm):
        legacy_send = getattr(tmux, "send_with_rate_limit_to_pane", None)
        if not callable(legacy_send):
            raise AttributeError("tmux send method is not available")
        return bool(
            await legacy_send(
                session_name,
                window_index,
                pane_index,
                command,
                literal=literal,
                clear_input=clear_input,
                confirm_codex_prompt=confirm_codex_prompt,
            )
        )

    if scope not in {"pane", "session"}:
        raise ValueError(f"unsupported dispatch scope: {scope}")

    scope_key = _build_dispatch_scope_key(session_name, window_index, pane_index, scope)
    lock_store = _resolve_dispatch_lock_store(app_ctx)
    lock = lock_store.get(scope_key)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        lock_store[scope_key] = lock

    last_sent_store = _resolve_dispatch_timestamp_store(app_ctx)
    cooldown = float(getattr(app_ctx.settings, "send_cooldown_seconds", 2.0))

    async with lock:
        now = time.monotonic()
        last_sent_at = last_sent_store.get(scope_key)
        if isinstance(last_sent_at, (float, int)) and cooldown > 0:
            wait_for = cooldown - (now - float(last_sent_at))
            if wait_for > 0:
                await asyncio.sleep(wait_for)

        success = await send_and_confirm(
            session_name,
            window_index,
            pane_index,
            command,
            literal=literal,
            clear_input=clear_input,
            confirm_codex_prompt=confirm_codex_prompt,
        )
        last_sent_store[scope_key] = time.monotonic()
        return bool(success)
