"""コマンド実行ツール。"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.workflow_guides import get_role_template_path
from src.models.agent import AgentRole, AgentStatus
from src.models.dashboard import TaskStatus
from src.tools.agent_helpers import (
    _create_worktree_for_worker,
    _send_task_to_worker,
    build_worker_task_branch,
    resolve_worker_number_from_slot,
)
from src.tools.cost_capture import capture_claude_actual_cost_for_agent
from src.tools.helpers import (
    ensure_dashboard_manager,
    get_mcp_tool_prefix_from_config,
    get_worktree_manager,
    require_permission,
    resolve_main_repo_root,
    save_agent_to_file,
    search_memory_context,
    sync_agents_from_file,
)
from src.tools.model_profile import get_current_profile_settings
from src.tools.task_templates import generate_admin_task

logger = logging.getLogger(__name__)


def register_tools(mcp: FastMCP) -> None:
    """コマンド実行ツールを登録する。"""

    @mcp.tool()
    async def send_command(
        agent_id: str,
        command: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """指定エージェントにコマンドを送信する。

        ※ Owner と Admin のみ使用可能。

        Args:
            agent_id: 対象エージェントID
            command: 実行するコマンド
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            送信結果（success, agent_id, command, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "send_command", caller_agent_id)
        if role_error:
            return role_error

        tmux = app_ctx.tmux
        agents = app_ctx.agents

        # ファイルからエージェント情報を同期
        sync_agents_from_file(app_ctx)

        agent = agents.get(agent_id)
        if not agent:
            return {
                "success": False,
                "error": f"エージェント {agent_id} が見つかりません",
            }

        # tmux ペインが設定されていない場合（Owner）はエラー
        if agent.session_name is None or agent.window_index is None or agent.pane_index is None:
            return {
                "success": False,
                "error": f"エージェント {agent_id} は tmux ペインに配置されていません",
            }

        agent_cli_name = (
            agent.ai_cli.value
            if hasattr(agent.ai_cli, "value")
            else str(agent.ai_cli or app_ctx.ai_cli.get_default_cli())
        ).lower()
        success = await tmux.send_with_rate_limit_to_pane(
            agent.session_name,
            agent.window_index,
            agent.pane_index,
            command,
            confirm_codex_prompt=agent_cli_name == "codex",
        )

        if success:
            agent.status = AgentStatus.BUSY
            agent.last_activity = datetime.now()
            # ファイルに保存（MCP インスタンス間で共有）
            save_agent_to_file(app_ctx, agent)

        return {
            "success": success,
            "agent_id": agent_id,
            "command": command,
            "message": "コマンドを送信しました" if success else "コマンド送信に失敗しました",
        }

    @mcp.tool()
    async def get_output(
        agent_id: str,
        lines: int = 50,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェントのtmux出力を取得する。

        ※ Owner と Admin のみ使用可能。

        Args:
            agent_id: 対象エージェントID
            lines: 取得する行数（デフォルト: 50）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            出力内容（success, agent_id, lines, output または error）
        """
        app_ctx, role_error = require_permission(ctx, "get_output", caller_agent_id)
        if role_error:
            return role_error

        tmux = app_ctx.tmux
        agents = app_ctx.agents

        # ファイルからエージェント情報を同期
        sync_agents_from_file(app_ctx)

        agent = agents.get(agent_id)
        if not agent:
            return {
                "success": False,
                "error": f"エージェント {agent_id} が見つかりません",
            }

        # tmux ペインが設定されていない場合（Owner）はエラー
        if agent.session_name is None or agent.window_index is None or agent.pane_index is None:
            return {
                "success": False,
                "error": f"エージェント {agent_id} は tmux ペインに配置されていません",
            }

        output = await tmux.capture_pane_by_index(
            agent.session_name, agent.window_index, agent.pane_index, lines
        )

        # Claude の statusLine からのみ実測コストを取得
        try:
            await capture_claude_actual_cost_for_agent(
                app_ctx=app_ctx,
                agent=agent,
                task_id=agent.current_task,
                capture_lines=max(lines, 80),
            )
        except Exception as e:
            # 実測コスト取得は補助機能のため失敗しても処理継続
            logger.debug("実測コスト取得に失敗: %s", e)

        return {
            "success": True,
            "agent_id": agent_id,
            "lines": lines,
            "output": output,
        }

    async def _resolve_worker_task_id(app_ctx, agent, agent_id, dashboard):
        """Worker 用の task_id を解決する。"""
        effective_task_id = agent.current_task
        selected_task = None
        if not effective_task_id:
            assigned_tasks = dashboard.list_tasks(agent_id=agent_id)
            active_tasks = [
                task
                for task in assigned_tasks
                if task.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)
            ]
            if len(active_tasks) == 1:
                selected_task = active_tasks[0]
                effective_task_id = selected_task.id
        return effective_task_id, selected_task

    async def _prepare_worker_worktree(
        app_ctx, agent, project_root, branch_name, worker_no, effective_task_id,
    ):
        """Worker 用の worktree を準備する。"""
        worktree_manager = get_worktree_manager(app_ctx, str(project_root))
        base_branch = await worktree_manager.get_current_branch(str(project_root))
        if not base_branch:
            base_branch = "main"
        generated_branch = (
            branch_name
            or build_worker_task_branch(base_branch, worker_no, effective_task_id)
        )
        wt_path, wt_error = await _create_worktree_for_worker(
            app_ctx=app_ctx,
            repo_path=str(project_root),
            branch=generated_branch,
            base_branch=base_branch,
            worker_index=max(worker_no - 1, 0),
        )
        return wt_path, wt_error, generated_branch

    def _assign_task_to_dashboard(
        dashboard, effective_task_id, agent_id, dispatch_branch, dispatch_worktree_path, enable_wt,
    ) -> dict | None:
        """dashboard にタスクを割り当てる。失敗時はエラー dict を返す。"""
        try:
            assigned, _ = dashboard.assign_task(
                task_id=effective_task_id, agent_id=agent_id,
                branch=dispatch_branch or None,
                worktree_path=dispatch_worktree_path if enable_wt else None,
            )
            if not assigned:
                return {
                    "success": False,
                    "error": f"task {effective_task_id} を dashboard に割り当てできませんでした。",
                    "assignment_error": f"task_not_found:{effective_task_id}",
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"task 割当更新に失敗: {e}",
                "assignment_error": str(e),
            }
        return None

    async def _send_task_to_worker_via_command(
        app_ctx, agent, agent_id, task_content, session_id,
        auto_enhance, branch_name, project_root, profile_settings, caller_agent_id,
    ) -> dict[str, Any]:
        """Worker へのタスク送信処理。"""
        dashboard = ensure_dashboard_manager(app_ctx)
        if agent.session_name is None or agent.window_index is None or agent.pane_index is None:
            return {
                "success": False,
                "error": f"エージェント {agent_id} は tmux ペインに配置されていません",
            }

        try:
            worker_no = resolve_worker_number_from_slot(
                app_ctx.settings, agent.window_index, agent.pane_index,
            )
        except Exception as e:
            logger.debug("Worker 番号の解決に失敗: %s", e)
            worker_no = 1

        effective_task_id, selected_task = await _resolve_worker_task_id(
            app_ctx, agent, agent_id, dashboard,
        )
        if not effective_task_id:
            return {
                "success": False,
                "error": "worker へ送信する task_id を特定できません。",
                "assignment_error": "task_id_unresolved",
            }

        dispatch_wt = agent.worktree_path or agent.working_dir or str(project_root)
        dispatch_branch = branch_name or (selected_task.branch if selected_task else "")
        enable_wt = app_ctx.settings.enable_worktree

        if enable_wt:
            wt_path, wt_error, generated_branch = await _prepare_worker_worktree(
                app_ctx, agent, project_root, branch_name, worker_no, effective_task_id,
            )
            if wt_error or not wt_path:
                return {"success": False, "error": wt_error or "worktree 作成に失敗しました"}
            dispatch_wt, dispatch_branch = wt_path, generated_branch
            agent.worktree_path = wt_path
            agent.working_dir = wt_path

        assign_err = _assign_task_to_dashboard(
            dashboard, effective_task_id, agent_id,
            dispatch_branch, dispatch_wt, enable_wt,
        )
        if assign_err:
            return assign_err

        agent.current_task = effective_task_id
        agent.status = AgentStatus.BUSY
        agent.last_activity = datetime.now()
        save_agent_to_file(app_ctx, agent)
        dashboard.update_agent_summary(agent)

        send_result = await _send_task_to_worker(
            app_ctx=app_ctx, agent=agent, task_content=task_content,
            task_id=effective_task_id, branch=dispatch_branch,
            worktree_path=dispatch_wt, session_id=session_id,
            worker_index=max(worker_no - 1, 0),
            enable_worktree=enable_wt, profile_settings=profile_settings,
            caller_agent_id=caller_agent_id,
        )
        ok = bool(send_result.get("task_sent"))
        return {
            "success": ok, "agent_id": agent_id, "agent_role": agent.role,
            "session_id": session_id, "task_file": send_result.get("task_file"),
            "command_sent": send_result.get("command_sent"), "auto_enhanced": auto_enhance,
            "dispatch_mode": send_result.get("dispatch_mode", "none"),
            "dispatch_error": send_result.get("dispatch_error"), "assignment_error": None,
            "branch_name": dispatch_branch or None,
            "worktree_path": dispatch_wt if enable_wt else None,
            "message": "タスクを送信しました" if ok else "タスク送信に失敗しました",
        }

    async def _send_task_to_admin_via_command(
        app_ctx, agent, agent_id, final_task_content, session_id,
        auto_enhance, branch_name, project_root, profile_settings,
    ) -> dict[str, Any]:
        """Admin へのタスク送信処理。"""
        tmux = app_ctx.tmux
        dashboard = ensure_dashboard_manager(app_ctx)
        if hasattr(dashboard, "get_agent_label"):
            agent_label = dashboard.get_agent_label(agent)
        else:
            agent_label = agent.id
        task_file = dashboard.write_task_file(
            project_root, session_id, session_id, agent_label, final_task_content,
        )

        agent_cli = agent.ai_cli or app_ctx.ai_cli.get_default_cli()
        agent_model = profile_settings.get("admin_model")
        thinking_tokens = profile_settings.get("admin_thinking_tokens", 4000)
        reasoning_effort = profile_settings.get("admin_reasoning_effort", "none")

        try:
            read_command = app_ctx.ai_cli.build_stdin_command(
                cli=agent_cli,
                task_file_path=str(task_file),
                worktree_path=agent.worktree_path,
                project_root=str(project_root),
                model=agent_model,
                role="admin",
                role_template_path=str(get_role_template_path("admin")),
                thinking_tokens=thinking_tokens,
                reasoning_effort=reasoning_effort,
            )
        except ValueError as e:
            return {"success": False, "error": f"CLIコマンド生成に失敗しました: {e}"}

        if agent.session_name is None or agent.window_index is None or agent.pane_index is None:
            return {
                "success": False,
                "error": f"エージェント {agent_id} は tmux ペインに配置されていません",
            }

        success = await tmux.send_with_rate_limit_to_pane(
            agent.session_name, agent.window_index, agent.pane_index,
            read_command, confirm_codex_prompt=str(agent_cli).lower() == "codex",
        )
        if success:
            agent.status = AgentStatus.BUSY
            agent.last_activity = datetime.now()
            save_agent_to_file(app_ctx, agent)
            dashboard.save_markdown_dashboard(project_root, session_id)
            try:
                dashboard.record_api_call(
                    ai_cli=agent_cli, model=agent_model,
                    estimated_tokens=thinking_tokens,
                    agent_id=agent_id, task_id=session_id,
                )
            except Exception as e:
                logger.debug(f"コスト記録をスキップ: {e}")

        msg = "タスクを送信しました" if success else "タスク送信に失敗しました"
        return {
            "success": success,
            "agent_id": agent_id,
            "agent_role": agent.role,
            "session_id": session_id,
            "task_file": str(task_file),
            "command_sent": read_command,
            "auto_enhanced": auto_enhance,
            "message": msg,
            "branch_name": branch_name or f"feature/{session_id}",
            "model_profile": profile_settings["profile"],
        }

    def _enhance_admin_task(
        app_ctx, agent_id, task_content, branch_name,
        session_id, project_root, effective_worker_count,
    ):
        """Admin 用タスク内容を自動拡張する。"""
        memory_context = search_memory_context(app_ctx, task_content)
        mcp_prefix = get_mcp_tool_prefix_from_config(str(project_root))
        actual_branch = branch_name or f"feature/{session_id}"
        return generate_admin_task(
            session_id=session_id, agent_id=agent_id,
            plan_content=task_content,
            branch_name=actual_branch,
            worker_count=effective_worker_count,
            memory_context=memory_context,
            project_name=project_root.name,
            working_dir=str(project_root),
            mcp_tool_prefix=mcp_prefix,
            settings=app_ctx.settings,
        )

    @mcp.tool()
    async def send_task(
        agent_id: str, task_content: str, session_id: str,
        auto_enhance: bool = True, branch_name: str | None = None,
        caller_agent_id: str | None = None, ctx: Context = None,
    ) -> dict[str, Any]:
        """タスク指示をファイル経由でエージェントに送信する。※ Owner と Admin のみ使用可能。

        Args:
            agent_id: エージェントID
            task_content: タスク内容（Markdown形式）
            session_id: Issue番号または一意なタスクID
            auto_enhance: 自動拡張を行うか（デフォルト: True）
            branch_name: 作業ブランチ名（Admin 用、省略時は feature/{session_id}）
            caller_agent_id: 呼び出し元エージェントID（必須）
        """
        app_ctx, role_error = require_permission(ctx, "send_task", caller_agent_id)
        if role_error:
            return role_error

        agents = app_ctx.agents
        app_ctx.session_id = session_id
        sync_agents_from_file(app_ctx)

        profile_settings = get_current_profile_settings(app_ctx)
        agent = agents.get(agent_id)
        if not agent:
            return {"success": False, "error": f"エージェント {agent_id} が見つかりません"}

        if agent.worktree_path:
            project_root = Path(resolve_main_repo_root(agent.worktree_path))
        elif agent.working_dir:
            project_root = Path(resolve_main_repo_root(agent.working_dir))
        else:
            return {
                "success": False,
                "error": "エージェントに working_dir または worktree_path が設定されていません",
            }

        is_admin = agent.role == AgentRole.ADMIN.value

        if not is_admin:
            return await _send_task_to_worker_via_command(
                app_ctx, agent, agent_id, task_content, session_id,
                auto_enhance, branch_name, project_root, profile_settings, caller_agent_id,
            )

        final_task_content = task_content
        if auto_enhance:
            final_task_content = _enhance_admin_task(
                app_ctx, agent_id, task_content, branch_name, session_id,
                project_root, profile_settings["max_workers"],
            )

        return await _send_task_to_admin_via_command(
            app_ctx, agent, agent_id, final_task_content, session_id,
            auto_enhance, branch_name, project_root, profile_settings,
        )

    @mcp.tool()
    async def open_session(
        agent_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェントのtmuxセッションをターミナルアプリで開く。

        優先順位: ghostty → iTerm2 → Terminal.app

        ※ Owner のみ使用可能。

        Args:
            agent_id: エージェントID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            開く結果（success, agent_id, session, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "open_session", caller_agent_id)
        if role_error:
            return role_error

        tmux = app_ctx.tmux
        agents = app_ctx.agents

        agent = agents.get(agent_id)
        if not agent:
            return {
                "success": False,
                "error": f"エージェント {agent_id} が見つかりません",
            }

        # tmux ペインが設定されていない場合（Owner）はエラー
        if agent.session_name is None:
            return {
                "success": False,
                "error": f"エージェント {agent_id} は tmux ペインに配置されていません",
            }

        success = await tmux.open_session_in_terminal(agent.session_name)
        return {
            "success": success,
            "agent_id": agent_id,
            "session": agent.session_name,
            "pane": f"{agent.window_index}.{agent.pane_index}",
            "message": (
                "ターミナルでセッションを開きました"
                if success
                else "セッションを開けませんでした"
            ),
        }

    @mcp.tool()
    async def broadcast_command(
        command: str,
        role: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """全エージェント（または特定役割）にコマンドをブロードキャストする。

        ※ Owner と Admin のみ使用可能。

        Args:
            command: 実行するコマンド
            role: 対象の役割（省略時は全員、有効: owner/admin/worker）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            送信結果（success, command, role_filter, results, summary または error）
        """
        app_ctx, role_error = require_permission(ctx, "broadcast_command", caller_agent_id)
        if role_error:
            return role_error

        tmux = app_ctx.tmux
        agents = app_ctx.agents

        target_role = None
        if role:
            try:
                target_role = AgentRole(role)
            except ValueError:
                return {
                    "success": False,
                    "error": f"無効な役割です: {role}（有効: owner, admin, worker）",
                }

        results: dict[str, bool] = {}
        now = datetime.now()

        for aid, agent in agents.items():
            if target_role and agent.role != target_role:
                continue

            # tmux ペインが設定されていない場合（Owner）はスキップ
            if agent.session_name is None or agent.window_index is None or agent.pane_index is None:
                continue

            agent_cli_name = (
                agent.ai_cli.value
                if hasattr(agent.ai_cli, "value")
                else str(agent.ai_cli or app_ctx.ai_cli.get_default_cli())
            ).lower()
            success = await tmux.send_with_rate_limit_to_pane(
                agent.session_name,
                agent.window_index,
                agent.pane_index,
                command,
                confirm_codex_prompt=agent_cli_name == "codex",
            )
            results[aid] = success

            if success:
                agent.last_activity = now
                # ファイルに保存（MCP インスタンス間で共有）
                save_agent_to_file(app_ctx, agent)

        success_count = sum(1 for v in results.values() if v)
        total_count = len(results)

        return {
            "success": True,
            "command": command,
            "role_filter": role,
            "results": results,
            "summary": f"{success_count}/{total_count} エージェントに送信成功",
        }
