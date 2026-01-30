"""ヘルスチェック管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.tools.helpers import ensure_healthcheck_manager


def register_tools(mcp: FastMCP) -> None:
    """ヘルスチェック管理ツールを登録する。"""

    @mcp.tool()
    async def healthcheck_agent(agent_id: str, ctx: Context = None) -> dict[str, Any]:
        """特定エージェントのヘルスチェックを実行する。

        Args:
            agent_id: エージェントID

        Returns:
            ヘルス状態（success, health_status）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        healthcheck = ensure_healthcheck_manager(app_ctx)

        status = await healthcheck.check_agent(agent_id)

        return {
            "success": True,
            "health_status": status.to_dict(),
        }

    @mcp.tool()
    async def healthcheck_all(ctx: Context = None) -> dict[str, Any]:
        """全エージェントのヘルスチェックを実行する。

        Returns:
            全ヘルス状態（success, statuses, summary）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        healthcheck = ensure_healthcheck_manager(app_ctx)

        statuses = await healthcheck.check_all_agents()
        healthy_count = sum(1 for s in statuses if s.is_healthy)
        unhealthy_count = len(statuses) - healthy_count

        return {
            "success": True,
            "statuses": [s.to_dict() for s in statuses],
            "summary": {
                "total": len(statuses),
                "healthy": healthy_count,
                "unhealthy": unhealthy_count,
            },
        }

    @mcp.tool()
    async def get_unhealthy_agents(ctx: Context = None) -> dict[str, Any]:
        """異常なエージェント一覧を取得する。

        Returns:
            異常エージェント一覧（success, unhealthy_agents, count）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        healthcheck = ensure_healthcheck_manager(app_ctx)

        unhealthy = await healthcheck.get_unhealthy_agents()

        return {
            "success": True,
            "unhealthy_agents": [s.to_dict() for s in unhealthy],
            "count": len(unhealthy),
        }

    @mcp.tool()
    async def attempt_recovery(agent_id: str, ctx: Context = None) -> dict[str, Any]:
        """エージェントの復旧を試みる。

        Args:
            agent_id: エージェントID

        Returns:
            復旧結果（success, message）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        healthcheck = ensure_healthcheck_manager(app_ctx)

        success, message = await healthcheck.attempt_recovery(agent_id)

        return {
            "success": success,
            "agent_id": agent_id,
            "message": message,
        }

    @mcp.tool()
    async def record_heartbeat(agent_id: str, ctx: Context = None) -> dict[str, Any]:
        """ハートビートを記録する。

        Args:
            agent_id: エージェントID

        Returns:
            記録結果（success, message）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        healthcheck = ensure_healthcheck_manager(app_ctx)

        success = healthcheck.record_heartbeat(agent_id)

        return {
            "success": success,
            "agent_id": agent_id,
            "message": "ハートビートを記録しました" if success else "エージェントが見つかりません",
        }
