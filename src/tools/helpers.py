"""MCPツール用共通ヘルパー関数。

このモジュールはプロジェクトルート解決関数を定義し、
サブモジュールから全シンボルを re-export して後方互換性を維持する。
"""

import logging
import os
from pathlib import Path

from src.config.settings import load_effective_settings_for_project, resolve_project_env_file
from src.context import AppContext

logger = logging.getLogger(__name__)


# ========== プロジェクトルート解決 ==========


def refresh_app_settings(app_ctx: AppContext, project_root: str) -> None:
    """project_root に紐づく .env を読み込み、AppContext の settings を同期する。

    Args:
        app_ctx: アプリケーションコンテキスト
        project_root: プロジェクトルート
    """
    from src.tools.helpers_git import resolve_main_repo_root

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
    """project_root を解決する共通ロジック。

    複数のソースから project_root を探索し、解決する。
    ensure_*_manager() 関数で共通して使用される。

    Args:
        app_ctx: アプリケーションコンテキスト
        allow_env_fallback: MCP_PROJECT_ROOT 環境変数からの取得を許可
        allow_agent_fallback: エージェントの working_dir からの取得を許可
        require_worktree_resolution: worktree の場合にメインリポジトリを返す
        caller_agent_id: 呼び出し元エージェントID（レジストリ検索用）

    Returns:
        project_root のパス

    Raises:
        ValueError: project_root が解決できない場合
    """
    # app_ctx.project_root から取得
    project_root = app_ctx.project_root

    # グローバルレジストリ / config.json から取得
    if not project_root:
        project_root = get_project_root_from_config(caller_agent_id=caller_agent_id)

    # エージェントの working_dir または worktree_path から取得（オプション）
    if not project_root and allow_agent_fallback:
        sync_agents_from_file(app_ctx)
        for agent in app_ctx.agents.values():
            if agent.working_dir:
                if app_ctx.settings.enable_git:
                    project_root = resolve_main_repo_root(agent.working_dir)
                else:
                    project_root = agent.working_dir
                break
            elif agent.worktree_path:
                if app_ctx.settings.enable_git:
                    project_root = resolve_main_repo_root(agent.worktree_path)
                else:
                    project_root = agent.worktree_path
                break

    # 環境変数 MCP_PROJECT_ROOT からのフォールバック（オプション）
    if not project_root and allow_env_fallback:
        env_project_root = os.environ.get("MCP_PROJECT_ROOT")
        if env_project_root:
            project_root = env_project_root

    if not project_root:
        raise ValueError(
            "project_root が設定されていません。init_tmux_workspace を先に実行してください。"
        )

    # worktree の場合はメインリポジトリのパスを使用
    if require_worktree_resolution and app_ctx.settings.enable_git:
        project_root = resolve_main_repo_root(project_root)

    return project_root


# ========== サブモジュールからの re-export ==========
# 全ての既存 import パスを維持するため

from src.tools.helpers_git import resolve_main_repo_root  # noqa: E402
from src.tools.helpers_managers import (  # noqa: E402, F401
    _global_memory_manager,
    ensure_dashboard_manager,
    ensure_global_memory_manager,
    ensure_healthcheck_manager,
    ensure_ipc_manager,
    ensure_memory_manager,
    ensure_persona_manager,
    ensure_scheduler_manager,
    get_gtrconfig_manager,
    get_worktree_manager,
    search_memory_context,
)
from src.tools.helpers_notifications import (  # noqa: E402, F401
    _send_macos_notification,
    notify_agent_via_tmux,
)
from src.tools.helpers_permissions import (  # noqa: E402, F401
    ADMIN_DASHBOARD_GRANT_SECONDS,
    BOOTSTRAP_TOOLS,
    OWNER_WAIT_ALLOWED_TOOLS,
    _owner_polling_blocked_response,
    check_tool_permission,
    clear_owner_wait_state,
    ensure_project_root_from_caller,
    find_agents_by_role,
    get_admin_poll_state,
    get_agent_role,
    get_app_ctx,
    get_owner_wait_state,
    mark_owner_waiting_for_admin,
    require_permission,
    reset_agent_to_idle,
    validate_sender_caller_match,
)
from src.tools.helpers_persistence import (  # noqa: E402, F401
    _get_agents_file_path,
    delete_agents_file,
    load_agents_from_file,
    remove_agent_from_file,
    save_agent_to_file,
    sync_agents_from_file,
)
from src.tools.helpers_registry import (  # noqa: E402, F401
    InvalidConfigError,
    _get_agent_registry_dir,
    _get_from_config,
    _get_global_mcp_dir,
    ensure_session_id,
    get_enable_git_from_config,
    get_mcp_tool_prefix_from_config,
    get_project_root_from_config,
    get_project_root_from_registry,
    get_session_id_from_config,
    get_session_id_from_registry,
    remove_agent_from_registry,
    remove_agents_by_owner,
    save_agent_to_registry,
)
