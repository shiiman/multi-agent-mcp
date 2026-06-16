"""IPC/メッセージング管理ツール。"""

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.context import AppContext

from mcp.server.fastmcp import Context, FastMCP

from src.config.role_permissions import requires_worker_admin_receiver
from src.models.agent import AgentRole
from src.models.message import MessagePriority, MessageType
from src.tools.helpers import (
    ADMIN_DASHBOARD_GRANT_SECONDS,
    _owner_polling_blocked_response,
    clear_owner_wait_state,
    ensure_ipc_manager,
    find_agents_by_role,
    get_admin_poll_state,
    get_owner_wait_state,
    notify_agent_via_tmux,
    require_permission,
    resolve_effective_caller_agent_id,
    sync_agents_from_file,
    validate_sender_caller_match,
)
from src.tools.helpers_managers import ensure_dashboard_manager
from src.tools.quality_gate import _validate_admin_completion_gate
from src.tools.session_state import cleanup_session_resources

logger = logging.getLogger(__name__)
# polling_blocked 後にブロックを解除するまでの猶予時間（秒）
_POLLING_BLOCKED_GRACE_SECONDS = 30
# メッセージ長さ制限
_MAX_CONTENT_LENGTH = 10000
_MAX_SUBJECT_LENGTH = 200


def _mark_admin_waiting_for_ipc(app_ctx: "AppContext", admin_id: str) -> None:
    state = get_admin_poll_state(app_ctx, admin_id)
    state["waiting_for_ipc"] = True


def _mark_admin_ipc_consumed(app_ctx: "AppContext", admin_id: str) -> None:
    state = get_admin_poll_state(app_ctx, admin_id)
    state["waiting_for_ipc"] = False
    state["allow_dashboard_until"] = datetime.now() + timedelta(
        seconds=ADMIN_DASHBOARD_GRANT_SECONDS
    )


def _admin_polling_blocked_response(tool_name: str) -> dict[str, Any]:
    """Admin の空読みポーリング抑止レスポンスを生成する。"""
    return {
        "success": False,
        "error": (f"polling_blocked: unread=0 の状態で {tool_name} を連続実行できません"),
        "next_action": "wait_for_ipc_notification",
    }


def _apply_admin_empty_polling_guard(
    app_ctx: "AppContext",
    admin_id: str,
    *,
    should_guard: bool,
    tool_name: str,
) -> dict[str, Any] | None:
    """Admin の空読みポーリング抑止を適用する。"""
    if not should_guard:
        return None

    poll_state = get_admin_poll_state(app_ctx, admin_id)
    last_blocked = poll_state.get("last_poll_blocked_at")
    now = datetime.now()
    if last_blocked is None:
        # 初回の空読み: 記録だけして通す（ブロックしない）
        poll_state["last_poll_blocked_at"] = now
        return None

    if (now - last_blocked).total_seconds() >= _POLLING_BLOCKED_GRACE_SECONDS:
        # 猶予時間を超過: ブロック解除して1回だけ確認を許可
        poll_state["last_poll_blocked_at"] = None
        logger.info(
            "polling_blocked 猶予時間超過: %s のブロックを一時解除",
            admin_id,
        )
        return None

    return _admin_polling_blocked_response(tool_name)


def _validate_send_message_params(
    sender_id: str,
    caller_agent_id: str | None,
    content: str,
    message_type: str,
    subject: str,
    priority: str,
) -> dict[str, Any] | tuple[MessageType, MessagePriority]:
    """send_message のパラメータを検証する。

    Args:
        sender_id: 送信元エージェントID
        caller_agent_id: 呼び出し元エージェントID
        content: メッセージ内容
        message_type: メッセージタイプ文字列
        subject: 件名
        priority: 優先度文字列

    Returns:
        エラーの場合は error dict、成功の場合は (msg_type, msg_priority) タプル
    """
    sender_validation_error = validate_sender_caller_match(sender_id, caller_agent_id)
    if sender_validation_error:
        return sender_validation_error

    if len(content) > _MAX_CONTENT_LENGTH:
        return {
            "success": False,
            "error": (
                f"content が長すぎます（{len(content)} 文字）。"
                f"上限は {_MAX_CONTENT_LENGTH} 文字です。"
            ),
        }
    if subject and len(subject) > _MAX_SUBJECT_LENGTH:
        return {
            "success": False,
            "error": (
                f"subject が長すぎます（{len(subject)} 文字）。"
                f"上限は {_MAX_SUBJECT_LENGTH} 文字です。"
            ),
        }

    try:
        msg_type = MessageType(message_type)
    except ValueError:
        valid_types = [t.value for t in MessageType]
        return {
            "success": False,
            "error": f"無効なメッセージタイプです: {message_type}（有効: {valid_types}）",
        }

    try:
        msg_priority = MessagePriority(priority)
    except ValueError:
        valid_priorities = [p.value for p in MessagePriority]
        return {
            "success": False,
            "error": f"無効な優先度です: {priority}（有効: {valid_priorities}）",
        }

    return (msg_type, msg_priority)


