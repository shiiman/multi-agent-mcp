"""メトリクス管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.tools.helpers import check_tool_permission, ensure_metrics_manager


def register_tools(mcp: FastMCP) -> None:
    """メトリクス管理ツールを登録する。"""

    @mcp.tool()
    async def get_task_metrics(
        task_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスクのメトリクスを取得する。

        Args:
            task_id: タスクID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            タスクメトリクス（success, metrics または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_task_metrics", caller_agent_id)
        if role_error:
            return role_error

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
    async def get_agent_metrics(
        agent_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェントのメトリクスを取得する。

        Args:
            agent_id: エージェントID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            エージェントメトリクス（success, metrics）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_agent_metrics", caller_agent_id)
        if role_error:
            return role_error

        metrics = ensure_metrics_manager(app_ctx)

        agent_metrics = metrics.get_agent_metrics(agent_id)

        return {
            "success": True,
            "metrics": agent_metrics.to_dict(),
        }

    @mcp.tool()
    async def get_workspace_metrics(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """ワークスペース全体のメトリクスを取得する。

        ※ Owner と Admin のみ使用可能。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            ワークスペースメトリクス（success, metrics）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_workspace_metrics", caller_agent_id)
        if role_error:
            return role_error

        metrics = ensure_metrics_manager(app_ctx)

        workspace_metrics = metrics.get_workspace_metrics(app_ctx.agents)

        return {
            "success": True,
            "metrics": workspace_metrics.to_dict(),
        }

    @mcp.tool()
    async def get_metrics_summary(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """メトリクスのサマリーを取得する。

        ※ Owner と Admin のみ使用可能。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            サマリー（success, summary）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_metrics_summary", caller_agent_id)
        if role_error:
            return role_error

        metrics = ensure_metrics_manager(app_ctx)

        summary = metrics.get_summary()

        return {
            "success": True,
            "summary": summary,
        }
