"""ダッシュボード/タスク管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.models.dashboard import TaskStatus
from src.models.message import MessagePriority, MessageType
from src.tools.helpers import (
    check_role_permission,
    ensure_dashboard_manager,
    ensure_ipc_manager,
    find_agents_by_role,
)


def register_tools(mcp: FastMCP) -> None:
    """ダッシュボード/タスク管理ツールを登録する。"""

    @mcp.tool()
    async def create_task(
        title: str,
        description: str = "",
        assigned_agent_id: str | None = None,
        branch: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """新しいタスクを作成する。

        Args:
            title: タスクタイトル
            description: タスク説明
            assigned_agent_id: 割り当て先エージェントID（オプション）
            branch: 作業ブランチ（オプション）

        Returns:
            作成結果（success, task, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
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
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック: Admin のみ
        role_error = check_role_permission(app_ctx, caller_agent_id, ["admin"])
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
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック: Admin のみ
        role_error = check_role_permission(app_ctx, caller_agent_id, ["admin"])
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

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
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスク一覧を取得する。

        Args:
            status: フィルターするステータス（オプション）
            agent_id: フィルターするエージェントID（オプション）

        Returns:
            タスク一覧（success, tasks, count または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
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
    async def report_task_completion(
        task_id: str,
        status: str,
        message: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """Worker が Admin にタスク完了を報告する。

        Worker はこのツールを使って Admin に作業結果を報告します。
        Admin が受け取って dashboard を更新します。

        ※ Worker のみ使用可能。

        Args:
            task_id: 完了したタスクのID
            status: 結果ステータス（"completed" | "failed"）
            message: 完了報告メッセージ（作業内容の要約）
            caller_agent_id: 呼び出し元エージェントID（Worker のID）

        Returns:
            報告結果（success, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック: Worker のみ
        role_error = check_role_permission(app_ctx, caller_agent_id, ["worker"])
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

        # IPC マネージャーを取得
        ipc = app_ctx.ipc_manager
        if ipc is None:
            return {
                "success": False,
                "error": "IPC マネージャーが初期化されていません",
            }

        # タスク完了報告を送信
        ipc.send_message(
            sender_id=caller_agent_id,
            receiver_id=admin_id,
            message_type=MessageType.TASK_COMPLETE if status == "completed" else MessageType.ERROR,
            subject=f"タスク報告: {task_id} ({status})",
            content=message,
            priority=MessagePriority.HIGH,
            metadata={
                "task_id": task_id,
                "status": status,
                "reporter": caller_agent_id,
            },
        )

        return {
            "success": True,
            "message": f"Admin ({admin_id}) に報告を送信しました",
            "task_id": task_id,
            "reported_status": status,
        }

    @mcp.tool()
    async def get_task(task_id: str, ctx: Context = None) -> dict[str, Any]:
        """タスクの詳細を取得する。

        Args:
            task_id: タスクID

        Returns:
            タスク詳細（success, task または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
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
    async def remove_task(task_id: str, ctx: Context = None) -> dict[str, Any]:
        """タスクを削除する。

        Args:
            task_id: タスクID

        Returns:
            削除結果（success, task_id, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        dashboard = ensure_dashboard_manager(app_ctx)

        success, message = dashboard.remove_task(task_id)

        return {
            "success": success,
            "task_id": task_id,
            "message": message,
        }

    @mcp.tool()
    async def get_dashboard(ctx: Context = None) -> dict[str, Any]:
        """ダッシュボード全体を取得する。

        Returns:
            ダッシュボード情報（success, dashboard）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        dashboard = ensure_dashboard_manager(app_ctx)

        # エージェント情報を同期
        for agent in app_ctx.agents.values():
            dashboard.update_agent_summary(agent)

        dashboard_data = dashboard.get_dashboard()

        return {
            "success": True,
            "dashboard": dashboard_data.model_dump(mode="json"),
        }

    @mcp.tool()
    async def get_dashboard_summary(ctx: Context = None) -> dict[str, Any]:
        """ダッシュボードのサマリーを取得する。

        Returns:
            サマリー情報（success, summary）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        dashboard = ensure_dashboard_manager(app_ctx)

        # エージェント情報を同期
        for agent in app_ctx.agents.values():
            dashboard.update_agent_summary(agent)

        summary = dashboard.get_summary()

        return {
            "success": True,
            "summary": summary,
        }
