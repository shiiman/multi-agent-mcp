"""エージェント batch 作成ツール実装。"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.context import AppContext

from mcp.server.fastmcp import Context, FastMCP

from src.managers.tmux_manager import MAIN_WINDOW_WORKER_PANES, get_project_name
from src.models.agent import Agent, AgentRole, AgentStatus
from src.tools.agent_helpers import (
    _create_worktree_for_worker,
    _post_create_agent,
    _send_task_to_worker,
    build_worker_task_branch,
    resolve_worker_number_from_slot,
)
from src.tools.helpers import ensure_dashboard_manager, require_permission, save_agent_to_file
from src.tools.model_profile import get_current_profile_settings

logger = logging.getLogger(__name__)

MAX_IMAGE_TASK_PARALLEL = 2


def _validate_batch_config(config: dict, worker_index: int) -> dict[str, Any] | None:
    """worker_config のバリデーション。エラー時は dict を返す。"""
    task_content = config.get("task_content")
    task_id = config.get("task_id")
    if task_content and not task_id:
        return {
            "success": False,
            "error": (
                f"Worker {worker_index + 1}: task_content を送信する場合は task_id が必須です"
            ),
            "worker_index": worker_index,
        }
    return None


async def _assign_and_dispatch_task(
    app_ctx: "AppContext",
    agent: Agent,
    task_id: str | None,
    task_content: str | None,
    branch: str,
    worktree_path: str,
    session_id: str | None,
    worker_index: int,
    enable_worktree: bool,
    profile_settings: dict,
    caller_agent_id: str | None,
) -> tuple[bool, str | None, bool, str, str | None]:
    """タスク割り当て＋送信の共通処理。

    Returns:
        (task_assigned, assignment_error, task_sent, dispatch_mode, dispatch_error)
    """
    task_assigned = False
    assignment_error: str | None = None
    dashboard = None
    if app_ctx.session_id and app_ctx.project_root:
        try:
            dashboard = ensure_dashboard_manager(app_ctx)
        except Exception as e:
            logger.debug(f"ダッシュボードマネージャー取得をスキップ: {e}")

    if task_id and dashboard:
        try:
            success, message = dashboard.assign_task(
                task_id=task_id,
                agent_id=agent.id,
                branch=branch,
                worktree_path=worktree_path,
            )
            task_assigned = success
            if not success:
                assignment_error = message
                logger.warning(f"Worker {worker_index + 1}: タスク割り当て失敗 - {message}")
            else:
                agent.current_task = task_id
                agent.branch = branch
                if str(agent.role) == AgentRole.WORKER.value:
                    agent.status = AgentStatus.BUSY
                agent.last_activity = datetime.now()
                save_agent_to_file(app_ctx, agent)
                dashboard.update_agent_summary(agent)
        except Exception as e:
            assignment_error = str(e)
            logger.warning(f"Worker {worker_index + 1}: タスク割り当てエラー - {e}")

    task_sent = False
    dispatch_mode = "none"
    dispatch_error: str | None = None
    if task_content and session_id:
        send_result = await _send_task_to_worker(
            app_ctx,
            agent,
            task_content,
            task_id,
            branch,
            worktree_path,
            session_id,
            worker_index,
            enable_worktree,
            profile_settings,
            caller_agent_id,
        )
        task_sent = bool(send_result.get("task_sent"))
        dispatch_mode = str(send_result.get("dispatch_mode", "none"))
        dispatch_error = send_result.get("dispatch_error")

    return task_assigned, assignment_error, task_sent, dispatch_mode, dispatch_error


def _pre_assign_pane_slots(
    agents: dict[str, Agent],
    project_name: str,
    create_count: int,
) -> list[tuple[int, int] | None]:
    """新規 Worker 用の pane スロットを事前割り当てする。"""
    used_slots: set[tuple[int, int]] = set()
    for agent in agents.values():
        if (
            agent.role == AgentRole.WORKER
            and agent.status != AgentStatus.TERMINATED
            and agent.session_name == project_name
            and agent.window_index is not None
            and agent.pane_index is not None
        ):
            used_slots.add((agent.window_index, agent.pane_index))

    pre_assigned: list[tuple[int, int] | None] = []
    for i in range(create_count):
        slot = None
        for pane_index in MAIN_WINDOW_WORKER_PANES:
            if (0, pane_index) not in used_slots:
                slot = (0, pane_index)
                used_slots.add(slot)
                break
        if slot is None:
            logger.warning(
                f"Worker {i + 1}: 利用可能な pane がありません"
                "（Workerの完了を待って再試行してください）"
            )
        pre_assigned.append(slot)

    return pre_assigned


async def _setup_worker_tmux_pane(
    app_ctx: "AppContext",
    settings: "Settings",
    project_name: str,
    repo_path: str,
    window_index: int,
    pane_index: int,
    worker_no: int,
    worktree_path: str,
    enable_worktree: bool,
    worker_index: int,
    preferred_cli: str | None = None,
) -> tuple[Agent | None, dict[str, Any] | None]:
    """tmux セッション確保とエージェントオブジェクトを作成する。"""
    tmux = app_ctx.tmux
    if not await tmux.create_main_session(repo_path):
        return None, {
            "success": False,
            "error": f"Worker {worker_index + 1}: メインセッション作成失敗",
            "worker_index": worker_index,
        }

    if preferred_cli:
        from src.config.settings import AICli

        try:
            worker_cli = AICli(preferred_cli)
        except ValueError:
            logger.warning(
                "無効な preferred_cli '%s' → デフォルトCLIにフォールバック", preferred_cli
            )
            worker_cli = settings.get_worker_cli(worker_no)
    else:
        worker_cli = settings.get_worker_cli(worker_no)

    if window_index > 0:
        ok = await tmux.add_extra_worker_window(
            project_name=project_name,
            window_index=window_index,
            rows=settings.extra_worker_rows,
            cols=settings.extra_worker_cols,
        )
        if not ok:
            return None, {
                "success": False,
                "error": f"Worker {worker_index + 1}: 追加ウィンドウ作成失敗",
                "worker_index": worker_index,
            }

    agent_id = str(uuid.uuid4())[:8]
    await tmux.set_pane_title(project_name, window_index, pane_index, f"worker-{agent_id}")
    tmux_session = f"{project_name}:{window_index}.{pane_index}"

    now = datetime.now()
    agent = Agent(
        id=agent_id,
        role=AgentRole.WORKER,
        status=AgentStatus.IDLE,
        tmux_session=tmux_session,
        working_dir=worktree_path,
        worktree_path=worktree_path if enable_worktree else None,
        session_name=project_name,
        window_index=window_index,
        pane_index=pane_index,
        ai_cli=worker_cli,
        created_at=now,
        last_activity=now,
    )
    return agent, None


async def _create_single_worker(
    app_ctx: "AppContext",
    agents: dict[str, Agent],
    settings: "Settings",
    config: dict,
    worker_index: int,
    assigned_slot: tuple[int, int] | None,
    repo_path: str,
    base_branch: str,
    project_name: str,
    enable_worktree: bool,
    session_id: str | None,
    profile_settings: dict,
    caller_agent_id: str | None,
) -> dict[str, Any]:
    """単一の Worker を新規作成する。"""
    validation_error = _validate_batch_config(config, worker_index)
    if validation_error:
        return validation_error

    requested_branch = config.get("branch")
    task_title = config.get("task_title", f"Worker {worker_index + 1}")
    task_id = config.get("task_id")
    task_content = config.get("task_content")
    preferred_cli = config.get("preferred_cli")

    try:
        if assigned_slot is None:
            return {
                "success": False,
                "worker_index": worker_index,
                "error": (f"Worker {worker_index + 1}: 利用可能なスロットがありません"),
            }

        window_index, pane_index = assigned_slot
        worker_no = resolve_worker_number_from_slot(
            settings,
            window_index,
            pane_index,
        )
        branch = requested_branch or f"worker-{worker_no}"
        if enable_worktree:
            if not task_id:
                return {
                    "success": False,
                    "worker_index": worker_index,
                    "error": f"Worker {worker_index + 1}: task_id が必須です",
                }
            branch = build_worker_task_branch(base_branch, worker_no, task_id)

        worktree_path = repo_path
        if enable_worktree:
            wt_path, wt_error = await _create_worktree_for_worker(
                app_ctx,
                repo_path,
                branch,
                base_branch,
                worker_index,
            )
            if wt_error:
                return {"success": False, "error": wt_error, "worker_index": worker_index}
            worktree_path = wt_path

        agent, tmux_error = await _setup_worker_tmux_pane(
            app_ctx,
            settings,
            project_name,
            repo_path,
            window_index,
            pane_index,
            worker_no,
            worktree_path,
            enable_worktree,
            worker_index,
            preferred_cli=preferred_cli,
        )
        if tmux_error:
            return tmux_error

        agents[agent.id] = agent
        logger.info(
            "Worker %d (ID: %s) を作成しました: %s",
            worker_index + 1,
            agent.id,
            agent.tmux_session,
        )
        post_result = _post_create_agent(app_ctx, agent, agents)

        dispatch = await _assign_and_dispatch_task(
            app_ctx,
            agent,
            task_id,
            task_content,
            branch,
            worktree_path,
            session_id,
            worker_index,
            enable_worktree,
            profile_settings,
            caller_agent_id,
        )
        (task_assigned, assignment_error, task_sent, dispatch_mode, dispatch_error) = dispatch

        return {
            "success": True,
            "worker_index": worker_index,
            "agent_id": agent.id,
            "branch": branch,
            "worktree_path": worktree_path,
            "tmux_session": agent.tmux_session,
            "task_title": task_title,
            "ipc_registered": post_result["ipc_registered"],
            "file_persisted": post_result["file_persisted"],
            "dashboard_updated": post_result["dashboard_updated"],
            "task_assigned": task_assigned,
            "assignment_error": assignment_error,
            "task_sent": task_sent,
            "dispatch_mode": dispatch_mode,
            "dispatch_error": dispatch_error,
        }

    except Exception as e:
        logger.exception("Worker %d 作成中にエラー: %s", worker_index + 1, e)
        return {
            "success": False,
            "error": f"Worker {worker_index + 1}: {e!s}",
            "worker_index": worker_index,
        }


async def _reuse_single_worker(
    app_ctx: "AppContext",
    settings: "Settings",
    config: dict,
    worker_index: int,
    worker: Agent,
    repo_path: str,
    base_branch: str,
    enable_worktree: bool,
    session_id: str | None,
    profile_settings: dict,
    caller_agent_id: str | None,
) -> dict[str, Any]:
    """既存 idle Worker を再利用してタスクを割り当てる。"""
    validation_error = _validate_batch_config(config, worker_index)
    if validation_error:
        return validation_error

    requested_branch = config.get("branch")
    task_title = config.get("task_title", f"Worker {worker_index + 1}")
    task_id = config.get("task_id")
    task_content = config.get("task_content")
    preferred_cli = config.get("preferred_cli")

    if preferred_cli:
        from src.config.settings import AICli

        try:
            requested_cli = AICli(preferred_cli)
        except ValueError:
            requested_cli = None
        if requested_cli and worker.ai_cli != requested_cli:
            return {
                "success": False,
                "worker_index": worker_index,
                "error": (
                    f"Worker {worker_index + 1}: preferred_cli='{preferred_cli}' "
                    f"だが再利用Worker の CLI は '{worker.ai_cli}' です。"
                    "CLI が異なる Worker は再利用できません。"
                ),
            }

    worktree_path = worker.worktree_path or repo_path
    worker_no = resolve_worker_number_from_slot(
        settings,
        worker.window_index or 0,
        worker.pane_index or 0,
    )
    worker.ai_cli = settings.get_worker_cli(worker_no)
    branch = requested_branch or f"worker-{worker_no}"
    if enable_worktree:
        if not task_id:
            return {
                "success": False,
                "error": (
                    f"Worker {worker_index + 1}: MCP_ENABLE_WORKTREE=true のため task_id が必須です"
                ),
                "worker_index": worker_index,
            }
        branch = build_worker_task_branch(base_branch, worker_no, task_id)
        wt_path, wt_error = await _create_worktree_for_worker(
            app_ctx, repo_path, branch, base_branch, worker_index
        )
        if wt_error:
            return {"success": False, "error": wt_error, "worker_index": worker_index}
        worktree_path = wt_path
        worker.worktree_path = wt_path
        worker.working_dir = wt_path

    (
        task_assigned,
        assignment_error,
        task_sent,
        dispatch_mode,
        dispatch_error,
    ) = await _assign_and_dispatch_task(
        app_ctx,
        worker,
        task_id,
        task_content,
        branch,
        worktree_path,
        session_id,
        worker_index,
        enable_worktree,
        profile_settings,
        caller_agent_id,
    )

    worker.last_activity = datetime.now()
    save_agent_to_file(app_ctx, worker)

    return {
        "success": True,
        "worker_index": worker_index,
        "agent_id": worker.id,
        "branch": branch,
        "worktree_path": worktree_path,
        "tmux_session": worker.tmux_session,
        "task_title": task_title,
        "reused": True,
        "task_assigned": task_assigned,
        "assignment_error": assignment_error,
        "task_sent": task_sent,
        "dispatch_mode": dispatch_mode,
        "dispatch_error": dispatch_error,
    }


def _collect_batch_results(results: list) -> tuple[list, int, list[str]]:
    """gather 結果を (workers, failed_count, errors) に整理する。"""
    workers = []
    failed_count = 0
    errors = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            failed_count += 1
            errors.append(f"Worker {i + 1}: 例外発生 - {result!s}")
        elif result.get("success"):
            workers.append(result)
        else:
            failed_count += 1
            errors.append(result.get("error", f"Worker {i + 1}: 不明なエラー"))
    return workers, failed_count, errors


def _validate_batch_capacity(
    agents: dict[str, Agent],
    worker_configs: list[dict],
    reuse_idle_workers: bool,
    profile_max_workers: int,
) -> tuple[list[Agent], int, dict[str, Any] | None]:
    """バッチ作成のキャパシティを検証し、再利用候補を返す。

    Returns:
        (reusable_workers, reuse_count, error_or_None)
    """
    current_worker_count = sum(
        1
        for a in agents.values()
        if a.role == AgentRole.WORKER and a.status != AgentStatus.TERMINATED
    )
    requested_count = len(worker_configs)
    reusable_workers: list[Agent] = []
    if reuse_idle_workers:
        reusable_workers = sorted(
            [
                a
                for a in agents.values()
                if a.role == AgentRole.WORKER
                and a.status == AgentStatus.IDLE
                and not a.current_task
                and a.session_name is not None
                and a.window_index is not None
                and a.pane_index is not None
            ],
            key=lambda a: a.last_activity,
        )

    reuse_count = min(requested_count, len(reusable_workers)) if reuse_idle_workers else 0
    new_worker_needed = requested_count - reuse_count
    new_worker_capacity = max(profile_max_workers - current_worker_count, 0)
    if new_worker_needed > new_worker_capacity:
        return (
            reusable_workers,
            reuse_count,
            {
                "success": False,
                "error": (
                    "Worker数が上限を超えます"
                    f"（現在: {current_worker_count}, 要求: {requested_count}, "
                    f"再利用可能: {reuse_count}, 新規上限: {new_worker_capacity}, "
                    f"総上限: {profile_max_workers}）"
                ),
            },
        )
    return reusable_workers, reuse_count, None


def register_batch_tools(mcp: FastMCP) -> None:
    """batch 系エージェントツールを登録する。"""

    @mcp.tool()
    async def create_workers_batch(
        worker_configs: list[dict],
        repo_path: str,
        base_branch: str,
        session_id: str | None = None,
        reuse_idle_workers: bool = True,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """複数 Worker を並列作成し、タスク割り当て・送信も実行する。※ Owner/Admin のみ。"""
        app_ctx, role_error = require_permission(ctx, "create_workers_batch", caller_agent_id)
        if role_error:
            return role_error
        settings = app_ctx.settings
        if not worker_configs:
            return {"success": False, "error": "worker_configs が空です"}

        profile_settings = get_current_profile_settings(app_ctx)
        agents = app_ctx.agents

        # 画像生成タスク（Cursor CLI）の並列実行数上限チェック
        from src.config.settings import AICli

        cursor_request_count = sum(
            1 for c in worker_configs if c.get("preferred_cli") == "cursor"
        )
        busy_cursor_count = sum(
            1
            for a in agents.values()
            if a.role == AgentRole.WORKER
            and a.status == AgentStatus.BUSY
            and a.ai_cli == AICli.CURSOR
        )
        if cursor_request_count + busy_cursor_count > MAX_IMAGE_TASK_PARALLEL:
            return {
                "success": False,
                "error": (
                    f"画像生成タスクの並列実行数が上限を超えます"
                    f"（新規要求: {cursor_request_count}, 実行中: {busy_cursor_count}, "
                    f"上限: {MAX_IMAGE_TASK_PARALLEL}）"
                ),
            }

        reusable_workers, _reuse_count, capacity_error = _validate_batch_capacity(
            agents,
            worker_configs,
            reuse_idle_workers,
            profile_settings["max_workers"],
        )
        if capacity_error:
            return capacity_error

        enable_wt = settings.is_worktree_enabled()

        # preferred_cli を考慮した再利用候補マッチング
        reuse_pairs: list[tuple[dict, Agent]] = []
        create_configs: list[dict] = []
        remaining_workers = list(reusable_workers)

        for config in worker_configs:
            pref_cli = config.get("preferred_cli")
            matched = False
            if remaining_workers and reuse_idle_workers:
                if pref_cli:
                    try:
                        target_cli = AICli(pref_cli)
                    except ValueError:
                        target_cli = None
                    if target_cli:
                        for w in remaining_workers:
                            if w.ai_cli == target_cli:
                                reuse_pairs.append((config, w))
                                remaining_workers.remove(w)
                                matched = True
                                break
                else:
                    reuse_pairs.append((config, remaining_workers.pop(0)))
                    matched = True
            if not matched:
                create_configs.append(config)

        # create_configs の数に基づいてキャパシティを再検証
        current_worker_count = sum(
            1
            for a in agents.values()
            if a.role == AgentRole.WORKER and a.status != AgentStatus.TERMINATED
        )
        new_worker_capacity = max(
            profile_settings["max_workers"] - current_worker_count, 0
        )
        if len(create_configs) > new_worker_capacity:
            return {
                "success": False,
                "error": (
                    "Worker数が上限を超えます"
                    f"（現在: {current_worker_count}, 要求: {len(worker_configs)}, "
                    f"再利用: {len(reuse_pairs)}, 新規必要: {len(create_configs)}, "
                    f"新規上限: {new_worker_capacity}, "
                    f"総上限: {profile_settings['max_workers']}）"
                ),
            }

        project_name = get_project_name(repo_path, enable_git=settings.enable_git)
        pre_assigned_slots = _pre_assign_pane_slots(
            agents, project_name, len(create_configs)
        )
        logger.info(
            "Workerバッチ: reuse=%s, create=%s",
            len(reuse_pairs),
            len(create_configs),
        )

        reuse_results = await asyncio.gather(
            *[
                _reuse_single_worker(
                    app_ctx,
                    settings,
                    config,
                    i,
                    worker,
                    repo_path,
                    base_branch,
                    enable_wt,
                    session_id,
                    profile_settings,
                    caller_agent_id,
                )
                for i, (config, worker) in enumerate(reuse_pairs)
            ],
            return_exceptions=True,
        )
        create_results = await asyncio.gather(
            *[
                _create_single_worker(
                    app_ctx,
                    agents,
                    settings,
                    c,
                    i + len(reuse_pairs),
                    pre_assigned_slots[i],
                    repo_path,
                    base_branch,
                    project_name,
                    enable_wt,
                    session_id,
                    profile_settings,
                    caller_agent_id,
                )
                for i, c in enumerate(create_configs)
            ],
            return_exceptions=True,
        )

        workers, failed_count, errors = _collect_batch_results([*reuse_results, *create_results])
        ok = failed_count == 0
        msg = (
            f"{len(workers)} 件のWorker処理が完了しました"
            if ok
            else f"{len(workers)} 件のWorker処理が完了（{failed_count} 件失敗）"
        )
        try:
            from src.managers.healthcheck_daemon import ensure_healthcheck_daemon_started

            await ensure_healthcheck_daemon_started(app_ctx)
        except Exception as e:
            logger.warning("healthcheck daemon 起動に失敗: %s", e)
        logger.info(msg)
        return {
            "success": ok,
            "workers": workers,
            "failed_count": failed_count,
            "errors": errors if errors else None,
            "message": msg,
        }
