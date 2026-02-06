"""ダッシュボード/タスク管理ツール。"""

import logging
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.models.agent import AgentRole, AgentStatus
from src.models.dashboard import TaskStatus
from src.models.message import MessagePriority, MessageType
from src.tools.helpers import (
    ensure_dashboard_manager,
    ensure_ipc_manager,
    ensure_memory_manager,
    find_agents_by_role,
    require_permission,
    save_agent_to_file,
    sync_agents_from_file,
)

logger = logging.getLogger(__name__)


def register_tools(mcp: FastMCP) -> None:
    """ダッシュボード/タスク管理ツールを登録する。"""

    @mcp.tool()
    async def create_task(
        title: str,
        description: str = "",
        assigned_agent_id: str | None = None,
        branch: str | None = None,
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
        )

        return {
            "success": True,
            "task": task.model_dump(mode="json"),
            "message": f"タスクを作成しました: {task.id}",
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
            status: 新しいステータス（pending/in_progress/completed/failed/blocked）
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
        app_ctx, role_error = require_permission(ctx, "list_tasks", caller_agent_id)
        if role_error:
            return role_error

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

        # progress の検証（checklist がある場合は自動計算されるためスキップ可）
        if progress is not None and not (0 <= progress <= 100):
            return {
                "success": False,
                "error": f"無効な進捗率です: {progress}（有効: 0-100）",
            }

        # Worker は Dashboard を直接更新しない（Admin が IPC 経由で更新する）
        actual_progress = progress or 0

        # Admin にも進捗を通知（IPC メッセージ）
        admin_notified = False
        try:
            admin_ids = find_agents_by_role(app_ctx, "admin")
            if admin_ids:
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
                        "progress": actual_progress,
                        "checklist": checklist,
                        "message": message,
                        "reporter": caller_agent_id,
                    },
                )
                admin_notified = True
        except Exception as e:
            logger.warning(f"Admin への進捗通知に失敗: {e}")

        # 🔴 Admin に tmux 通知を送信（IPC 通知駆動のため必須）
        # BUSY/IDLE に関係なく常に通知を送信
        if admin_notified and admin_ids:
            try:
                tmux = app_ctx.tmux
                admin_id_for_notify = admin_ids[0]

                # ファイルから最新の状態を取得
                sync_agents_from_file(app_ctx)
                agents = app_ctx.agents

                admin_agent = agents.get(admin_id_for_notify)
                if (
                    not admin_agent
                    or not admin_agent.session_name
                    or admin_agent.pane_index is None
                ):
                    logger.warning(
                        f"Admin エージェントの tmux 情報が見つかりません: {admin_id_for_notify}"
                    )
                else:
                    notification_text = (
                        "echo '[IPC] 新しいメッセージ:"
                        f" task_progress from {caller_agent_id}'"
                    )
                    await tmux.send_keys_to_pane(
                        admin_agent.session_name,
                        admin_agent.window_index or 0,
                        admin_agent.pane_index,
                        notification_text,
                        clear_input=False,
                    )
                    logger.info(f"Admin への tmux 通知を送信: {admin_id_for_notify}")
            except Exception as e:
                logger.warning(f"Admin への tmux 通知の送信に失敗: {e}")

        return {
            "success": True,
            "task_id": task_id,
            "progress": actual_progress,
            "admin_notified": admin_notified,
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

        # Worker は Dashboard を直接更新しない（Admin が IPC 経由で更新する）

        # IPC マネージャーを取得（自動初期化）
        ipc = ensure_ipc_manager(app_ctx)

        # タスク完了報告を送信
        msg_type = MessageType.TASK_COMPLETE if status == "completed" else MessageType.ERROR
        ipc.send_message(
            sender_id=caller_agent_id,
            receiver_id=admin_id,
            message_type=msg_type,
            subject=f"タスク報告: {task_id} ({status})",
            content=message,
            priority=MessagePriority.HIGH,
            metadata={
                "task_id": task_id,
                "status": status,
                "reporter": caller_agent_id,
            },
        )

        # 🔴 Admin に tmux 通知を送信（IPC 通知駆動のため必須）
        # BUSY/IDLE に関係なく常に通知を送信
        notification_sent = False
        try:
            tmux = app_ctx.tmux

            # ファイルから最新の状態を取得
            sync_agents_from_file(app_ctx)
            agents = app_ctx.agents

            admin_agent = agents.get(admin_id)
            if not admin_agent or not admin_agent.session_name or admin_agent.pane_index is None:
                logger.warning(f"Admin エージェントの tmux 情報が見つかりません: {admin_id}")
            else:
                notification_text = (
                    "echo '[IPC] 新しいメッセージ:"
                    f" {msg_type.value} from {caller_agent_id}'"
                )
                await tmux.send_keys_to_pane(
                    admin_agent.session_name,
                    admin_agent.window_index or 0,
                    admin_agent.pane_index,
                    notification_text,
                    clear_input=False,
                )
                logger.info(f"Admin への tmux 通知を送信: {admin_id}")
        except Exception as e:
            logger.warning(f"Admin への tmux 通知の送信に失敗: {e}")

        # 🔴 Worker 自身を IDLE にリセット
        if caller_agent_id:
            try:
                worker_agent = agents.get(caller_agent_id)
                if worker_agent and worker_agent.role == AgentRole.WORKER.value:
                    worker_agent.status = AgentStatus.IDLE
                    worker_agent.current_task = None
                    worker_agent.last_activity = datetime.now()
                    save_agent_to_file(app_ctx, worker_agent)
                    logger.info(f"Worker {caller_agent_id} を IDLE にリセットしました")
            except Exception as e:
                logger.warning(f"Worker ステータス更新に失敗: {e}")

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
        except Exception as e:
            logger.debug(f"メモリ保存をスキップ: {e}")

        return {
            "success": True,
            "message": f"Admin ({admin_id}) に報告を送信しました",
            "task_id": task_id,
            "reported_status": status,
            "memory_saved": memory_saved,
            "notification_sent": notification_sent,
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
        app_ctx, role_error = require_permission(ctx, "get_task", caller_agent_id)
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        task = dashboard.get_task(task_id)
        if not task:
            return {
                "success": False,
                "error": f"タスク {task_id} が見つかりません",
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
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        # Worker の場合は Dashboard を読み取り専用で返す（上書き防止）
        caller = app_ctx.agents.get(caller_agent_id)
        caller_role = getattr(caller, "role", None)
        is_admin_or_owner = caller_role in (
            AgentRole.ADMIN.value, AgentRole.OWNER.value, "admin", "owner",
        )

        if is_admin_or_owner:
            # Admin/Owner: エージェント情報を同期して Dashboard を更新
            sync_agents_from_file(app_ctx)
            for agent in app_ctx.agents.values():
                dashboard.update_agent_summary(agent)
            if app_ctx.session_id and app_ctx.project_root:
                try:
                    dashboard.save_markdown_dashboard(
                        app_ctx.project_root, app_ctx.session_id
                    )
                except Exception as e:
                    logger.warning(f"Dashboard ファイル更新に失敗: {e}")

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
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        # Worker の場合は Dashboard を読み取り専用で返す（上書き防止）
        caller = app_ctx.agents.get(caller_agent_id)
        caller_role = getattr(caller, "role", None)
        is_admin_or_owner = caller_role in (
            AgentRole.ADMIN.value, AgentRole.OWNER.value, "admin", "owner",
        )

        if is_admin_or_owner:
            # Admin/Owner: エージェント情報を同期して Dashboard を更新
            sync_agents_from_file(app_ctx)
            for agent in app_ctx.agents.values():
                dashboard.update_agent_summary(agent)
            if app_ctx.session_id and app_ctx.project_root:
                try:
                    dashboard.save_markdown_dashboard(
                        app_ctx.project_root, app_ctx.session_id
                    )
                except Exception as e:
                    logger.warning(f"Dashboard ファイル更新に失敗: {e}")

        summary = dashboard.get_summary()

        return {
            "success": True,
            "summary": summary,
        }

