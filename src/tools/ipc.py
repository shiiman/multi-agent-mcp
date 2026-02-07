"""IPC/メッセージング管理ツール。"""

import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.managers.tmux_shared import escape_applescript
from src.models.agent import AgentRole, AgentStatus
from src.models.dashboard import TaskStatus, normalize_task_id
from src.models.message import Message, MessagePriority, MessageType
from src.tools.helpers import (
    ensure_ipc_manager,
    find_agents_by_role,
    notify_agent_via_tmux,
    require_permission,
    save_agent_to_file,
    sync_agents_from_file,
)
from src.tools.helpers_managers import ensure_dashboard_manager

logger = logging.getLogger(__name__)
_ADMIN_DASHBOARD_GRANT_SECONDS = 90


def _get_admin_poll_state(app_ctx: Any, admin_id: str) -> dict[str, Any]:
    """Admin ごとのポーリングガード状態を取得する。"""
    state_map = getattr(app_ctx, "_admin_poll_state", None)
    if not isinstance(state_map, dict):
        state_map = {}
        app_ctx._admin_poll_state = state_map
    state = state_map.get(admin_id)
    if not isinstance(state, dict):
        state = {
            "waiting_for_ipc": False,
            "allow_dashboard_until": None,
        }
        state_map[admin_id] = state
    return state


def _mark_admin_waiting_for_ipc(app_ctx: Any, admin_id: str) -> None:
    state = _get_admin_poll_state(app_ctx, admin_id)
    state["waiting_for_ipc"] = True


def _mark_admin_ipc_consumed(app_ctx: Any, admin_id: str) -> None:
    state = _get_admin_poll_state(app_ctx, admin_id)
    state["waiting_for_ipc"] = False
    state["allow_dashboard_until"] = datetime.now() + timedelta(
        seconds=_ADMIN_DASHBOARD_GRANT_SECONDS
    )


def _auto_update_dashboard_from_messages(
    app_ctx: Any, messages: list[Message]
) -> tuple[bool, int, list[str]]:
    """Admin の read_messages 時に、タスク関連メッセージから Dashboard を自動更新する。"""
    task_messages = [
        m
        for m in messages
        if m.message_type
        in (
            MessageType.TASK_PROGRESS,
            MessageType.TASK_COMPLETE,
            MessageType.TASK_FAILED,
        )
    ]
    if not task_messages:
        return False, 0, []

    try:
        dashboard = ensure_dashboard_manager(app_ctx)
    except Exception as e:
        logger.debug(f"Dashboard 自動更新をスキップ: {e}")
        return False, 0, ["dashboard_manager_unavailable"]

    task_map: dict[str, str] = {}
    for task in dashboard.list_tasks():
        normalized = normalize_task_id(task.id)
        if normalized:
            task_map[normalized] = task.id

    applied = 0
    skipped_reasons: list[str] = []

    for msg in task_messages:
        raw_task_id = msg.metadata.get("task_id")
        normalized_task_id = msg.metadata.get("normalized_task_id") or normalize_task_id(
            raw_task_id
        )
        if not normalized_task_id:
            skipped_reasons.append("missing_task_id")
            continue
        task_id = task_map.get(normalized_task_id)
        if not task_id:
            skipped_reasons.append(f"task_not_found:{normalized_task_id}")
            continue

        try:
            if msg.message_type == MessageType.TASK_PROGRESS:
                progress = msg.metadata.get("progress", 0)
                checklist = msg.metadata.get("checklist")
                message_text = msg.metadata.get("message")
                reporter = msg.metadata.get("reporter")
                if checklist:
                    dashboard.update_task_checklist(
                        task_id, checklist, log_message=message_text
                    )
                dashboard.update_task_status(task_id, TaskStatus.IN_PROGRESS, progress)
                if reporter and reporter in app_ctx.agents:
                    agent = app_ctx.agents[reporter]
                    agent.current_task = task_id
                    if str(agent.role) == AgentRole.WORKER.value:
                        agent.status = AgentStatus.BUSY
                    save_agent_to_file(app_ctx, agent)
                applied += 1

            elif msg.message_type == MessageType.TASK_COMPLETE:
                reporter = msg.metadata.get("reporter")
                task = dashboard.get_task(task_id)
                if task and task.status == TaskStatus.COMPLETED:
                    skipped_reasons.append(f"already_completed:{task_id}")
                    continue
                dashboard.update_task_status(
                    task_id, TaskStatus.COMPLETED, progress=100
                )
                if reporter and reporter in app_ctx.agents:
                    agent = app_ctx.agents[reporter]
                    if agent.current_task == task_id:
                        agent.current_task = None
                    if str(agent.role) == AgentRole.WORKER.value:
                        agent.status = AgentStatus.IDLE
                    save_agent_to_file(app_ctx, agent)
                applied += 1

            elif msg.message_type == MessageType.TASK_FAILED:
                reporter = msg.metadata.get("reporter")
                task = dashboard.get_task(task_id)
                if task and task.status == TaskStatus.FAILED:
                    skipped_reasons.append(f"already_failed:{task_id}")
                    continue
                dashboard.update_task_status(task_id, TaskStatus.FAILED)
                if reporter and reporter in app_ctx.agents:
                    agent = app_ctx.agents[reporter]
                    if agent.current_task == task_id:
                        agent.current_task = None
                    if str(agent.role) == AgentRole.WORKER.value:
                        agent.status = AgentStatus.IDLE
                    save_agent_to_file(app_ctx, agent)
                applied += 1
        except Exception as e:
            logger.debug(f"タスク {task_id} の Dashboard 更新をスキップ: {e}")
            skipped_reasons.append(f"update_error:{task_id}")

    # Markdown ダッシュボードも更新
    try:
        if app_ctx.session_id and app_ctx.project_root:
            dashboard.save_markdown_dashboard(
                Path(app_ctx.project_root), app_ctx.session_id
            )
    except Exception as e:
        logger.debug(f"Markdown ダッシュボード更新をスキップ: {e}")

    return True, applied, skipped_reasons


