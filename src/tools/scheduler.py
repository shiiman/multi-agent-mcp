"""スケジューラー管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.managers.scheduler_manager import TaskPriority
from src.tools.helpers import ensure_scheduler_manager


def register_tools(mcp: FastMCP) -> None:
    """スケジューラー管理ツールを登録する。"""

    @mcp.tool()
    async def enqueue_task(
        task_id: str,
        priority: str = "medium",
        dependencies: list[str] | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスクをスケジューラーキューに追加する。

        Args:
            task_id: タスクID
            priority: 優先度（critical/high/medium/low）
            dependencies: 依存タスクのIDリスト

        Returns:
            追加結果（success, task_id, priority, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        scheduler = ensure_scheduler_manager(app_ctx)

        # 優先度の検証
        try:
            task_priority = TaskPriority[priority.upper()]
        except KeyError:
            valid_priorities = [p.name.lower() for p in TaskPriority]
            return {
                "success": False,
                "error": f"無効な優先度です: {priority}（有効: {valid_priorities}）",
            }

        success = scheduler.enqueue_task(task_id, task_priority, dependencies)

        if not success:
            return {
                "success": False,
                "error": f"タスク {task_id} は既にキューに存在します",
            }

        return {
            "success": True,
            "task_id": task_id,
            "priority": priority,
            "message": f"タスク {task_id} をキューに追加しました",
        }

    @mcp.tool()
    async def auto_assign_tasks(ctx: Context = None) -> dict[str, Any]:
        """空いているWorkerにタスクを自動割り当てする。

        Returns:
            割り当て結果（success, assignments, count）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        scheduler = ensure_scheduler_manager(app_ctx)

        assignments = scheduler.run_auto_assign_loop()

        return {
            "success": True,
            "assignments": [
                {"task_id": tid, "worker_id": wid} for tid, wid in assignments
            ],
            "count": len(assignments),
            "message": f"{len(assignments)} 件のタスクを割り当てました",
        }

    @mcp.tool()
    async def get_task_queue(ctx: Context = None) -> dict[str, Any]:
        """現在のタスクキューを取得する。

        Returns:
            キュー状態（success, queue）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        scheduler = ensure_scheduler_manager(app_ctx)

        queue_status = scheduler.get_queue_status()

        return {
            "success": True,
            "queue": queue_status,
        }
