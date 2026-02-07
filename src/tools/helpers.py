"""MCPツール用共通ヘルパー関数。

このモジュールはコアのロール/権限関数と resolve_project_root を定義し、
サブモジュールから全シンボルを re-export して後方互換性を維持する。
"""

import logging
import os
from typing import Any

from src.config.settings import load_settings_for_project, resolve_project_env_file
from src.context import AppContext
from src.models.agent import AgentRole

logger = logging.getLogger(__name__)


# ========== プロジェクトルート解決 ==========


def refresh_app_settings(app_ctx: AppContext, project_root: str) -> None:
    """project_root に紐づく .env を読み込み、AppContext の settings を同期する。

    Args:
        app_ctx: アプリケーションコンテキスト
        project_root: プロジェクトルート
    """
    from src.tools.helpers_git import resolve_main_repo_root

    main_repo_root = resolve_main_repo_root(project_root)
    os.environ["MCP_PROJECT_ROOT"] = str(main_repo_root)
    env_file = resolve_project_env_file(main_repo_root)
    settings = load_settings_for_project(main_repo_root)

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
        logger.info(f"project settings を .env から再読み込み: {env_file}")
    else:
        logger.info(
            "project settings をデフォルトで再読み込み（.env なし）: "
            f"{main_repo_root}/.multi-agent-mcp/.env"
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
                project_root = resolve_main_repo_root(agent.working_dir)
                break
            elif agent.worktree_path:
                project_root = resolve_main_repo_root(agent.worktree_path)
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
    if require_worktree_resolution:
        project_root = resolve_main_repo_root(project_root)

    return project_root


# ========== ロールチェック ヘルパー ==========


def ensure_project_root_from_caller(
    app_ctx: AppContext, caller_agent_id: str | None
) -> None:
    """caller_agent_id からレジストリを検索し、app_ctx.project_root と session_id を設定する。

    各ツールの最初で呼び出すことで、Admin/Worker の MCP インスタンスでも
    正しい project_root と session_id を使用できるようにする。

    Args:
        app_ctx: アプリケーションコンテキスト
        caller_agent_id: 呼び出し元エージェントID
    """
    if caller_agent_id:
        def _apply_project_root(candidate: str | None) -> bool:
            """有効な project_root 候補を AppContext に適用する。"""
            if not candidate:
                return False
            if not os.path.isdir(candidate):
                logger.warning(f"無効な project_root 候補を無視します: {candidate}")
                return False

            app_ctx.project_root = candidate
            try:
                refresh_app_settings(app_ctx, candidate)
            except (ValueError, OSError) as e:
                logger.warning(f"project settings の再読み込みをスキップ: {e}")
            logger.debug(
                f"caller_agent_id {caller_agent_id} から project_root を設定: {candidate}"
            )
            return True

        # project_root が未設定の場合、レジストリから取得
        if not app_ctx.project_root:
            project_root = get_project_root_from_registry(caller_agent_id)
            if not _apply_project_root(project_root):
                # レジストリに有効な値がない場合、呼び出し元エージェントから補完
                agent = app_ctx.agents.get(caller_agent_id)
                if agent:
                    for candidate in (agent.working_dir, agent.worktree_path):
                        if _apply_project_root(candidate):
                            break

        # session_id が未設定の場合、レジストリから取得
        if not app_ctx.session_id:
            session_id = get_session_id_from_registry(caller_agent_id)
            if session_id:
                app_ctx.session_id = session_id
                logger.debug(
                    f"caller_agent_id {caller_agent_id} から session_id を設定: {session_id}"
                )


def get_agent_role(app_ctx: AppContext, agent_id: str) -> AgentRole | None:
    """エージェントIDからロールを取得する。

    Args:
        app_ctx: アプリケーションコンテキスト
        agent_id: エージェントID

    Returns:
        エージェントのロール、見つからない場合はNone
    """
    agent = app_ctx.agents.get(agent_id)
    if agent:
        return AgentRole(agent.role)
    return None


# 初期化フェーズで caller_agent_id なしで呼び出し可能なツール
# （Owner 作成前に実行する必要があるため）
BOOTSTRAP_TOOLS = {"init_tmux_workspace", "create_agent"}


def check_tool_permission(
    app_ctx: AppContext,
    tool_name: str,
    caller_agent_id: str | None,
) -> dict[str, Any] | None:
    """ツールのロール権限をチェックする。

    全ての MCP ツールで使用する統一的な権限チェック関数。
    role_permissions.py で定義された許可ロールに基づいてチェックする。

    Args:
        app_ctx: アプリケーションコンテキスト
        tool_name: ツール名
        caller_agent_id: 呼び出し元エージェントID（必須、ただし初期化ツールは例外）

    Returns:
        権限エラーの場合はエラー dict、許可されている場合は None
    """
    from src.config.role_permissions import get_allowed_roles, get_role_error_message

    # 初期化ツールは caller_agent_id なしで許可（Owner 作成前に実行）
    if caller_agent_id is None and tool_name in BOOTSTRAP_TOOLS:
        logger.info(f"初期化ツール '{tool_name}' を caller_agent_id なしで許可します")
        return None

    # caller_agent_id は必須
    if caller_agent_id is None:
        return {
            "success": False,
            "error": (
                f"`{tool_name}` の呼び出しには `caller_agent_id` が必須です。"
                "自身のエージェント ID を指定してください。"
            ),
        }

    # caller_agent_id からレジストリを検索し project_root を設定
    # （Admin/Worker の MCP インスタンスでも正しい project_root を使用可能にする）
    ensure_project_root_from_caller(app_ctx, caller_agent_id)

    # ファイルからエージェント情報を同期（他の MCP インスタンスで作成されたエージェントを取得）
    sync_agents_from_file(app_ctx)

    # ロールを取得
    role = get_agent_role(app_ctx, caller_agent_id)
    if role is None:
        return {
            "success": False,
            "error": f"エージェント {caller_agent_id} が見つかりません",
        }

    # 許可ロールを取得
    allowed_roles = get_allowed_roles(tool_name)

    # ツールが未定義の場合は全ロール許可（後方互換性）
    if not allowed_roles:
        logger.warning(f"ツール '{tool_name}' の権限が未定義です。全ロールに許可します。")
        return None

    # ロールチェック
    if role.value not in allowed_roles:
        return {
            "success": False,
            "error": get_role_error_message(tool_name, role.value),
        }

    return None


def find_agents_by_role(app_ctx: AppContext, role: str) -> list[str]:
    """指定されたロールのエージェントIDを取得する。

    Args:
        app_ctx: アプリケーションコンテキスト
        role: 検索するロール（"owner", "admin", "worker"）

    Returns:
        該当するエージェントIDのリスト
    """
    return [
        agent_id
        for agent_id, agent in app_ctx.agents.items()
        if agent.role == role
    ]


# ========== MCP ツール用ショートカット ==========


def get_app_ctx(ctx: Any) -> AppContext:
    """MCP Context から AppContext を取得する。"""
    return ctx.request_context.lifespan_context


def require_permission(
    ctx: Any, tool_name: str, caller_agent_id: str | None
) -> tuple[AppContext, dict[str, Any] | None]:
    """AppContext 取得と権限チェックをまとめて行う。

    Returns:
        (app_ctx, error_or_none) のタプル。error が None なら許可。
    """
    app_ctx = get_app_ctx(ctx)
    error = check_tool_permission(app_ctx, tool_name, caller_agent_id)
    return app_ctx, error


# ========== tmux 通知ヘルパー ==========


async def notify_agent_via_tmux(
    app_ctx: "AppContext",
    agent: Any,
    msg_type_value: str,
    sender_id: str,
) -> bool:
    """エージェントに tmux 経由で IPC 通知を送信する。

    Args:
        app_ctx: アプリケーションコンテキスト
        agent: 通知対象のエージェント
        msg_type_value: メッセージタイプの値文字列
        sender_id: 送信元エージェントID

    Returns:
        送信成功時は True、失敗時は False
    """
    if (
        not agent
        or not agent.session_name
        or agent.pane_index is None
    ):
        logger.warning(
            f"エージェントの tmux 情報が見つかりません: {getattr(agent, 'id', 'unknown')}"
        )
        return False

    notification_text = (
        f"echo '[IPC] 新しいメッセージ: {msg_type_value} from {sender_id}'"
    )
    default_cli = app_ctx.ai_cli.get_default_cli()
    resolved_cli = agent.ai_cli or default_cli
    agent_cli = (
        resolved_cli.value
        if hasattr(resolved_cli, "value")
        else str(resolved_cli or "")
    ).lower()
    try:
        success = await app_ctx.tmux.send_with_rate_limit_to_pane(
            agent.session_name,
            agent.window_index or 0,
            agent.pane_index,
            notification_text,
            clear_input=False,
            confirm_codex_prompt=agent_cli == "codex",
        )
        if not success:
            logger.warning(
                "tmux 通知の送信に失敗（未確定の可能性）: %s",
                getattr(agent, "id", "unknown"),
            )
            return False
        logger.info(
            f"tmux 通知を送信: {getattr(agent, 'id', 'unknown')}"
        )
        return True
    except Exception as e:
        logger.warning(f"tmux 通知の送信に失敗: {e}")
        return False


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
from src.tools.helpers_persistence import (  # noqa: E402, F401
    _get_agents_file_path,
    load_agents_from_file,
    remove_agent_from_file,
    save_agent_to_file,
    sync_agents_from_file,
)
from src.tools.helpers_registry import (  # noqa: E402, F401
    _get_agent_registry_dir,
    _get_from_config,
    _get_global_mcp_dir,
    ensure_session_id,
    get_mcp_tool_prefix_from_config,
    get_project_root_from_config,
    get_project_root_from_registry,
    get_session_id_from_config,
    get_session_id_from_registry,
    remove_agent_from_registry,
    remove_agents_by_owner,
    save_agent_to_registry,
)
