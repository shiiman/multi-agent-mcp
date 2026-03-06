"""権限チェック・ロール管理ヘルパー関数。

ロールベースの権限チェック、Owner 待機ロック、Admin ポーリングガード、
エージェント状態リセットなどの関数を提供する。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.context import AppContext

from src.models.agent import AgentRole
from src.tools.helpers_persistence import save_agent_to_file, sync_agents_from_file
from src.tools.helpers_registry import get_project_root_from_registry, get_session_id_from_registry

logger = logging.getLogger(__name__)


# ========== ロールチェック ヘルパー ==========


def ensure_project_root_from_caller(app_ctx: AppContext, caller_agent_id: str | None) -> None:
    """caller_agent_id からレジストリを検索し、app_ctx.project_root と session_id を設定する。

    各ツールの最初で呼び出すことで、Admin/Worker の MCP インスタンスでも
    正しい project_root と session_id を使用できるようにする。

    Args:
        app_ctx: アプリケーションコンテキスト
        caller_agent_id: 呼び出し元エージェントID
    """
    if caller_agent_id:
        # 循環参照回避のため遅延 import
        from src.tools.helpers import refresh_app_settings

        def _apply_project_root(candidate: str | None) -> bool:
            """有効な project_root 候補を AppContext に適用する。"""
            if not candidate:
                return False
            if not os.path.isdir(candidate):
                logger.warning("無効な project_root 候補を無視します: %s", candidate)
                return False

            app_ctx.project_root = candidate
            try:
                refresh_app_settings(app_ctx, candidate)
            except (ValueError, OSError) as e:
                logger.warning("project settings の再読み込みをスキップ: %s", e)
            logger.debug(
                "caller_agent_id %s から project_root を設定: %s",
                caller_agent_id,
                candidate,
            )
            return True

        # レジストリの値が現在の app_ctx と異なる場合は再同期する
        registry_project_root = get_project_root_from_registry(caller_agent_id)
        if registry_project_root:
            if app_ctx.project_root != registry_project_root:
                _apply_project_root(registry_project_root)
        elif not app_ctx.project_root:
            # レジストリに有効な値がない場合、呼び出し元エージェントから補完
            agent = app_ctx.agents.get(caller_agent_id)
            if agent:
                for candidate in (agent.working_dir, agent.worktree_path):
                    if _apply_project_root(candidate):
                        break

        registry_session_id = get_session_id_from_registry(caller_agent_id)
        if registry_session_id and app_ctx.session_id != registry_session_id:
            previous_session_id = app_ctx.session_id
            app_ctx.session_id = registry_session_id
            logger.debug(
                "caller_agent_id %s から session_id を同期: %s -> %s",
                caller_agent_id,
                previous_session_id,
                registry_session_id,
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
BOOTSTRAP_TOOLS = {"init_tmux_workspace"}
OWNER_WAIT_ALLOWED_TOOLS = {"read_messages", "get_unread_count", "unlock_owner_wait"}


def check_tool_permission(
    app_ctx: AppContext,
    tool_name: str,
    caller_agent_id: str | None,
    target_agent_id: str | None = None,
) -> dict[str, Any] | None:
    """ツールのロール権限をチェックする。

    全ての MCP ツールで使用する統一的な権限チェック関数。
    role_permissions.py で定義された許可ロールに基づいてチェックする。

    Args:
        app_ctx: アプリケーションコンテキスト
        tool_name: ツール名
        caller_agent_id: 呼び出し元エージェントID（必須、ただし初期化ツールは例外）
        target_agent_id: 対象エージェントID（Worker self-scope チェック用）

    Returns:
        権限エラーの場合はエラー dict、許可されている場合は None
    """
    from src.config.role_permissions import (
        get_allowed_roles,
        get_role_error_message,
        requires_worker_self_scope,
    )

    # 初期化ツールは caller_agent_id なしで許可（Owner 作成前に実行）
    if caller_agent_id is None and tool_name in BOOTSTRAP_TOOLS:
        logger.info("初期化ツール '%s' を caller_agent_id なしで許可します", tool_name)
        return None

    # caller_agent_id は必須
    if caller_agent_id is None:
        return {
            "success": False,
            "error_code": "MISSING_CALLER_ID",
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
            "error_code": "AGENT_NOT_FOUND",
            "error": f"エージェント {caller_agent_id} が見つかりません",
        }

    # Owner が待機ロック中の場合、許可ツール以外をブロック
    if role == AgentRole.OWNER:
        owner_state = get_owner_wait_state(app_ctx, caller_agent_id)
        if owner_state.get("waiting_for_admin") and tool_name not in OWNER_WAIT_ALLOWED_TOOLS:
            waiting_admin_id = owner_state.get("admin_id")
            return {
                "success": False,
                "error_code": "OWNER_WAIT_LOCKED",
                "error": (
                    "owner_wait_locked: Admin からの通知待機中のため、"
                    f"`{tool_name}` は実行できません。"
                ),
                "next_action": "wait_for_admin_notification_or_unlock_owner_wait",
                "waiting_for_admin_id": waiting_admin_id,
                "allowed_tools": sorted(OWNER_WAIT_ALLOWED_TOOLS),
            }

    # 許可ロールを取得
    allowed_roles = get_allowed_roles(tool_name)

    # ツールが未定義の場合は fail-close（明示定義必須）
    if not allowed_roles:
        logger.error("ツール '%s' の権限が未定義のため拒否しました", tool_name)
        return {
            "success": False,
            "error_code": "PERMISSION_UNDEFINED",
            "error": (
                f"ツール `{tool_name}` の権限定義が存在しないため実行を拒否しました。"
                " `src/config/role_permissions.py` に明示的な定義を追加してください。"
            ),
        }

    # ロールチェック
    if role.value not in allowed_roles:
        return {
            "success": False,
            "error_code": "ROLE_NOT_ALLOWED",
            "error": get_role_error_message(tool_name, role.value),
        }

    # Worker self-scope 制約: 対象エージェントIDは caller_agent_id と一致必須
    if role == AgentRole.WORKER and requires_worker_self_scope(tool_name):
        if target_agent_id is None:
            return {
                "success": False,
                "error_code": "WORKER_SELF_SCOPE_MISSING",
                "error": (
                    f"`{tool_name}` は Worker self-scope 対象ツールです。"
                    "`target_agent_id` が未指定のため拒否しました。"
                ),
            }
        if target_agent_id != caller_agent_id:
            return {
                "success": False,
                "error_code": "WORKER_SELF_SCOPE_VIOLATION",
                "error": (
                    f"Worker は `{tool_name}` を自分自身の agent_id でのみ実行できます。"
                    f"caller_agent_id={caller_agent_id}, target_agent_id={target_agent_id}"
                ),
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
    return [agent_id for agent_id, agent in app_ctx.agents.items() if agent.role == role]


def get_owner_wait_state(app_ctx: AppContext, owner_id: str) -> dict[str, Any]:
    """Owner ごとの待機ロック状態を取得する。"""
    state = app_ctx._owner_wait_state.get(owner_id)
    if not isinstance(state, dict):
        state = {
            "waiting_for_admin": False,
            "admin_id": None,
            "session_id": None,
            "locked_at": None,
            "unlocked_at": None,
            "unlock_reason": None,
        }
        app_ctx._owner_wait_state[owner_id] = state
    return state


def mark_owner_waiting_for_admin(
    app_ctx: AppContext, owner_id: str, admin_id: str, session_id: str | None
) -> None:
    """Owner を Admin 通知待機状態に遷移させる。"""
    state = get_owner_wait_state(app_ctx, owner_id)
    state["waiting_for_admin"] = True
    state["admin_id"] = admin_id
    state["session_id"] = session_id
    state["locked_at"] = datetime.now()
    state["unlocked_at"] = None
    state["unlock_reason"] = None


def clear_owner_wait_state(app_ctx: AppContext, owner_id: str, reason: str) -> None:
    """Owner の待機ロック状態を解除する。"""
    state = get_owner_wait_state(app_ctx, owner_id)
    state["waiting_for_admin"] = False
    state["admin_id"] = None
    state["unlocked_at"] = datetime.now()
    state["unlock_reason"] = reason


# ========== MCP ツール用ショートカット ==========


def get_app_ctx(ctx: Any) -> AppContext:
    """MCP Context から AppContext を取得する。"""
    return ctx.request_context.lifespan_context


_AUTHENTICATED_AGENT_ID_KEYS = (
    "authenticated_agent_id",
    "authenticatedAgentId",
)


def _extract_text_value(container: Any, key: str) -> str | None:
    """dict/オブジェクトから文字列フィールドを安全に抽出する。"""
    value: Any = None
    if isinstance(container, dict):
        value = container.get(key)
    else:
        value = getattr(container, key, None)

    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def get_authenticated_agent_id(ctx: Any) -> str | None:
    """MCP Context から認証済み主体の agent_id を取得する。

    Notes:
        RequestContext.meta は Pydantic Model / dict のどちらでも来るため、
        両形式を許容して抽出する。
    """
    request_context = getattr(ctx, "request_context", None)
    if request_context is None:
        return None

    meta = getattr(request_context, "meta", None)
    if meta is None:
        return None

    for key in _AUTHENTICATED_AGENT_ID_KEYS:
        candidate = _extract_text_value(meta, key)
        if candidate:
            return candidate
    return None


def resolve_effective_caller_agent_id(
    ctx: Any,
    caller_agent_id: str | None,
) -> tuple[str | None, dict[str, Any] | None]:
    """caller_agent_id と認証済み主体から実効 caller を決定する。"""
    authenticated_agent_id = get_authenticated_agent_id(ctx)
    if authenticated_agent_id is None:
        return caller_agent_id, None

    if caller_agent_id is not None and caller_agent_id != authenticated_agent_id:
        logger.warning(
            "caller/auth mismatch: caller_agent_id=%s authenticated_agent_id=%s",
            caller_agent_id,
            authenticated_agent_id,
        )
        return None, {
            "success": False,
            "error_code": "CALLER_AUTH_MISMATCH",
            "error": "caller_agent_id と認証済み主体が一致しないため拒否しました。",
        }
    return authenticated_agent_id, None


def require_permission(
    ctx: Any,
    tool_name: str,
    caller_agent_id: str | None,
    target_agent_id: str | None = None,
) -> tuple[AppContext, dict[str, Any] | None]:
    """AppContext 取得と権限チェックをまとめて行う。

    Returns:
        (app_ctx, error_or_none) のタプル。error が None なら許可。
    """
    app_ctx = get_app_ctx(ctx)
    effective_caller_agent_id, caller_error = resolve_effective_caller_agent_id(
        ctx=ctx,
        caller_agent_id=caller_agent_id,
    )
    if caller_error:
        return app_ctx, caller_error

    error = check_tool_permission(
        app_ctx,
        tool_name,
        effective_caller_agent_id,
        target_agent_id=target_agent_id,
    )
    return app_ctx, error


def validate_sender_caller_match(
    sender_id: str,
    caller_agent_id: str | None,
) -> dict[str, Any] | None:
    """sender_id と caller_agent_id の一致を検証する。"""
    if caller_agent_id is None:
        return {
            "success": False,
            "error_code": "MISSING_CALLER_ID",
            "error": "caller_agent_id が必要です",
        }
    if sender_id != caller_agent_id:
        return {
            "success": False,
            "error_code": "SENDER_CALLER_MISMATCH",
            "error": (
                "sender_id と caller_agent_id が一致しないため拒否しました。"
                f" sender_id={sender_id}, caller_agent_id={caller_agent_id}"
            ),
        }
    return None


# ========== Admin ポーリングガード ==========


def get_admin_poll_state(app_ctx: AppContext, admin_id: str) -> dict[str, Any]:
    """Admin ごとのポーリングガード状態を取得する。

    AppContext._admin_poll_state に状態を保持し、未初期化なら
    デフォルト dict を作成して返す。

    Args:
        app_ctx: アプリケーションコンテキスト
        admin_id: Admin エージェントID

    Returns:
        ポーリングガード状態辞書
    """
    state = app_ctx._admin_poll_state.get(admin_id)
    if not isinstance(state, dict):
        state = {
            "waiting_for_ipc": False,
            "allow_dashboard_until": None,
            "last_poll_blocked_at": None,
        }
        app_ctx._admin_poll_state[admin_id] = state
    return state


# ポーリング制御タイミング定数（ipc.py/dashboard.py の重複定義を統合）
ADMIN_DASHBOARD_GRANT_SECONDS = 90


def _owner_polling_blocked_response(waiting_admin_id: str | None) -> dict[str, Any]:
    """Owner の待機ロック中に発生するポーリング抑止レスポンスを生成する。"""
    return {
        "success": False,
        "error": (
            "polling_blocked: Owner は Admin からの通知待機中のため、"
            "unread=0 の監視呼び出しはできません"
        ),
        "next_action": "wait_for_user_input_or_unlock_owner_wait",
        "waiting_for_admin_id": waiting_admin_id,
    }


def reset_agent_to_idle(app_ctx: AppContext, agent: Any, clear_task: bool = True) -> None:
    """エージェント状態を IDLE にリセットして保存する。

    Args:
        app_ctx: アプリケーションコンテキスト
        agent: リセット対象のエージェント
        clear_task: True の場合、current_task も None にリセットする
    """
    from src.models.agent import AgentStatus

    if clear_task:
        agent.current_task = None
    agent.status = AgentStatus.IDLE
    agent.last_activity = datetime.now()
    save_agent_to_file(app_ctx, agent)
