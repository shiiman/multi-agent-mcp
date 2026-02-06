"""エージェント管理ツール。"""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.settings import AICli, Settings, TerminalApp
from src.config.template_loader import get_template_loader
from src.config.workflow_guides import get_role_template_path
from src.context import AppContext
from src.managers.tmux_manager import (
    MAIN_WINDOW_PANE_ADMIN,
    MAIN_WINDOW_WORKER_PANES,
    get_project_name,
)
from src.models.agent import Agent, AgentRole, AgentStatus
from src.tools.helpers import (
    ensure_dashboard_manager,
    ensure_ipc_manager,
    ensure_persona_manager,
    get_mcp_tool_prefix_from_config,
    refresh_app_settings,
    require_permission,
    resolve_main_repo_root,
    save_agent_to_file,
    search_memory_context,
    sync_agents_from_file,
)
from src.tools.model_profile import get_current_profile_settings
from src.tools.task_templates import generate_7section_task

logger = logging.getLogger(__name__)


def _get_next_worker_slot(
    agents: dict[str, Agent],
    settings: Settings,
    session_name: str,
    max_workers: int | None = None,
) -> tuple[int, int] | None:
    """次に利用可能なWorkerスロット（ウィンドウ, ペイン）を取得する。

    単一セッション方式（40:60 レイアウト）:
    - メインウィンドウ（window 0）: Admin はペイン 0、Worker 1-6 はペイン 1-6
    - 追加ウィンドウ（window 1+）: 10ペイン/ウィンドウ（2×5）

    Args:
        agents: エージェント辞書
        settings: 設定オブジェクト
        session_name: 対象のセッション名（プロジェクト名）
        max_workers: Worker 上限（省略時は settings.max_workers を使用）

    Returns:
        (window_index, pane_index) のタプル、空きがない場合はNone
    """
    # プロファイル設定の max_workers を優先
    effective_max_workers = max_workers if max_workers is not None else settings.max_workers

    # 最大Worker数チェック
    total_workers = len(
        [a for a in agents.values() if a.role == AgentRole.WORKER]
    )
    if total_workers >= effective_max_workers:
        return None

    # 現在のWorkerペイン割り当て状況を取得
    used_slots: set[tuple[int, int]] = set()
    for agent in agents.values():
        if (
            agent.role == AgentRole.WORKER
            and agent.session_name == session_name
            and agent.window_index is not None
            and agent.pane_index is not None
        ):
            used_slots.add((agent.window_index, agent.pane_index))

    # メインウィンドウ（Worker 1-6: pane 1-6）の空きを探す
    for pane_index in MAIN_WINDOW_WORKER_PANES:
        if (0, pane_index) not in used_slots:
            return (0, pane_index)

    # 追加ウィンドウの空きを探す
    panes_per_extra = settings.workers_per_extra_window
    extra_worker_index = 0
    while total_workers + extra_worker_index < effective_max_workers:
        window_index = 1 + (extra_worker_index // panes_per_extra)
        pane_index = extra_worker_index % panes_per_extra
        if (window_index, pane_index) not in used_slots:
            return (window_index, pane_index)
        extra_worker_index += 1

    return None


def _resolve_tmux_session_name(agent: Agent) -> str | None:
    """Agent から tmux セッション名を解決する。"""
    if agent.session_name:
        return agent.session_name
    if agent.tmux_session:
        return str(agent.tmux_session).split(":", 1)[0]
    return None


def _validate_agent_creation(
    agents: dict[str, Agent],
    role: str,
    ai_cli: str | None,
    profile_max_workers: int,
) -> tuple[AgentRole | None, AICli | None, dict[str, Any] | None]:
    """エージェント作成の入力を検証する。

    Returns:
        (agent_role, selected_cli, error): 検証OK時は error=None
    """
    try:
        agent_role = AgentRole(role)
    except ValueError:
        return None, None, {
            "success": False,
            "error": f"無効な役割です: {role}（有効: owner, admin, worker）",
        }

    selected_cli: AICli | None = None
    if ai_cli:
        try:
            selected_cli = AICli(ai_cli)
        except ValueError:
            valid_clis = [c.value for c in AICli]
            return None, None, {
                "success": False,
                "error": f"無効なAI CLIです: {ai_cli}（有効: {valid_clis}）",
            }

    if agent_role == AgentRole.WORKER:
        worker_count = sum(1 for a in agents.values() if a.role == AgentRole.WORKER)
        if worker_count >= profile_max_workers:
            return None, None, {
                "success": False,
                "error": f"Worker数が上限（{profile_max_workers}）に達しています",
            }

    if agent_role in (AgentRole.OWNER, AgentRole.ADMIN):
        existing = [a for a in agents.values() if a.role == agent_role]
        if existing:
            return None, None, {
                "success": False,
                "error": f"{agent_role.value}は既に存在します（ID: {existing[0].id}）",
            }

    return agent_role, selected_cli, None


async def _determine_pane_position(
    tmux,
    agents: dict[str, Agent],
    settings: Settings,
    agent_role: AgentRole,
    agent_id: str,
    working_dir: str,
    profile_max_workers: int,
) -> dict[str, Any]:
    """ロールに応じてペイン位置を決定し、tmux セッション情報を返す。

    Returns:
        成功時: {"success": True, "session_name", "window_index", "pane_index",
                "tmux_session", "log_location"}
        失敗時: {"success": False, "error": ...}
    """
    project_name = get_project_name(working_dir)

    if agent_role == AgentRole.OWNER:
        return {
            "success": True,
            "session_name": None,
            "window_index": None,
            "pane_index": None,
            "tmux_session": None,
            "log_location": "tmux なし（起点の AI CLI（Owner））",
        }

    # Admin/Worker はメインセッションが必要
    if not await tmux.create_main_session(working_dir):
        return {"success": False, "error": "メインセッションの作成に失敗しました"}

    session_name = project_name

    if agent_role == AgentRole.ADMIN:
        window_index = 0
        pane_index = MAIN_WINDOW_PANE_ADMIN
    else:
        slot = _get_next_worker_slot(agents, settings, project_name, profile_max_workers)
        if slot is None:
            return {"success": False, "error": "利用可能なWorkerスロットがありません"}
        window_index, pane_index = slot

        if window_index > 0:
            ok = await tmux.add_extra_worker_window(
                project_name=project_name,
                window_index=window_index,
                rows=settings.extra_worker_rows,
                cols=settings.extra_worker_cols,
            )
            if not ok:
                return {
                    "success": False,
                    "error": f"追加Workerウィンドウ {window_index} の作成に失敗しました",
                }

    await tmux.set_pane_title(
        session_name, window_index, pane_index, f"{agent_role.value}-{agent_id}"
    )
    tmux_session = f"{session_name}:{window_index}.{pane_index}"

    return {
        "success": True,
        "session_name": session_name,
        "window_index": window_index,
        "pane_index": pane_index,
        "tmux_session": tmux_session,
        "log_location": tmux_session,
    }


def _post_create_agent(
    app_ctx: AppContext,
    agent: Agent,
    agents: dict[str, Agent],
) -> dict[str, bool]:
    """エージェント作成後の共通処理（IPC登録、ファイル保存、レジストリ、ダッシュボード）。"""
    result = {
        "ipc_registered": False,
        "file_persisted": False,
        "dashboard_updated": False,
    }

    # IPC マネージャーに登録
    if app_ctx.session_id:
        try:
            ipc = ensure_ipc_manager(app_ctx)
            ipc.register_agent(agent.id)
            result["ipc_registered"] = True
            logger.info(f"エージェント {agent.id} を IPC に登録しました")
        except ValueError as e:
            logger.warning(f"IPC 登録をスキップ: {e}")
    else:
        logger.info(
            f"エージェント {agent.id} の IPC 登録をスキップしました"
            "（session_id 未設定、後で init_tmux_workspace で設定）"
        )

    # エージェント情報をファイルに保存
    result["file_persisted"] = save_agent_to_file(app_ctx, agent)
    if result["file_persisted"]:
        logger.info(f"エージェント {agent.id} をファイルに保存しました")

    # グローバルレジストリに登録
    from src.tools.helpers import save_agent_to_registry

    if agent.role == AgentRole.OWNER:
        owner_id = agent.id
    else:
        owner_agent = next(
            (a for a in agents.values() if a.role == AgentRole.OWNER),
            None,
        )
        owner_id = owner_agent.id if owner_agent else agent.id

    if app_ctx.project_root:
        save_agent_to_registry(
            agent.id, owner_id, app_ctx.project_root, app_ctx.session_id
        )
        logger.info(f"エージェント {agent.id} をグローバルレジストリに登録しました")

    # ダッシュボードにエージェント情報を追加
    if app_ctx.session_id and app_ctx.project_root:
        try:
            dashboard = ensure_dashboard_manager(app_ctx)
            dashboard.update_agent_summary(agent)
            dashboard.save_markdown_dashboard(
                app_ctx.project_root, app_ctx.session_id
            )
            result["dashboard_updated"] = True
            logger.info(f"エージェント {agent.id} をダッシュボードに追加しました")
        except Exception as e:
            logger.warning(f"ダッシュボード更新に失敗: {e}")

    return result


async def _create_worktree_for_worker(
    app_ctx: AppContext,
    repo_path: str,
    branch: str,
    base_branch: str,
    worker_index: int,
) -> tuple[str | None, str | None]:
    """Worker 用の worktree を作成する。

    Returns:
        (worktree_path, error_message): 成功時は (path, None)、失敗時は (None, error)
    """
    from src.tools.helpers import get_worktree_manager

    worktree = get_worktree_manager(app_ctx, repo_path)
    worktree_dir = Path(repo_path).parent / f".worktrees/{branch}"
    success, message, actual_path = await worktree.create_worktree(
        str(worktree_dir), branch, create_branch=True, base_branch=base_branch
    )
    if not success:
        return None, f"Worker {worker_index + 1}: Worktree 作成失敗 - {message}"
    logger.info(f"Worker {worker_index + 1}: Worktree 作成完了 - {actual_path}")
    return actual_path, None


async def _send_task_to_worker(
    app_ctx: AppContext,
    agent: Agent,
    task_content: str,
    task_id: str | None,
    branch: str,
    worktree_path: str,
    session_id: str,
    worker_index: int,
    enable_worktree: bool,
    profile_settings: dict,
    caller_agent_id: str | None,
) -> bool:
    """Worker にタスクを送信する。"""
    try:
        project_root = Path(resolve_main_repo_root(worktree_path))
        if not task_id:
            logger.warning(
                "Worker %s へのタスク送信を中止: task_id が未指定です",
                worker_index + 1,
            )
            return False
        effective_task_id = task_id

        # メモリから関連情報を検索
        memory_context = search_memory_context(app_ctx, task_content)

        # ペルソナを取得
        persona_manager = ensure_persona_manager(app_ctx)
        persona = persona_manager.get_optimal_persona(task_content)

        # 7セクション構造のタスクを生成
        mcp_prefix = get_mcp_tool_prefix_from_config(str(project_root))
        final_task_content = generate_7section_task(
            task_id=effective_task_id,
            agent_id=agent.id,
            task_description=task_content,
            persona_name=persona.name,
            persona_prompt=persona.system_prompt_addition,
            memory_context=memory_context,
            project_name=project_root.name,
            worktree_path=worktree_path if enable_worktree else None,
            branch_name=branch,
            admin_id=caller_agent_id,
            mcp_tool_prefix=mcp_prefix,
        )

        # タスクファイル作成・送信
        dashboard = ensure_dashboard_manager(app_ctx)
        task_file = dashboard.write_task_file(
            project_root, session_id, agent.id, final_task_content
        )

        agent_cli = agent.ai_cli or app_ctx.ai_cli.get_default_cli()
        agent_model = profile_settings.get("worker_model")

        thinking_tokens = profile_settings.get("worker_thinking_tokens", 4000)

        read_command = app_ctx.ai_cli.build_stdin_command(
            cli=agent_cli,
            task_file_path=str(task_file),
            worktree_path=worktree_path if enable_worktree else None,
            project_root=str(project_root),
            model=agent_model,
            role="worker",
            role_template_path=str(get_role_template_path("worker")),
            thinking_tokens=thinking_tokens,
        )

        tmux = app_ctx.tmux
        success = await tmux.send_keys_to_pane(
            agent.session_name, agent.window_index, agent.pane_index, read_command
        )
        if success:
            agent.status = AgentStatus.BUSY
            agent.last_activity = datetime.now()
            save_agent_to_file(app_ctx, agent)
            dashboard.save_markdown_dashboard(project_root, session_id)

            # コスト記録（Worker CLI 起動）
            try:
                dashboard.record_api_call(
                    ai_cli=agent_cli or "claude",
                    estimated_tokens=profile_settings.get("worker_thinking_tokens", 4000),
                    agent_id=agent.id,
                    task_id=effective_task_id,
                )
            except Exception:
                pass

            logger.info(
                f"Worker {worker_index + 1} (ID: {agent.id}) にタスクを送信しました"
            )
            return True
        else:
            logger.warning(f"Worker {worker_index + 1}: タスク送信失敗")
            return False
    except Exception as e:
        logger.warning(f"Worker {worker_index + 1}: タスク送信エラー - {e}")
        return False


def register_tools(mcp: FastMCP) -> None:
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

    @mcp.tool()
    async def create_workers_batch(
        worker_configs: list[dict],
        repo_path: str,
        base_branch: str,
        session_id: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """複数の Worker を並列で作成し、オプションでタスク割り当て・送信も実行する。

        Worktree 作成、エージェント作成、タスク割り当て、タスク送信を並列で実行し、
        セットアップ時間を大幅に短縮する。

        ※ Owner と Admin のみ使用可能。

        Args:
            worker_configs: Worker 設定のリスト。各設定は以下のキーを持つ:
                - branch: ブランチ名（worktree 用、必須）
                - task_title: タスク名（オプション、ログ用）
                - task_id: 割り当てるタスクID（オプション、assign_task_to_agent 用）
                - task_content: 送信するタスク内容（オプション、send_task 用）
            repo_path: メインリポジトリのパス
            base_branch: ベースブランチ名（worktree 作成時の基点）
            session_id: セッションID（task_content 指定時は必須）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            作成結果（success, workers, failed_count, message）
            workers: 作成された Worker 情報のリスト
            failed_count: 失敗した Worker 数
        """
        app_ctx, role_error = require_permission(ctx, "create_workers_batch", caller_agent_id)
        if role_error:
            return role_error

        settings = app_ctx.settings

        if not worker_configs:
            return {
                "success": False,
                "error": "worker_configs が空です",
            }

        # 現在のプロファイル設定を取得
        profile_settings = get_current_profile_settings(app_ctx)
        profile_max_workers = profile_settings["max_workers"]

        # Worker 数の上限チェック
        agents = app_ctx.agents
        current_worker_count = sum(1 for a in agents.values() if a.role == AgentRole.WORKER)
        requested_count = len(worker_configs)

        if current_worker_count + requested_count > profile_max_workers:
            return {
                "success": False,
                "error": f"Worker 数が上限を超えます（現在: {current_worker_count}, "
                         f"要求: {requested_count}, 上限: {profile_max_workers}）",
            }

        # worktree 無効モードのチェック
        enable_worktree = settings.enable_worktree

        # 🔴 Race condition 対策: 並列実行前に pane を事前割り当て
        project_name = get_project_name(repo_path)
        pre_assigned_slots: list[tuple[int, int] | None] = []

        # 現在のWorkerペイン割り当て状況を取得
        used_slots: set[tuple[int, int]] = set()
        for agent in agents.values():
            if (
                agent.role == AgentRole.WORKER
                and agent.session_name == project_name
                and agent.window_index is not None
                and agent.pane_index is not None
            ):
                used_slots.add((agent.window_index, agent.pane_index))

        # 各 Worker に pane を事前割り当て
        for i in range(len(worker_configs)):
            slot = None
            # メインウィンドウの空きを探す
            for pane_index in MAIN_WINDOW_WORKER_PANES:
                if (0, pane_index) not in used_slots:
                    slot = (0, pane_index)
                    used_slots.add(slot)  # 確保済みとしてマーク
                    break

            # メインウィンドウが満杯の場合は警告（Worker の完了を待って再試行が必要）
            if slot is None:
                logger.warning(
                    f"Worker {i + 1}: 利用可能な pane がありません"
                    "（Worker の完了を待って再試行してください）"
                )

            pre_assigned_slots.append(slot)

        logger.info(f"事前割り当て済み pane: {pre_assigned_slots}")

        async def create_single_worker(
            config: dict, worker_index: int, assigned_slot: tuple[int, int] | None
        ) -> dict[str, Any]:
            """単一の Worker を作成する内部関数。"""
            branch = config.get("branch")
            task_title = config.get("task_title", f"Worker {worker_index + 1}")

            if not branch:
                return {
                    "success": False,
                    "error": f"Worker {worker_index + 1}: branch が指定されていません",
                    "worker_index": worker_index,
                }

            try:
                # 1. Worktree 作成（有効な場合のみ）
                worktree_path = repo_path
                if enable_worktree:
                    wt_path, wt_error = await _create_worktree_for_worker(
                        app_ctx, repo_path, branch, base_branch, worker_index
                    )
                    if wt_error:
                        return {
                            "success": False,
                            "error": wt_error,
                            "worker_index": worker_index,
                        }
                    worktree_path = wt_path

                # 2. tmux セッション確保・エージェント作成
                tmux = app_ctx.tmux
                if not await tmux.create_main_session(repo_path):
                    return {
                        "success": False,
                        "error": f"Worker {worker_index + 1}: メインセッション作成失敗",
                        "worker_index": worker_index,
                    }

                if assigned_slot is None:
                    return {
                        "success": False,
                        "error": (
                            f"Worker {worker_index + 1}: "
                            "利用可能なスロットがありません（事前割り当て失敗）"
                        ),
                        "worker_index": worker_index,
                    }
                window_index, pane_index = assigned_slot

                if window_index > 0:
                    ok = await tmux.add_extra_worker_window(
                        project_name=project_name,
                        window_index=window_index,
                        rows=settings.extra_worker_rows,
                        cols=settings.extra_worker_cols,
                    )
                    if not ok:
                        return {
                            "success": False,
                            "error": f"Worker {worker_index + 1}: 追加ウィンドウ作成失敗",
                            "worker_index": worker_index,
                        }

                agent_id = str(uuid.uuid4())[:8]
                await tmux.set_pane_title(
                    project_name, window_index, pane_index, f"worker-{agent_id}"
                )
                tmux_session = f"{project_name}:{window_index}.{pane_index}"

                now = datetime.now()
                agent = Agent(
                    id=agent_id,
                    role=AgentRole.WORKER,
                    status=AgentStatus.IDLE,
                    tmux_session=tmux_session,
                    working_dir=worktree_path,
                    worktree_path=worktree_path if enable_worktree else None,
                    session_name=project_name,
                    window_index=window_index,
                    pane_index=pane_index,
                    created_at=now,
                    last_activity=now,
                )
                agents[agent_id] = agent

                logger.info(
                    f"Worker {worker_index + 1} (ID: {agent_id}) を作成しました: {tmux_session}"
                )

                # 3. 後処理（IPC登録、ファイル保存、レジストリ、ダッシュボード）
                post_result = _post_create_agent(app_ctx, agent, agents)

                # 4. タスク割り当て（task_id が指定されている場合）
                task_assigned = False
                task_id = config.get("task_id")
                dashboard = None
                if app_ctx.session_id and app_ctx.project_root:
                    try:
                        dashboard = ensure_dashboard_manager(app_ctx)
                    except Exception as e:
                        logger.debug(f"ダッシュボードマネージャー取得をスキップ: {e}")

                if task_id and dashboard:
                    try:
                        success, message = dashboard.assign_task(
                            task_id=task_id,
                            agent_id=agent_id,
                            branch=branch,
                            worktree_path=worktree_path,
                        )
                        task_assigned = success
                        if not success:
                            logger.warning(
                                f"Worker {worker_index + 1}: タスク割り当て失敗 - {message}"
                            )
                    except Exception as e:
                        logger.warning(f"Worker {worker_index + 1}: タスク割り当てエラー - {e}")

                # 5. タスク送信（task_content が指定されている場合）
                task_sent = False
                task_content = config.get("task_content")
                if task_content and session_id:
                    task_sent = await _send_task_to_worker(
                        app_ctx, agent, task_content, task_id, branch, worktree_path,
                        session_id, worker_index, enable_worktree,
                        profile_settings, caller_agent_id,
                    )

                return {
                    "success": True,
                    "worker_index": worker_index,
                    "agent_id": agent_id,
                    "branch": branch,
                    "worktree_path": worktree_path,
                    "tmux_session": tmux_session,
                    "task_title": task_title,
                    "ipc_registered": post_result["ipc_registered"],
                    "file_persisted": post_result["file_persisted"],
                    "dashboard_updated": post_result["dashboard_updated"],
                    "task_assigned": task_assigned,
                    "task_sent": task_sent,
                }

            except Exception as e:
                logger.exception(f"Worker {worker_index + 1} 作成中にエラー: {e}")
                return {
                    "success": False,
                    "error": f"Worker {worker_index + 1}: {str(e)}",
                    "worker_index": worker_index,
                }

        # 全 Worker を並列で作成（事前割り当てされた pane を渡す）
        logger.info(f"{len(worker_configs)} 個の Worker を並列で作成開始")
        results = await asyncio.gather(
            *[
                create_single_worker(config, i, pre_assigned_slots[i])
                for i, config in enumerate(worker_configs)
            ],
            return_exceptions=True
        )

        # 結果を整理
        workers = []
        failed_count = 0
        errors = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_count += 1
                errors.append(f"Worker {i + 1}: 例外発生 - {str(result)}")
            elif result.get("success"):
                workers.append(result)
            else:
                failed_count += 1
                errors.append(result.get("error", f"Worker {i + 1}: 不明なエラー"))

        success = failed_count == 0
        message = (
            f"{len(workers)} 個の Worker を作成しました"
            if success
            else f"{len(workers)} 個の Worker を作成（{failed_count} 個失敗）"
        )

        logger.info(message)

        return {
            "success": success,
            "workers": workers,
            "failed_count": failed_count,
            "errors": errors if errors else None,
            "message": message,
        }
