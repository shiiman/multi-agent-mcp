"""エージェント管理ツール実装。"""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.settings import AICli, TerminalApp
from src.config.template_loader import get_template_loader
from src.models.agent import Agent, AgentRole, AgentStatus
from src.tools.agent_helpers import (
    _determine_pane_position,
    _post_create_agent,
    _resolve_tmux_session_name,
    _validate_agent_creation,
)
from src.tools.helpers import (
    refresh_app_settings,
    require_permission,
    resolve_main_repo_root,
    save_agent_to_file,
    sync_agents_from_file,
)
from src.tools.model_profile import get_current_profile_settings

logger = logging.getLogger(__name__)

def register_lifecycle_tools(mcp: FastMCP) -> None:
    """エージェント管理ツールを登録する。"""

    @mcp.tool()
    async def create_agent(
        role: str,
        working_dir: str,
        ai_cli: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """新しいエージェントを作成する。

        単一セッション方式: 左右40:60分離レイアウト
        - Owner: tmux ペインに配置しない（実行AIエージェントが担う）
        - 左 40%: Admin (pane 0)
        - 右 60%: Worker 1-6 (pane 1-6)
        - Worker 7以降は追加ウィンドウ（2×5=10ペイン/ウィンドウ）

        ※ Owner と Admin のみ使用可能。

        Args:
            role: エージェントの役割（owner/admin/worker）
            working_dir: 作業ディレクトリのパス
            ai_cli: 使用するAI CLI（claude/codex/gemini、省略でデフォルト）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            作成結果（success, agent, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "create_agent", caller_agent_id)
        settings = app_ctx.settings
        agents = app_ctx.agents

        # ロールチェック（Owner 作成時は caller_agent_id 不要、それ以外は必須）
        if role != "owner":
            if role_error:
                return role_error
        else:
            # Owner 作成時は working_dir から project_root を自動設定
            # （init_tmux_workspace より前に create_agent(owner) が呼ばれるため）
            if not app_ctx.project_root and working_dir:
                app_ctx.project_root = resolve_main_repo_root(working_dir)
                refresh_app_settings(app_ctx, app_ctx.project_root)
                logger.info(f"Owner 作成時に project_root を自動設定: {app_ctx.project_root}")

        # 入力検証
        profile_settings = get_current_profile_settings(app_ctx)
        profile_max_workers = profile_settings["max_workers"]

        agent_role, selected_cli, validation_error = _validate_agent_creation(
            agents, role, ai_cli, profile_max_workers
        )
        if validation_error:
            return validation_error

        # ペイン位置の決定
        agent_id = str(uuid.uuid4())[:8]
        pane_result = await _determine_pane_position(
            app_ctx.tmux, agents, settings, agent_role, agent_id,
            working_dir, profile_max_workers,
        )
        if not pane_result["success"]:
            return {"success": False, "error": pane_result["error"]}

        # エージェント情報を登録
        now = datetime.now()
        agent = Agent(
            id=agent_id,
            role=agent_role,
            status=AgentStatus.IDLE,
            tmux_session=pane_result["tmux_session"],
            working_dir=working_dir,
            session_name=pane_result["session_name"],
            window_index=pane_result["window_index"],
            pane_index=pane_result["pane_index"],
            ai_cli=selected_cli,
            created_at=now,
            last_activity=now,
        )
        agents[agent_id] = agent

        logger.info(
            f"エージェント {agent_id}（{role}）を作成しました: {pane_result['log_location']}"
        )

        # 後処理（IPC登録、ファイル保存、レジストリ、ダッシュボード）
        post_result = _post_create_agent(app_ctx, agent, agents)

        result = {
            "success": True,
            "agent": agent.model_dump(mode="json"),
            "message": f"エージェント {agent_id}（{role}）を作成しました",
            "ipc_registered": post_result["ipc_registered"],
            "file_persisted": post_result["file_persisted"],
            "dashboard_updated": post_result["dashboard_updated"],
        }
        if selected_cli:
            result["ai_cli"] = selected_cli.value
        return result

    @mcp.tool()
    async def list_agents(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """全エージェントの一覧を取得する。

        ファイルに保存されたエージェント情報も含めて返す。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            エージェント一覧（success, agents, count, synced_from_file）
        """
        app_ctx, role_error = require_permission(ctx, "list_agents", caller_agent_id)
        if role_error:
            return role_error

        agents = app_ctx.agents

        # ファイルからエージェント情報を同期（他の MCP インスタンスで作成されたエージェントを取得）
        synced = sync_agents_from_file(app_ctx)

        agent_list = [a.model_dump(mode="json") for a in agents.values()]

        return {
            "success": True,
            "agents": agent_list,
            "count": len(agent_list),
            "synced_from_file": synced,
        }

    @mcp.tool()
    async def get_agent_status(
        agent_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """指定エージェントの詳細ステータスを取得する。

        Args:
            agent_id: エージェントID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            エージェント詳細（success, agent, session_active または error）
        """
        app_ctx, role_error = require_permission(ctx, "get_agent_status", caller_agent_id)
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

        session_name = _resolve_tmux_session_name(agent)
        session_exists = False
        if session_name:
            session_exists = await tmux.session_exists(session_name)

        return {
            "success": True,
            "agent": agent.model_dump(mode="json"),
            "session_active": session_exists,
        }

    @mcp.tool()
    async def terminate_agent(
        agent_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェントを終了する。

        グリッドレイアウトではペインは維持され、再利用可能になる。

        ※ Owner と Admin のみ使用可能。

        Args:
            agent_id: 終了するエージェントID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            終了結果（success, agent_id, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "terminate_agent", caller_agent_id)
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

        # tmux ペインがある場合はクリア（セッションは維持）
        if (
            agent.session_name is not None
            and agent.window_index is not None
            and agent.pane_index is not None
        ):
            # ペインに Ctrl+C を送信してプロセスを停止
            await tmux.send_keys_to_pane(
                agent.session_name, agent.window_index, agent.pane_index, "", literal=False
            )
            session_name = agent.session_name
            window_name = tmux._get_window_name(agent.window_index)
            target = f"{session_name}:{window_name}.{agent.pane_index}"
            await tmux._run("send-keys", "-t", target, "C-c")
            # ペインタイトルをクリア
            await tmux.set_pane_title(
                agent.session_name, agent.window_index, agent.pane_index, "(empty)"
            )
        # Owner の場合は tmux 操作なしでエージェント情報のみ更新

        # エージェントの状態を terminated に変更（削除せず履歴を残す）
        agent.status = AgentStatus.TERMINATED
        agent.last_activity = datetime.now()

        # ファイルに保存（MCP インスタンス間で共有）
        file_saved = save_agent_to_file(app_ctx, agent)

        logger.info(
            f"エージェント {agent_id} を終了しました"
            f" (status: terminated, file_saved: {file_saved})"
        )

        return {
            "success": True,
            "agent_id": agent_id,
            "message": f"エージェント {agent_id} を終了しました",
            "status": "terminated",
            "file_persisted": file_saved,
        }

    @mcp.tool()
    async def initialize_agent(
        agent_id: str,
        prompt_type: str = "auto",
        custom_prompt: str | None = None,
        terminal: str = "auto",
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェントを初期化し、ロールテンプレートを渡して AI CLI を起動する。

        create_agent で作成されたエージェントに対して、roles/ テンプレートを
        初期プロンプトとして渡し、ターミナルで AI CLI を起動する。

        ※ Owner と Admin のみ使用可能。

        Args:
            agent_id: 初期化するエージェントID
            prompt_type: プロンプトタイプ
                - "auto": roles/ テンプレートを自動読み込み（デフォルト）
                - "custom": custom_prompt をそのまま使用
                - "file": custom_prompt をファイルパスとして読み込み
            custom_prompt: カスタムプロンプト（prompt_type が "custom" または "file" の場合）
            terminal: ターミナルアプリ（auto/ghostty/iterm2/terminal）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            初期化結果（success, agent_id, cli, prompt_source, message）
        """
        app_ctx, role_error = require_permission(ctx, "initialize_agent", caller_agent_id)
        if role_error:
            return role_error

        agents = app_ctx.agents
        ai_cli_manager = app_ctx.ai_cli

        # ファイルからエージェント情報を同期
        sync_agents_from_file(app_ctx)

        # エージェントの存在確認
        agent = agents.get(agent_id)
        if not agent:
            return {
                "success": False,
                "error": f"エージェント {agent_id} が見つかりません",
            }

        # Owner は tmux ペインを持たないため初期化不可
        if agent.role == AgentRole.OWNER:
            return {
                "success": False,
                "error": (
                    "Owner エージェントは initialize_agent の"
                    "対象外です（起点の AI CLI が担う）"
                ),
            }

        # 作業ディレクトリの確認
        working_dir = agent.working_dir
        if not working_dir:
            return {
                "success": False,
                "error": f"エージェント {agent_id} に working_dir が設定されていません",
            }

        # プロンプトの構築
        prompt: str | None = None
        prompt_source: str = ""

        if prompt_type == "auto":
            # roles/ テンプレートを自動読み込み
            try:
                loader = get_template_loader()
                prompt = loader.load("roles", agent.role.value)
                prompt_source = f"roles/{agent.role.value}.md"
            except FileNotFoundError as e:
                return {
                    "success": False,
                    "error": f"ロールテンプレートが見つかりません: {e}",
                }
        elif prompt_type == "custom":
            # custom_prompt をそのまま使用
            if not custom_prompt:
                return {
                    "success": False,
                    "error": "prompt_type='custom' の場合、custom_prompt は必須です",
                }
            prompt = custom_prompt
            prompt_source = "custom"
        elif prompt_type == "file":
            # custom_prompt をファイルパスとして読み込み
            if not custom_prompt:
                return {
                    "success": False,
                    "error": (
                        "prompt_type='file' の場合、"
                        "custom_prompt にファイルパスを指定してください"
                    ),
                }
            file_path = Path(custom_prompt)
            if not file_path.exists():
                return {
                    "success": False,
                    "error": f"ファイルが見つかりません: {custom_prompt}",
                }
            try:
                prompt = file_path.read_text(encoding="utf-8")
                prompt_source = str(file_path)
            except Exception as e:
                return {
                    "success": False,
                    "error": f"ファイルの読み込みに失敗しました: {e}",
                }
        else:
            return {
                "success": False,
                "error": f"無効な prompt_type です: {prompt_type}（有効: auto, custom, file）",
            }

        # ターミナルアプリの検証
        try:
            terminal_app = TerminalApp(terminal)
        except ValueError:
            valid_terminals = [t.value for t in TerminalApp]
            return {
                "success": False,
                "error": f"無効なターミナルです: {terminal}（有効: {valid_terminals}）",
            }

        # AI CLI を取得（エージェントに設定されていればそれを使用、なければデフォルト）
        # agent.ai_cli は use_enum_values=True により文字列になっている可能性がある
        agent_cli = agent.ai_cli
        if agent_cli is not None:
            if isinstance(agent_cli, str):
                agent_cli = AICli(agent_cli)
            cli = agent_cli
        else:
            cli = ai_cli_manager.get_default_cli()

        # ターミナルで AI CLI を起動
        success, message = await ai_cli_manager.open_worktree_in_terminal(
            worktree_path=working_dir,
            cli=cli,
            prompt=prompt,
            terminal=terminal_app,
        )

        if not success:
            return {
                "success": False,
                "error": f"AI CLI の起動に失敗しました: {message}",
            }

        # エージェントのステータスを更新
        agent.status = AgentStatus.BUSY
        agent.last_activity = datetime.now()

        # ファイルに保存（MCP インスタンス間で共有）
        file_saved = save_agent_to_file(app_ctx, agent)

        logger.info(
            f"エージェント {agent_id}（{agent.role.value}）を初期化しました: "
            f"CLI={cli.value}, prompt_source={prompt_source}, file_saved={file_saved}"
        )

        return {
            "success": True,
            "agent_id": agent_id,
            "role": agent.role.value,
            "cli": cli.value,
            "prompt_source": prompt_source,
            "terminal": terminal_app.value,
            "working_dir": working_dir,
            "message": f"エージェント {agent_id} を初期化しました（{cli.value} で起動）",
            "file_persisted": file_saved,
        }

