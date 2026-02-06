"""コマンド実行ツール。"""

from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.workflow_guides import get_role_guide, get_role_template_path
from src.models.agent import AgentRole, AgentStatus
from src.tools.helpers import (
    ensure_dashboard_manager,
    ensure_persona_manager,
    get_mcp_tool_prefix_from_config,
    require_permission,
    resolve_main_repo_root,
    save_agent_to_file,
    search_memory_context,
    sync_agents_from_file,
)
from src.tools.model_profile import get_current_profile_settings
from src.tools.task_templates import generate_7section_task, generate_admin_task


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
        persona_info = None
        is_admin = agent.role == AgentRole.ADMIN.value

        if auto_enhance:
            # メモリから関連情報を検索（プロジェクト + グローバル）
            memory_context = search_memory_context(app_ctx, task_content)

            # プロジェクト名を取得
            project_name = project_root.name

            # config.json から MCP ツールプレフィックスを取得（Admin/Worker 共通）
            mcp_prefix = get_mcp_tool_prefix_from_config(str(project_root))

            if is_admin:
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
            else:
                # Worker 用: 7セクション構造 + ペルソナ + 作業環境情報
                persona_manager = ensure_persona_manager(app_ctx)
                persona = persona_manager.get_optimal_persona(task_content)
                persona_info = {
                    "name": persona.name,
                    "description": persona.description,
                }
                # Worker の作業環境情報を取得
                worker_worktree = agent.worktree_path
                worker_branch = agent.branch if hasattr(agent, "branch") else None
                final_task_content = generate_7section_task(
                    task_id=session_id,
                    agent_id=agent_id,
                    task_description=task_content,
                    persona_name=persona.name,
                    persona_prompt=persona.system_prompt_addition,
                    memory_context=memory_context,
                    project_name=project_name,
                    worktree_path=worker_worktree,
                    branch_name=worker_branch,
                    admin_id=caller_agent_id,  # Worker に Admin の ID を渡す
                    mcp_tool_prefix=mcp_prefix,
                )

            # ロールテンプレートを先頭に追加
            role_name = "admin" if is_admin else "worker"
            role_guide = get_role_guide(role_name)
            if role_guide:
                final_task_content = (
                    role_guide.content + "\n\n---\n\n# タスク指示\n\n" + final_task_content
                )

        # タスクファイル作成
        dashboard = ensure_dashboard_manager(app_ctx)
        task_file = dashboard.write_task_file(
            project_root, session_id, agent_id, final_task_content
        )

        # WorkerにAI CLIコマンドを送信
        # エージェントのAI CLIを取得（未設定の場合はデフォルト）
        agent_cli = agent.ai_cli or app_ctx.ai_cli.get_default_cli()

        # ロール別のモデルを取得
        if agent.role == AgentRole.ADMIN.value:
            agent_model = profile_settings.get("admin_model")
        else:  # WORKER
            agent_model = profile_settings.get("worker_model")

        # ロール名を build_stdin_command に渡す
        agent_role_name = "admin" if agent.role == AgentRole.ADMIN.value else "worker"

        # Extended Thinking トークン数をプロファイル設定から取得
        if agent.role == AgentRole.ADMIN.value:
            thinking_tokens = profile_settings.get("admin_thinking_tokens", 4000)
        else:
            thinking_tokens = profile_settings.get("worker_thinking_tokens", 4000)

        read_command = app_ctx.ai_cli.build_stdin_command(
            cli=agent_cli,
            task_file_path=str(task_file),
            worktree_path=agent.worktree_path,
            project_root=str(project_root),  # MCP_PROJECT_ROOT 環境変数用
            model=agent_model,
            role=agent_role_name,
            role_template_path=str(get_role_template_path(agent_role_name)),
            thinking_tokens=thinking_tokens,
        )
        # tmux ペインが設定されていない場合（Owner）はエラー
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
            # ファイルに保存（MCP インスタンス間で共有）
            save_agent_to_file(app_ctx, agent)
            # ダッシュボード更新
            dashboard.save_markdown_dashboard(project_root, session_id)

            # コスト記録（CLI 起動 = API 呼び出し）
            try:
                thinking_tokens = (
                    profile_settings.get("admin_thinking_tokens", 4000)
                    if is_admin
                    else profile_settings.get("worker_thinking_tokens", 4000)
                )
                dashboard.record_api_call(
                    ai_cli=agent_cli,
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
        }

        if persona_info:
            result["persona"] = persona_info

        if is_admin:
            result["branch_name"] = branch_name or f"feature/{session_id}"
            result["model_profile"] = profile_settings["profile"]

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
