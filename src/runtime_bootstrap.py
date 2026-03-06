"""アプリケーション runtime/bootstrap 層。

project_root / session_id の解決と manager 初期化責務を
`src.tools.helpers*` から切り離して集約する。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from src.config.settings import load_effective_settings_for_project, resolve_project_env_file
from src.tools.helpers_git import resolve_main_repo_root
from src.tools.helpers_registry import ensure_session_id, get_project_root_from_config

if TYPE_CHECKING:
    from src.context import AppContext
    from src.managers.dashboard_manager import DashboardManager
    from src.managers.gtrconfig_manager import GtrconfigManager
    from src.managers.healthcheck_manager import HealthcheckManager
    from src.managers.ipc_manager import IPCManager
    from src.managers.memory_manager import MemoryManager
    from src.managers.persona_manager import PersonaManager
    from src.managers.scheduler_manager import SchedulerManager
    from src.managers.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


def refresh_app_settings(app_ctx: AppContext, project_root: str) -> None:
    """project_root に紐づく .env を読み込み、AppContext の settings を同期する。"""
    normalized_root = str(Path(project_root).expanduser())
    try:
        main_repo_root = resolve_main_repo_root(normalized_root)
    except ValueError:
        main_repo_root = normalized_root

    settings = load_effective_settings_for_project(main_repo_root)
    effective_root = main_repo_root
    if settings.enable_git:
        try:
            effective_root = resolve_main_repo_root(main_repo_root)
        except ValueError:
            logger.warning(
                "enable_git=true ですが git ルート解決に失敗したため、"
                "作業ディレクトリを使用します: %s",
                main_repo_root,
            )
            effective_root = main_repo_root

    os.environ["MCP_PROJECT_ROOT"] = str(effective_root)
    env_file = resolve_project_env_file(effective_root)

    app_ctx.settings = settings
    app_ctx.ai_cli.settings = settings
    app_ctx.tmux.settings = settings
    if app_ctx.healthcheck_manager is not None:
        app_ctx.healthcheck_manager.healthcheck_interval_seconds = (
            settings.healthcheck_interval_seconds
        )
        app_ctx.healthcheck_manager.stall_timeout_seconds = (
            settings.healthcheck_stall_timeout_seconds
        )
        app_ctx.healthcheck_manager.in_progress_no_ipc_timeout_seconds = (
            settings.healthcheck_in_progress_no_ipc_timeout_seconds
        )
        app_ctx.healthcheck_manager.max_recovery_attempts = (
            settings.healthcheck_max_recovery_attempts
        )

    if env_file:
        logger.info("project settings を .env から再読み込み: %s", env_file)
    else:
        logger.info(
            "project settings をデフォルトで再読み込み（.env なし）: %s/.multi-agent-mcp/.env",
            effective_root,
        )


def resolve_project_root(
    app_ctx: AppContext,
    allow_env_fallback: bool = False,
    allow_agent_fallback: bool = False,
    require_worktree_resolution: bool = True,
    caller_agent_id: str | None = None,
) -> str:
    """project_root を解決する共通ロジック。"""
    project_root = app_ctx.project_root

    if not project_root:
        project_root = get_project_root_from_config(caller_agent_id=caller_agent_id)

    if not project_root and allow_agent_fallback:
        from src.tools.helpers_persistence import sync_agents_from_file

        sync_agents_from_file(app_ctx)
        for agent in app_ctx.agents.values():
            if agent.working_dir:
                if app_ctx.settings.enable_git:
                    project_root = resolve_main_repo_root(agent.working_dir)
                else:
                    project_root = agent.working_dir
                break
            if agent.worktree_path:
                if app_ctx.settings.enable_git:
                    project_root = resolve_main_repo_root(agent.worktree_path)
                else:
                    project_root = agent.worktree_path
                break

    if not project_root and allow_env_fallback:
        env_project_root = os.environ.get("MCP_PROJECT_ROOT")
        if env_project_root:
            project_root = env_project_root

    if not project_root:
        raise ValueError(
            "project_root が設定されていません。init_tmux_workspace を先に実行してください。"
        )

    if require_worktree_resolution and app_ctx.settings.enable_git:
        project_root = resolve_main_repo_root(project_root)

    return project_root


def _resolve_session_scoped_dir(
    base_dir: str,
    mcp_dir_name: str,
    session_id: str,
    leaf_dir_name: str,
) -> Path:
    """セッションスコープ配下のディレクトリを解決し、境界外アクセスを拒否する。"""
    root = Path(base_dir).expanduser().resolve()
    mcp_root = (root / mcp_dir_name).resolve()
    target = (mcp_root / session_id / leaf_dir_name).resolve()
    try:
        target.relative_to(mcp_root)
    except ValueError as e:
        logger.warning("セッションスコープ外のパスを拒否: session_id=%s", session_id)
        raise ValueError(
            "session_id によるパス逸脱を検出したため拒否しました。"
        ) from e
    return target


def get_worktree_manager(app_ctx: AppContext, repo_path: str) -> WorktreeManager:
    """指定リポジトリの WorktreeManager を取得または作成する。"""
    from src.managers.worktree_manager import WorktreeManager

    if repo_path not in app_ctx.worktree_managers:
        app_ctx.worktree_managers[repo_path] = WorktreeManager(repo_path)
    return app_ctx.worktree_managers[repo_path]


def get_gtrconfig_manager(app_ctx: AppContext, project_path: str) -> GtrconfigManager:
    """指定プロジェクトの GtrconfigManager を取得または作成する。"""
    from src.managers.gtrconfig_manager import GtrconfigManager

    if project_path not in app_ctx.gtrconfig_managers:
        app_ctx.gtrconfig_managers[project_path] = GtrconfigManager(project_path)
    return app_ctx.gtrconfig_managers[project_path]


def ensure_ipc_manager(app_ctx: AppContext) -> IPCManager:
    """IPCManager が初期化されていることを確認する。"""
    from src.managers.ipc_manager import IPCManager

    try:
        base_dir = resolve_project_root(app_ctx)
    except ValueError:
        if app_ctx.project_root:
            base_dir = app_ctx.project_root
        else:
            raise

    session_id = ensure_session_id(app_ctx)
    if not session_id:
        raise ValueError(
            "session_id が設定されていません。"
            "init_tmux_workspace で session_id を指定してください。"
        )

    ipc_dir = _resolve_session_scoped_dir(
        base_dir=base_dir,
        mcp_dir_name=app_ctx.settings.mcp_dir,
        session_id=session_id,
        leaf_dir_name="ipc",
    )
    ipc_dir_abs = str(ipc_dir.resolve())

    reuse_current = False
    if app_ctx.ipc_manager is not None:
        current_dir_abs = str(Path(app_ctx.ipc_manager.ipc_dir).resolve())
        is_session_scoped_ipc = (
            f"{os.sep}{app_ctx.settings.mcp_dir}{os.sep}" in current_dir_abs
            and current_dir_abs.endswith(f"{os.sep}ipc")
        )
        reuse_current = current_dir_abs == ipc_dir_abs or not is_session_scoped_ipc
        if not reuse_current:
            logger.info(
                "IPCManager の参照先を再同期します: %s -> %s",
                current_dir_abs,
                ipc_dir_abs,
            )

    if not reuse_current:
        app_ctx.ipc_manager = IPCManager(str(ipc_dir))
        app_ctx.ipc_manager.initialize()
    return app_ctx.ipc_manager


def ensure_dashboard_manager(app_ctx: AppContext) -> DashboardManager:
    """DashboardManager が初期化されていることを確認する。"""
    from src.managers.dashboard_manager import DashboardManager

    base_dir = resolve_project_root(app_ctx)
    session_id = ensure_session_id(app_ctx)
    if not session_id:
        raise ValueError(
            "session_id が設定されていません。"
            "init_tmux_workspace で session_id を指定してください。"
        )

    dashboard_dir = _resolve_session_scoped_dir(
        base_dir=base_dir,
        mcp_dir_name=app_ctx.settings.mcp_dir,
        session_id=session_id,
        leaf_dir_name="dashboard",
    )
    dashboard_dir_abs = str(dashboard_dir.resolve())

    reuse_current = False
    if app_ctx.dashboard_manager is not None:
        current = app_ctx.dashboard_manager
        current_dir_abs = str(Path(current.dashboard_dir).resolve())
        same_dashboard_dir = current_dir_abs == dashboard_dir_abs
        same_workspace = str(Path(current.workspace_path).resolve()) == str(
            Path(base_dir).resolve()
        )
        is_session_scoped_dashboard = (
            f"{os.sep}{app_ctx.settings.mcp_dir}{os.sep}" in current_dir_abs
            and current_dir_abs.endswith(f"{os.sep}dashboard")
        )
        same_workspace_id = current.workspace_id == session_id
        if (
            not same_workspace_id
            and not is_session_scoped_dashboard
            and app_ctx.workspace_id is not None
            and current.workspace_id == app_ctx.workspace_id
        ):
            same_workspace_id = True
        reuse_current = same_dashboard_dir or (same_workspace and same_workspace_id)

    if not reuse_current:
        app_ctx.workspace_id = session_id
        app_ctx.dashboard_manager = DashboardManager(
            workspace_id=session_id,
            workspace_path=base_dir,
            dashboard_dir=str(dashboard_dir),
            settings=app_ctx.settings,
        )
    else:
        app_ctx.dashboard_manager.settings = app_ctx.settings
    return app_ctx.dashboard_manager


def _build_scheduler_persist_callback(app_ctx: AppContext):
    """Scheduler 用のエージェント永続化コールバックを構築する。"""
    from src.tools.helpers_persistence import save_agent_to_file

    return lambda agent: save_agent_to_file(app_ctx, agent)


def _build_scheduler_dashboard_provider(app_ctx: AppContext):
    """Scheduler 用の Dashboard provider を構築する。"""
    return lambda: ensure_dashboard_manager(app_ctx)


def ensure_scheduler_manager(app_ctx: AppContext) -> SchedulerManager:
    """SchedulerManager が初期化されていることを確認する。"""
    from src.managers.scheduler_manager import SchedulerManager

    dashboard_provider = _build_scheduler_dashboard_provider(app_ctx)
    persist_agent_state = _build_scheduler_persist_callback(app_ctx)

    if app_ctx.scheduler_manager is None:
        app_ctx.scheduler_manager = SchedulerManager(
            dashboard_manager=dashboard_provider(),
            agents=app_ctx.agents,
            persist_agent_state=persist_agent_state,
            dashboard_provider=dashboard_provider,
        )
    else:
        app_ctx.scheduler_manager.agents = app_ctx.agents
        app_ctx.scheduler_manager.set_persist_agent_state(persist_agent_state)
        app_ctx.scheduler_manager.set_dashboard_provider(dashboard_provider)
    return app_ctx.scheduler_manager


def ensure_healthcheck_manager(app_ctx: AppContext) -> HealthcheckManager:
    """HealthcheckManager が初期化されていることを確認する。"""
    from src.managers.healthcheck_manager import HealthcheckManager

    if app_ctx.healthcheck_manager is None:
        app_ctx.healthcheck_manager = HealthcheckManager(
            tmux_manager=app_ctx.tmux,
            agents=app_ctx.agents,
            healthcheck_interval_seconds=app_ctx.settings.healthcheck_interval_seconds,
            stall_timeout_seconds=app_ctx.settings.healthcheck_stall_timeout_seconds,
            in_progress_no_ipc_timeout_seconds=(
                app_ctx.settings.healthcheck_in_progress_no_ipc_timeout_seconds
            ),
            max_recovery_attempts=app_ctx.settings.healthcheck_max_recovery_attempts,
        )
    return app_ctx.healthcheck_manager


def ensure_persona_manager(app_ctx: AppContext) -> PersonaManager:
    """PersonaManager が初期化されていることを確認する。"""
    from src.managers.persona_manager import PersonaManager

    if app_ctx.persona_manager is None:
        app_ctx.persona_manager = PersonaManager()
    return app_ctx.persona_manager


def ensure_memory_manager(app_ctx: AppContext) -> MemoryManager:
    """MemoryManager が初期化されていることを確認する。"""
    from src.managers.memory_manager import MemoryManager

    project_root = resolve_project_root(
        app_ctx,
        allow_env_fallback=True,
        allow_agent_fallback=True,
    )
    if not app_ctx.project_root:
        app_ctx.project_root = project_root
        logger.info("project_root を自動設定: %s", project_root)

    memory_dir = os.path.join(project_root, app_ctx.settings.mcp_dir, "memory")
    memory_dir_abs = os.path.realpath(os.path.abspath(memory_dir))
    current_dir_abs: str | None = None
    if app_ctx.memory_manager is not None and app_ctx.memory_manager.storage_dir is not None:
        current_dir_abs = os.path.realpath(
            os.path.abspath(str(Path(app_ctx.memory_manager.storage_dir)))
        )

    if app_ctx.memory_manager is None or current_dir_abs != memory_dir_abs:
        app_ctx.memory_manager = MemoryManager(storage_dir=memory_dir)
    return app_ctx.memory_manager


_global_memory_manager: MemoryManager | None = None


def ensure_global_memory_manager() -> MemoryManager:
    """グローバル MemoryManager が初期化されていることを確認する。"""
    global _global_memory_manager
    from src.managers.memory_manager import MemoryManager

    if _global_memory_manager is None:
        _global_memory_manager = MemoryManager.from_global()
    return _global_memory_manager


def search_memory_context(
    app_ctx: AppContext,
    query: str,
    project_limit: int = 3,
    global_limit: int = 2,
) -> str:
    """プロジェクトメモリとグローバルメモリから関連情報を検索する。"""
    memory_lines: list[str] = []

    try:
        memory_manager = ensure_memory_manager(app_ctx)
        project_results = memory_manager.search(query, limit=project_limit)
        if project_results:
            memory_lines.append("**プロジェクトメモリ:**")
            for entry in project_results:
                memory_lines.append(f"- **{entry.key}**: {entry.content[:200]}...")
    except Exception as e:
        logger.debug("プロジェクトメモリ検索をスキップ: %s", e)

    try:
        global_memory = ensure_global_memory_manager()
        global_results = global_memory.search(query, limit=global_limit)
        if global_results:
            if memory_lines:
                memory_lines.append("")
            memory_lines.append("**グローバルメモリ:**")
            for entry in global_results:
                memory_lines.append(f"- **{entry.key}**: {entry.content[:200]}...")
    except Exception as e:
        logger.debug("グローバルメモリ検索をスキップ: %s", e)

    return "\n".join(memory_lines) if memory_lines else ""
