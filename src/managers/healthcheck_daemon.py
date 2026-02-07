"""Health check 常駐監視ループ。"""

import asyncio
import logging

from src.models.agent import AgentRole, AgentStatus

logger = logging.getLogger(__name__)

# 連続エラーの閾値
_CONSECUTIVE_ERROR_REINIT_THRESHOLD = 3
_CONSECUTIVE_ERROR_STOP_THRESHOLD = 5
# 即座に停止すべき致命的例外
_FATAL_EXCEPTIONS = (ImportError, AttributeError, TypeError)


def is_healthcheck_daemon_running(app_ctx) -> bool:
    """health check daemon が稼働中かどうか。"""
    task = app_ctx.healthcheck_daemon_task
    return task is not None and not task.done()


def _list_workers(app_ctx) -> list:
    """現在の Worker 一覧を返す。"""
    return [
        agent
        for agent in app_ctx.agents.values()
        if agent.role == AgentRole.WORKER.value and agent.status != AgentStatus.TERMINATED
    ]


def _should_auto_stop(app_ctx) -> bool:
    """daemon 自動停止条件を満たすか判定する。

    PENDINGタスクがある場合はauto-stopしない（まだ割り当てが必要なため）。
    """
    workers = _list_workers(app_ctx)
    if not workers:
        return True

    all_idle = all(
        (worker.status == AgentStatus.IDLE or worker.status == AgentStatus.IDLE.value)
        and not worker.current_task
        for worker in workers
    )

    in_progress_tasks = 0
    pending_tasks = 0
    try:
        from src.tools.helpers_managers import ensure_dashboard_manager

        dashboard = ensure_dashboard_manager(app_ctx)
        summary = dashboard.get_summary()
        in_progress_tasks = int(summary.get("in_progress_tasks", 0))
        pending_tasks = int(summary.get("pending_tasks", 0))
    except (OSError, ValueError, KeyError):
        in_progress_tasks = sum(
            1
            for worker in workers
            if worker.current_task
            or worker.status == AgentStatus.BUSY
            or worker.status == AgentStatus.BUSY.value
        )

    # PENDINGタスクがある場合はauto-stopしない
    if pending_tasks > 0:
        return False

    return in_progress_tasks == 0 and all_idle


async def _run_healthcheck_loop(app_ctx) -> None:
    """health check の常駐ループ本体。"""
    consecutive_errors = 0
    try:
        while True:
            stop_event = app_ctx.healthcheck_daemon_stop_event
            if stop_event is None or stop_event.is_set():
                break

            try:
                from src.tools.helpers import sync_agents_from_file
                from src.tools.helpers_managers import ensure_healthcheck_manager

                sync_agents_from_file(app_ctx)
                healthcheck = ensure_healthcheck_manager(app_ctx)
                result = await healthcheck.monitor_and_recover_workers(app_ctx)
                escalated = result.get("escalated", [])
                failed = result.get("failed_tasks", [])
                if escalated or failed:
                    logger.warning(
                        "healthcheck daemon: recovered=%s escalated=%s failed=%s",
                        len(result.get("recovered", [])),
                        len(escalated),
                        len(failed),
                    )
                # 正常サイクル: エラーカウンターリセット
                consecutive_errors = 0
            except _FATAL_EXCEPTIONS as e:
                # 致命的例外: 即座に daemon 停止
                logger.error(
                    "healthcheck daemon 致命的エラーにより停止: %s", e
                )
                break
            except Exception as e:
                consecutive_errors += 1
                logger.warning(
                    "healthcheck daemon loop error (consecutive=%d): %s",
                    consecutive_errors,
                    e,
                )
                if consecutive_errors >= _CONSECUTIVE_ERROR_STOP_THRESHOLD:
                    logger.error(
                        "healthcheck daemon を停止: 連続 %d 回エラー",
                        consecutive_errors,
                    )
                    break
                if consecutive_errors >= _CONSECUTIVE_ERROR_REINIT_THRESHOLD:
                    logger.warning(
                        "healthcheck daemon を再初期化: 連続 %d 回エラー",
                        consecutive_errors,
                    )
                    # healthcheck_manager をリセットして再初期化を促す
                    app_ctx.healthcheck_manager = None

            if _should_auto_stop(app_ctx):
                app_ctx.healthcheck_idle_cycles += 1
                if (
                    app_ctx.healthcheck_idle_cycles
                    >= app_ctx.settings.healthcheck_idle_stop_consecutive
                ):
                    logger.info(
                        "healthcheck daemon auto-stopped "
                        "(idle_count=%s)",
                        app_ctx.healthcheck_idle_cycles,
                    )
                    break
            else:
                app_ctx.healthcheck_idle_cycles = 0

            wait_seconds = max(1, int(app_ctx.settings.healthcheck_interval_seconds))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=wait_seconds)
            except asyncio.TimeoutError:
                pass
    finally:
        app_ctx.healthcheck_daemon_task = None
        app_ctx.healthcheck_daemon_stop_event = None
        app_ctx.healthcheck_idle_cycles = 0


async def start_healthcheck_daemon(app_ctx) -> bool:
    """health check daemon を開始する。"""
    if app_ctx.healthcheck_daemon_lock is None:
        app_ctx.healthcheck_daemon_lock = asyncio.Lock()

    async with app_ctx.healthcheck_daemon_lock:
        if is_healthcheck_daemon_running(app_ctx):
            return False

        app_ctx.healthcheck_daemon_stop_event = asyncio.Event()
        app_ctx.healthcheck_idle_cycles = 0
        app_ctx.healthcheck_daemon_task = asyncio.create_task(
            _run_healthcheck_loop(app_ctx),
            name="multi-agent-mcp-healthcheck-daemon",
        )
        logger.info("healthcheck daemon started")
        return True


async def stop_healthcheck_daemon(app_ctx, timeout_seconds: float = 5.0) -> bool:
    """health check daemon を停止する。"""
    if app_ctx.healthcheck_daemon_lock is None:
        app_ctx.healthcheck_daemon_lock = asyncio.Lock()

    async with app_ctx.healthcheck_daemon_lock:
        task = app_ctx.healthcheck_daemon_task
        if task is None:
            app_ctx.healthcheck_daemon_stop_event = None
            app_ctx.healthcheck_idle_cycles = 0
            return False

        stop_event = app_ctx.healthcheck_daemon_stop_event
        if stop_event is not None:
            stop_event.set()

        current = asyncio.current_task()
        if task is current:
            return True

        try:
            await asyncio.wait_for(task, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        app_ctx.healthcheck_daemon_task = None
        app_ctx.healthcheck_daemon_stop_event = None
        app_ctx.healthcheck_idle_cycles = 0
        logger.info("healthcheck daemon stopped")
        return True


async def ensure_healthcheck_daemon_started(app_ctx) -> bool:
    """Worker が存在する場合に daemon を開始する。"""
    if not _list_workers(app_ctx):
        return False
    return await start_healthcheck_daemon(app_ctx)
