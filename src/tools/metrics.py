"""メトリクス管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.tools.helpers import ensure_metrics_manager


def register_tools(mcp: FastMCP) -> None:
    """メトリクス管理ツールを登録する。"""

    @mcp.tool()
    async def get_task_metrics(task_id: str, ctx: Context = None) -> dict[str, Any]:
        """タスクのメトリクスを取得する。

        Args:
            task_id: タスクID

        Returns:
            タスクメトリクス（success, metrics または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        metrics = ensure_metrics_manager(app_ctx)

        task_metrics = metrics.get_task_metrics(task_id)

        if not task_metrics:
            return {
                "success": False,
                "error": f"タスク {task_id} のメトリクスが見つかりません",
            }

        return {
            "success": True,
            "metrics": task_metrics.to_dict(),
        }

    @mcp.tool()
    async def get_agent_metrics(agent_id: str, ctx: Context = None) -> dict[str, Any]:
        """エージェントのメトリクスを取得する。

        Args:
            agent_id: エージェントID

        Returns:
            エージェントメトリクス（success, metrics）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        metrics = ensure_metrics_manager(app_ctx)

        agent_metrics = metrics.get_agent_metrics(agent_id)

        return {
            "success": True,
            "metrics": agent_metrics.to_dict(),
        }

    @mcp.tool()
    async def get_workspace_metrics(ctx: Context = None) -> dict[str, Any]:
        """ワークスペース全体のメトリクスを取得する。

        Returns:
            ワークスペースメトリクス（success, metrics）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        metrics = ensure_metrics_manager(app_ctx)

        workspace_metrics = metrics.get_workspace_metrics(app_ctx.agents)

        return {
            "success": True,
            "metrics": workspace_metrics.to_dict(),
        }

    @mcp.tool()
    async def get_metrics_summary(ctx: Context = None) -> dict[str, Any]:
        """メトリクスのサマリーを取得する。

        Returns:
            サマリー（success, summary）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        metrics = ensure_metrics_manager(app_ctx)

        summary = metrics.get_summary()

        return {
            "success": True,
            "summary": summary,
        }
