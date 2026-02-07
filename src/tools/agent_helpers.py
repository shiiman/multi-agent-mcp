"""エージェント管理ツール。"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config.settings import AICli, Settings
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
    resolve_main_repo_root,
    save_agent_to_file,
    search_memory_context,
)
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


def _resolve_agent_cli_name(agent: Agent, app_ctx: AppContext) -> str:
    """Agent の CLI 名を文字列で返す。"""
    if agent.ai_cli:
        return agent.ai_cli.value if hasattr(agent.ai_cli, "value") else str(agent.ai_cli)
    return str(app_ctx.ai_cli.get_default_cli().value)


def _build_change_directory_command(cli_name: str, worktree_path: str) -> str:
    """CLI ごとのディレクトリ移動コマンドを返す。"""
    if cli_name == AICli.CLAUDE.value:
        return f"!cd {worktree_path}"
    return f"cd {worktree_path}"


def resolve_worker_number_from_slot(settings: Settings, window_index: int, pane_index: int) -> int:
    """tmux slot から Worker 番号（1..16）を計算する。"""
    if window_index == 0:
        return pane_index
    workers_per_extra = settings.workers_per_extra_window
    return 6 + ((window_index - 1) * workers_per_extra) + pane_index + 1


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
    # session_id 未確定時は古い config.json の session_id を拾うリスクがあるため保存しない。
    if app_ctx.session_id:
        result["file_persisted"] = save_agent_to_file(app_ctx, agent)
        if result["file_persisted"]:
            logger.info(f"エージェント {agent.id} をファイルに保存しました")
    else:
        logger.info(
            f"エージェント {agent.id} のファイル保存をスキップしました"
            "（session_id 未設定、init_tmux_workspace 後に保存）"
        )

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

        tmux = app_ctx.tmux
        agent_cli_name = _resolve_agent_cli_name(agent, app_ctx)

        if enable_worktree:
            change_dir = _build_change_directory_command(agent_cli_name, worktree_path)
            await tmux.send_keys_to_pane(
                agent.session_name,
                agent.window_index,
                agent.pane_index,
                change_dir,
            )

        instruction = f"次のタスク指示ファイルを実行してください: {task_file}"
        success = await tmux.send_keys_to_pane(
            agent.session_name,
            agent.window_index,
            agent.pane_index,
            instruction,
        )
        if success:
            agent.status = AgentStatus.BUSY
            agent.last_activity = datetime.now()
            save_agent_to_file(app_ctx, agent)
            dashboard.save_markdown_dashboard(project_root, session_id)

            # コスト記録（Worker CLI 起動）
            try:
                worker_model_default = profile_settings.get("worker_model")
                worker_no = resolve_worker_number_from_slot(
                    app_ctx.settings,
                    agent.window_index or 0,
                    agent.pane_index or 0,
                )
                worker_model = app_ctx.settings.get_worker_model(worker_no, worker_model_default)
                dashboard.record_api_call(
                    ai_cli=agent_cli_name,
                    model=worker_model,
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