def _task_context_text(title: str, description: str, metadata: dict | None = None) -> str:
    requested = ""
    if isinstance(metadata, dict):
        requested = str(metadata.get("requested_description", "") or "")
    return f"{title} {requested} {description}".lower()


def _is_quality_task(title: str, description: str, metadata: dict | None = None) -> bool:
    text = _task_context_text(title, description, metadata)
    keywords = ("qa", "quality", "test", "e2e", "検証", "テスト", "品質", "playwright")
    return any(keyword in text for keyword in keywords)


def _is_playwright_task(title: str, description: str, metadata: dict | None = None) -> bool:
    text = _task_context_text(title, description, metadata)
    return "playwright" in text


def _is_ui_related_task(title: str, description: str, metadata: dict | None = None) -> bool:
    text = _task_context_text(title, description, metadata)
    keywords = ("ui", "frontend", "画面", "表示", "フロント", "browser", "e2e")
    return any(keyword in text for keyword in keywords)


def _check_branch_merge_state(project_root: str, branches: list[str]) -> list[str]:
    """現在ブランチに未マージのブランチ一覧を返す。"""
    try:
        current_branch = subprocess.check_output(
            ["git", "-C", project_root, "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception as e:
        logger.debug("ブランチマージ状態の確認に失敗: %s", e)
        return []

    unmerged: list[str] = []
    for branch in sorted(set(branches)):
        if not branch or branch == current_branch:
            continue
        try:
            exists = subprocess.run(
                ["git", "-C", project_root, "rev-parse", "--verify", branch],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if exists.returncode != 0:
                continue
            merged = subprocess.run(
                ["git", "-C", project_root, "merge-base", "--is-ancestor", branch, "HEAD"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if merged.returncode != 0:
                unmerged.append(branch)
        except Exception as e:
            logger.debug("ブランチ %s のマージ判定に失敗: %s", branch, e)
            continue
    return unmerged


def _validate_admin_completion_gate(
    app_ctx: Any, sender_id: str, receiver_id: str | None, msg_type: MessageType
) -> tuple[bool, dict[str, Any]]:
    """Admin -> Owner の task_complete を品質ゲートで検証する。"""
    if msg_type != MessageType.TASK_COMPLETE or not receiver_id:
        return True, {}

    sender = app_ctx.agents.get(sender_id)
    receiver = app_ctx.agents.get(receiver_id)
    if not sender or not receiver:
        return True, {}
    if sender.role != AgentRole.ADMIN.value or receiver.role != AgentRole.OWNER.value:
        return True, {}

    dashboard = ensure_dashboard_manager(app_ctx)
    tasks = dashboard.list_tasks()
    summary = dashboard.get_summary()
    settings = app_ctx.settings

    reasons: list[str] = []
    suggestions: list[str] = []

    if (
        summary["pending_tasks"] > 0
        or summary["in_progress_tasks"] > 0
        or summary["failed_tasks"] > 0
    ):
        reasons.append(
            "未完了タスクがあります"
            " "
            f"(pending={summary['pending_tasks']}, "
            f"in_progress={summary['in_progress_tasks']}, "
            f"failed={summary['failed_tasks']})"
        )
        suggestions.append("未完了/失敗タスクを再計画し、Worker に再割り当てしてください。")

    completed_tasks = [t for t in tasks if t.status == TaskStatus.COMPLETED]
    quality_tasks = [
        t
        for t in completed_tasks
        if _is_quality_task(t.title, t.description, getattr(t, "metadata", None))
    ]
    if not quality_tasks:
        reasons.append("品質証跡タスク（test/QA/検証）が完了していません")
        suggestions.append("品質チェック専用タスクを作成し、証跡を揃えてください。")

    ui_required = any(
        _is_ui_related_task(t.title, t.description, getattr(t, "metadata", None))
        for t in tasks
    )
    playwright_done = any(
        _is_playwright_task(t.title, t.description, getattr(t, "metadata", None))
        for t in quality_tasks
    )
    if ui_required and not playwright_done:
        reasons.append("UI関連タスクに対する Playwright 証跡が不足しています")
        suggestions.append("Playwright 実行タスクを追加し、完了報告を取り込んでください。")

    branches = [t.branch for t in completed_tasks if t.branch]
    if app_ctx.project_root and branches:
        unmerged = _check_branch_merge_state(str(app_ctx.project_root), branches)
        if unmerged:
            reasons.append(f"未マージの完了タスクブランチがあります: {', '.join(unmerged[:5])}")
            suggestions.append("未マージブランチを統合後に再度完了通知を送ってください。")

    if reasons:
        return False, {
            "status": "needs_replan",
            "reasons": reasons,
            "suggestions": suggestions,
            "quality_limits": {
                "max_iterations": settings.quality_check_max_iterations,
                "same_issue_limit": settings.quality_check_same_issue_limit,
            },
        }

    return True, {"status": "passed"}


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

        ipc = ensure_ipc_manager(app_ctx)
        sync_agents_from_file(app_ctx)

        # メッセージタイプの検証
        try:
            msg_type = MessageType(message_type)
        except ValueError:
            valid_types = [t.value for t in MessageType]
            return {
                "success": False,
                "error": f"無効なメッセージタイプです: {message_type}（有効: {valid_types}）",
            }

        # 優先度の検証
        try:
            msg_priority = MessagePriority(priority)
        except ValueError:
            valid_priorities = [p.value for p in MessagePriority]
            return {
                "success": False,
                "error": f"無効な優先度です: {priority}（有効: {valid_priorities}）",
            }

        # 送信者がIPCに登録されているか確認
        if sender_id not in ipc.get_all_agent_ids():
            ipc.register_agent(sender_id)

        original_receiver_id = receiver_id
        rerouted_receiver_id: str | None = None
        if receiver_id:
            sync_agents_from_file(app_ctx)
            receiver_agent = app_ctx.agents.get(receiver_id)
            if not receiver_agent:
                sender_agent = app_ctx.agents.get(sender_id)
                sender_role = str(getattr(sender_agent, "role", ""))
                is_worker_request = (
                    msg_type == MessageType.REQUEST
                    and sender_role == AgentRole.WORKER.value
                )
                if is_worker_request:
                    admin_ids = find_agents_by_role(app_ctx, "admin")
                    if len(admin_ids) == 1 and admin_ids[0] in app_ctx.agents:
                        receiver_id = admin_ids[0]
                        rerouted_receiver_id = receiver_id
                        logger.warning(
                            "Worker request の受信者IDを Admin に補正: sender=%s receiver=%s -> %s",
                            sender_id,
                            original_receiver_id,
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

            if receiver_id not in ipc.get_all_agent_ids():
                ipc.register_agent(receiver_id)

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
        notification_sent = False
        notification_method = None
        if receiver_id:
            sync_agents_from_file(app_ctx)
            receiver_agent = app_ctx.agents.get(receiver_id)
            if receiver_agent:
                # tmux ペインがある場合は tmux 経由で通知
                tmux_ok = await notify_agent_via_tmux(
                    app_ctx, receiver_agent, msg_type.value, sender_id
                )
                if tmux_ok:
                    notification_sent = True
                    notification_method = "tmux"
                elif not (
                    receiver_agent.session_name
                    and receiver_agent.pane_index is not None
                ):
                    # tmux ペインがない場合（Owner など）は macOS 通知を送る
                    try:
                        notification_title = "Multi-Agent MCP"
                        notification_body = escape_applescript(
                            f"{msg_type.value}: {content[:100]}"
                        )
                        escaped_title = escape_applescript(notification_title)
                        subprocess.run(
                            [
                                "osascript",
                                "-e",
                                "display notification"
                                f' "{notification_body}"'
                                f' with title "{escaped_title}"',
                            ],
                            capture_output=True,
                            timeout=5,
                        )
                        notification_sent = True
                        notification_method = "macos"
                        logger.info(
                            f"IPC通知を送信(macOS): {receiver_id}"
                        )
                    except Exception as e:
                        logger.warning(f"macOS通知の送信に失敗: {e}")

        return {
            "success": True,
            "message_id": message.id,
            "notification_sent": notification_sent,
            "notification_method": notification_method,  # "tmux" or "macos" or None
            "original_receiver_id": original_receiver_id,
            "receiver_id": receiver_id,
            "rerouted_receiver_id": rerouted_receiver_id,
            "gate": gate_detail if gate_detail else None,
            "message": (
                "ブロードキャストを送信しました"
                if receiver_id is None
                else f"メッセージを {receiver_id} に送信しました"
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
        app_ctx, role_error = require_permission(ctx, "read_messages", caller_agent_id)
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
                    "error": (
                        f"無効なメッセージタイプです: {message_type}"
                        f"（有効: {valid_types}）"
                    ),
                }

        # エージェントが登録されていなければ登録
        if agent_id not in ipc.get_all_agent_ids():
            ipc.register_agent(agent_id)

        messages = ipc.read_messages(
            agent_id=agent_id,
            unread_only=unread_only,
            message_type=msg_type,
            mark_as_read=mark_as_read,
        )

        # Admin の場合: タスク関連メッセージから Dashboard を自動更新
        dashboard_updated = False
        dashboard_updates_applied = 0
        dashboard_updates_skipped_reason: list[str] = []
        sync_agents_from_file(app_ctx)
        caller = app_ctx.agents.get(caller_agent_id)
        caller_role = getattr(caller, "role", None)
        is_admin_caller = caller_role in (AgentRole.ADMIN.value, "admin")
        if is_admin_caller:
            unread_count = ipc.get_unread_count(agent_id)
            if unread_only and unread_count == 0:
                return {
                    "success": False,
                    "error": (
                        "polling_blocked: unread=0 の状態で read_messages を連続実行できません"
                    ),
                    "next_action": "wait_for_ipc_notification",
                }

        if is_admin_caller:
            (
                dashboard_updated,
                dashboard_updates_applied,
                dashboard_updates_skipped_reason,
            ) = _auto_update_dashboard_from_messages(
                app_ctx, messages
            )
            if messages:
                _mark_admin_ipc_consumed(app_ctx, caller_agent_id or agent_id)
            else:
                _mark_admin_waiting_for_ipc(app_ctx, caller_agent_id or agent_id)

        return {
            "success": True,
            "messages": [m.model_dump(mode="json") for m in messages],
            "count": len(messages),
            "dashboard_updated": dashboard_updated,
            "dashboard_updates_applied": dashboard_updates_applied,
            "dashboard_updates_skipped_reason": dashboard_updates_skipped_reason,
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
        app_ctx, role_error = require_permission(ctx, "get_unread_count", caller_agent_id)
        if role_error:
            return role_error

        ipc = ensure_ipc_manager(app_ctx)

        if agent_id not in ipc.get_all_agent_ids():
            ipc.register_agent(agent_id)

        count = ipc.get_unread_count(agent_id)

        return {
            "success": True,
            "agent_id": agent_id,
            "unread_count": count,
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
