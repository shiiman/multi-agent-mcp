"""エージェント管理ツール。"""

import asyncio
import logging
import re
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config.settings import AICli, Settings
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
    get_enable_git_from_config,
    get_mcp_tool_prefix_from_config,
    resolve_main_repo_root,
    save_agent_to_file,
    search_memory_context,
)
from src.tools.task_templates import generate_7section_task

logger = logging.getLogger(__name__)

_SHELL_COMMANDS = {"zsh", "bash", "sh", "fish"}


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

    # 最大Worker数チェック（TERMINATED Worker を除外）
    total_workers = len(
        [
            a
            for a in agents.values()
            if a.role == AgentRole.WORKER and a.status != AgentStatus.TERMINATED
        ]
    )
    if total_workers >= effective_max_workers:
        return None

    # 現在のWorkerペイン割り当て状況を取得（TERMINATED Worker を除外）
    used_slots: set[tuple[int, int]] = set()
    for agent in agents.values():
        if (
            agent.role == AgentRole.WORKER
            and agent.status != AgentStatus.TERMINATED
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
    if (
        agent.role == AgentRole.WORKER
        and agent.window_index is not None
        and agent.pane_index is not None
    ):
        try:
            worker_no = resolve_worker_number_from_slot(
                app_ctx.settings,
                agent.window_index,
                agent.pane_index,
            )
            return app_ctx.settings.get_worker_cli(worker_no).value
        except Exception as e:
            logger.debug("Worker CLI の再解決に失敗したため agent.ai_cli を使用: %s", e)

    if agent.ai_cli:
        return agent.ai_cli.value if hasattr(agent.ai_cli, "value") else str(agent.ai_cli)
    return str(app_ctx.ai_cli.get_default_cli().value)


def _resolve_agent_enable_git(
    app_ctx: AppContext,
    agent: Agent,
    strict: bool = False,
) -> bool:
    """対象エージェント基準の enable_git を解決する。"""
    config_base = agent.worktree_path or agent.working_dir or app_ctx.project_root
    if not config_base:
        return app_ctx.settings.enable_git
    resolved = get_enable_git_from_config(config_base, strict=strict)
    if resolved is None:
        return app_ctx.settings.enable_git
    return resolved


def _build_change_directory_command(cli_name: str, worktree_path: str) -> str:
    """CLI ごとのディレクトリ移動コマンドを返す。"""
    quoted_path = shlex.quote(worktree_path)
    if cli_name == AICli.CLAUDE.value:
        return f"!cd {quoted_path}"
    return f"cd {quoted_path}"


def _sanitize_branch_part(value: str) -> str:
    """ブランチ名用に安全な文字へ正規化する。"""
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", value or "").strip("-")
    return cleaned or "main"


def _normalize_worker_base_branch(base_branch: str) -> str:
    """Worker 用ブランチ名に使う base 部分を正規化する。"""
    normalized = (base_branch or "").strip()
    if normalized.startswith("feature/"):
        normalized = normalized[len("feature/") :]
    return _sanitize_branch_part(normalized)


def _short_task_id(task_id: str) -> str:
    """task_id を 8 桁に短縮する。"""
    alnum = re.sub(r"[^0-9A-Za-z]", "", task_id or "")
    if not alnum:
        return "task0000"
    return alnum[:8].lower()


def build_worker_task_branch(base_branch: str, worker_no: int, task_id: str) -> str:
    """task 単位 worktree 用のブランチ名を生成する。"""
    base = _normalize_worker_base_branch(base_branch)
    return f"feature/{base}-worker-{worker_no}-{_short_task_id(task_id)}"


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
        return (
            None,
            None,
            {
                "success": False,
                "error": f"無効な役割です: {role}（有効: owner, admin, worker）",
            },
        )

    selected_cli: AICli | None = None
    if ai_cli:
        try:
            selected_cli = AICli(ai_cli)
        except ValueError:
            valid_clis = [c.value for c in AICli]
            return (
                None,
                None,
                {
                    "success": False,
                    "error": f"無効なAI CLIです: {ai_cli}（有効: {valid_clis}）",
                },
            )

    if agent_role == AgentRole.WORKER:
        worker_count = sum(
            1
            for a in agents.values()
            if a.role == AgentRole.WORKER and a.status != AgentStatus.TERMINATED
        )
        if worker_count >= profile_max_workers:
            return (
                None,
                None,
                {
                    "success": False,
                    "error": f"Worker数が上限（{profile_max_workers}）に達しています",
                },
            )

    if agent_role in (AgentRole.OWNER, AgentRole.ADMIN):
        existing = [a for a in agents.values() if a.role == agent_role]
        if existing:
            return (
                None,
                None,
                {
                    "success": False,
                    "error": f"{agent_role.value}は既に存在します（ID: {existing[0].id}）",
                },
            )

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
    project_name = get_project_name(working_dir, enable_git=settings.enable_git)

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
    import uuid as _uuid

    result = {
        "ipc_registered": False,
        "file_persisted": False,
        "dashboard_updated": False,
    }

    # Owner 作成時に session_id が未設定の場合は仮 ID を設定
    # （init_tmux_workspace で正式な session_id に上書きされる）
    provisional_session = False
    if not app_ctx.session_id and agent.role == AgentRole.OWNER:
        app_ctx.session_id = f"provisional-{_uuid.uuid4().hex[:8]}"
        provisional_session = True
        logger.info("Owner 作成時に仮 session_id を設定: %s", app_ctx.session_id)

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
    if app_ctx.session_id:
        result["file_persisted"] = save_agent_to_file(app_ctx, agent)
        if result["file_persisted"]:
            logger.info(
                "エージェント %s をファイルに保存しました%s",
                agent.id,
                "（仮session_id）" if provisional_session else "",
            )
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
        save_agent_to_registry(agent.id, owner_id, app_ctx.project_root, app_ctx.session_id)
        logger.info(f"エージェント {agent.id} をグローバルレジストリに登録しました")

    # ダッシュボードにエージェント情報を追加
    if app_ctx.session_id and app_ctx.project_root:
        try:
            dashboard = ensure_dashboard_manager(app_ctx)
            dashboard.update_agent_summary(agent)
            dashboard.save_markdown_dashboard(app_ctx.project_root, app_ctx.session_id)
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


def _make_dispatch_result(
    task_sent: bool,
    dispatch_mode: str = "none",
    dispatch_error: str | None = None,
    task_file: str | None = None,
    command_sent: str | None = None,
) -> dict[str, Any]:
    """_send_task_to_worker の結果辞書を組み立てる。"""
    return {
        "task_sent": task_sent,
        "dispatch_mode": dispatch_mode,
        "dispatch_error": dispatch_error,
        "task_file": task_file,
        "command_sent": command_sent,
    }


async def _reset_bootstrap_state_if_shell(
    app_ctx: AppContext,
    agent: Agent,
    tmux: Any,
    worker_index: int,
) -> str | None:
    """pane の実行コマンドを確認し、shell なら bootstrap 状態をリセットする。"""
    if agent.session_name is None or agent.window_index is None or agent.pane_index is None:
        return None

    try:
        current_command = await tmux.get_pane_current_command(
            agent.session_name,
            agent.window_index,
            agent.pane_index,
        )
    except Exception as check_error:
        logger.debug(
            "Worker %s pane command の補正判定に失敗: %s",
            worker_index + 1,
            check_error,
        )
        return None

    command_name = (current_command or "").strip().lower()
    if command_name in _SHELL_COMMANDS:
        agent.ai_bootstrapped = False
        save_agent_to_file(app_ctx, agent)
        logger.info(
            "Worker %s の pane が shell (%s) のため ai_bootstrapped を False に戻しました",
            worker_index + 1,
            current_command,
        )
    return current_command


def _prepare_worker_task_content(
    app_ctx: AppContext,
    agent: Agent,
    task_content: str,
    task_id: str,
    branch: str,
    worktree_path: str,
    session_id: str,
    enable_worktree: bool,
    caller_agent_id: str | None,
) -> tuple[Path, Path]:
    """Worker 用の7セクション構造タスクを生成し、ファイルに書き出す。

    Returns:
        (project_root, task_file)
    """
    agent_enable_git = _resolve_agent_enable_git(app_ctx, agent, strict=True)
    if agent_enable_git:
        project_root = Path(resolve_main_repo_root(worktree_path))
    else:
        project_root = Path(worktree_path).expanduser()

    # メモリから関連情報を検索
    memory_context = search_memory_context(app_ctx, task_content)

    # ペルソナを取得
    persona_manager = ensure_persona_manager(app_ctx)
    persona = persona_manager.get_optimal_persona(task_content)

    # 7セクション構造のタスクを生成
    mcp_prefix = get_mcp_tool_prefix_from_config(str(project_root), strict=True)
    final_task_content = generate_7section_task(
        task_id=task_id,
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
        enable_git=agent_enable_git,
    )

    # タスクファイル作成
    dashboard = ensure_dashboard_manager(app_ctx)
    agent_label = (
        dashboard.get_agent_label(agent) if hasattr(dashboard, "get_agent_label") else agent.id
    )
    task_file = dashboard.write_task_file(
        project_root,
        session_id,
        task_id,
        agent_label,
        final_task_content,
    )
    return project_root, task_file


async def _dispatch_bootstrap_command(
    app_ctx: AppContext,
    agent: Agent,
    task_file: Path,
    worktree_path: str,
    project_root: Path,
    enable_worktree: bool,
    profile_settings: dict,
) -> tuple[bool, str]:
    """AI CLI の初回起動コマンドを tmux に送信する。"""
    tmux = app_ctx.tmux
    agent_cli_name = _resolve_agent_cli_name(agent, app_ctx)
    worker_no = resolve_worker_number_from_slot(
        app_ctx.settings,
        agent.window_index,
        agent.pane_index,
    )
    worker_model_default = profile_settings.get("worker_model")
    worker_model = app_ctx.settings.get_worker_model(worker_no, worker_model_default)
    thinking_tokens = profile_settings.get("worker_thinking_tokens", 4000)
    reasoning_effort = profile_settings.get("worker_reasoning_effort", "none")

    agent_enable_git = _resolve_agent_enable_git(app_ctx, agent)
    bootstrap_command = app_ctx.ai_cli.build_stdin_command(
        cli=agent_cli_name,
        task_file_path=str(task_file),
        worktree_path=worktree_path if enable_worktree else None,
        project_root=str(project_root),
        model=worker_model,
        role="worker",
        role_template_path=str(get_role_template_path("worker", enable_git=agent_enable_git)),
        thinking_tokens=thinking_tokens,
        reasoning_effort=reasoning_effort,
    )
    success = await tmux.send_with_rate_limit_to_pane(
        agent.session_name,
        agent.window_index,
        agent.pane_index,
        bootstrap_command,
        clear_input=False,
        confirm_codex_prompt=agent_cli_name == "codex",
    )
    return success, bootstrap_command


async def _dispatch_followup_command(
    app_ctx: AppContext,
    agent: Agent,
    task_file: Path,
    worktree_path: str,
    enable_worktree: bool,
    worker_index: int,
    profile_settings: dict,
) -> tuple[bool, str, str | None]:
    """既に起動中の AI CLI に followup タスクを送信する。

    Returns:
        (success, command_sent, dispatch_error)
    """
    tmux = app_ctx.tmux
    agent_cli_name = _resolve_agent_cli_name(agent, app_ctx)
    confirm_codex_prompt = agent_cli_name == "codex"

    if enable_worktree:
        change_dir = _build_change_directory_command(agent_cli_name, worktree_path)
        changed = await tmux.send_with_rate_limit_to_pane(
            agent.session_name,
            agent.window_index,
            agent.pane_index,
            change_dir,
            clear_input=False,
            confirm_codex_prompt=confirm_codex_prompt,
        )
        if not changed:
            current_command = await _reset_bootstrap_state_if_shell(
                app_ctx,
                agent,
                tmux,
                worker_index,
            )
            error = (
                "failed to change directory before followup dispatch"
                f" (pane_current_command={current_command or 'unknown'})"
            )
            return False, change_dir, error
        await asyncio.sleep(0.25)

    instruction = f"次のタスク指示ファイルを実行してください: {task_file}"
    success = await tmux.send_with_rate_limit_to_pane(
        agent.session_name,
        agent.window_index,
        agent.pane_index,
        instruction,
        clear_input=False,
        confirm_codex_prompt=confirm_codex_prompt,
    )
    return success, instruction, None


async def _handle_dispatch_failure(
    app_ctx: AppContext,
    agent: Agent,
    task_file: Path,
    worktree_path: str,
    project_root: Path,
    session_id: str,
    worker_index: int,
    dispatch_mode: str,
    command_sent: str | None,
    enable_worktree: bool,
    profile_settings: dict,
) -> dict[str, Any]:
    """dispatch 失敗時の bootstrap リトライと結果組み立てを行う。"""
    tmux = app_ctx.tmux
    dashboard = ensure_dashboard_manager(app_ctx)
    correction_info = ""

    if dispatch_mode == "followup":
        current_command = await _reset_bootstrap_state_if_shell(
            app_ctx,
            agent,
            tmux,
            worker_index,
        )
        if (current_command or "").strip().lower() in _SHELL_COMMANDS:
            logger.info(
                "Worker %s の followup 失敗を検知。bootstrap を 1 回再試行します",
                worker_index + 1,
            )
            retry_success, retry_command = await _dispatch_bootstrap_command(
                app_ctx,
                agent,
                task_file,
                worktree_path,
                project_root,
                enable_worktree,
                profile_settings,
            )
            if retry_success:
                agent.status = AgentStatus.BUSY
                agent.last_activity = datetime.now()
                agent.ai_bootstrapped = True
                save_agent_to_file(app_ctx, agent)
                dashboard.save_markdown_dashboard(project_root, session_id)
                return _make_dispatch_result(
                    True,
                    dispatch_mode="bootstrap",
                    task_file=str(task_file),
                    command_sent=retry_command,
                )
            correction_info = " (pane_current_command=shell, bootstrap_retry_failed)"
            command_sent = retry_command
        else:
            correction_info = f" (pane_current_command={current_command or 'unknown'})"

    logger.warning(f"Worker {worker_index + 1}: タスク送信失敗")
    return _make_dispatch_result(
        False,
        dispatch_mode=dispatch_mode,
        dispatch_error=f"tmux send_keys_to_pane failed{correction_info}",
        task_file=str(task_file),
        command_sent=command_sent,
    )


def _record_dispatch_success(
    app_ctx: AppContext,
    agent: Agent,
    dispatch_mode: str,
    project_root: Path,
    session_id: str,
    agent_cli_name: str,
    worker_model: str | None,
    thinking_tokens: int,
    task_id: str,
    worker_index: int,
) -> None:
    """dispatch 成功時のエージェント状態更新とコスト記録を行う。"""
    agent.status = AgentStatus.BUSY
    agent.last_activity = datetime.now()
    if dispatch_mode == "bootstrap":
        agent.ai_bootstrapped = True
    save_agent_to_file(app_ctx, agent)
    dashboard = ensure_dashboard_manager(app_ctx)
    dashboard.save_markdown_dashboard(project_root, session_id)
    try:
        dashboard.record_api_call(
            ai_cli=agent_cli_name,
            model=worker_model,
            estimated_tokens=thinking_tokens,
            agent_id=agent.id,
            task_id=task_id,
        )
    except Exception as e:
        logger.debug("API コール記録に失敗: %s", e)
    logger.info(f"Worker {worker_index + 1} (ID: {agent.id}) にタスクを送信しました")


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
) -> dict[str, Any]:
    """Worker にタスクを送信する。"""
    try:
        if not task_id:
            logger.warning("Worker %s へのタスク送信を中止: task_id が未指定です", worker_index + 1)
            return _make_dispatch_result(False, dispatch_error="task_id が必要です")

        project_root, task_file = _prepare_worker_task_content(
            app_ctx,
            agent,
            task_content,
            task_id,
            branch,
            worktree_path,
            session_id,
            enable_worktree,
            caller_agent_id,
        )

        if agent.session_name is None or agent.window_index is None or agent.pane_index is None:
            return _make_dispatch_result(False, dispatch_error="Workerペインが未設定です")

        agent_cli_name = _resolve_agent_cli_name(agent, app_ctx)
        worker_no = resolve_worker_number_from_slot(
            app_ctx.settings,
            agent.window_index,
            agent.pane_index,
        )
        worker_model = app_ctx.settings.get_worker_model(
            worker_no,
            profile_settings.get("worker_model"),
        )
        thinking_tokens = profile_settings.get("worker_thinking_tokens", 4000)
        should_bootstrap = not bool(getattr(agent, "ai_bootstrapped", False))

        if should_bootstrap:
            success, command_sent = await _dispatch_bootstrap_command(
                app_ctx,
                agent,
                task_file,
                worktree_path,
                project_root,
                enable_worktree,
                profile_settings,
            )
            dispatch_mode = "bootstrap"
        else:
            dispatch_mode = "followup"
            success, command_sent, followup_error = await _dispatch_followup_command(
                app_ctx,
                agent,
                task_file,
                worktree_path,
                enable_worktree,
                worker_index,
                profile_settings,
            )
            if followup_error:
                return _make_dispatch_result(
                    False,
                    dispatch_mode=dispatch_mode,
                    dispatch_error=followup_error,
                    task_file=str(task_file),
                    command_sent=command_sent,
                )

        if success:
            _record_dispatch_success(
                app_ctx,
                agent,
                dispatch_mode,
                project_root,
                session_id,
                agent_cli_name,
                worker_model,
                thinking_tokens,
                task_id,
                worker_index,
            )
            return _make_dispatch_result(
                True,
                dispatch_mode=dispatch_mode,
                task_file=str(task_file),
                command_sent=command_sent,
            )

        return await _handle_dispatch_failure(
            app_ctx,
            agent,
            task_file,
            worktree_path,
            project_root,
            session_id,
            worker_index,
            dispatch_mode,
            command_sent,
            enable_worktree,
            profile_settings,
        )
    except Exception as e:
        logger.warning(f"Worker {worker_index + 1}: タスク送信エラー - {e}")
        return _make_dispatch_result(False, dispatch_error=str(e))
