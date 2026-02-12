"""healthcheck daemon のテスト。"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.healthcheck_daemon import (
    _list_workers,
    _should_auto_stop,
    ensure_healthcheck_daemon_started,
    is_healthcheck_daemon_running,
    start_healthcheck_daemon,
    stop_healthcheck_daemon,
)
from src.models.agent import Agent, AgentRole, AgentStatus


def _make_daemon_ctx(temp_dir, settings, agents=None):
    """daemon テスト用の AppContext を作成する。"""
    tmux = MagicMock()
    ai_cli = AiCliManager(settings)

    ctx = AppContext(
        settings=settings,
        tmux=tmux,
        ai_cli=ai_cli,
        agents=agents or {},
        project_root=str(temp_dir),
        session_id="test-session",
    )
    ctx.healthcheck_manager = MagicMock()
    ctx.healthcheck_manager.monitor_and_recover_workers = AsyncMock(
        return_value={
            "recovered": [],
            "escalated": [],
            "failed_tasks": [],
            "skipped": list((agents or {}).keys()),
        }
    )
    return ctx


def _make_idle_worker(worker_id="worker-001"):
    """idle 状態の Worker を作成する。"""
    now = datetime.now()
    return Agent(
        id=worker_id,
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


@pytest.mark.asyncio
async def test_healthcheck_daemon_auto_stops_on_idle(temp_dir, settings):
    """idle 状態が連続するとdaemonが自動停止する。"""
    settings.healthcheck_interval_seconds = 1
    settings.healthcheck_idle_stop_consecutive = 1

    worker = _make_idle_worker()
    app_ctx = _make_daemon_ctx(temp_dir, settings, {worker.id: worker})

    started = await start_healthcheck_daemon(app_ctx)
    assert started is True

    daemon_task = app_ctx.healthcheck_daemon_task
    assert daemon_task is not None
    await asyncio.wait_for(daemon_task, timeout=5.0)

    assert is_healthcheck_daemon_running(app_ctx) is False


@pytest.mark.asyncio
async def test_healthcheck_daemon_notifies_on_auto_stop(temp_dir, settings):
    """auto-stop 時に停止通知を送信する。"""
    settings.healthcheck_interval_seconds = 1
    settings.healthcheck_idle_stop_consecutive = 1

    worker = _make_idle_worker()
    app_ctx = _make_daemon_ctx(temp_dir, settings, {worker.id: worker})
    app_ctx.agents["admin-001"] = Agent(
        id="admin-001",
        role=AgentRole.ADMIN,
        status=AgentStatus.IDLE,
        tmux_session="test:0.0",
        session_name="test",
        window_index=0,
        pane_index=0,
        current_task=None,
        created_at=datetime.now(),
        last_activity=datetime.now(),
    )

    with patch("src.managers.healthcheck_daemon._notify_daemon_stopped", new=AsyncMock()) as notify:
        started = await start_healthcheck_daemon(app_ctx)
        assert started is True
        daemon_task = app_ctx.healthcheck_daemon_task
        assert daemon_task is not None
        await asyncio.wait_for(daemon_task, timeout=5.0)

    notify.assert_awaited_once()
    assert notify.await_args.kwargs["stop_reason"] == "auto_stop_idle"


@pytest.mark.asyncio
async def test_healthcheck_daemon_notifies_on_auto_stop_check_failure(temp_dir, settings):
    """auto-stop 判定例外時に停止通知を送信する。"""
    settings.healthcheck_interval_seconds = 1
    settings.healthcheck_idle_stop_consecutive = 10

    worker = _make_idle_worker()
    app_ctx = _make_daemon_ctx(temp_dir, settings, {worker.id: worker})

    with (
        patch(
            "src.managers.healthcheck_daemon._should_auto_stop",
            side_effect=RuntimeError("boom"),
        ),
        patch("src.managers.healthcheck_daemon._notify_daemon_stopped", new=AsyncMock()) as notify,
    ):
        started = await start_healthcheck_daemon(app_ctx)
        assert started is True
        daemon_task = app_ctx.healthcheck_daemon_task
        assert daemon_task is not None
        await asyncio.wait_for(daemon_task, timeout=5.0)

    notify.assert_awaited_once()
    assert notify.await_args.kwargs["stop_reason"] == "auto_stop_check_failed"


@pytest.mark.asyncio
async def test_healthcheck_daemon_not_started_without_workers(temp_dir, settings):
    """Worker 不在時は daemon を起動しない。"""
    app_ctx = _make_daemon_ctx(temp_dir, settings)

    started = await ensure_healthcheck_daemon_started(app_ctx)
    assert started is False


@pytest.mark.asyncio
async def test_duplicate_start_returns_false(temp_dir, settings):
    """既に起動中の daemon に対して start を呼ぶと False を返す。"""
    settings.healthcheck_interval_seconds = 10
    settings.healthcheck_idle_stop_consecutive = 100

    worker = _make_idle_worker()
    app_ctx = _make_daemon_ctx(temp_dir, settings, {worker.id: worker})

    first = await start_healthcheck_daemon(app_ctx)
    assert first is True
    assert is_healthcheck_daemon_running(app_ctx) is True

    second = await start_healthcheck_daemon(app_ctx)
    assert second is False

    # クリーンアップ
    await stop_healthcheck_daemon(app_ctx, timeout_seconds=2.0)


@pytest.mark.asyncio
async def test_stop_healthcheck_daemon(temp_dir, settings):
    """stop_healthcheck_daemon で daemon を正常に停止できる。"""
    settings.healthcheck_interval_seconds = 10
    settings.healthcheck_idle_stop_consecutive = 100

    worker = _make_idle_worker()
    app_ctx = _make_daemon_ctx(temp_dir, settings, {worker.id: worker})

    await start_healthcheck_daemon(app_ctx)
    assert is_healthcheck_daemon_running(app_ctx) is True

    stopped = await stop_healthcheck_daemon(app_ctx, timeout_seconds=2.0)
    assert stopped is True
    assert is_healthcheck_daemon_running(app_ctx) is False


@pytest.mark.asyncio
async def test_stop_when_not_running_returns_false(temp_dir, settings):
    """daemon が起動していない状態で stop を呼ぶと False を返す。"""
    app_ctx = _make_daemon_ctx(temp_dir, settings)

    stopped = await stop_healthcheck_daemon(app_ctx)
    assert stopped is False


def test_list_workers_excludes_terminated(temp_dir, settings):
    """_list_workers は TERMINATED な Worker を除外する。"""
    now = datetime.now()
    worker_active = Agent(
        id="w-1",
        role=AgentRole.WORKER,
        status=AgentStatus.IDLE,
        tmux_session="t:0.1",
        created_at=now,
        last_activity=now,
    )
    worker_terminated = Agent(
        id="w-2",
        role=AgentRole.WORKER,
        status=AgentStatus.TERMINATED,
        tmux_session="t:0.2",
        created_at=now,
        last_activity=now,
    )
    app_ctx = _make_daemon_ctx(
        temp_dir, settings, {"w-1": worker_active, "w-2": worker_terminated}
    )

    workers = _list_workers(app_ctx)
    worker_ids = [w.id for w in workers]
    assert "w-1" in worker_ids
    assert "w-2" not in worker_ids


def test_should_auto_stop_with_no_workers(temp_dir, settings):
    """Worker がいない場合は auto-stop 条件を満たす。"""
    app_ctx = _make_daemon_ctx(temp_dir, settings)
    assert _should_auto_stop(app_ctx) is True
