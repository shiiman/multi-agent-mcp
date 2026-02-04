"""ヘルスチェック管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.tools.helpers import check_tool_permission, ensure_healthcheck_manager


def register_tools(mcp: FastMCP) -> None:
    """ヘルスチェック管理ツールを登録する。"""

    @mcp.tool()
    async def healthcheck_agent(
        agent_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """特定エージェントのヘルスチェックを実行する。

        ※ Owner と Admin のみ使用可能。

        Args:
            agent_id: エージェントID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            ヘルス状態（success, health_status）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "healthcheck_agent", caller_agent_id)
        if role_error:
            return role_error

        healthcheck = ensure_healthcheck_manager(app_ctx)

        status = await healthcheck.check_agent(agent_id)

        return {
            "success": True,
            "health_status": status.to_dict(),
        }

    @mcp.tool()
    async def healthcheck_all(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """全エージェントのヘルスチェックを実行する。

        ※ Owner と Admin のみ使用可能。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            全ヘルス状態（success, statuses, summary）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "healthcheck_all", caller_agent_id)
        if role_error:
            return role_error

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
    async def get_unhealthy_agents(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """異常なエージェント一覧を取得する。

        ※ Owner と Admin のみ使用可能。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            異常エージェント一覧（success, unhealthy_agents, count）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_unhealthy_agents", caller_agent_id)
        if role_error:
            return role_error

        healthcheck = ensure_healthcheck_manager(app_ctx)

        unhealthy = await healthcheck.get_unhealthy_agents()

        return {
            "success": True,
            "unhealthy_agents": [s.to_dict() for s in unhealthy],
            "count": len(unhealthy),
        }

    @mcp.tool()
    async def attempt_recovery(
        agent_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェントの復旧を試みる。

        ※ Owner と Admin のみ使用可能。

        Args:
            agent_id: エージェントID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            復旧結果（success, message）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "attempt_recovery", caller_agent_id)
        if role_error:
            return role_error

        healthcheck = ensure_healthcheck_manager(app_ctx)

        success, message = await healthcheck.attempt_recovery(agent_id)

        return {
            "success": success,
            "agent_id": agent_id,
            "message": message,
        }

    @mcp.tool()
    async def record_heartbeat(
        agent_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """ハートビートを記録する。

        Args:
            agent_id: エージェントID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            記録結果（success, message）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "record_heartbeat", caller_agent_id)
        if role_error:
            return role_error

        healthcheck = ensure_healthcheck_manager(app_ctx)

        success = healthcheck.record_heartbeat(agent_id)

        return {
            "success": success,
            "agent_id": agent_id,
            "message": "ハートビートを記録しました" if success else "エージェントが見つかりません",
        }
