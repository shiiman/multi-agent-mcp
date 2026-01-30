"""コマンド実行ツール。"""

from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.models.agent import AgentRole, AgentStatus
from src.tools.helpers import ensure_dashboard_manager


def register_tools(mcp: FastMCP) -> None:
    """コマンド実行ツールを登録する。"""

    @mcp.tool()
    async def send_command(agent_id: str, command: str, ctx: Context) -> dict[str, Any]:
        """指定エージェントにコマンドを送信する。

        Args:
            agent_id: 対象エージェントID
            command: 実行するコマンド

        Returns:
            送信結果（success, agent_id, command, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        tmux = app_ctx.tmux
        agents = app_ctx.agents

        agent = agents.get(agent_id)
        if not agent:
            return {
                "success": False,
                "error": f"エージェント {agent_id} が見つかりません",
            }

        # グリッドレイアウトのペイン指定でコマンド送信
        if (
            agent.session_name is not None
            and agent.window_index is not None
            and agent.pane_index is not None
        ):
            success = await tmux.send_keys_to_pane(
                agent.session_name, agent.window_index, agent.pane_index, command
            )
        else:
            # フォールバック: 従来のセッション方式
            success = await tmux.send_keys(agent.tmux_session, command)

        if success:
            agent.status = AgentStatus.BUSY
            agent.last_activity = datetime.now()

        return {
            "success": success,
            "agent_id": agent_id,
            "command": command,
            "message": "コマンドを送信しました" if success else "コマンド送信に失敗しました",
        }

    @mcp.tool()
    async def get_output(agent_id: str, lines: int = 50, ctx: Context = None) -> dict[str, Any]:
        """エージェントのtmux出力を取得する。

        Args:
            agent_id: 対象エージェントID
            lines: 取得する行数（デフォルト: 50）

        Returns:
            出力内容（success, agent_id, lines, output または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        tmux = app_ctx.tmux
        agents = app_ctx.agents

        agent = agents.get(agent_id)
        if not agent:
            return {
                "success": False,
                "error": f"エージェント {agent_id} が見つかりません",
            }

        # グリッドレイアウトのペイン指定で出力取得
        if (
            agent.session_name is not None
            and agent.window_index is not None
            and agent.pane_index is not None
        ):
            output = await tmux.capture_pane_by_index(
                agent.session_name, agent.window_index, agent.pane_index, lines
            )
        else:
            # フォールバック: 従来のセッション方式
            output = await tmux.capture_pane(agent.tmux_session, lines)

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
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスク指示をファイル経由でWorkerに送信する。

        長いマルチライン指示に対応。Workerは claude < TASK.md でタスクを実行。

        Args:
            agent_id: エージェントID
            task_content: タスク内容（Markdown形式）
            session_id: Issue番号または一意なタスクID（例: "94", "a1b2c3d4"）

        Returns:
            送信結果（success, task_file, command_sent, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        tmux = app_ctx.tmux
        agents = app_ctx.agents

        agent = agents.get(agent_id)
        if not agent:
            return {
                "success": False,
                "error": f"エージェント {agent_id} が見つかりません",
            }

        # プロジェクトルートを取得（Workerの working_dir から）
        # worktree_path が設定されていればそれを使用、なければ workspace_base_dir を使用
        if agent.worktree_path:
            project_root = Path(agent.worktree_path)
        else:
            project_root = Path(app_ctx.settings.workspace_base_dir)

        # タスクファイル作成
        dashboard = ensure_dashboard_manager(app_ctx)
        task_file = dashboard.write_task_file(
            project_root, session_id, agent_id, task_content
        )

        # Workerに claude < TASK.md コマンドを送信
        # --dangerously-skip-permissions で確認プロンプトをスキップ
        read_command = f"claude --dangerously-skip-permissions < {task_file}"
        if (
            agent.session_name is not None
            and agent.window_index is not None
            and agent.pane_index is not None
        ):
            success = await tmux.send_keys_to_pane(
                agent.session_name, agent.window_index, agent.pane_index, read_command
            )
        else:
            success = await tmux.send_keys(agent.tmux_session, read_command)

        if success:
            agent.status = AgentStatus.BUSY
            agent.last_activity = datetime.now()
            # ダッシュボード更新
            dashboard.save_markdown_dashboard(project_root, session_id)

        return {
            "success": success,
            "agent_id": agent_id,
            "session_id": session_id,
            "task_file": str(task_file),
            "command_sent": read_command,
            "message": "タスクを送信しました" if success else "タスク送信に失敗しました",
        }

    @mcp.tool()
    async def open_session(agent_id: str, ctx: Context = None) -> dict[str, Any]:
        """エージェントのtmuxセッションをターミナルアプリで開く。

        優先順位: ghostty → iTerm2 → Terminal.app

        Args:
            agent_id: エージェントID

        Returns:
            開く結果（success, agent_id, session, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        tmux = app_ctx.tmux
        agents = app_ctx.agents

        agent = agents.get(agent_id)
        if not agent:
            return {
                "success": False,
                "error": f"エージェント {agent_id} が見つかりません",
            }

        # グリッドレイアウトの場合はセッション名を使用
        if agent.session_name is not None:
            success = await tmux.open_session_in_terminal(agent.session_name)
            session_display = agent.session_name
        else:
            success = await tmux.open_session_in_terminal(agent.tmux_session)
            session_display = agent.tmux_session

        return {
            "success": success,
            "agent_id": agent_id,
            "session": session_display,
            "pane": (
                f"{agent.window_index}.{agent.pane_index}"
                if agent.window_index is not None
                else None
            ),
            "message": (
                "ターミナルでセッションを開きました"
                if success
                else "セッションを開けませんでした"
            ),
        }

    @mcp.tool()
    async def broadcast_command(
        command: str, role: str | None = None, ctx: Context = None
    ) -> dict[str, Any]:
        """全エージェント（または特定役割）にコマンドをブロードキャストする。

        Args:
            command: 実行するコマンド
            role: 対象の役割（省略時は全員、有効: owner/admin/worker）

        Returns:
            送信結果（success, command, role_filter, results, summary または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
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

            # グリッドレイアウトのペイン指定でコマンド送信
            if (
                agent.session_name is not None
                and agent.window_index is not None
                and agent.pane_index is not None
            ):
                success = await tmux.send_keys_to_pane(
                    agent.session_name, agent.window_index, agent.pane_index, command
                )
            else:
                success = await tmux.send_keys(agent.tmux_session, command)
            results[aid] = success

            if success:
                agent.last_activity = now

        success_count = sum(1 for v in results.values() if v)
        total_count = len(results)

        return {
            "success": True,
            "command": command,
            "role_filter": role,
            "results": results,
            "summary": f"{success_count}/{total_count} エージェントに送信成功",
        }
