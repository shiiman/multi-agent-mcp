"""エージェント batch 作成ツール実装。"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.managers.tmux_manager import MAIN_WINDOW_WORKER_PANES, get_project_name
from src.models.agent import Agent, AgentRole, AgentStatus
from src.tools.agent_helpers import (
    build_worker_task_branch,
    _create_worktree_for_worker,
    _post_create_agent,
    _send_task_to_worker,
    resolve_worker_number_from_slot,
)
from src.tools.helpers import ensure_dashboard_manager, require_permission, save_agent_to_file
from src.tools.model_profile import get_current_profile_settings

logger = logging.getLogger(__name__)


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
        """複数の Worker を並列で作成し、オプションでタスク割り当て・送信も実行する。

        Worktree 作成、エージェント作成、タスク割り当て、タスク送信を並列で実行し、
        セットアップ時間を大幅に短縮する。

        ※ Owner と Admin のみ使用可能。

        Args:
            worker_configs: Worker 設定のリスト。各設定は以下のキーを持つ:
                - branch: ブランチ名（worktree 用、必須）
                - task_title: タスク名（オプション、ログ用）
                - task_id: 割り当てるタスクID（オプション、assign_task_to_agent 用）
                - task_content: 送信するタスク内容（オプション、send_task 用）
            repo_path: メインリポジトリのパス
            base_branch: ベースブランチ名（worktree 作成時の基点）
            session_id: セッションID（task_content 指定時は必須）
            reuse_idle_workers: idle Worker を再利用するか
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            作成結果（success, workers, failed_count, message）
            workers: 作成された Worker 情報のリスト
            failed_count: 失敗した Worker 数
        """
        app_ctx, role_error = require_permission(ctx, "create_workers_batch", caller_agent_id)
        if role_error:
            return role_error

        settings = app_ctx.settings

        if not worker_configs:
            return {
                "success": False,
                "error": "worker_configs が空です",
            }

        # 現在のプロファイル設定を取得
        profile_settings = get_current_profile_settings(app_ctx)
        profile_max_workers = profile_settings["max_workers"]

        # Worker 数の上限と再利用候補を確認
        agents = app_ctx.agents
        current_worker_count = sum(1 for a in agents.values() if a.role == AgentRole.WORKER)
        requested_count = len(worker_configs)
        reusable_workers: list[Agent] = []
        if reuse_idle_workers:
            reusable_workers = sorted(
                [
                    a for a in agents.values()
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
            return {
                "success": False,
                "error": (
                    "Worker 数が上限を超えます"
                    f"（現在: {current_worker_count}, 要求: {requested_count}, "
                    f"再利用可能: {reuse_count}, 新規上限: {new_worker_capacity}, "
                    f"総上限: {profile_max_workers}）"
                ),
            }

        # worktree 無効モードのチェック
        enable_worktree = settings.enable_worktree
        reuse_configs = worker_configs[:reuse_count]
        create_configs = worker_configs[reuse_count:]

        # 🔴 Race condition 対策: 並列実行前に pane を事前割り当て
        project_name = get_project_name(repo_path)
        pre_assigned_slots: list[tuple[int, int] | None] = []

        # 現在のWorkerペイン割り当て状況を取得
        used_slots: set[tuple[int, int]] = set()
        for agent in agents.values():
            if (
                agent.role == AgentRole.WORKER
                and agent.session_name == project_name
                and agent.window_index is not None
                and agent.pane_index is not None
            ):
                used_slots.add((agent.window_index, agent.pane_index))

        # 各新規 Worker に pane を事前割り当て
        for i in range(len(create_configs)):
            slot = None
            # メインウィンドウの空きを探す
            for pane_index in MAIN_WINDOW_WORKER_PANES:
                if (0, pane_index) not in used_slots:
                    slot = (0, pane_index)
                    used_slots.add(slot)  # 確保済みとしてマーク
                    break

            # メインウィンドウが満杯の場合は警告（Worker の完了を待って再試行が必要）
            if slot is None:
                logger.warning(
                    f"Worker {i + 1}: 利用可能な pane がありません"
                    "（Worker の完了を待って再試行してください）"
                )

            pre_assigned_slots.append(slot)

        logger.info(
            "Worker batch: reuse=%s, create=%s, slots=%s",
            reuse_count,
            len(create_configs),
            pre_assigned_slots,
        )

        async def create_single_worker(
            config: dict, worker_index: int, assigned_slot: tuple[int, int] | None
        ) -> dict[str, Any]:
            """単一の Worker を作成する内部関数。"""
            requested_branch = config.get("branch")
            task_title = config.get("task_title", f"Worker {worker_index + 1}")
            task_id = config.get("task_id")
            task_content = config.get("task_content")
            if task_content and not task_id:
                return {
                    "success": False,
                    "error": (
                        f"Worker {worker_index + 1}: task_content を送信する場合は "
                        "task_id が必須です"
                    ),
                    "worker_index": worker_index,
                }

            try:
                if assigned_slot is None:
                    return {
                        "success": False,
                        "error": (
                            f"Worker {worker_index + 1}: "
                            "利用可能なスロットがありません（事前割り当て失敗）"
                        ),
                        "worker_index": worker_index,
                    }

                window_index, pane_index = assigned_slot
                worker_no = resolve_worker_number_from_slot(settings, window_index, pane_index)
                branch = requested_branch or f"worker-{worker_no}"
                if enable_worktree:
                    if not task_id:
                        return {
                            "success": False,
                            "error": (
                                f"Worker {worker_index + 1}: MCP_ENABLE_WORKTREE=true のため "
                                "task_id が必須です"
                            ),
                            "worker_index": worker_index,
                        }
                    branch = build_worker_task_branch(base_branch, worker_no, task_id)

                # 1. Worktree 作成（有効な場合のみ）
                worktree_path = repo_path
                if enable_worktree:
                    wt_path, wt_error = await _create_worktree_for_worker(
                        app_ctx, repo_path, branch, base_branch, worker_index
                    )
                    if wt_error:
                        return {
                            "success": False,
                            "error": wt_error,
                            "worker_index": worker_index,
                        }
                    worktree_path = wt_path

                # 2. tmux セッション確保・エージェント作成
                tmux = app_ctx.tmux
                if not await tmux.create_main_session(repo_path):
                    return {
                        "success": False,
                        "error": f"Worker {worker_index + 1}: メインセッション作成失敗",
                        "worker_index": worker_index,
                    }

                worker_cli = settings.get_worker_cli(worker_no)

                if window_index > 0:
                    ok = await tmux.add_extra_worker_window(
                        project_name=project_name,
                        window_index=window_index,
                        rows=settings.extra_worker_rows,
                        cols=settings.extra_worker_cols,
                    )
                    if not ok:
                        return {
                            "success": False,
                            "error": f"Worker {worker_index + 1}: 追加ウィンドウ作成失敗",
                            "worker_index": worker_index,
                        }

                agent_id = str(uuid.uuid4())[:8]
                await tmux.set_pane_title(
                    project_name, window_index, pane_index, f"worker-{agent_id}"
                )
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
                agents[agent_id] = agent

                logger.info(
                    f"Worker {worker_index + 1} (ID: {agent_id}) を作成しました: {tmux_session}"
                )

                # 3. 後処理（IPC登録、ファイル保存、レジストリ、ダッシュボード）
                post_result = _post_create_agent(app_ctx, agent, agents)

                # 4. タスク割り当て（task_id が指定されている場合）
                task_assigned = False
                assignment_error = None
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
                            agent_id=agent_id,
                            branch=branch,
                            worktree_path=worktree_path,
                        )
                        task_assigned = success
                        if not success:
                            assignment_error = message
                            logger.warning(
                                f"Worker {worker_index + 1}: タスク割り当て失敗 - {message}"
                            )
                        else:
                            agent.current_task = task_id
                            if str(agent.role) == AgentRole.WORKER.value:
                                agent.status = AgentStatus.BUSY
                            agent.last_activity = datetime.now()
                            save_agent_to_file(app_ctx, agent)
                            dashboard.update_agent_summary(agent)
                    except Exception as e:
                        assignment_error = str(e)
                        logger.warning(f"Worker {worker_index + 1}: タスク割り当てエラー - {e}")

                # 5. タスク送信（task_content が指定されている場合）
                task_sent = False
                dispatch_mode = "none"
                dispatch_error = None
                if task_content and session_id:
                    send_result = await _send_task_to_worker(
                        app_ctx, agent, task_content, task_id, branch, worktree_path,
                        session_id, worker_index, enable_worktree,
                        profile_settings, caller_agent_id,
                    )
                    task_sent = bool(send_result.get("task_sent"))
                    dispatch_mode = str(send_result.get("dispatch_mode", "none"))
                    dispatch_error = send_result.get("dispatch_error")

                return {
                    "success": True,
                    "worker_index": worker_index,
                    "agent_id": agent_id,
                    "branch": branch,
                    "worktree_path": worktree_path,
                    "tmux_session": tmux_session,
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
                logger.exception(f"Worker {worker_index + 1} 作成中にエラー: {e}")
                return {
                    "success": False,
                    "error": f"Worker {worker_index + 1}: {str(e)}",
                    "worker_index": worker_index,
                }

        async def reuse_single_worker(
            config: dict, worker_index: int, worker: Agent
        ) -> dict[str, Any]:
            """既存 idle Worker を再利用してタスクを割り当てる。"""
            requested_branch = config.get("branch")
            task_title = config.get("task_title", f"Worker {worker_index + 1}")
            task_id = config.get("task_id")
            task_content = config.get("task_content")
            if task_content and not task_id:
                return {
                    "success": False,
                    "error": (
                        f"Worker {worker_index + 1}: task_content を送信する場合は "
                        "task_id が必須です"
                    ),
                    "worker_index": worker_index,
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
                            f"Worker {worker_index + 1}: MCP_ENABLE_WORKTREE=true のため "
                            "task_id が必須です"
                        ),
                        "worker_index": worker_index,
                    }
                branch = build_worker_task_branch(base_branch, worker_no, task_id)
                wt_path, wt_error = await _create_worktree_for_worker(
                    app_ctx, repo_path, branch, base_branch, worker_index
                )
                if wt_error:
                    return {
                        "success": False,
                        "error": wt_error,
                        "worker_index": worker_index,
                    }
                worktree_path = wt_path
                worker.worktree_path = wt_path
                worker.working_dir = wt_path

            task_assigned = False
            assignment_error = None
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
                        agent_id=worker.id,
                        branch=branch,
                        worktree_path=worktree_path,
                    )
                    task_assigned = success
                    if not success:
                        assignment_error = message
                        logger.warning(f"再利用Workerへのタスク割り当て失敗: {message}")
                    else:
                        worker.current_task = task_id
                        if str(worker.role) == AgentRole.WORKER.value:
                            worker.status = AgentStatus.BUSY
                        worker.last_activity = datetime.now()
                        save_agent_to_file(app_ctx, worker)
                        dashboard.update_agent_summary(worker)
                except Exception as e:
                    assignment_error = str(e)
                    logger.warning(f"再利用Workerへのタスク割り当てエラー: {e}")

            task_sent = False
            dispatch_mode = "none"
            dispatch_error = None
            if task_content and session_id:
                send_result = await _send_task_to_worker(
                    app_ctx,
                    worker,
                    task_content,
                    task_id,
                    branch or "",
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

        # 再利用 Worker と新規 Worker を並列処理
        logger.info(
            "%s 件の再利用, %s 件の新規作成を実行します",
            len(reuse_configs),
            len(create_configs),
        )
        reuse_results = await asyncio.gather(
            *[
                reuse_single_worker(config, i, reusable_workers[i])
                for i, config in enumerate(reuse_configs)
            ],
            return_exceptions=True,
        )
        create_results = await asyncio.gather(
            *[
                create_single_worker(config, i + len(reuse_configs), pre_assigned_slots[i])
                for i, config in enumerate(create_configs)
            ],
            return_exceptions=True,
        )
        results = [*reuse_results, *create_results]

        # 結果を整理
        workers = []
        failed_count = 0
        errors = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_count += 1
                errors.append(f"Worker {i + 1}: 例外発生 - {str(result)}")
            elif result.get("success"):
                workers.append(result)
            else:
                failed_count += 1
                errors.append(result.get("error", f"Worker {i + 1}: 不明なエラー"))

        success = failed_count == 0
        message = (
            f"{len(workers)} 件の Worker 処理が完了しました"
            if success
            else f"{len(workers)} 件の Worker 処理が完了（{failed_count} 件失敗）"
        )

        try:
            from src.managers.healthcheck_daemon import ensure_healthcheck_daemon_started

            await ensure_healthcheck_daemon_started(app_ctx)
        except Exception as e:
            logger.warning(f"healthcheck daemon 起動に失敗: {e}")

        logger.info(message)

        return {
            "success": success,
            "workers": workers,
            "failed_count": failed_count,
            "errors": errors if errors else None,
            "message": message,
        }