def _resolve_send_message_receiver(
    app_ctx: "AppContext",
    sender_id: str,
    receiver_id: str | None,
    msg_type: MessageType,
    ipc: Any,
) -> dict[str, Any] | tuple[str | None, str | None]:
    """send_message の受信者を解決する。

    Worker のブロードキャスト禁止、不正な receiver_id の補正、
    Worker→Admin 制約の検証、IPC 登録を行う。

    Args:
        app_ctx: アプリケーションコンテキスト
        sender_id: 送信元エージェントID
        receiver_id: 宛先エージェントID（None でブロードキャスト）
        msg_type: 検証済みメッセージタイプ
        ipc: IPCManager インスタンス

    Returns:
        エラーの場合は error dict、成功の場合は (resolved_receiver_id, rerouted_receiver_id) タプル
    """
    sender_agent = app_ctx.agents.get(sender_id)
    sender_role = str(getattr(sender_agent, "role", ""))
    rerouted_receiver_id: str | None = None

    # Worker ブロードキャスト禁止
    if (
        sender_role == AgentRole.WORKER.value
        and requires_worker_admin_receiver("send_message")
        and receiver_id is None
    ):
        return {
            "success": False,
            "error": (
                "Worker は send_message をブロードキャストできません。"
                "Admin の agent_id を receiver_id に指定してください。"
            ),
        }

    if receiver_id:
        sync_agents_from_file(app_ctx)
        receiver_agent = app_ctx.agents.get(receiver_id)
        if not receiver_agent:
            is_worker_request = (
                msg_type == MessageType.REQUEST and sender_role == AgentRole.WORKER.value
            )
            if is_worker_request:
                admin_ids = find_agents_by_role(app_ctx, "admin")
                if len(admin_ids) == 1 and admin_ids[0] in app_ctx.agents:
                    original = receiver_id
                    receiver_id = admin_ids[0]
                    rerouted_receiver_id = receiver_id
                    logger.warning(
                        "Worker request の受信者IDを Admin に補正: sender=%s receiver=%s -> %s",
                        sender_id,
                        original,
                        receiver_id,
                    )
                else:
                    return {
                        "success": False,
                        "error": (
                            "不正な receiver_id です（有効な Admin が一意に解決できません）"
                        ),
                    }
            else:
                return {
                    "success": False,
                    "error": f"受信者 {receiver_id} が見つかりません",
                }

        if sender_role == AgentRole.WORKER.value:
            receiver_agent = app_ctx.agents.get(receiver_id)
            if str(getattr(receiver_agent, "role", "")) != AgentRole.ADMIN.value:
                return {
                    "success": False,
                    "error": (
                        "Worker は Admin にのみ send_message を送信できます。"
                        f" receiver_id={receiver_id}"
                    ),
                }

        if receiver_id not in ipc.get_all_agent_ids():
            ipc.register_agent(receiver_id)

    return (receiver_id, rerouted_receiver_id)


