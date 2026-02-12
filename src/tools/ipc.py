"""IPC/メッセージング管理ツール。"""

import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.context import AppContext

from mcp.server.fastmcp import Context, FastMCP

from src.config.role_permissions import requires_worker_admin_receiver
from src.models.agent import AgentRole, AgentStatus
from src.models.dashboard import TaskStatus, normalize_task_id
from src.models.message import Message, MessagePriority, MessageType
from src.tools.helpers import (
    clear_owner_wait_state,
    ensure_ipc_manager,
    find_agents_by_role,
    get_admin_poll_state,
    get_owner_wait_state,
    notify_agent_via_tmux,
    require_permission,
    save_agent_to_file,
    sync_agents_from_file,
    validate_sender_caller_match,
)
from src.tools.helpers_managers import ensure_dashboard_manager
from src.tools.session_state import cleanup_session_resources

logger = logging.getLogger(__name__)
_ADMIN_DASHBOARD_GRANT_SECONDS = 90
# polling_blocked 後にブロックを解除するまでの猶予時間（秒）
_POLLING_BLOCKED_GRACE_SECONDS = 30


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


def _mark_admin_waiting_for_ipc(app_ctx: "AppContext", admin_id: str) -> None:
    state = get_admin_poll_state(app_ctx, admin_id)
    state["waiting_for_ipc"] = True


