"""コマンド実行ツール。"""

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.workflow_guides import get_role_template_path
from src.models.agent import AgentRole, AgentStatus
from src.tools.helpers import (
    ensure_dashboard_manager,
    get_worktree_manager,
    get_mcp_tool_prefix_from_config,
    require_permission,
    resolve_main_repo_root,
    save_agent_to_file,
    search_memory_context,
    sync_agents_from_file,
)
from src.tools.agent_helpers import (
    _create_worktree_for_worker,
    _send_task_to_worker,
    resolve_worker_number_from_slot,
)
from src.tools.model_profile import get_current_profile_settings
from src.tools.task_templates import generate_admin_task

logger = logging.getLogger(__name__)


def _extract_claude_statusline_cost(output: str) -> tuple[float, str] | None:
    """Claude の statusLine からコスト値を抽出する。"""
    patterns = (
        r"(?:cost|Cost|COST)[^$\n]*\$\s*([0-9]+(?:\.[0-9]+)?)",
        r"\$\s*([0-9]+(?:\.[0-9]+)?)\s*(?:cost|Cost|COST)",
    )
    for line in reversed(output.splitlines()):
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                try:
                    return float(match.group(1)), line.strip()
                except ValueError:
                    continue
    return None


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

        success = await tmux.send_keys_to_pane(
            agent.session_name, agent.window_index, agent.pane_index, command
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
            agent_cli = agent.ai_cli or app_ctx.ai_cli.get_default_cli()
            cli_value = agent_cli.value if hasattr(agent_cli, "value") else str(agent_cli)
            if cli_value == "claude":
                parsed = _extract_claude_statusline_cost(output)
                if parsed:
                    actual_cost_usd, status_line = parsed
                    profile_settings = get_current_profile_settings(app_ctx)
                    model = (
                        profile_settings.get("admin_model")
                        if str(agent.role) == AgentRole.ADMIN.value
                        else profile_settings.get("worker_model")
                    )
                    dashboard = ensure_dashboard_manager(app_ctx)
                    latest_calls = dashboard.get_dashboard().cost.calls[-20:]
                    already_recorded = any(
                        c.agent_id == agent_id and c.status_line == status_line
                        for c in latest_calls
                    )
                    if not already_recorded:
                        dashboard.record_api_call(
                            ai_cli="claude",
                            model=model,
                            estimated_tokens=app_ctx.settings.estimated_tokens_per_call,
                            agent_id=agent_id,
                            task_id=agent.current_task,
                            actual_cost_usd=actual_cost_usd,
                            status_line=status_line,
                            cost_source="actual",
                        )
        except Exception:
            # 実測コスト取得は補助機能のため失敗しても処理継続
            pass

        return {
            "success": True,
            "agent_id": agent_id,
            "lines": lines,
            "output": output,
        }

    @mcp.tool()
    async def send_task(
        agent_id: str,
        task_content: str,
        session_id: str,
        auto_enhance: bool = True,
        branch_name: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスク指示をファイル経由でエージェントに送信する。

        長いマルチライン指示に対応。エージェントはファイル経由でタスクを実行。
        auto_enhance=True の場合:
        - Admin: 計画書 + Worker管理手順を自動生成（Worker 数はプロファイル設定から自動決定）
        - Worker: 7セクション構造・ペルソナ・メモリを自動統合

        ※ Owner と Admin のみ使用可能。

        Args:
            agent_id: エージェントID
            task_content: タスク内容（Markdown形式）
            session_id: Issue番号または一意なタスクID（例: "94", "a1b2c3d4"）
            auto_enhance: 自動拡張を行うか（デフォルト: True）
            branch_name: 作業ブランチ名（Admin 用、省略時は feature/{session_id}）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            送信結果（success, task_file, command_sent, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "send_task", caller_agent_id)
        if role_error:
            return role_error

        tmux = app_ctx.tmux
        agents = app_ctx.agents

        # session_id を AppContext に設定（ディレクトリパス決定に使用）
        app_ctx.session_id = session_id

        # ファイルからエージェント情報を同期（他の MCP インスタンスで作成されたエージェントを取得）
        sync_agents_from_file(app_ctx)

        # プロファイル設定から Worker 数を取得（MCP 側で一元管理）
        profile_settings = get_current_profile_settings(app_ctx)
        effective_worker_count = profile_settings["max_workers"]

        agent = agents.get(agent_id)
        if not agent:
            return {
                "success": False,
                "error": f"エージェント {agent_id} が見つかりません",
            }

        # プロジェクトルートを取得
        # worktree の場合はメインリポジトリのルートを使用
        if agent.worktree_path:
            project_root = Path(resolve_main_repo_root(agent.worktree_path))
        elif agent.working_dir:
            project_root = Path(resolve_main_repo_root(agent.working_dir))
        else:
            return {
                "success": False,
                "error": "エージェントに working_dir または worktree_path が設定されていません",
            }

        # タスク内容の処理
        final_task_content = task_content
        is_admin = agent.role == AgentRole.ADMIN.value

        if auto_enhance and is_admin:
            # メモリから関連情報を検索（プロジェクト + グローバル）
            memory_context = search_memory_context(app_ctx, task_content)

            # プロジェクト名を取得
            project_name = project_root.name

            # config.json から MCP ツールプレフィックスを取得（Admin/Worker 共通）
            mcp_prefix = get_mcp_tool_prefix_from_config(str(project_root))

            # Admin 用: 計画書 + Worker管理手順
            actual_branch = branch_name or f"feature/{session_id}"
            final_task_content = generate_admin_task(
                session_id=session_id,
                agent_id=agent_id,
                plan_content=task_content,
                branch_name=actual_branch,
                worker_count=effective_worker_count,
                memory_context=memory_context,
                project_name=project_name,
                working_dir=str(project_root),
                mcp_tool_prefix=mcp_prefix,
            )

            # Keep role/task separation: role guidance is passed via CLI bootstrap command.

        dashboard = ensure_dashboard_manager(app_ctx)

        # Worker は _send_task_to_worker に統一し、
        # ai_bootstrapped / followup 分岐を共通化する。
        if not is_admin:
            if (
                agent.session_name is None
                or agent.window_index is None
                or agent.pane_index is None
            ):
                return {
                    "success": False,
                    "error": f"エージェント {agent_id} は tmux ペインに配置されていません",
                }

            try:
                worker_no = resolve_worker_number_from_slot(
                    app_ctx.settings,
                    agent.window_index,
                    agent.pane_index,
                )
            except Exception:
                worker_no = 1

            # 2回目以降も含め、タスク割当直前に worktree 準備を実施する
            # （MCP_ENABLE_WORKTREE=false の場合は作成・切替を行わない）
            dispatch_worktree_path = agent.worktree_path or agent.working_dir or str(project_root)
            dispatch_branch = branch_name or ""

            if app_ctx.settings.enable_worktree:
                safe_session_id = re.sub(r"[^0-9A-Za-z._-]+", "-", session_id).strip("-")
                if not safe_session_id:
                    safe_session_id = "task"
                generated_branch = (
                    branch_name
                    or f"feature/{safe_session_id}-worker-{worker_no}-{uuid.uuid4().hex[:6]}"
                )

                worktree_manager = get_worktree_manager(app_ctx, str(project_root))
                base_branch = await worktree_manager.get_current_branch(str(project_root))
                if not base_branch:
                    base_branch = "main"

                wt_path, wt_error = await _create_worktree_for_worker(
                    app_ctx=app_ctx,
                    repo_path=str(project_root),
                    branch=generated_branch,
                    base_branch=base_branch,
                    worker_index=max(worker_no - 1, 0),
                )
                if wt_error or not wt_path:
                    return {
                        "success": False,
                        "error": wt_error or "worktree 作成に失敗しました",
                    }

                dispatch_worktree_path = wt_path
                dispatch_branch = generated_branch
                agent.worktree_path = wt_path
                agent.working_dir = wt_path

            try:
                assigned, _ = dashboard.assign_task(
                    task_id=session_id,
                    agent_id=agent_id,
                    branch=dispatch_branch or None,
                    worktree_path=dispatch_worktree_path if app_ctx.settings.enable_worktree else None,
                )
                if not assigned:
                    logger.debug("send_task: task %s は dashboard 未登録のため割当更新をスキップ", session_id)
            except Exception as assign_error:
                logger.debug("send_task: task 割当更新をスキップ: %s", assign_error)

            agent.current_task = session_id
            agent.status = AgentStatus.BUSY
            agent.last_activity = datetime.now()
            save_agent_to_file(app_ctx, agent)
            dashboard.update_agent_summary(agent)

            send_result = await _send_task_to_worker(
                app_ctx=app_ctx,
                agent=agent,
                task_content=task_content,
                task_id=session_id,
                branch=dispatch_branch,
                worktree_path=dispatch_worktree_path,
                session_id=session_id,
                worker_index=max(worker_no - 1, 0),
                enable_worktree=app_ctx.settings.enable_worktree,
                profile_settings=profile_settings,
                caller_agent_id=caller_agent_id,
            )

            success = bool(send_result.get("task_sent"))
            result = {
                "success": success,
                "agent_id": agent_id,
                "agent_role": agent.role,
                "session_id": session_id,
                "task_file": send_result.get("task_file"),
                "command_sent": send_result.get("command_sent"),
                "auto_enhanced": auto_enhance,
                "dispatch_mode": send_result.get("dispatch_mode", "none"),
                "dispatch_error": send_result.get("dispatch_error"),
                "branch_name": dispatch_branch or None,
                "worktree_path": (
                    dispatch_worktree_path if app_ctx.settings.enable_worktree else None
                ),
                "message": "タスクを送信しました" if success else "タスク送信に失敗しました",
            }
            return result

        # Admin への送信は従来どおり bootstrap コマンドを使用
        task_file = dashboard.write_task_file(
            project_root, session_id, agent_id, final_task_content
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
            return {
                "success": False,
                "error": f"CLIコマンド生成に失敗しました: {e}",
            }

        if agent.session_name is None or agent.window_index is None or agent.pane_index is None:
            return {
                "success": False,
                "error": f"エージェント {agent_id} は tmux ペインに配置されていません",
            }

        success = await tmux.send_keys_to_pane(
            agent.session_name, agent.window_index, agent.pane_index, read_command
        )
        if success:
            agent.status = AgentStatus.BUSY
            agent.last_activity = datetime.now()
            save_agent_to_file(app_ctx, agent)
            dashboard.save_markdown_dashboard(project_root, session_id)

            try:
                dashboard.record_api_call(
                    ai_cli=agent_cli,
                    model=agent_model,
                    estimated_tokens=thinking_tokens,
                    agent_id=agent_id,
                    task_id=session_id,
                )
            except Exception as e:
                logger.debug(f"コスト記録をスキップ: {e}")

        result = {
            "success": success,
            "agent_id": agent_id,
            "agent_role": agent.role,
            "session_id": session_id,
            "task_file": str(task_file),
            "command_sent": read_command,
            "auto_enhanced": auto_enhance,
            "message": "タスクを送信しました" if success else "タスク送信に失敗しました",
            "branch_name": branch_name or f"feature/{session_id}",
            "model_profile": profile_settings["profile"],
        }

        return result

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

            success = await tmux.send_keys_to_pane(
                agent.session_name, agent.window_index, agent.pane_index, command
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
