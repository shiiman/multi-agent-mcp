"""品質ゲート検証ツール。

ipc.py から分離した責務。IPC メッセージングとは独立した機能を提供する。
汎用 Git ユーティリティ関数は helpers_git.py に集約。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.context import AppContext

from src.models.agent import AgentRole
from src.models.dashboard import TaskStatus
from src.tools.helpers_git import _check_branch_merge_state
from src.tools.helpers_managers import ensure_dashboard_manager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# タスク種別判定
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 品質ゲート検証
# ---------------------------------------------------------------------------


def _validate_admin_completion_gate(
    app_ctx: "AppContext", sender_id: str, receiver_id: str | None, msg_type: "MessageType"
) -> tuple[bool, dict[str, Any]]:
    """Admin -> Owner の task_complete を品質ゲートで検証する。"""
    from src.models.message import MessageType

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

    # No Git モードではブランチ統合チェックをスキップ
    # (git コマンド不可 + merge_completed_tasks も無効でデッドエンドになるため)
    branches: list[str] = []
    integration_states: list[dict[str, Any]] = []
    if app_ctx.settings.enable_git:
        branches = [t.branch for t in completed_tasks if t.branch]
        if app_ctx.project_root and branches:
            integration_states = _check_branch_merge_state(
                str(app_ctx.project_root), branches
            )
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
                            f"{state['branch']}: diff に不足"
                            f" ({len(missing_files)} files: {sample})"
                        )
                    elif state.get("error"):
                        detail_lines.append(
                            f"{state['branch']}: 判定エラー ({state['error']})"
                        )
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
