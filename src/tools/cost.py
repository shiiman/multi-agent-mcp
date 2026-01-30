"""コスト管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.tools.helpers import ensure_cost_manager


def register_tools(mcp: FastMCP) -> None:
    """コスト管理ツールを登録する。"""

    @mcp.tool()
    async def get_cost_estimate(ctx: Context = None) -> dict[str, Any]:
        """現在のコスト推定を取得する。

        Returns:
            コスト推定（success, estimate, warning）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
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
        ctx: Context = None,
    ) -> dict[str, Any]:
        """コスト警告の閾値を設定する。

        Args:
            threshold_usd: 新しい閾値（USD）

        Returns:
            設定結果（success, threshold, message）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        cost = ensure_cost_manager(app_ctx)

        cost.set_warning_threshold(threshold_usd)

        return {
            "success": True,
            "threshold": threshold_usd,
            "message": f"コスト警告閾値を ${threshold_usd:.2f} に設定しました",
        }

    @mcp.tool()
    async def reset_cost_counter(ctx: Context = None) -> dict[str, Any]:
        """コストカウンターをリセットする。

        Returns:
            リセット結果（success, deleted_count, message）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        cost = ensure_cost_manager(app_ctx)

        deleted = cost.reset()

        return {
            "success": True,
            "deleted_count": deleted,
            "message": f"{deleted} 件の記録をリセットしました",
        }

    @mcp.tool()
    async def get_cost_summary(ctx: Context = None) -> dict[str, Any]:
        """コストサマリーを取得する。

        Returns:
            コストサマリー（success, summary）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        cost = ensure_cost_manager(app_ctx)

        summary = cost.get_summary()

        return {
            "success": True,
            "summary": summary,
        }
