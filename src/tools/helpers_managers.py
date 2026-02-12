"""Manager 初期化ヘルパー関数。

TODO: 各 ensure_*_manager() は初回アクセス時に遅延初期化する lazy loading パターン。
将来的に AppContext.__getattr__ で自動初期化するか、DI コンテナの導入を検討。
"""

import logging
import os
from pathlib import Path

from src.context import AppContext
from src.managers.dashboard_manager import DashboardManager
from src.managers.gtrconfig_manager import GtrconfigManager
from src.managers.healthcheck_manager import HealthcheckManager
from src.managers.ipc_manager import IPCManager
from src.managers.memory_manager import MemoryManager
from src.managers.persona_manager import PersonaManager
from src.managers.scheduler_manager import SchedulerManager
from src.managers.worktree_manager import WorktreeManager
from src.tools.helpers_registry import ensure_session_id

logger = logging.getLogger(__name__)


def get_worktree_manager(app_ctx: AppContext, repo_path: str) -> WorktreeManager:
    """指定リポジトリのWorktreeManagerを取得または作成する。"""
    if repo_path not in app_ctx.worktree_managers:
        app_ctx.worktree_managers[repo_path] = WorktreeManager(repo_path)
    return app_ctx.worktree_managers[repo_path]


def get_gtrconfig_manager(app_ctx: AppContext, project_path: str) -> GtrconfigManager:
    """指定プロジェクトのGtrconfigManagerを取得または作成する。"""
    if project_path not in app_ctx.gtrconfig_managers:
        app_ctx.gtrconfig_managers[project_path] = GtrconfigManager(project_path)
    return app_ctx.gtrconfig_managers[project_path]


def ensure_ipc_manager(app_ctx: AppContext) -> IPCManager:
    """IPCManagerが初期化されていることを確認する。

    worktree 内で実行されている場合でも、メインリポジトリの IPC ディレクトリを使用する。

    Raises:
        ValueError: project_root が設定されていない場合
    """
    from src.tools.helpers import resolve_project_root

    try:
        base_dir = resolve_project_root(app_ctx)
    except ValueError:
        # 非 git テスト環境などでは app_ctx.project_root をそのまま使用する
        # （IPC パス解決にメインリポジトリ判定は必須ではない）
        if app_ctx.project_root:
            base_dir = app_ctx.project_root
        else:
            raise
    # session_id を確保（必須）
    session_id = ensure_session_id(app_ctx)
    if not session_id:
        raise ValueError(
            "session_id が設定されていません。"
            "init_tmux_workspace で session_id を指定してください。"
        )

    ipc_dir = os.path.join(base_dir, app_ctx.settings.mcp_dir, session_id, "ipc")
    ipc_dir_abs = os.path.realpath(os.path.abspath(ipc_dir))

    reuse_current = False
    if app_ctx.ipc_manager is not None:
        current_dir_abs = os.path.realpath(os.path.abspath(str(app_ctx.ipc_manager.ipc_dir)))
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
        app_ctx.ipc_manager = IPCManager(ipc_dir)
        app_ctx.ipc_manager.initialize()
    return app_ctx.ipc_manager


