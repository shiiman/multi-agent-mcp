"""ダッシュボード/タスク管理ツール。"""

import logging
from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.models.agent import AgentRole, AgentStatus
from src.models.dashboard import TaskStatus, normalize_task_id
from src.models.message import MessagePriority, MessageType
from src.tools.cost_capture import capture_claude_actual_cost_for_agent
from src.tools.helpers import (
    ADMIN_DASHBOARD_GRANT_SECONDS,
    _owner_polling_blocked_response,
    ensure_dashboard_manager,
    ensure_ipc_manager,
    ensure_memory_manager,
    find_agents_by_role,
    get_admin_poll_state,
    get_owner_wait_state,
    notify_agent_via_tmux,
    require_permission,
    reset_agent_to_idle,
    save_agent_to_file,
    sync_agents_from_file,
)

logger = logging.getLogger(__name__)
_TASK_STATUS_LABELS_JA = {
    "pending": "未着手",
    "in_progress": "進行中",
    "completed": "完了",
    "failed": "失敗",
    "blocked": "ブロック中",
    "cancelled": "キャンセル",
}


def _task_status_label_ja(status: str) -> str:
    """タスクステータスの日本語表示ラベルを返す。"""
    return _TASK_STATUS_LABELS_JA.get(status, status)


def _has_recent_healthcheck_event(app_ctx: Any, admin_id: str) -> bool:
    at = app_ctx._admin_last_healthcheck_at.get(admin_id)
    if not isinstance(at, datetime):
        return False
    window = max(
        ADMIN_DASHBOARD_GRANT_SECONDS,
        int(getattr(app_ctx.settings, "healthcheck_interval_seconds", 60)),
    )
    return datetime.now() - at <= timedelta(seconds=window)


def _should_block_admin_dashboard_polling(app_ctx: Any, admin_id: str) -> bool:
    state = get_admin_poll_state(app_ctx, admin_id)
    if not bool(state.get("waiting_for_ipc")):
        return False

    allow_until = state.get("allow_dashboard_until")
    if isinstance(allow_until, datetime) and datetime.now() <= allow_until:
        return False

    try:
        ipc = ensure_ipc_manager(app_ctx)
        if ipc.get_unread_count(admin_id) > 0:
            return False
    except Exception as e:
        logger.debug("IPC 未読数チェックをスキップ: %s", e)

    if _has_recent_healthcheck_event(app_ctx, admin_id):
        state["allow_dashboard_until"] = datetime.now() + timedelta(
            seconds=ADMIN_DASHBOARD_GRANT_SECONDS
        )
        return False

    return True


def _polling_blocked_response() -> dict[str, Any]:
    return {
        "success": False,
        "error": ("polling_blocked: IPC 通知待機中のため連続ダッシュボード参照はできません"),
        "next_action": "wait_for_ipc_notification",
    }