async def _deliver_notification(
    app_ctx: "AppContext",
    sender_id: str,
    receiver_id: str | None,
    msg_type: MessageType,
) -> tuple[bool, str | None]:
    """tmux/macOS 通知を配信し、結果を返す。

    Args:
        app_ctx: アプリケーションコンテキスト
        sender_id: 送信元エージェントID
        receiver_id: 宛先エージェントID（None でブロードキャスト）
        msg_type: メッセージタイプ

    Returns:
        (notification_sent, notification_method) タプル
    """
    if not receiver_id:
        return False, None

    sync_agents_from_file(app_ctx)
    receiver_agent = app_ctx.agents.get(receiver_id)
    sender_agent = app_ctx.agents.get(sender_id)

    # macOS通知は admin→owner の task_complete のみ（フォールバック禁止）
    is_admin_task_complete_to_owner = (
        sender_agent
        and receiver_agent
        and str(getattr(sender_agent, "role", "")) == AgentRole.ADMIN.value
        and str(getattr(receiver_agent, "role", "")) == AgentRole.OWNER.value
        and msg_type == MessageType.TASK_COMPLETE
    )

    if not receiver_agent:
        return False, None

    has_tmux_pane = receiver_agent.session_name and receiver_agent.pane_index is not None
    if has_tmux_pane:
        tmux_ok = await notify_agent_via_tmux(
            app_ctx,
            receiver_agent,
            msg_type.value,
            sender_id,
            allow_macos_fallback=False,
        )
        if tmux_ok:
            return True, "tmux"
        # 仕様: macOS通知は admin→owner の task_complete のみに限定。
        # tmux失敗時のフォールバックは行わない
    elif is_admin_task_complete_to_owner:
        from src.tools.helpers import _send_macos_notification

        macos_ok = await _send_macos_notification(msg_type.value, sender_id)
        if macos_ok:
            logger.info("IPC通知を送信(macOS): %s", receiver_id)
            return True, "macos"

    return False, None


