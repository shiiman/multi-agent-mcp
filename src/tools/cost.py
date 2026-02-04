"""コスト管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.tools.helpers import check_tool_permission, ensure_cost_manager


def register_tools(mcp: FastMCP) -> None:
    """コスト管理ツールを登録する。"""

    @mcp.tool()
    async def get_cost_estimate(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """現在のコスト推定を取得する。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            コスト推定（success, estimate, warning）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_cost_estimate", caller_agent_id)
        if role_error:
            return role_error

        cost = ensure_cost_manager(app_ctx)

        estimate = cost.get_estimate()
        warning = cost.check_warning()

        return {
            "success": True,
            "estimate": estimate.to_dict(),
            "warning": warning,
        }

    @mcp.tool()
    async def set_cost_warning_threshold(
        threshold_usd: float,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """コスト警告の閾値を設定する。

        ※ Owner のみ使用可能。

        Args:
            threshold_usd: 新しい閾値（USD）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            設定結果（success, threshold, message）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "set_cost_warning_threshold", caller_agent_id)
        if role_error:
            return role_error

        cost = ensure_cost_manager(app_ctx)

        cost.set_warning_threshold(threshold_usd)

        return {
            "success": True,
            "threshold": threshold_usd,
            "message": f"コスト警告閾値を ${threshold_usd:.2f} に設定しました",
        }

    @mcp.tool()
    async def reset_cost_counter(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """コストカウンターをリセットする。

        ※ Owner のみ使用可能。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            リセット結果（success, deleted_count, message）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "reset_cost_counter", caller_agent_id)
        if role_error:
            return role_error

        cost = ensure_cost_manager(app_ctx)

        deleted = cost.reset()

        return {
            "success": True,
            "deleted_count": deleted,
            "message": f"{deleted} 件の記録をリセットしました",
        }

    @mcp.tool()
    async def get_cost_summary(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """コストサマリーを取得する。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            コストサマリー（success, summary）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_cost_summary", caller_agent_id)
        if role_error:
            return role_error

        cost = ensure_cost_manager(app_ctx)

        summary = cost.get_summary()

        return {
            "success": True,
            "summary": summary,
        }
