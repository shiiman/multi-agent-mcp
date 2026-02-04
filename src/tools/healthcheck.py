"""ヘルスチェック管理ツール。"""

import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.tools.helpers import check_tool_permission, ensure_healthcheck_manager

logger = logging.getLogger(__name__)


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
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "full_recovery", caller_agent_id)
        if role_error:
            return role_error

        agents = app_ctx.agents
        tmux = app_ctx.tmux
        settings = app_ctx.settings

        # 対象エージェント取得
        old_agent = agents.get(agent_id)
        if not old_agent:
            return {
                "success": False,
                "error": f"エージェント {agent_id} が見つかりません",
            }

        # Worker のみ復旧対象
        from src.models.agent import AgentRole
        if old_agent.role != AgentRole.WORKER:
            return {
                "success": False,
                "error": f"Worker のみ復旧可能です（対象: {old_agent.role.value}）",
            }

        # 元の情報を保存
        old_worktree_path = old_agent.worktree_path
        old_branch = old_agent.branch
        old_ai_cli = old_agent.ai_cli
        old_session_name = old_agent.session_name
        old_window_index = old_agent.window_index
        old_pane_index = old_agent.pane_index

        # Dashboard からタスク情報を取得（agent に割り当てられていたタスク）
        from src.tools.helpers import ensure_dashboard_manager
        dashboard = ensure_dashboard_manager(app_ctx)

        reassigned_tasks = []
        if dashboard:
            # 対象エージェントに割り当てられていた未完了タスク
            tasks = dashboard.list_all_tasks()
            for task in tasks:
                if (
                    task.get("assigned_to") == agent_id
                    and task.get("status") not in ["completed", "failed"]
                ):
                    reassigned_tasks.append(task)

        logger.info(f"full_recovery 開始: agent={agent_id}, tasks={len(reassigned_tasks)}")

        # 1. 古い agent の tmux ペインをクリア（terminate）
        if (
            old_session_name is not None
            and old_window_index is not None
            and old_pane_index is not None
        ):
            try:
                # Ctrl+C を送信してプロセスを停止
                session_name = tmux._session_name(old_session_name)
                window_name = tmux._get_window_name(old_window_index)
                target = f"{session_name}:{window_name}.{old_pane_index}"
                await tmux._run("send-keys", "-t", target, "C-c")
                # ペインをクリア
                await tmux._run("send-keys", "-t", target, "clear", "Enter")
            except Exception as e:
                logger.warning(f"tmux ペインのクリアに失敗: {e}")

        # 2. agents 辞書から削除
        del agents[agent_id]

        # 3. 古い worktree を削除（存在する場合）
        new_worktree_path = old_worktree_path
        if old_worktree_path and old_branch:
            from src.managers.worktree_manager import WorktreeManager
            try:
                worktree_manager = WorktreeManager(app_ctx.project_root)
                # 強制削除
                await worktree_manager.remove_worktree(old_worktree_path, force=True)
                logger.info(f"古い worktree を削除: {old_worktree_path}")

                # 4. 新しい worktree を作成（同じブランチ名で）
                # パスは同じ場所を再利用
                result = await worktree_manager.create_worktree(
                    worktree_path=old_worktree_path,
                    branch=old_branch,
                    base_branch="main",  # 既存ブランチを使用するため base_branch は無視される
                )
                if not result:
                    # 新しいパスで作成
                    import uuid
                    new_worktree_path = f"{old_worktree_path}-{uuid.uuid4().hex[:8]}"
                    result = await worktree_manager.create_worktree(
                        worktree_path=new_worktree_path,
                        branch=old_branch,
                        base_branch="main",
                    )
                logger.info(f"新しい worktree を作成: {new_worktree_path}")
            except Exception as e:
                logger.warning(f"worktree 操作に失敗: {e}")
                new_worktree_path = old_worktree_path

        # 5. 新しい agent を作成
        import uuid
        from datetime import datetime
        from src.models.agent import Agent, AgentStatus
        from src.tools.helpers import save_agent_to_file

        new_agent_id = f"worker-{uuid.uuid4().hex[:8]}"
        new_agent = Agent(
            id=new_agent_id,
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session=f"{settings.tmux_prefix}-{new_agent_id}",
            created_at=datetime.now(),
            last_activity=datetime.now(),
            worktree_path=new_worktree_path,
            branch=old_branch,
            ai_cli=old_ai_cli,
            session_name=old_session_name,
            window_index=old_window_index,
            pane_index=old_pane_index,
        )
        agents[new_agent_id] = new_agent
        save_agent_to_file(app_ctx, new_agent)
        logger.info(f"新しい agent を作成: {new_agent_id}")

        # 6. tmux ペインで新しい agent を起動（working_dir を設定）
        if (
            old_session_name is not None
            and old_window_index is not None
            and old_pane_index is not None
            and new_worktree_path
        ):
            try:
                session_name = tmux._session_name(old_session_name)
                window_name = tmux._get_window_name(old_window_index)
                target = f"{session_name}:{window_name}.{old_pane_index}"
                # working directory を変更
                await tmux._run("send-keys", "-t", target, f"cd {new_worktree_path}", "Enter")
                # ペインタイトルを設定
                await tmux.set_pane_title(
                    old_session_name, old_window_index, old_pane_index, new_agent_id
                )
            except Exception as e:
                logger.warning(f"tmux ペインの設定に失敗: {e}")

        # 7. タスクを新しい agent に再割り当て
        for task in reassigned_tasks:
            task_id = task.get("id")
            if task_id and dashboard:
                try:
                    dashboard.update_task(task_id, assigned_to=new_agent_id)
                    logger.info(f"タスク {task_id} を {new_agent_id} に再割り当て")
                except Exception as e:
                    logger.warning(f"タスク再割り当てに失敗: {e}")

        return {
            "success": True,
            "old_agent_id": agent_id,
            "new_agent_id": new_agent_id,
            "new_worktree_path": new_worktree_path,
            "reassigned_tasks": [t.get("id") for t in reassigned_tasks],
            "message": f"エージェント {agent_id} を {new_agent_id} として復旧しました（タスク: {len(reassigned_tasks)} 件再割り当て）",
        }