async def _handle_post_send_actions(
    app_ctx: "AppContext",
    msg_type: MessageType,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """送信後の後処理（TASK_APPROVED 時の自動クリーンアップ等）を実行する。

    Args:
        app_ctx: アプリケーションコンテキスト
        msg_type: メッセージタイプ

    Returns:
        (auto_cleanup_executed, auto_cleanup_result, auto_cleanup_error) タプル
    """
    if msg_type != MessageType.TASK_APPROVED:
        return False, None, None

    try:
        result = await cleanup_session_resources(
            app_ctx,
            remove_worktrees=True,
            repo_path=app_ctx.project_root,
        )
        return True, result, None
    except (OSError, RuntimeError) as e:
        logger.warning("task_approved 後の自動クリーンアップに失敗: %s", e)
        return True, None, str(e)


def register_tools(mcp: FastMCP) -> None:
    """IPC/メッセージング管理ツールを登録する。"""

    @mcp.tool()
    async def send_message(
        sender_id: str,
        receiver_id: str | None,
        message_type: str,
        content: str,
        subject: str = "",
        priority: str = "normal",
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェント間でメッセージを送信する。

        Args:
            sender_id: 送信元エージェントID
            receiver_id: 宛先エージェントID（Noneでブロードキャスト）
            message_type: メッセージタイプ（task_assign, task_complete, etc.）
            content: メッセージ内容
            subject: 件名（オプション）
            priority: 優先度（low/normal/high/urgent）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            送信結果（success, message_id, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "send_message", caller_agent_id)
        if role_error:
            return role_error

        # パラメータ検証
        params_result = _validate_send_message_params(
            sender_id, caller_agent_id, content, message_type, subject, priority,
        )
        if isinstance(params_result, dict):
            return params_result
        msg_type, msg_priority = params_result

        ipc = ensure_ipc_manager(app_ctx)
        sync_agents_from_file(app_ctx)

        # 送信者がIPCに登録されているか確認
        if sender_id not in ipc.get_all_agent_ids():
            ipc.register_agent(sender_id)

        # 受信者解決
        original_receiver_id = receiver_id
        receiver_result = _resolve_send_message_receiver(
            app_ctx, sender_id, receiver_id, msg_type, ipc,
        )
        if isinstance(receiver_result, dict):
            return receiver_result
        receiver_id, rerouted_receiver_id = receiver_result

        gate_ok, gate_detail = _validate_admin_completion_gate(
            app_ctx, sender_id, receiver_id, msg_type
        )
        if not gate_ok:
            return {
                "success": False,
                "error": "品質ゲート未達のため Owner への完了通知を保留しました",
                "next_action": "replan_and_reassign",
                "gate": gate_detail,
            }

        message = ipc.send_message(
            sender_id=sender_id,
            receiver_id=receiver_id,
            message_type=msg_type,
            content=content,
            subject=subject,
            priority=msg_priority,
        )

        # イベント駆動通知: 受信者の状態に応じて通知方法を選択
        notification_sent, notification_method = await _deliver_notification(
            app_ctx, sender_id, receiver_id, msg_type,
        )

        # 送信後の後処理（TASK_APPROVED 時の自動クリーンアップ等）
        auto_cleanup_executed, auto_cleanup_result, auto_cleanup_error = (
            await _handle_post_send_actions(app_ctx, msg_type)
        )

        delivery_state = (
            "broadcast"
            if receiver_id is None
            else ("delivered" if notification_sent else "queued_unnotified")
        )
        if receiver_id and not notification_sent:
            logger.warning(
                "IPC メッセージは保存されましたが通知に失敗: sender=%s receiver=%s type=%s",
                sender_id,
                receiver_id,
                msg_type.value,
            )

        success = delivery_state in {"broadcast", "delivered"}
        response_message = (
            "ブロードキャストを送信しました"
            if receiver_id is None
            else f"メッセージを {receiver_id} に送信しました"
        )
        if receiver_id and not notification_sent:
            response_message = f"メッセージを {receiver_id} に保存しましたが通知に失敗しました"

        return {
            "success": success,
            "message_id": message.id,
            "delivery_state": delivery_state,
            "message_saved": True,
            "notification_sent": notification_sent,
            "notification_method": notification_method,  # "tmux" or "macos" or None
            "original_receiver_id": original_receiver_id,
            "receiver_id": receiver_id,
            "rerouted_receiver_id": rerouted_receiver_id,
            "gate": gate_detail if gate_detail else None,
            "auto_cleanup_executed": auto_cleanup_executed,
            "auto_cleanup_result": auto_cleanup_result,
            "auto_cleanup_error": auto_cleanup_error,
            "message": response_message,
            "error": (
                "delivery_failed: メッセージ保存後の通知送信に失敗しました"
                if receiver_id and not notification_sent
                else None
            ),
        }

    @mcp.tool()
    async def read_messages(
        agent_id: str,
        unread_only: bool = False,
        message_type: str | None = None,
        mark_as_read: bool = True,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェントのメッセージを読み取る。

        Args:
            agent_id: エージェントID
            unread_only: 未読のみ取得するか
            message_type: フィルターするメッセージタイプ
            mark_as_read: 既読としてマークするか
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            メッセージ一覧（success, messages, count または error）
        """
        app_ctx, role_error = require_permission(
            ctx,
            "read_messages",
            caller_agent_id,
            target_agent_id=agent_id,
        )
        if role_error:
            return role_error

        ipc = ensure_ipc_manager(app_ctx)

        # メッセージタイプの検証
        msg_type = None
        if message_type:
            try:
                msg_type = MessageType(message_type)
            except ValueError:
                valid_types = [t.value for t in MessageType]
                return {
                    "success": False,
                    "error": (f"無効なメッセージタイプです: {message_type}（有効: {valid_types}）"),
                }

        # エージェントが登録されていなければ登録
        if agent_id not in ipc.get_all_agent_ids():
            ipc.register_agent(agent_id)

        effective_caller_agent_id, caller_error = resolve_effective_caller_agent_id(
            ctx=ctx,
            caller_agent_id=caller_agent_id,
        )
        if caller_error:
            return caller_error

        sync_agents_from_file(app_ctx)
        caller = app_ctx.agents.get(effective_caller_agent_id)
        caller_role = getattr(caller, "role", None)
        is_admin_caller = caller_role in (AgentRole.ADMIN.value, "admin")
        is_owner_caller = caller_role in (AgentRole.OWNER.value, "owner")

        owner_wait_state: dict[str, Any] | None = None
        if is_owner_caller and effective_caller_agent_id:
            owner_wait_state = get_owner_wait_state(app_ctx, effective_caller_agent_id)
            if owner_wait_state.get("waiting_for_admin"):
                # Owner 待機中は自身 inbox の通知待機のみ許可する。
                if agent_id != effective_caller_agent_id:
                    return _owner_polling_blocked_response(owner_wait_state.get("admin_id"))
                if ipc.get_unread_count(effective_caller_agent_id) == 0:
                    return _owner_polling_blocked_response(owner_wait_state.get("admin_id"))

        # Admin の場合: unread=0 連続ポーリング抑止を読み取り前に判定
        dashboard_updated = False
        dashboard_updates_applied = 0
        dashboard_updates_skipped_reason: list[str] = []
        acked_task_message_ids: set[str] = set()
        deferred_task_message_ids: set[str] = set()
        if is_admin_caller:
            unread_count_before = ipc.get_unread_count(agent_id)
            guard_error = _apply_admin_empty_polling_guard(
                app_ctx,
                effective_caller_agent_id or agent_id,
                should_guard=bool(unread_only and unread_count_before == 0),
                tool_name="read_messages",
            )
            if guard_error:
                return guard_error

        # 既読化は後段で制御するため、ここでは副作用なしで読み取る
        messages = ipc.read_messages(
            agent_id=agent_id,
            unread_only=unread_only,
            message_type=msg_type,
            mark_as_read=False,
        )

        owner_wait_unlocked = False
        if is_owner_caller and effective_caller_agent_id and owner_wait_state:
            waiting_for_admin = bool(owner_wait_state.get("waiting_for_admin"))
            expected_admin_id = owner_wait_state.get("admin_id")
            has_admin_notification = any(
                (
                    (msg.sender_id == expected_admin_id)
                    if expected_admin_id
                    else (
                        getattr(app_ctx.agents.get(msg.sender_id), "role", None)
                        in (AgentRole.ADMIN.value, "admin")
                    )
                )
                for msg in messages
            )
            if waiting_for_admin and has_admin_notification:
                clear_owner_wait_state(
                    app_ctx,
                    effective_caller_agent_id,
                    reason="admin_notification_consumed",
                )
                owner_wait_unlocked = True

        if is_admin_caller:
            try:
                dashboard = ensure_dashboard_manager(app_ctx)
                (
                    dashboard_updated,
                    dashboard_updates_applied,
                    dashboard_updates_skipped_reason,
                    acked_task_ids,
                    deferred_task_ids,
                ) = dashboard.apply_task_messages(app_ctx, messages)
                acked_task_message_ids = set(acked_task_ids)
                deferred_task_message_ids = set(deferred_task_ids)
            except (RuntimeError, AttributeError, OSError) as e:
                logger.debug("Dashboard 自動更新をスキップ: %s", e)
                dashboard_updated = False
                dashboard_updates_applied = 0
                dashboard_updates_skipped_reason = ["dashboard_manager_unavailable"]
                deferred_task_message_ids = {
                    msg.id
                    for msg in messages
                    if msg.message_type
                    in (
                        MessageType.TASK_PROGRESS,
                        MessageType.TASK_COMPLETE,
                        MessageType.TASK_FAILED,
                    )
                }

            if messages:
                _mark_admin_ipc_consumed(app_ctx, effective_caller_agent_id or agent_id)
            else:
                _mark_admin_waiting_for_ipc(app_ctx, effective_caller_agent_id or agent_id)

        if mark_as_read and messages:
            task_message_types = {
                MessageType.TASK_PROGRESS,
                MessageType.TASK_COMPLETE,
                MessageType.TASK_FAILED,
            }
            mark_ids: list[str] = []
            for msg in messages:
                if msg.is_read:
                    continue
                if (
                    is_admin_caller
                    and msg.message_type in task_message_types
                    and msg.id in deferred_task_message_ids
                ):
                    continue
                if (
                    is_admin_caller
                    and msg.message_type in task_message_types
                    and msg.id not in acked_task_message_ids
                ):
                    continue
                mark_ids.append(msg.id)

            marked_at = ipc.mark_messages_as_read(agent_id, mark_ids)
            if marked_at is not None:
                marked_set = set(mark_ids)
                for msg in messages:
                    if msg.id in marked_set and not msg.is_read:
                        msg.read_at = marked_at

        return {
            "success": True,
            "messages": [m.model_dump(mode="json") for m in messages],
            "count": len(messages),
            "dashboard_updated": dashboard_updated,
            "dashboard_updates_applied": dashboard_updates_applied,
            "dashboard_updates_skipped_reason": dashboard_updates_skipped_reason,
            "owner_wait_unlocked": owner_wait_unlocked,
        }

    @mcp.tool()
    async def get_unread_count(
        agent_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェントの未読メッセージ数を取得する。

        Args:
            agent_id: エージェントID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            未読数（success, agent_id, unread_count）
        """
        app_ctx, role_error = require_permission(
            ctx,
            "get_unread_count",
            caller_agent_id,
            target_agent_id=agent_id,
        )
        if role_error:
            return role_error

        ipc = ensure_ipc_manager(app_ctx)

        if agent_id not in ipc.get_all_agent_ids():
            ipc.register_agent(agent_id)

        effective_caller_agent_id, caller_error = resolve_effective_caller_agent_id(
            ctx=ctx,
            caller_agent_id=caller_agent_id,
        )
        if caller_error:
            return caller_error

        count = ipc.get_unread_count(agent_id)
        sync_agents_from_file(app_ctx)
        caller = app_ctx.agents.get(effective_caller_agent_id)
        caller_role = getattr(caller, "role", None)
        is_admin_caller = caller_role in (AgentRole.ADMIN.value, "admin")
        is_owner_caller = caller_role in (AgentRole.OWNER.value, "owner")
        if is_owner_caller and effective_caller_agent_id:
            owner_wait_state = get_owner_wait_state(app_ctx, effective_caller_agent_id)
            if owner_wait_state.get("waiting_for_admin"):
                # Owner 待機中は自身 inbox の通知待機のみ許可する。
                if agent_id != effective_caller_agent_id:
                    return _owner_polling_blocked_response(owner_wait_state.get("admin_id"))
                if count == 0:
                    return _owner_polling_blocked_response(owner_wait_state.get("admin_id"))

        if is_admin_caller:
            guard_error = _apply_admin_empty_polling_guard(
                app_ctx,
                effective_caller_agent_id or agent_id,
                should_guard=(count == 0),
                tool_name="get_unread_count",
            )
            if guard_error:
                return guard_error
            if count > 0:
                _mark_admin_ipc_consumed(app_ctx, effective_caller_agent_id or agent_id)
            else:
                _mark_admin_waiting_for_ipc(app_ctx, effective_caller_agent_id or agent_id)

        return {
            "success": True,
            "agent_id": agent_id,
            "unread_count": count,
        }

    @mcp.tool()
    async def unlock_owner_wait(
        reason: str = "manual_unlock",
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """Owner の待機ロックを手動解除する。

        Args:
            reason: 解除理由
            caller_agent_id: 呼び出し元エージェントID（必須）
            ctx: MCP Context

        Returns:
            解除結果
        """
        app_ctx, role_error = require_permission(ctx, "unlock_owner_wait", caller_agent_id)
        if role_error:
            return role_error

        if not caller_agent_id:
            return {
                "success": False,
                "error": "caller_agent_id が必要です",
            }

        state = get_owner_wait_state(app_ctx, caller_agent_id)
        waiting_before = bool(state.get("waiting_for_admin"))
        clear_owner_wait_state(app_ctx, caller_agent_id, reason=reason or "manual_unlock")

        return {
            "success": True,
            "owner_id": caller_agent_id,
            "waiting_before": waiting_before,
            "waiting_after": False,
            "unlock_reason": reason or "manual_unlock",
            "message": "Owner 待機ロックを解除しました",
        }

    @mcp.tool()
    async def register_agent_to_ipc(
        agent_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェントをIPCシステムに登録する。

        Args:
            agent_id: エージェントID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            登録結果（success, agent_id, message）
        """
        app_ctx, role_error = require_permission(ctx, "register_agent_to_ipc", caller_agent_id)
        if role_error:
            return role_error

        ipc = ensure_ipc_manager(app_ctx)

        ipc.register_agent(agent_id)

        return {
            "success": True,
            "agent_id": agent_id,
            "message": f"エージェント {agent_id} をIPCに登録しました",
        }