def _normalize_owner_wait_error(
    app_ctx: Any,
    caller_agent_id: str | None,
    role_error: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not role_error:
        return None

    error_text = str(role_error.get("error", ""))
    if "owner_wait_locked" not in error_text:
        return role_error

    waiting_admin_id = role_error.get("waiting_for_admin_id")
    if waiting_admin_id is None and caller_agent_id:
        waiting_admin_id = get_owner_wait_state(app_ctx, caller_agent_id).get("admin_id")
    return _owner_polling_blocked_response(waiting_admin_id)


async def _sync_dashboard_for_admin(app_ctx: Any, dashboard: Any) -> None:
    """Admin/Owner 向けに Dashboard のエージェント情報・コスト・Markdownを同期する。"""
    sync_agents_from_file(app_ctx)
    for agent in app_ctx.agents.values():
        dashboard.update_agent_summary(agent)
    # 実測コスト収集は Claude の statusLine のみに限定する
    claude_agents = []
    for candidate in app_ctx.agents.values():
        role_value = str(candidate.role)
        if role_value not in (
            AgentRole.ADMIN.value,
            AgentRole.WORKER.value,
            "admin",
            "worker",
        ):
            continue
        cli_value = (
            candidate.ai_cli.value
            if hasattr(candidate.ai_cli, "value")
            else str(candidate.ai_cli or "")
        )
        if cli_value == "claude":
            claude_agents.append(candidate)
    for target_agent in claude_agents:
        try:
            await capture_claude_actual_cost_for_agent(
                app_ctx=app_ctx,
                agent=target_agent,
                task_id=target_agent.current_task,
            )
        except (OSError, ValueError, TypeError) as e:
            logger.debug("Dashboard 同期時の Claude 実測コスト更新をスキップ: %s", e)
    # Markdown ダッシュボードを保存
    if app_ctx.session_id and app_ctx.project_root:
        try:
            dashboard.save_markdown_dashboard(app_ctx.project_root, app_ctx.session_id)
        except OSError as e:
            logger.warning("Dashboard ファイル更新に失敗: %s", e)


def register_tools(mcp: FastMCP) -> None:
    """ダッシュボード/タスク管理ツールを登録する。"""

    @mcp.tool()
    async def create_task(
        title: str,
        description: str = "",
        assigned_agent_id: str | None = None,
        branch: str | None = None,
        metadata: dict | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """新しいタスクを作成する。

        ※ Owner と Admin のみ使用可能。

        Args:
            title: タスクタイトル
            description: タスク説明
            assigned_agent_id: 割り当て先エージェントID（オプション）
            branch: 作業ブランチ（オプション）
            metadata: 追加メタデータ（オプション）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            作成結果（success, task, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "create_task", caller_agent_id)
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        task = dashboard.create_task(
            title=title,
            description=description,
            assigned_agent_id=assigned_agent_id,
            branch=branch,
            metadata=metadata,
        )

        return {
            "success": True,
            "task": task.model_dump(mode="json"),
            "message": f"タスクを作成しました: {task.id}",
        }

    @mcp.tool()
    async def reopen_task(
        task_id: str,
        reset_progress: bool = False,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """終端タスクを再開する。

        ※ Admin のみ使用可能。

        Args:
            task_id: 再開するタスクID
            reset_progress: 進捗率を 0 に戻すか
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            再開結果（success, task_id, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "reopen_task", caller_agent_id)
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)
        success, message = dashboard.reopen_task(task_id=task_id, reset_progress=reset_progress)

        if success:
            task = dashboard.get_task(task_id)
            if task and task.assigned_agent_id:
                assigned = app_ctx.agents.get(task.assigned_agent_id)
                if assigned and assigned.current_task == task.id:
                    assigned.current_task = None
                    if assigned.role == AgentRole.WORKER.value:
                        assigned.status = AgentStatus.IDLE
                    assigned.last_activity = datetime.now()
                    save_agent_to_file(app_ctx, assigned)

        return {
            "success": success,
            "task_id": task_id,
            "message": message,
        }

    @mcp.tool()
    async def update_task_status(
        task_id: str,
        status: str,
        progress: int | None = None,
        error_message: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスクのステータスを更新する。

        ※ Admin のみ使用可能。Worker は report_task_completion を使用してください。

        Args:
            task_id: タスクID
            status: 新しいステータス（pending/in_progress/blocked/completed/failed/cancelled）
            progress: 進捗率（0-100）
            error_message: エラーメッセージ（failedの場合）
            caller_agent_id: 呼び出し元エージェントID（ロールチェック用）

        Returns:
            更新結果（success, task_id, status, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "update_task_status", caller_agent_id)
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        # ステータスの検証
        try:
            task_status = TaskStatus(status)
        except ValueError:
            valid_statuses = [s.value for s in TaskStatus]
            return {
                "success": False,
                "error": f"無効なステータスです: {status}（有効: {valid_statuses}）",
            }

        success, message = dashboard.update_task_status(
            task_id=task_id,
            status=task_status,
            progress=progress,
            error_message=error_message,
        )

        # agents.json 側の current_task も同期する（Dashboard 再同期時の巻き戻りを防ぐ）
        if success and task_status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        ):
            task = dashboard.get_task(task_id)
            if task and task.assigned_agent_id:
                assigned = app_ctx.agents.get(task.assigned_agent_id)
                if assigned and assigned.current_task == task_id:
                    assigned.current_task = None
                    if assigned.role == AgentRole.WORKER.value:
                        assigned.status = AgentStatus.IDLE
                    assigned.last_activity = datetime.now()
                    save_agent_to_file(app_ctx, assigned)

        return {
            "success": success,
            "task_id": task_id,
            "status": status if success else None,
            "message": message,
        }

    @mcp.tool()
    async def assign_task_to_agent(
        task_id: str,
        agent_id: str,
        branch: str | None = None,
        worktree_path: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスクをエージェントに割り当てる。

        ※ Admin のみ使用可能。

        Args:
            task_id: タスクID
            agent_id: エージェントID
            branch: 作業ブランチ（オプション）
            worktree_path: worktreeパス（オプション）
            caller_agent_id: 呼び出し元エージェントID（ロールチェック用）

        Returns:
            割り当て結果（success, task_id, agent_id, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "assign_task_to_agent", caller_agent_id)
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        # ファイルからエージェント情報を同期
        sync_agents_from_file(app_ctx)

        # エージェントの存在確認
        if agent_id not in app_ctx.agents:
            return {
                "success": False,
                "error": f"エージェント {agent_id} が見つかりません",
            }

        success, message = dashboard.assign_task(
            task_id=task_id,
            agent_id=agent_id,
            branch=branch,
            worktree_path=worktree_path,
        )

        if success:
            # agents.json 側の current_task を更新
            agent = app_ctx.agents.get(agent_id)
            if agent:
                agent.current_task = task_id
                if branch:
                    agent.branch = branch
                if agent.role == AgentRole.WORKER.value:
                    agent.status = AgentStatus.BUSY
                agent.last_activity = datetime.now()
                save_agent_to_file(app_ctx, agent)

        return {
            "success": success,
            "task_id": task_id,
            "agent_id": agent_id if success else None,
            "message": message,
        }

    @mcp.tool()
    async def list_tasks(
        status: str | None = None,
        agent_id: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスク一覧を取得する。

        Args:
            status: フィルターするステータス（オプション）
            agent_id: フィルターするエージェントID（オプション）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            タスク一覧（success, tasks, count または error）
        """
        permission_target_agent_id = agent_id or caller_agent_id
        app_ctx, role_error = require_permission(
            ctx,
            "list_tasks",
            caller_agent_id,
            target_agent_id=permission_target_agent_id,
        )
        if role_error:
            return _normalize_owner_wait_error(app_ctx, caller_agent_id, role_error)

        caller = app_ctx.agents.get(caller_agent_id)
        caller_role = getattr(caller, "role", None)
        is_worker = caller_role in (AgentRole.WORKER.value, "worker")
        is_admin = caller_role in (AgentRole.ADMIN.value, "admin")
        if is_worker:
            if agent_id and caller_agent_id and agent_id != caller_agent_id:
                return {
                    "success": False,
                    "error": (
                        "Worker は list_tasks を自分自身の agent_id でのみ実行できます。"
                        f" caller_agent_id={caller_agent_id}, agent_id={agent_id}"
                    ),
                }
            # Worker は常に self-scope（自分に割り当てられたタスクのみ）
            agent_id = caller_agent_id
        if (
            is_admin
            and caller_agent_id
            and _should_block_admin_dashboard_polling(app_ctx, caller_agent_id)
        ):
            return _polling_blocked_response()

        dashboard = ensure_dashboard_manager(app_ctx)

        # ステータスの検証
        task_status = None
        if status:
            try:
                task_status = TaskStatus(status)
            except ValueError:
                valid_statuses = [s.value for s in TaskStatus]
                return {
                    "success": False,
                    "error": f"無効なステータスです: {status}（有効: {valid_statuses}）",
                }

        tasks = dashboard.list_tasks(status=task_status, agent_id=agent_id)

        return {
            "success": True,
            "tasks": [t.model_dump(mode="json") for t in tasks],
            "count": len(tasks),
        }

    @mcp.tool()
    async def report_task_progress(
        task_id: str,
        progress: int | None = None,
        message: str | None = None,
        checklist: list[dict] | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """Worker がタスクの進捗を報告する。

        Worker は 10% ごとに進捗を報告することで、Admin と Owner が
        リアルタイムで作業状況を把握できます。

        チェックリストを使用する場合、進捗率は自動計算されます。

        ※ Worker のみ使用可能。

        Args:
            task_id: タスクID
            progress: 進捗率（0-100、10% 単位で報告推奨。checklist使用時は自動計算）
            message: 進捗メッセージ（現在の作業内容など、ログに追加されます）
            checklist: チェックリスト [{"text": "項目名", "completed": true/false}, ...]
            caller_agent_id: 呼び出し元エージェントID（Worker のID）

        Returns:
            報告結果（success, task_id, progress, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "report_task_progress", caller_agent_id)
        if role_error:
            return role_error

        # ファイルから最新のエージェント情報を同期
        sync_agents_from_file(app_ctx)

        # progress の検証（checklist がある場合は自動計算されるためスキップ可）
        if progress is not None and not (0 <= progress <= 100):
            return {
                "success": False,
                "error": f"無効な進捗率です: {progress}（有効: 0-100）",
            }

        dashboard = ensure_dashboard_manager(app_ctx)
        normalized_task_id = normalize_task_id(task_id)
        task = dashboard.get_task(task_id)
        if not task:
            return {
                "success": False,
                "error": f"タスク {task_id} が見つかりません",
            }
        if task.assigned_agent_id != caller_agent_id:
            return {
                "success": False,
                "error": (
                    "タスクの割り当て先と caller_agent_id が一致しません: "
                    f"assigned={task.assigned_agent_id}, caller={caller_agent_id}"
                ),
            }

        # Worker は Dashboard を直接更新しない（Admin が IPC 経由で更新する）
        actual_progress = progress or 0
        worker_cost_snapshot = None
        worker_agent = app_ctx.agents.get(caller_agent_id) if caller_agent_id else None
        if worker_agent:
            try:
                worker_cost_snapshot = await capture_claude_actual_cost_for_agent(
                    app_ctx=app_ctx,
                    agent=worker_agent,
                    task_id=task_id,
                )
            except (OSError, ValueError, TypeError) as e:
                logger.debug("進捗報告時のコスト取得をスキップ: %s", e)

        # Admin にも進捗を通知（IPC メッセージ）
        admin_notified = False
        notification_sent = False
        admin_ids = find_agents_by_role(app_ctx, "admin")
        if not admin_ids:
            return {
                "success": False,
                "error": "Admin エージェントが見つかりません",
            }

        try:
            ipc = ensure_ipc_manager(app_ctx)
            ipc.send_message(
                sender_id=caller_agent_id,
                receiver_id=admin_ids[0],
                message_type=MessageType.TASK_PROGRESS,
                subject=f"進捗報告: {task_id} ({actual_progress}%)",
                content=message or f"タスク {task_id} の進捗: {actual_progress}%",
                priority=MessagePriority.NORMAL,
                metadata={
                    "task_id": task_id,
                    "normalized_task_id": normalized_task_id,
                    "progress": actual_progress,
                    "checklist": checklist,
                    "message": message,
                    "reporter": caller_agent_id,
                    "cost_snapshot": worker_cost_snapshot,
                },
            )
            admin_notified = True
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Admin への進捗通知に失敗: %s", e)
            return {
                "success": False,
                "error": f"Admin への進捗通知に失敗しました: {e}",
            }

        # 🔴 Admin に tmux 通知を送信（IPC 通知駆動のため必須）
        if admin_notified and admin_ids:
            sync_agents_from_file(app_ctx)
            admin_agent = app_ctx.agents.get(admin_ids[0])
            if admin_agent is None:
                return {
                    "success": False,
                    "error": f"Admin エージェント {admin_ids[0]} が見つかりません",
                    "task_id": task_id,
                    "progress": actual_progress,
                    "admin_notified": admin_notified,
                    "notification_sent": False,
                }
            notification_sent = await notify_agent_via_tmux(
                app_ctx, admin_agent, "task_progress", caller_agent_id
            )
            if not notification_sent:
                return {
                    "success": False,
                    "error": "Admin への tmux 通知に失敗しました",
                    "task_id": task_id,
                    "progress": actual_progress,
                    "admin_notified": admin_notified,
                    "notification_sent": False,
                }

        return {
            "success": True,
            "task_id": task_id,
            "progress": actual_progress,
            "admin_notified": admin_notified,
            "notification_sent": notification_sent,
            "cost_snapshot": worker_cost_snapshot,
            "message": f"進捗 {actual_progress}% を報告しました",
        }

    @mcp.tool()
    async def report_task_completion(
        task_id: str,
        status: str,
        message: str,
        summary: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """Worker が Admin にタスク完了を報告する。

        Worker はこのツールを使って Admin に作業結果を報告します。
        Admin が受け取って dashboard を更新します。
        自動的にメモリ保存とメトリクス更新も行います。

        ※ Worker のみ使用可能。

        Args:
            task_id: 完了したタスクのID
            status: 結果ステータス（"completed" | "failed"）
            message: 完了報告メッセージ（作業内容の要約）
            summary: タスク結果のサマリー（メモリに保存、省略時はmessageを使用）
            caller_agent_id: 呼び出し元エージェントID（Worker のID）

        Returns:
            報告結果（success, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "report_task_completion", caller_agent_id)
        if role_error:
            return role_error

        # ファイルから最新のエージェント情報を同期
        sync_agents_from_file(app_ctx)

        # Admin を検索
        admin_ids = find_agents_by_role(app_ctx, "admin")
        if not admin_ids:
            return {
                "success": False,
                "error": "Admin エージェントが見つかりません",
            }

        # 最初の Admin に報告（通常は1人のみ）
        admin_id = admin_ids[0]

        # status の検証
        if status not in ["completed", "failed"]:
            return {
                "success": False,
                "error": f"無効なステータスです: {status}（有効: completed, failed）",
            }

        normalized_task_id = normalize_task_id(task_id)
        dashboard = ensure_dashboard_manager(app_ctx)
        task = dashboard.get_task(task_id)
        if not task:
            return {
                "success": False,
                "error": f"タスク {task_id} が見つかりません",
            }
        if task.assigned_agent_id != caller_agent_id:
            return {
                "success": False,
                "error": (
                    "タスクの割り当て先と caller_agent_id が一致しません: "
                    f"assigned={task.assigned_agent_id}, caller={caller_agent_id}"
                ),
            }

        # Worker は Dashboard を直接更新しない（Admin が IPC 経由で更新する）
        worker_cost_snapshot = None
        worker_agent = app_ctx.agents.get(caller_agent_id) if caller_agent_id else None
        if worker_agent:
            try:
                worker_cost_snapshot = await capture_claude_actual_cost_for_agent(
                    app_ctx=app_ctx,
                    agent=worker_agent,
                    task_id=task_id,
                )
            except (OSError, ValueError, TypeError) as e:
                logger.debug("完了報告時のコスト取得をスキップ: %s", e)

        # IPC マネージャーを取得（自動初期化）
        ipc = ensure_ipc_manager(app_ctx)

        # タスク完了報告を送信
        msg_type = MessageType.TASK_COMPLETE if status == "completed" else MessageType.TASK_FAILED
        status_label = _task_status_label_ja(status)
        completion_message = ipc.send_message(
            sender_id=caller_agent_id,
            receiver_id=admin_id,
            message_type=msg_type,
            subject=f"タスク報告: {task_id} ({status_label})",
            content=message,
            priority=MessagePriority.HIGH,
            metadata={
                "task_id": task_id,
                "normalized_task_id": normalized_task_id,
                "status": status,
                "reporter": caller_agent_id,
                "cost_snapshot": worker_cost_snapshot,
            },
        )

        # 🔴 Admin に tmux 通知を送信（IPC 通知駆動のため必須）
        sync_agents_from_file(app_ctx)
        admin_agent = app_ctx.agents.get(admin_id)
        notification_sent = await notify_agent_via_tmux(
            app_ctx, admin_agent, msg_type.value, caller_agent_id
        )
        if not notification_sent:
            return {
                "success": False,
                "error": "Admin への tmux 通知に失敗しました",
                "task_id": task_id,
                "normalized_task_id": normalized_task_id,
                "message_id": completion_message.id,
                "reported_status": status,
                "notification_sent": False,
                "cost_snapshot": worker_cost_snapshot,
            }

        # 🔴 Worker 自身を IDLE にリセット
        if caller_agent_id:
            try:
                worker_agent = app_ctx.agents.get(caller_agent_id)
                if worker_agent and worker_agent.role == AgentRole.WORKER.value:
                    reset_agent_to_idle(app_ctx, worker_agent)
                    logger.info("Worker %s を IDLE にリセットしました", caller_agent_id)
            except (OSError, KeyError, ValueError) as e:
                logger.warning("Worker ステータス更新に失敗: %s", e)

        # 自動メモリ保存（タスク結果を記録）
        memory_saved = False
        try:
            memory_manager = ensure_memory_manager(app_ctx)
            memory_content = summary if summary else message
            memory_manager.save(
                key=f"task:{task_id}:result",
                content=f"[{status}] {memory_content}",
                tags=["task", status, task_id],
            )
            memory_saved = True
        except (OSError, ValueError, TypeError) as e:
            logger.debug("メモリ保存をスキップ: %s", e)

        return {
            "success": True,
            "message": f"Admin ({admin_id}) に報告を送信しました",
            "task_id": task_id,
            "normalized_task_id": normalized_task_id,
            "message_id": completion_message.id,
            "reported_status": status,
            "memory_saved": memory_saved,
            "notification_sent": notification_sent,
            "cost_snapshot": worker_cost_snapshot,
        }

    @mcp.tool()
    async def get_task(
        task_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスクの詳細を取得する。

        Args:
            task_id: タスクID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            タスク詳細（success, task または error）
        """
        app_ctx, role_error = require_permission(
            ctx,
            "get_task",
            caller_agent_id,
            target_agent_id=caller_agent_id,
        )
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        task = dashboard.get_task(task_id)
        if not task:
            return {
                "success": False,
                "error": f"タスク {task_id} が見つかりません",
            }

        caller = app_ctx.agents.get(caller_agent_id)
        caller_role = getattr(caller, "role", None)
        is_worker = caller_role in (AgentRole.WORKER.value, "worker")
        if is_worker and task.assigned_agent_id != caller_agent_id:
            return {
                "success": False,
                "error": (
                    "Worker は自分に割り当てられたタスクのみ取得できます。"
                    f" assigned={task.assigned_agent_id}, caller={caller_agent_id}"
                ),
            }

        return {
            "success": True,
            "task": task.model_dump(mode="json"),
        }

    @mcp.tool()
    async def remove_task(
        task_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスクを削除する。

        ※ Owner と Admin のみ使用可能。

        Args:
            task_id: タスクID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            削除結果（success, task_id, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "remove_task", caller_agent_id)
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        success, message = dashboard.remove_task(task_id)

        return {
            "success": success,
            "task_id": task_id,
            "message": message,
        }

    @mcp.tool()
    async def get_dashboard(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """ダッシュボード全体を取得する。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            ダッシュボード情報（success, dashboard）
        """
        app_ctx, role_error = require_permission(ctx, "get_dashboard", caller_agent_id)
        if role_error:
            return _normalize_owner_wait_error(app_ctx, caller_agent_id, role_error)

        dashboard = ensure_dashboard_manager(app_ctx)

        # Worker の場合は Dashboard を読み取り専用で返す（上書き防止）
        caller = app_ctx.agents.get(caller_agent_id)
        caller_role = getattr(caller, "role", None)
        is_admin = caller_role in (AgentRole.ADMIN.value, "admin")
        is_admin_or_owner = caller_role in (
            AgentRole.ADMIN.value,
            AgentRole.OWNER.value,
            "admin",
            "owner",
        )

        if (
            is_admin
            and caller_agent_id
            and _should_block_admin_dashboard_polling(app_ctx, caller_agent_id)
        ):
            return _polling_blocked_response()

        if is_admin_or_owner:
            await _sync_dashboard_for_admin(app_ctx, dashboard)

        dashboard_data = dashboard.get_dashboard()

        return {
            "success": True,
            "dashboard": dashboard_data.model_dump(mode="json"),
        }

    @mcp.tool()
    async def get_dashboard_summary(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """ダッシュボードのサマリーを取得する。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            サマリー情報（success, summary）
        """
        app_ctx, role_error = require_permission(ctx, "get_dashboard_summary", caller_agent_id)
        if role_error:
            return _normalize_owner_wait_error(app_ctx, caller_agent_id, role_error)

        dashboard = ensure_dashboard_manager(app_ctx)

        # Worker の場合は Dashboard を読み取り専用で返す（上書き防止）
        caller = app_ctx.agents.get(caller_agent_id)
        caller_role = getattr(caller, "role", None)
        is_admin = caller_role in (AgentRole.ADMIN.value, "admin")
        is_admin_or_owner = caller_role in (
            AgentRole.ADMIN.value,
            AgentRole.OWNER.value,
            "admin",
            "owner",
        )

        if (
            is_admin
            and caller_agent_id
            and _should_block_admin_dashboard_polling(app_ctx, caller_agent_id)
        ):
            return _polling_blocked_response()

        if is_admin_or_owner:
            await _sync_dashboard_for_admin(app_ctx, dashboard)

        summary = dashboard.get_summary()

        return {
            "success": True,
            "summary": summary,
        }
