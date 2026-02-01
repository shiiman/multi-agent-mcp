"""コマンド実行ツール。"""

from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.models.agent import AgentRole, AgentStatus
from src.tools.helpers import (
    ensure_dashboard_manager,
    ensure_global_memory_manager,
    ensure_memory_manager,
    ensure_persona_manager,
)


def generate_7section_task(
    task_id: str,
    agent_id: str,
    task_description: str,
    persona_name: str,
    persona_prompt: str,
    memory_context: str,
    project_name: str,
) -> str:
    """7セクション構造のタスクファイルを生成する。

    Args:
        task_id: タスクID（session_id）
        agent_id: エージェントID
        task_description: タスク内容
        persona_name: ペルソナ名
        persona_prompt: ペルソナのシステムプロンプト
        memory_context: メモリから取得した関連情報
        project_name: プロジェクト名

    Returns:
        7セクション構造のMarkdown文字列
    """
    timestamp = datetime.now().isoformat()

    return f"""# Task: {task_id}

## What（何をするか）

{task_description}

## Why（なぜやるか）

プロジェクト「{project_name}」の開発タスクとして実行します。

## Who（誰がやるか）

あなたは **{persona_name}** として作業します。

{persona_prompt}

## Constraints（制約）

- コードは既存のスタイルに合わせる
- テストが必要な場合は必ず追加する
- セキュリティ脆弱性を作らない
- 不明点がある場合は `send_message` で Admin に質問する

## Current State（現状）

### 関連情報（メモリから取得）

{memory_context if memory_context else "（関連情報なし）"}

### Self-Check（コンパクション復帰用）

コンテキストが失われた場合、以下を確認してください：

- **タスクID**: {task_id}
- **担当エージェント**: {agent_id}
- **開始時刻**: {timestamp}
- **復帰コマンド**: `retrieve_from_memory "{task_id}"`

## Decisions（決定事項）

（作業中に重要な決定があれば `save_to_memory` で記録してください）

## Notes（メモ）

- 作業完了時は `report_task_completion` で Admin に報告
- 作業結果は `save_to_memory` で保存
"""


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
        auto_enhance: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスク指示をファイル経由でWorkerに送信する。

        長いマルチライン指示に対応。Workerは claude < TASK.md でタスクを実行。
        auto_enhance=True の場合、7セクション構造・ペルソナ・メモリを自動統合。

        Args:
            agent_id: エージェントID
            task_content: タスク内容（Markdown形式）
            session_id: Issue番号または一意なタスクID（例: "94", "a1b2c3d4"）
            auto_enhance: 7セクション構造を自動生成するか（デフォルト: True）

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

        # プロジェクトルートを取得
        # 優先順位: worktree_path > working_dir > workspace_base_dir
        if agent.worktree_path:
            project_root = Path(agent.worktree_path)
        elif agent.working_dir:
            project_root = Path(agent.working_dir)
        else:
            project_root = Path(app_ctx.settings.workspace_base_dir)

        # タスク内容の処理
        final_task_content = task_content
        persona_info = None

        if auto_enhance:
            # ペルソナ検出
            persona_manager = ensure_persona_manager(app_ctx)
            persona = persona_manager.get_optimal_persona(task_content)
            persona_info = {
                "name": persona.name,
                "description": persona.description,
            }

            # メモリから関連情報を検索（プロジェクト + グローバル）
            memory_context = ""
            memory_lines = []

            # プロジェクトメモリ検索
            try:
                memory_manager = ensure_memory_manager(app_ctx)
                project_results = memory_manager.search(task_content, limit=3)
                if project_results:
                    memory_lines.append("**プロジェクトメモリ:**")
                    for entry in project_results:
                        memory_lines.append(f"- **{entry.key}**: {entry.content[:200]}...")
            except Exception:
                pass

            # グローバルメモリ検索
            try:
                global_memory = ensure_global_memory_manager()
                global_results = global_memory.search(task_content, limit=2)
                if global_results:
                    if memory_lines:
                        memory_lines.append("")  # 空行
                    memory_lines.append("**グローバルメモリ:**")
                    for entry in global_results:
                        memory_lines.append(f"- **{entry.key}**: {entry.content[:200]}...")
            except Exception:
                pass

            if memory_lines:
                memory_context = "\n".join(memory_lines)

            # プロジェクト名を取得
            project_name = project_root.name

            # 7セクション構造でタスクファイルを生成
            final_task_content = generate_7section_task(
                task_id=session_id,
                agent_id=agent_id,
                task_description=task_content,
                persona_name=persona.name,
                persona_prompt=persona.system_prompt_addition,
                memory_context=memory_context,
                project_name=project_name,
            )

        # タスクファイル作成
        dashboard = ensure_dashboard_manager(app_ctx)
        task_file = dashboard.write_task_file(
            project_root, session_id, agent_id, final_task_content
        )

        # WorkerにAI CLIコマンドを送信
        # エージェントのAI CLIを取得（未設定の場合はデフォルト）
        agent_cli = agent.ai_cli or app_ctx.ai_cli.get_default_cli()
        read_command = app_ctx.ai_cli.build_stdin_command(
            cli=agent_cli,
            task_file_path=str(task_file),
            worktree_path=agent.worktree_path,
        )
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

        result = {
            "success": success,
            "agent_id": agent_id,
            "session_id": session_id,
            "task_file": str(task_file),
            "command_sent": read_command,
            "auto_enhanced": auto_enhance,
            "message": "タスクを送信しました" if success else "タスク送信に失敗しました",
        }

        if persona_info:
            result["persona"] = persona_info

        return result

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
