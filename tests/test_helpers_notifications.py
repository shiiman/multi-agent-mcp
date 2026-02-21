"""tools/helpers_notifications.py のテスト。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.tools.helpers_notifications import notify_agent_via_tmux


def _build_app_ctx(send_side_effect):
    """通知テスト用の最小 AppContext 互換オブジェクトを作成する。"""
    tmux = SimpleNamespace(send_with_rate_limit_to_pane=AsyncMock(side_effect=send_side_effect))
    ai_cli = SimpleNamespace(get_default_cli=lambda: "codex")
    return SimpleNamespace(tmux=tmux, ai_cli=ai_cli)


class TestNotifyAgentViaTmux:
    """notify_agent_via_tmux のテスト。"""

    @pytest.mark.asyncio
    async def test_returns_false_when_agent_has_no_tmux_slot(self):
        """tmux 情報不足のエージェントは通知失敗扱いになることをテスト。"""
        app_ctx = _build_app_ctx(send_side_effect=[True])
        agent = SimpleNamespace(id="worker-001", session_name=None, pane_index=None, window_index=0)

        result = await notify_agent_via_tmux(
            app_ctx=app_ctx,
            agent=agent,
            msg_type_value="task_progress",
            sender_id="admin-001",
        )

        assert result is False
        assert app_ctx.tmux.send_with_rate_limit_to_pane.call_count == 0

    @pytest.mark.asyncio
    async def test_retries_and_succeeds_before_max_attempts(self):
        """初回失敗・2回目成功時に True を返すことをテスト。"""
        app_ctx = _build_app_ctx(send_side_effect=[False, True])
        agent = SimpleNamespace(
            id="worker-001",
            session_name="test-session",
            pane_index=1,
            window_index=0,
            ai_cli="codex",
        )

        with patch("src.tools.helpers_notifications.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            result = await notify_agent_via_tmux(
                app_ctx=app_ctx,
                agent=agent,
                msg_type_value="task_progress",
                sender_id="admin-001",
            )

        assert result is True
        assert app_ctx.tmux.send_with_rate_limit_to_pane.call_count == 2
        sleep_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_uses_macos_fallback_when_all_tmux_retries_fail(self):
        """tmux 全失敗時に allow_macos_fallback=True でフォールバックすることをテスト。"""
        app_ctx = _build_app_ctx(send_side_effect=[False, False, False])
        agent = SimpleNamespace(
            id="worker-001",
            session_name="test-session",
            pane_index=1,
            window_index=0,
            ai_cli="codex",
        )

        with (
            patch("src.tools.helpers_notifications.asyncio.sleep", new=AsyncMock()),
            patch(
                "src.tools.helpers_notifications._send_macos_notification",
                new=AsyncMock(return_value=True),
            ) as fallback_mock,
        ):
            result = await notify_agent_via_tmux(
                app_ctx=app_ctx,
                agent=agent,
                msg_type_value="task_complete",
                sender_id="worker-001",
                allow_macos_fallback=True,
            )

        assert result is False
        fallback_mock.assert_awaited_once_with("task_complete", "worker-001")

    @pytest.mark.asyncio
    async def test_retries_after_runtime_error_and_then_succeeds(self):
        """送信中例外後にリトライして成功できることをテスト。"""
        app_ctx = _build_app_ctx(send_side_effect=[RuntimeError("tmux error"), True])
        agent = SimpleNamespace(
            id="worker-001",
            session_name="test-session",
            pane_index=1,
            window_index=0,
            ai_cli="codex",
        )

        with patch("src.tools.helpers_notifications.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            result = await notify_agent_via_tmux(
                app_ctx=app_ctx,
                agent=agent,
                msg_type_value="task_failed",
                sender_id="admin-001",
            )

        assert result is True
        assert app_ctx.tmux.send_with_rate_limit_to_pane.call_count == 2
        sleep_mock.assert_awaited_once()
