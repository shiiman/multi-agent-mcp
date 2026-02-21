"""tmux/macOS 通知ヘルパー関数。

tmux 経由の IPC 通知送信や macOS ネイティブ通知のフォールバックを提供する。
"""

import asyncio
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


async def _send_macos_notification(msg_type_value: str, sender_id: str) -> bool:
    """macOS ネイティブ通知を送信する。

    Args:
        msg_type_value: メッセージタイプの値文字列
        sender_id: 送信元エージェントID

    Returns:
        送信成功時は True、失敗時は False
    """
    from src.managers.tmux_shared import escape_applescript

    try:
        notification_title = escape_applescript("Multi-Agent MCP")
        notification_body = escape_applescript(f"[IPC] {msg_type_value} from {sender_id}")
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{notification_body}" with title "{notification_title}"',
            ],
            capture_output=True,
            timeout=5,
        )
        return True
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("macOS 通知の送信に失敗: %s", e)
        return False


# tmux 通知リトライ設定
_TMUX_NOTIFY_MAX_RETRIES = 3
_TMUX_NOTIFY_RETRY_INTERVAL = 0.5


async def notify_agent_via_tmux(
    app_ctx: Any,
    agent: Any,
    msg_type_value: str,
    sender_id: str,
    *,
    allow_macos_fallback: bool = False,
) -> bool:
    """エージェントに tmux 経由で IPC 通知を送信する。

    最大3回リトライし、全て失敗かつ allow_macos_fallback=True の場合のみ
    macOS 通知にフォールバックする。

    Args:
        app_ctx: アプリケーションコンテキスト
        agent: 通知対象のエージェント
        msg_type_value: メッセージタイプの値文字列
        sender_id: 送信元エージェントID
        allow_macos_fallback: macOS フォールバック通知を許可するか

    Returns:
        送信成功時は True、失敗時は False
    """
    if not agent or not agent.session_name or agent.pane_index is None:
        logger.warning(
            "エージェントの tmux 情報が見つかりません: agent=%s sender=%s type=%s",
            getattr(agent, "id", "unknown"),
            sender_id,
            msg_type_value,
        )
        return False

    notification_text = f"[IPC] 新しいメッセージ: {msg_type_value} from {sender_id}"
    default_cli = app_ctx.ai_cli.get_default_cli()
    resolved_cli = agent.ai_cli or default_cli
    agent_cli = (
        resolved_cli.value if hasattr(resolved_cli, "value") else str(resolved_cli or "")
    ).lower()

    # リトライ付きで tmux 通知を送信
    for attempt in range(_TMUX_NOTIFY_MAX_RETRIES):
        try:
            success = await app_ctx.tmux.send_with_rate_limit_to_pane(
                agent.session_name,
                agent.window_index or 0,
                agent.pane_index,
                notification_text,
                clear_input=False,
                confirm_codex_prompt=agent_cli == "codex",
            )
            if success:
                logger.info(
                    "tmux 通知を送信: %s (attempt=%d)",
                    getattr(agent, "id", "unknown"),
                    attempt + 1,
                )
                return True
        except (OSError, RuntimeError) as e:
            logger.warning(
                "tmux 通知の送信に失敗 (attempt=%d): agent=%s sender=%s type=%s error=%s",
                attempt + 1,
                getattr(agent, "id", "unknown"),
                sender_id,
                msg_type_value,
                e,
            )

        if attempt < _TMUX_NOTIFY_MAX_RETRIES - 1:
            await asyncio.sleep(_TMUX_NOTIFY_RETRY_INTERVAL)

    # 全リトライ失敗
    logger.warning(
        "tmux 通知が %d 回失敗: agent=%s sender=%s type=%s target=%s:%s.%s",
        _TMUX_NOTIFY_MAX_RETRIES,
        getattr(agent, "id", "unknown"),
        sender_id,
        msg_type_value,
        agent.session_name,
        agent.window_index or 0,
        agent.pane_index,
    )
    if allow_macos_fallback:
        fallback_ok = await _send_macos_notification(msg_type_value, sender_id)
        if fallback_ok:
            logger.info(
                "macOS フォールバック通知を送信: %s",
                getattr(agent, "id", "unknown"),
            )
    return False
