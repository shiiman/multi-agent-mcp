"""ヘルスチェック管理ツール。"""

import logging
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.tools.helpers import ensure_healthcheck_manager, require_permission

logger = logging.getLogger(__name__)


def _mark_healthcheck_event(app_ctx: Any, caller_agent_id: str | None) -> None:
    """Admin のヘルスチェック実行時刻を記録する。"""
    if not caller_agent_id:
        return
    app_ctx._admin_last_healthcheck_at[caller_agent_id] = datetime.now()


async def execute_full_recovery(app_ctx, agent_id: str) -> dict[str, Any]:
    """異常な Worker の完全復旧を実行する。"""
    healthcheck = ensure_healthcheck_manager(app_ctx)
    return await healthcheck.execute_full_recovery(app_ctx, agent_id)


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
        app_ctx, role_error = require_permission(ctx, "healthcheck_agent", caller_agent_id)
        if role_error:
            return role_error

        _mark_healthcheck_event(app_ctx, caller_agent_id)
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
        app_ctx, role_error = require_permission(ctx, "healthcheck_all", caller_agent_id)
        if role_error:
            return role_error

        _mark_healthcheck_event(app_ctx, caller_agent_id)
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
        app_ctx, role_error = require_permission(ctx, "get_unhealthy_agents", caller_agent_id)
        if role_error:
            return role_error

        _mark_healthcheck_event(app_ctx, caller_agent_id)
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
        app_ctx, role_error = require_permission(ctx, "attempt_recovery", caller_agent_id)
        if role_error:
            return role_error

        _mark_healthcheck_event(app_ctx, caller_agent_id)
        healthcheck = ensure_healthcheck_manager(app_ctx)

        success, message = await healthcheck.attempt_recovery(agent_id)

        return {
            "success": success,
            "agent_id": agent_id,
            "message": message,
        }

    @mcp.tool()
    async def full_recovery(
        agent_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """異常なエージェントの完全復旧を実行する。

        以下のステップで復旧を行う：
        1. 古い agent を terminate
        2. 古い worktree を remove（存在する場合）
        3. 新しい worktree を作成（同じブランチ名で）
        4. 新しい agent を作成
        5. 未完了のタスクを新しい agent に再割り当て

        ※ Admin のみ使用可能。

        Args:
            agent_id: 復旧対象のエージェントID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            復旧結果（success, old_agent_id, new_agent_id, reassigned_tasks, message）
        """
        app_ctx, role_error = require_permission(ctx, "full_recovery", caller_agent_id)
        if role_error:
            return role_error

        _mark_healthcheck_event(app_ctx, caller_agent_id)
        return await execute_full_recovery(app_ctx, agent_id)

    @mcp.tool()
    async def monitor_and_recover_workers(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """Worker を監視し、異常時に復旧を実行する。"""
        app_ctx, role_error = require_permission(
            ctx, "monitor_and_recover_workers", caller_agent_id
        )
        if role_error:
            return role_error

        _mark_healthcheck_event(app_ctx, caller_agent_id)
        healthcheck = ensure_healthcheck_manager(app_ctx)
        result = await healthcheck.monitor_and_recover_workers(app_ctx)

        return {
            "success": True,
            **result,
            "message": (
                f"recovered={len(result['recovered'])}, "
                f"escalated={len(result['escalated'])}, skipped={len(result['skipped'])}"
            ),
        }