def _mark_admin_ipc_consumed(app_ctx: "AppContext", admin_id: str) -> None:
    state = get_admin_poll_state(app_ctx, admin_id)
    state["waiting_for_ipc"] = False
    state["allow_dashboard_until"] = datetime.now() + timedelta(
        seconds=_ADMIN_DASHBOARD_GRANT_SECONDS
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


def _auto_update_dashboard_from_messages(
    app_ctx: "AppContext", messages: list[Message]
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
                status_ok, status_msg = dashboard.update_task_status(
                    task_id, TaskStatus.IN_PROGRESS, progress
                )
                if not status_ok:
                    skipped_reasons.append(f"status_update_rejected:{task_id}:{status_msg}")
                    continue

                if checklist:
                    checklist_ok, checklist_msg = dashboard.update_task_checklist(
                        task_id, checklist, log_message=message_text
                    )
                    if not checklist_ok:
                        skipped_reasons.append(f"checklist_update_error:{task_id}:{checklist_msg}")

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
                status_ok, status_msg = dashboard.update_task_status(
                    task_id, TaskStatus.COMPLETED, progress=100
                )
                if not status_ok:
                    skipped_reasons.append(f"status_update_rejected:{task_id}:{status_msg}")
                    continue

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
                status_ok, status_msg = dashboard.update_task_status(task_id, TaskStatus.FAILED)
                if not status_ok:
                    skipped_reasons.append(f"status_update_rejected:{task_id}:{status_msg}")
                    continue

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
            dashboard.save_markdown_dashboard(Path(app_ctx.project_root), app_ctx.session_id)
    except Exception as e:
        logger.debug(f"Markdown ダッシュボード更新をスキップ: {e}")

    return True, applied, skipped_reasons


def _task_context_text(title: str, description: str, metadata: dict | None = None) -> str:
    requested = ""
    if isinstance(metadata, dict):
        requested = str(metadata.get("requested_description", "") or "")
    return f"{title} {requested} {description}".lower()


def _get_requires_playwright(metadata: dict | None) -> bool | None:
    """metadata.requires_playwright を bool として解釈する。"""
    if not isinstance(metadata, dict):
        return None

    raw_value = metadata.get("requires_playwright")
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None


def _is_quality_task(title: str, description: str, metadata: dict | None = None) -> bool:
    text = _task_context_text(title, description, metadata)
    keywords = ("qa", "quality", "test", "e2e", "検証", "テスト", "品質", "playwright")
    return any(keyword in text for keyword in keywords)


def _is_playwright_task(title: str, description: str, metadata: dict | None = None) -> bool:
    metadata_flag = _get_requires_playwright(metadata)
    if metadata_flag is not None:
        return metadata_flag

    text = _task_context_text(title, description, metadata)
    return "playwright" in text


def _is_ui_related_task(title: str, description: str, metadata: dict | None = None) -> bool:
    metadata_flag = _get_requires_playwright(metadata)
    if metadata_flag is not None:
        return metadata_flag

    text = _task_context_text(title, description, metadata)
    keywords = ("ui", "frontend", "画面", "表示", "フロント", "browser")
    return any(keyword in text for keyword in keywords)


def _run_git_capture(project_root: str, args: list[str]) -> tuple[bool, str]:
    """git コマンドを実行し、成否と出力を返す。"""
    try:
        proc = subprocess.run(
            ["git", "-C", project_root, *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as e:
        return False, str(e)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()
    return True, (proc.stdout or "").strip()


def _branch_exists(project_root: str, branch: str) -> bool:
    """ブランチが存在するか判定する。"""
    ok, _ = _run_git_capture(project_root, ["rev-parse", "--verify", branch])
    return ok


def _is_branch_merged_into_head(project_root: str, branch: str) -> bool:
    """ブランチが HEAD に取り込まれているか判定する。"""
    ok, _ = _run_git_capture(
        project_root,
        ["merge-base", "--is-ancestor", branch, "HEAD"],
    )
    return ok


def _split_lines(output: str) -> set[str]:
    """改行区切り出力を重複なしの集合へ変換する。"""
    return {line.strip() for line in output.splitlines() if line.strip()}


def _get_working_tree_diff_files(project_root: str) -> tuple[set[str], str | None]:
    """作業ツリー差分（staged + unstaged）のファイル集合を返す。"""
    unstaged_ok, unstaged_out = _run_git_capture(project_root, ["diff", "--name-only"])
    if not unstaged_ok:
        return set(), unstaged_out
    staged_ok, staged_out = _run_git_capture(
        project_root,
        ["diff", "--cached", "--name-only"],
    )
    if not staged_ok:
        return set(), staged_out
    return _split_lines(unstaged_out) | _split_lines(staged_out), None


def _get_branch_changed_files(project_root: str, branch: str) -> tuple[set[str], str | None]:
    """branch が HEAD から変更したファイル集合を返す。"""
    ok, out = _run_git_capture(
        project_root,
        ["diff", "--name-only", f"HEAD...{branch}"],
    )
    if not ok:
        return set(), out
    return _split_lines(out), None


def _is_branch_tree_equal_to_head(project_root: str, branch: str) -> tuple[bool, str | None]:
    """HEAD と branch のツリー内容が同一か判定する。"""
    try:
        proc = subprocess.run(
            ["git", "-C", project_root, "diff", "--quiet", "HEAD", branch],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as e:
        return False, str(e)

    if proc.returncode == 0:
        return True, None
    if proc.returncode == 1:
        return False, None
    return False, (proc.stderr or proc.stdout).strip()


def _is_branch_changes_already_applied(project_root: str, branch: str) -> tuple[bool, str | None]:
    """branch の変更が patch-id ベースで HEAD に適用済みか判定する。"""
    ok, out = _run_git_capture(project_root, ["cherry", "HEAD", branch])
    if not ok:
        return False, out
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if not lines:
        return False, None
    return all(line.startswith("-") for line in lines), None


def _check_branch_integration_state(project_root: str, branches: list[str]) -> list[dict[str, Any]]:
    """完了ブランチが統合済みか（merge/cherry/tree-equal/diff包含）を判定する。"""
    diff_files, diff_error = _get_working_tree_diff_files(project_root)
    if diff_error:
        logger.debug("作業ツリー差分の取得に失敗: %s", diff_error)
    branch_states: list[dict[str, Any]] = []

    for branch in sorted(set(branches)):
        if not branch:
            continue
        if not _branch_exists(project_root, branch):
            branch_states.append(
                {
                    "branch": branch,
                    "merged": False,
                    "tree_equal_to_head": False,
                    "changes_already_applied": False,
                    "covered_by_diff": False,
                    "branch_not_found": True,
                    "missing_files": [],
                }
            )
            continue

        merged = _is_branch_merged_into_head(project_root, branch)
        changed_files, branch_error = _get_branch_changed_files(project_root, branch)
        tree_equal_to_head, tree_equal_error = _is_branch_tree_equal_to_head(project_root, branch)
        changes_already_applied, cherry_error = _is_branch_changes_already_applied(
            project_root, branch
        )
        integration_error = branch_error or tree_equal_error or cherry_error
        if tree_equal_error:
            logger.debug("branch tree 比較に失敗: %s (%s)", branch, tree_equal_error)
        if cherry_error:
            logger.debug("branch cherry 判定に失敗: %s (%s)", branch, cherry_error)
        if branch_error:
            logger.debug("ブランチ変更ファイルの取得に失敗: %s (%s)", branch, branch_error)
        if integration_error:
            branch_states.append(
                {
                    "branch": branch,
                    "merged": merged,
                    "tree_equal_to_head": tree_equal_to_head,
                    "changes_already_applied": changes_already_applied,
                    "covered_by_diff": False,
                    "branch_not_found": False,
                    "missing_files": [],
                    "error": integration_error,
                }
            )
            continue

        missing_files = sorted(changed_files - diff_files)
        branch_states.append(
            {
                "branch": branch,
                "merged": merged,
                "tree_equal_to_head": tree_equal_to_head,
                "changes_already_applied": changes_already_applied,
                "covered_by_diff": len(missing_files) == 0,
                "branch_not_found": False,
                "missing_files": missing_files,
            }
        )

    return branch_states


def _check_branch_merge_state(project_root: str, branches: list[str]) -> list[dict[str, Any]]:
    """現在ブランチへの統合状態を返す。"""
    try:
        current_branch = subprocess.check_output(
            ["git", "-C", project_root, "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception as e:
        logger.debug("ブランチマージ状態の確認に失敗: %s", e)
        return []

    filtered = [branch for branch in branches if branch and branch != current_branch]
    return _check_branch_integration_state(project_root, filtered)


def _validate_admin_completion_gate(
    app_ctx: "AppContext", sender_id: str, receiver_id: str | None, msg_type: MessageType
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

    # 品質ゲート緩和モード: MCP_QUALITY_GATE_STRICT=false で品質チェックをスキップ
    if not getattr(app_ctx.settings, "quality_gate_strict", True):
        logger.info("品質ゲート緩和モード: 品質チェックをスキップします")
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
        _is_ui_related_task(t.title, t.description, getattr(t, "metadata", None)) for t in tasks
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
        integration_states = _check_branch_merge_state(str(app_ctx.project_root), branches)
        not_integrated = [
            s
            for s in integration_states
            if not (
                s.get("merged")
                or s.get("covered_by_diff")
                or s.get("tree_equal_to_head")
                or s.get("changes_already_applied")
            )
        ]
        if not_integrated:
            branch_names = ", ".join([s["branch"] for s in not_integrated[:5]])
            reasons.append(f"未統合の完了タスクブランチがあります: {branch_names}")
            detail_lines: list[str] = []
            for state in not_integrated[:5]:
                if state.get("branch_not_found"):
                    detail_lines.append(f"{state['branch']}: branch_not_found")
                    continue
                missing_files = state.get("missing_files") or []
                if missing_files:
                    sample = ", ".join(missing_files[:3])
                    if len(missing_files) > 3:
                        sample = f"{sample}, ..."
                    detail_lines.append(
                        f"{state['branch']}: diff に不足 ({len(missing_files)} files: {sample})"
                    )
                elif state.get("error"):
                    detail_lines.append(f"{state['branch']}: 判定エラー ({state['error']})")
            if detail_lines:
                reasons.extend(detail_lines)
            suggestions.append(
                "merge_completed_tasks で差分を展開し、"
                "統合ブランチ上の diff を確認後に再通知してください。"
            )

    if reasons:
        gate_payload: dict[str, Any] = {
            "status": "needs_replan",
            "reasons": reasons,
            "suggestions": suggestions,
            "quality_limits": {
                "max_iterations": settings.quality_check_max_iterations,
                "same_issue_limit": settings.quality_check_same_issue_limit,
            },
        }
        if app_ctx.project_root and branches:
            gate_payload["branch_integration"] = integration_states
        return False, {
            **gate_payload,
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

        sender_validation_error = validate_sender_caller_match(sender_id, caller_agent_id)
        if sender_validation_error:
            return sender_validation_error

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

        sender_agent = app_ctx.agents.get(sender_id)
        sender_role = str(getattr(sender_agent, "role", ""))
        original_receiver_id = receiver_id
        rerouted_receiver_id: str | None = None
        receiver_agent = None

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
        # tmux ペイン未配置の Owner 向けに、admin→owner は macOS へフォールバック
        notification_sent = False
        notification_method = None
        auto_cleanup_executed = False
        auto_cleanup_result: dict[str, Any] | None = None
        auto_cleanup_error: str | None = None
        if receiver_id:
            sync_agents_from_file(app_ctx)
            receiver_agent = app_ctx.agents.get(receiver_id)
            sender_agent = app_ctx.agents.get(sender_id)
            # macOS 通知条件: admin→owner の task_complete のみ
            is_admin_to_owner_task_complete = (
                sender_agent
                and receiver_agent
                and str(getattr(sender_agent, "role", "")) == AgentRole.ADMIN.value
                and str(getattr(receiver_agent, "role", "")) == AgentRole.OWNER.value
                and msg_type == MessageType.TASK_COMPLETE
            )
            if receiver_agent:
                has_tmux_pane = (
                    receiver_agent.session_name and receiver_agent.pane_index is not None
                )
                if has_tmux_pane:
                    # tmux ペインがある場合: リトライ付き tmux 通知
                    tmux_ok = await notify_agent_via_tmux(
                        app_ctx,
                        receiver_agent,
                        msg_type.value,
                        sender_id,
                        allow_macos_fallback=False,
                    )
                    if tmux_ok:
                        notification_sent = True
                        notification_method = "tmux"
                    elif is_admin_to_owner_task_complete:
                        # tmux 通知失敗時のみ macOS 通知を追加試行する
                        from src.tools.helpers import _send_macos_notification

                        macos_ok = await _send_macos_notification(msg_type.value, sender_id)
                        if macos_ok:
                            notification_sent = True
                            notification_method = "macos_fallback"
                elif is_admin_to_owner_task_complete:
                    # tmux ペインがない Owner への admin 通知を macOS で補完
                    from src.tools.helpers import _send_macos_notification

                    macos_ok = await _send_macos_notification(msg_type.value, sender_id)
                    if macos_ok:
                        notification_sent = True
                        notification_method = "macos"
                        logger.info("IPC通知を送信(macOS): %s", receiver_id)

        if msg_type == MessageType.TASK_APPROVED:
            auto_cleanup_executed = True
            try:
                auto_cleanup_result = await cleanup_session_resources(
                    app_ctx,
                    remove_worktrees=True,
                    repo_path=app_ctx.project_root,
                )
            except Exception as e:
                auto_cleanup_error = str(e)
                logger.warning("task_approved 後の自動クリーンアップに失敗: %s", e)

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

        sync_agents_from_file(app_ctx)
        caller = app_ctx.agents.get(caller_agent_id)
        caller_role = getattr(caller, "role", None)
        is_admin_caller = caller_role in (AgentRole.ADMIN.value, "admin")
        is_owner_caller = caller_role in (AgentRole.OWNER.value, "owner")

        owner_wait_state: dict[str, Any] | None = None
        if is_owner_caller and caller_agent_id:
            owner_wait_state = get_owner_wait_state(app_ctx, caller_agent_id)
            if owner_wait_state.get("waiting_for_admin"):
                # Owner 待機中は自身 inbox の通知待機のみ許可する。
                if agent_id != caller_agent_id:
                    return _owner_polling_blocked_response(owner_wait_state.get("admin_id"))
                if ipc.get_unread_count(caller_agent_id) == 0:
                    return _owner_polling_blocked_response(owner_wait_state.get("admin_id"))

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
        if is_admin_caller:
            unread_count = ipc.get_unread_count(agent_id)
            guard_error = _apply_admin_empty_polling_guard(
                app_ctx,
                caller_agent_id or agent_id,
                should_guard=bool(unread_only and unread_count == 0),
                tool_name="read_messages",
            )
            if guard_error:
                return guard_error

        owner_wait_unlocked = False
        if is_owner_caller and caller_agent_id and owner_wait_state:
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
                    app_ctx, caller_agent_id, reason="admin_notification_consumed"
                )
                owner_wait_unlocked = True

        if is_admin_caller:
            (
                dashboard_updated,
                dashboard_updates_applied,
                dashboard_updates_skipped_reason,
            ) = _auto_update_dashboard_from_messages(app_ctx, messages)
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

        count = ipc.get_unread_count(agent_id)
        sync_agents_from_file(app_ctx)
        caller = app_ctx.agents.get(caller_agent_id)
        caller_role = getattr(caller, "role", None)
        is_admin_caller = caller_role in (AgentRole.ADMIN.value, "admin")
        is_owner_caller = caller_role in (AgentRole.OWNER.value, "owner")
        if is_owner_caller and caller_agent_id:
            owner_wait_state = get_owner_wait_state(app_ctx, caller_agent_id)
            if owner_wait_state.get("waiting_for_admin"):
                # Owner 待機中は自身 inbox の通知待機のみ許可する。
                if agent_id != caller_agent_id:
                    return _owner_polling_blocked_response(owner_wait_state.get("admin_id"))
                if count == 0:
                    return _owner_polling_blocked_response(owner_wait_state.get("admin_id"))

        if is_admin_caller:
            guard_error = _apply_admin_empty_polling_guard(
                app_ctx,
                caller_agent_id or agent_id,
                should_guard=(count == 0),
                tool_name="get_unread_count",
            )
            if guard_error:
                return guard_error
            if count > 0:
                _mark_admin_ipc_consumed(app_ctx, caller_agent_id or agent_id)
            else:
                _mark_admin_waiting_for_ipc(app_ctx, caller_agent_id or agent_id)

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
