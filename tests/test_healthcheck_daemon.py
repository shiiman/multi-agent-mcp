"""healthcheck daemon のテスト。"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.healthcheck_daemon import (
    ensure_healthcheck_daemon_started,
    is_healthcheck_daemon_running,
    start_healthcheck_daemon,
)
from src.models.agent import Agent, AgentRole, AgentStatus


@pytest.mark.asyncio
async def test_healthcheck_daemon_auto_stops_on_idle(temp_dir, settings):
    settings.healthcheck_interval_seconds = 1
    settings.healthcheck_idle_stop_consecutive = 1

    tmux = MagicMock()
    ai_cli = AiCliManager(settings)

    now = datetime.now()
    worker = Agent(
        id="worker-001",
        role=AgentRole.WORKER,
        status=AgentStatus.IDLE,
        tmux_session="test:0.1",
        session_name="test",
        window_index=0,
        pane_index=1,
        current_task=None,
        created_at=now,
        last_activity=now,
    )

    app_ctx = AppContext(
        settings=settings,
        tmux=tmux,
        ai_cli=ai_cli,
        agents={worker.id: worker},
        project_root=str(temp_dir),
        session_id="test-session",
    )

    app_ctx.healthcheck_manager = MagicMock()
    app_ctx.healthcheck_manager.monitor_and_recover_workers = AsyncMock(
        return_value={
            "recovered": [],
            "escalated": [],
            "failed_tasks": [],
            "skipped": [worker.id],
        }
    )

    started = await start_healthcheck_daemon(app_ctx)
    assert started is True

    for _ in range(20):
        if not is_healthcheck_daemon_running(app_ctx):
            break
        await asyncio.sleep(0.1)

    assert is_healthcheck_daemon_running(app_ctx) is False


@pytest.mark.asyncio
async def test_healthcheck_daemon_not_started_without_workers(temp_dir, settings):
    tmux = MagicMock()
    ai_cli = AiCliManager(settings)

    app_ctx = AppContext(
        settings=settings,
        tmux=tmux,
        ai_cli=ai_cli,
        agents={},
        project_root=str(temp_dir),
        session_id="test-session",
    )

    started = await ensure_healthcheck_daemon_started(app_ctx)
    assert started is False
