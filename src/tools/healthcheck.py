"""ヘルスチェック管理ツール。"""

import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.tools.helpers import ensure_healthcheck_manager, require_permission

logger = logging.getLogger(__name__)


async def execute_full_recovery(app_ctx, agent_id: str) -> dict[str, Any]:
    """異常な Worker の完全復旧を実行する。"""
    agents = app_ctx.agents
    tmux = app_ctx.tmux
    old_agent = agents.get(agent_id)
    if not old_agent:
        return {
            "success": False,
            "error": f"エージェント {agent_id} が見つかりません",
        }

    from src.models.agent import AgentRole

    if old_agent.role != AgentRole.WORKER.value:
        return {
            "success": False,
            "error": f"Worker のみ復旧可能です（対象: {old_agent.role}）",
        }

    old_worktree_path = old_agent.worktree_path
    old_branch = getattr(old_agent, "branch", None)
    old_ai_cli = old_agent.ai_cli
    old_session_name = old_agent.session_name
    old_window_index = old_agent.window_index
    old_pane_index = old_agent.pane_index

    from src.tools.helpers import ensure_dashboard_manager

    dashboard = ensure_dashboard_manager(app_ctx)
    from src.models.dashboard import TaskStatus

    reassigned_tasks = []
    if dashboard:
        tasks = dashboard.list_tasks()
        for task in tasks:
            if (
                task.assigned_agent_id == agent_id
                and task.status not in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            ):
                reassigned_tasks.append(task)

    logger.info(f"full_recovery 開始: agent={agent_id}, tasks={len(reassigned_tasks)}")

    if (
        old_session_name is not None
        and old_window_index is not None
        and old_pane_index is not None
    ):
        try:
            window_name = tmux._get_window_name(old_window_index)
            target = f"{old_session_name}:{window_name}.{old_pane_index}"
            await tmux._run("send-keys", "-t", target, "C-c")
            await tmux._run("send-keys", "-t", target, "clear", "Enter")
        except Exception as e:
            logger.warning(f"tmux ペインのクリアに失敗: {e}")

    del agents[agent_id]

    new_worktree_path = old_worktree_path
    if old_worktree_path and old_branch:
        from src.managers.worktree_manager import WorktreeManager

        try:
            worktree_manager = WorktreeManager(app_ctx.project_root)
            await worktree_manager.remove_worktree(old_worktree_path, force=True)
            logger.info(f"古い worktree を削除: {old_worktree_path}")

            result = await worktree_manager.create_worktree(
                worktree_path=old_worktree_path,
                branch=old_branch,
                base_branch="main",
            )
            if not result:
                import uuid

                new_worktree_path = f"{old_worktree_path}-{uuid.uuid4().hex[:8]}"
                await worktree_manager.create_worktree(
                    worktree_path=new_worktree_path,
                    branch=old_branch,
                    base_branch="main",
                )
            logger.info(f"新しい worktree を作成: {new_worktree_path}")
        except Exception as e:
            logger.warning(f"worktree 操作に失敗: {e}")
            new_worktree_path = old_worktree_path

    import uuid
    from datetime import datetime

    from src.models.agent import Agent, AgentStatus
    from src.tools.helpers import save_agent_to_file

    new_agent_id = f"worker-{uuid.uuid4().hex[:8]}"
    tmux_session = None
    if (
        old_session_name is not None
        and old_window_index is not None
        and old_pane_index is not None
    ):
        tmux_session = f"{old_session_name}:{old_window_index}.{old_pane_index}"
    new_agent = Agent(
        id=new_agent_id,
        role=AgentRole.WORKER,
        status=AgentStatus.IDLE,
        tmux_session=tmux_session,
        created_at=datetime.now(),
        last_activity=datetime.now(),
        worktree_path=new_worktree_path,
        ai_cli=old_ai_cli,
        session_name=old_session_name,
        window_index=old_window_index,
        pane_index=old_pane_index,
    )
    agents[new_agent_id] = new_agent
    save_agent_to_file(app_ctx, new_agent)
    logger.info(f"新しい agent を作成: {new_agent_id}")

    if (
        old_session_name is not None
        and old_window_index is not None
        and old_pane_index is not None
        and new_worktree_path
    ):
        try:
            window_name = tmux._get_window_name(old_window_index)
            target = f"{old_session_name}:{window_name}.{old_pane_index}"
            await tmux._run("send-keys", "-t", target, f"cd {new_worktree_path}", "Enter")
            await tmux.set_pane_title(
                old_session_name, old_window_index, old_pane_index, new_agent_id
            )
        except Exception as e:
            logger.warning(f"tmux ペインの設定に失敗: {e}")

    for task in reassigned_tasks:
        task_id = task.id
        if task_id and dashboard:
            try:
                dashboard.assign_task(
                    task_id=task_id,
                    agent_id=new_agent_id,
                    branch=task.branch,
                    worktree_path=new_worktree_path,
                )
                logger.info(f"タスク {task_id} を {new_agent_id} に再割り当て")
            except Exception as e:
                logger.warning(f"タスク再割り当てに失敗: {e}")

    return {
        "success": True,
        "old_agent_id": agent_id,
        "new_agent_id": new_agent_id,
        "new_worktree_path": new_worktree_path,
        "reassigned_tasks": [t.id for t in reassigned_tasks],
        "message": (
            f"エージェント {agent_id} を {new_agent_id} として"
            f"復旧しました（タスク: {len(reassigned_tasks)} 件再割り当て）"
        ),
    }


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

        healthcheck = ensure_healthcheck_manager(app_ctx)
        result = await healthcheck.monitor_and_recover_workers()

        return {
            "success": True,
            **result,
            "message": (
                f"recovered={len(result['recovered'])}, "
                f"escalated={len(result['escalated'])}, skipped={len(result['skipped'])}"
            ),
        }