def ensure_dashboard_manager(app_ctx: AppContext) -> DashboardManager:
    """DashboardManagerが初期化されていることを確認する。

    worktree 内で実行されている場合でも、メインリポジトリの Dashboard ディレクトリを使用する。
    注意: initialize() は呼ばない。ディレクトリ・ファイル作成は
    init_tmux_workspace（Owner のみ）で明示的に行う。
    Worker の MCP プロセスからはファイル読み取りのみ安全に行える。

    Raises:
        ValueError: project_root または session_id が設定されていない場合
    """
    from src.tools.helpers import resolve_project_root

    base_dir = resolve_project_root(app_ctx)
    # session_id を確保（必須）
    session_id = ensure_session_id(app_ctx)
    if not session_id:
        raise ValueError(
            "session_id が設定されていません。"
            "init_tmux_workspace で session_id を指定してください。"
        )

    dashboard_dir = os.path.join(base_dir, app_ctx.settings.mcp_dir, session_id, "dashboard")
    dashboard_dir_abs = os.path.realpath(os.path.abspath(dashboard_dir))

    # セッション切替後に古い DashboardManager を使い回さない
    reuse_current = False
    if app_ctx.dashboard_manager is not None:
        current = app_ctx.dashboard_manager
        current_dir_abs = os.path.realpath(os.path.abspath(str(current.dashboard_dir)))
        same_dashboard_dir = current_dir_abs == dashboard_dir_abs
        same_workspace = os.path.realpath(os.path.abspath(str(current.workspace_path))) == (
            os.path.realpath(os.path.abspath(base_dir))
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
        # workspace_id は session_id を使用（同一タスク = 同一ダッシュボード）
        app_ctx.workspace_id = session_id
        app_ctx.dashboard_manager = DashboardManager(
            workspace_id=session_id,
            workspace_path=base_dir,
            dashboard_dir=dashboard_dir,
            settings=app_ctx.settings,
        )
    else:
        app_ctx.dashboard_manager.settings = app_ctx.settings
    return app_ctx.dashboard_manager


def ensure_scheduler_manager(app_ctx: AppContext) -> SchedulerManager:
    """SchedulerManagerが初期化されていることを確認する。"""
    if app_ctx.scheduler_manager is None:
        from src.tools.helpers_persistence import save_agent_to_file

        dashboard = ensure_dashboard_manager(app_ctx)
        app_ctx.scheduler_manager = SchedulerManager(
            dashboard,
            app_ctx.agents,
            persist_agent_state=lambda agent: save_agent_to_file(app_ctx, agent),
        )
    return app_ctx.scheduler_manager


def ensure_healthcheck_manager(app_ctx: AppContext) -> HealthcheckManager:
    """HealthcheckManagerが初期化されていることを確認する。"""
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
    """PersonaManagerが初期化されていることを確認する。"""
    if app_ctx.persona_manager is None:
        app_ctx.persona_manager = PersonaManager()
    return app_ctx.persona_manager


def ensure_memory_manager(app_ctx: AppContext) -> MemoryManager:
    """MemoryManagerが初期化されていることを確認する。

    worktree 内で実行されている場合でも、メインリポジトリの
    `{mcp_dir}/memory`（セッション非依存）を使用する。
    """
    from src.tools.helpers import resolve_project_root

    project_root = resolve_project_root(
        app_ctx,
        allow_env_fallback=True,
        allow_agent_fallback=True,
    )
    # project_root を設定（次回以降のために）
    if not app_ctx.project_root:
        app_ctx.project_root = project_root
        logger.info(f"project_root を自動設定: {project_root}")

    # report_task_completion の保存先整合のため、常に session 非依存の
    # .multi-agent-mcp/memory を使用する。
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


# グローバルメモリマネージャーのキャッシュ（アプリケーション全体で共有）
_global_memory_manager: MemoryManager | None = None


def ensure_global_memory_manager() -> MemoryManager:
    """グローバルMemoryManagerが初期化されていることを確認する。"""
    global _global_memory_manager
    if _global_memory_manager is None:
        _global_memory_manager = MemoryManager.from_global()
    return _global_memory_manager


def search_memory_context(
    app_ctx: "AppContext",
    query: str,
    project_limit: int = 3,
    global_limit: int = 2,
) -> str:
    """プロジェクトメモリとグローバルメモリから関連情報を検索する。

    Args:
        app_ctx: アプリケーションコンテキスト
        query: 検索クエリ
        project_limit: プロジェクトメモリの結果上限
        global_limit: グローバルメモリの結果上限

    Returns:
        メモリコンテキスト文字列（結果なしの場合は空文字列）
    """
    memory_lines: list[str] = []

    try:
        memory_manager = ensure_memory_manager(app_ctx)
        project_results = memory_manager.search(query, limit=project_limit)
        if project_results:
            memory_lines.append("**プロジェクトメモリ:**")
            for entry in project_results:
                memory_lines.append(f"- **{entry.key}**: {entry.content[:200]}...")
    except Exception as e:
        logger.debug(f"プロジェクトメモリ検索をスキップ: {e}")

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
        logger.debug(f"グローバルメモリ検索をスキップ: {e}")

    return "\n".join(memory_lines) if memory_lines else ""
