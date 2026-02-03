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
from src.tools.model_profile import get_current_profile_settings


def generate_admin_task(
    session_id: str,
    agent_id: str,
    plan_content: str,
    branch_name: str,
    worker_count: int,
    memory_context: str,
    project_name: str,
) -> str:
    """Admin エージェント用のタスク指示を生成する。

    Args:
        session_id: セッションID（Issue番号など）
        agent_id: Admin エージェントID
        plan_content: 計画書またはタスク説明
        branch_name: 作業ブランチ名
        worker_count: Worker 数
        memory_context: メモリから取得した関連情報
        project_name: プロジェクト名

    Returns:
        Admin 用のタスク指示（Markdown形式）
    """
    timestamp = datetime.now().isoformat()

    return f"""# Admin タスク: {session_id}

## あなたの役割

あなたは **Admin エージェント** です。
以下の計画書に基づいてタスクを分割し、Worker を管理してください。

## 計画書

{plan_content}

## 作業情報

- **プロジェクト**: {project_name}
- **作業ブランチ**: {branch_name}
- **Worker 数**: {worker_count}
- **開始時刻**: {timestamp}

## 実行手順

### 1. スクリーンショット確認（UI タスクの場合）
- `list_screenshots` でスクリーンショットの有無を確認
- UI 関連タスクの場合は `read_latest_screenshot` で視覚的問題を分析
- 分析結果をタスク分割に反映

### 2. タスク分割
- 計画書から並列実行可能なサブタスクを抽出
- 各サブタスクを Dashboard に登録（`create_task`）

### 3. Worker 作成・タスク割り当て
各 Worker に対して以下を実行：
1. Worktree 作成（`create_worktree`）
2. Worker エージェント作成（`create_agent(role="worker")`）
3. Worktree 割り当て（`assign_worktree`）
4. タスク割り当て（`assign_task_to_agent`）
5. タスク送信（`send_task`）

### 4. 進捗監視
- `get_dashboard_summary` で進捗確認
- `healthcheck_all` で Worker 状態確認
- `read_messages` で Worker からの質問に対応

### 5. 結果確認
- 全 Worker 完了後、変更内容をレビュー
- UI タスクの場合は `read_latest_screenshot` で視覚的確認

### 6. 完了報告
全 Worker 完了後、Owner に `send_message` で結果を報告

## 🔴 RACE-001: 同一論理ファイルの編集禁止（マージ競合防止）

**複数の Worker が同じ論理ファイルを編集すると、マージ時に conflict が発生します。**

- ❌ Worker 1 が src/utils.ts 編集 / Worker 2 も src/utils.ts 編集 → マージ時 conflict
- ✅ Worker 1 が src/utils-a.ts 編集 / Worker 2 が src/utils-b.ts 編集 → OK

タスク分割時に編集対象ファイルが重複しないか確認してください。

## 関連情報（メモリから取得）

{memory_context if memory_context else "（関連情報なし）"}

## Self-Check（コンパクション復帰用）

コンテキストが失われた場合：
- **セッションID**: {session_id}
- **Admin ID**: {agent_id}
- **復帰コマンド**: `retrieve_from_memory "{session_id}"`

## 完了条件

- 全 Worker のタスクが completed 状態
- 全ての変更が {branch_name} にマージ済み
- コンフリクトがないこと
"""


def generate_7section_task(
    task_id: str,
    agent_id: str,
    task_description: str,
    persona_name: str,
    persona_prompt: str,
    memory_context: str,
    project_name: str,
    worktree_path: str | None = None,
    branch_name: str | None = None,
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
        worktree_path: 作業ディレクトリパス（省略可）
        branch_name: 作業ブランチ名（省略可）

    Returns:
        7セクション構造のMarkdown文字列
    """
    timestamp = datetime.now().isoformat()

    # 作業環境情報
    work_env_lines = []
    if worktree_path:
        work_env_lines.append(f"- **作業ディレクトリ**: `{worktree_path}`")
    if branch_name:
        work_env_lines.append(f"- **作業ブランチ**: `{branch_name}`")
    work_env_section = "\n".join(work_env_lines) if work_env_lines else "（メインリポジトリで作業）"

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

### 作業環境

{work_env_section}

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
        worker_count: int | None = None,
        branch_name: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスク指示をファイル経由でエージェントに送信する。

        長いマルチライン指示に対応。エージェントは claude < TASK.md でタスクを実行。
        auto_enhance=True の場合:
        - Admin: 計画書 + Worker管理手順を自動生成
        - Worker: 7セクション構造・ペルソナ・メモリを自動統合

        Args:
            agent_id: エージェントID
            task_content: タスク内容（Markdown形式）
            session_id: Issue番号または一意なタスクID（例: "94", "a1b2c3d4"）
            auto_enhance: 自動拡張を行うか（デフォルト: True）
            worker_count: Worker 数（Admin 用、省略時はプロファイル設定を使用）
            branch_name: 作業ブランチ名（Admin 用、省略時は feature/{session_id}）

        Returns:
            送信結果（success, task_file, command_sent, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        tmux = app_ctx.tmux
        agents = app_ctx.agents

        # プロファイル設定から Worker 数のデフォルトを取得
        profile_settings = get_current_profile_settings(app_ctx)
        effective_worker_count = (
            worker_count if worker_count is not None else profile_settings["max_workers"]
        )

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
        is_admin = agent.role == AgentRole.ADMIN

        if auto_enhance:
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
            "agent_role": agent.role.value,
            "session_id": session_id,
            "task_file": str(task_file),
            "command_sent": read_command,
            "auto_enhanced": auto_enhance,
            "message": "タスクを送信しました" if success else "タスク送信に失敗しました",
        }

        if persona_info:
            result["persona"] = persona_info

        if is_admin:
            result["worker_count"] = effective_worker_count
            result["branch_name"] = branch_name or f"feature/{session_id}"
            result["model_profile"] = profile_settings["profile"]

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
