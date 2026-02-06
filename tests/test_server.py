"""server モジュールのテスト。"""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_app_lifespan_does_not_cleanup_tmux_sessions(monkeypatch):
    """サーバー終了時に tmux セッションを自動クリーンアップしないことをテスト。"""
    from src import server

    mock_cleanup = AsyncMock(return_value=3)

    class DummyTmux:
        def __init__(self, settings):
            self.settings = settings
            self.cleanup_all_sessions = mock_cleanup

    monkeypatch.setattr(server, "TmuxManager", DummyTmux)
    monkeypatch.setattr(server, "AiCliManager", lambda settings: MagicMock())

    async with server.app_lifespan(server.mcp) as app_ctx:
        assert app_ctx.tmux is not None

    mock_cleanup.assert_not_awaited()
