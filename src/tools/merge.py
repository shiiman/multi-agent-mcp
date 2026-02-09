"""完了タスクのマージ支援ツール。"""

import logging
import subprocess
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.models.dashboard import TaskStatus
from src.tools.helpers import ensure_dashboard_manager, require_permission

logger = logging.getLogger(__name__)


def _run_git(repo_path: str, args: list[str]) -> tuple[bool, str]:
    """git コマンドを実行する。"""
    try:
        proc = subprocess.run(
            ["git", "-C", repo_path, *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()
    return True, (proc.stdout or "").strip()


def _is_branch_merged(repo_path: str, branch: str, base_branch: str) -> bool:
    """branch が base_branch に取り込まれているか判定する。"""
    ok, _ = _run_git(
        repo_path,
        ["merge-base", "--is-ancestor", branch, base_branch],
    )
    return ok


def _branch_exists(repo_path: str, branch: str) -> bool:
    """ブランチがローカルに存在するかを判定する。"""
    ok, _ = _run_git(repo_path, ["rev-parse", "--verify", branch])
    return ok


def _is_worktree_clean(repo_path: str) -> tuple[bool, str]:
    """作業ツリーがクリーンかを判定する。"""
    ok, out = _run_git(repo_path, ["status", "--porcelain"])
    if not ok:
        return False, out
    return out.strip() == "", out


def register_tools(mcp: FastMCP) -> None:
    """マージ関連ツールを登録する。"""

    @mcp.tool()
    async def merge_completed_tasks(
        session_id: str,
        repo_path: str,
        base_branch: str,
        strategy: str = "merge",
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """完了タスクの作業ブランチを base_branch に統合する。"""
        app_ctx, role_error = require_permission(ctx, "merge_completed_tasks", caller_agent_id)
        if role_error:
            return role_error

        if strategy not in ("merge", "squash", "rebase"):
            return {
                "success": False,
                "error": "strategy は merge / squash / rebase のいずれかを指定してください",
            }

        repo = str(Path(repo_path).resolve())
        dashboard = ensure_dashboard_manager(app_ctx)
        tasks = dashboard.list_tasks(status=TaskStatus.COMPLETED)

        branches = sorted({t.branch for t in tasks if t.branch})
        merged: list[str] = []
        already_merged: list[str] = []
        failed: list[dict[str, str]] = []
        conflicts: list[dict[str, str]] = []

        clean, status_output = _is_worktree_clean(repo)
        if not clean:
            return {
                "success": False,
                "error": (
                    "作業ツリーがクリーンではありません。"
                    " merge_completed_tasks 実行前に変更を退避またはコミットしてください。"
                ),
                "status": status_output,
            }

        if not _branch_exists(repo, base_branch):
            return {
                "success": False,
                "error": f"base ブランチが存在しません: {base_branch}",
            }

        ok, checkout_error = _run_git(repo, ["checkout", base_branch])
        if not ok:
            return {
                "success": False,
                "error": f"base ブランチへの checkout に失敗しました: {checkout_error}",
            }

        ok, base_head = _run_git(repo, ["rev-parse", "HEAD"])
        if not ok:
            return {
                "success": False,
                "error": f"HEAD 取得に失敗しました: {base_head}",
            }

        temp_commit_count = 0
        strategy_warning: str | None = None
        effective_strategy = strategy
        if strategy == "rebase":
            effective_strategy = "merge"
            strategy_warning = (
                "strategy=rebase は no-commit プレビューでは非対応のため "
                "merge 相当で適用しました。"
            )

        for branch in branches:
            if not _branch_exists(repo, branch):
                failed.append({"branch": branch, "error": "branch_not_found"})
                continue
            if _is_branch_merged(repo, branch, base_branch):
                already_merged.append(branch)
                continue
            if effective_strategy == "merge":
                ok, out = _run_git(repo, ["merge", "--no-ff", "--no-commit", branch])
            else:
                ok, out = _run_git(repo, ["merge", "--squash", branch])

            if not ok:
                lower = out.lower()
                if "conflict" in lower:
                    conflicts.append({"branch": branch, "error": out})
                    _run_git(repo, ["merge", "--abort"])
                    _run_git(repo, ["rebase", "--abort"])
                else:
                    failed.append({"branch": branch, "error": out})
                continue

            commit_ok, commit_out = _run_git(
                repo,
                ["commit", "--no-verify", "-m", f"tmp merge preview: {branch}"],
            )
            if not commit_ok:
                failed.append({"branch": branch, "error": commit_out})
                _run_git(repo, ["merge", "--abort"])
                continue
            temp_commit_count += 1
            merged.append(branch)

        reset_ok = True
        reset_error: str | None = None
        if temp_commit_count > 0:
            reset_ok, reset_error = _run_git(repo, ["reset", "--mixed", base_head])

        # マージ結果を messages に残す
        dashboard.add_message(
            sender_id=caller_agent_id or "system",
            receiver_id=None,
            message_type="task_complete",
            subject=f"merge_completed_tasks: {session_id}",
            content=(
                "preview_merge=true, "
                f"merged={len(merged)}, "
                f"already_merged={len(already_merged)}, failed={len(failed)}"
            ),
        )

        if not reset_ok:
            return {
                "success": False,
                "session_id": session_id,
                "repo_path": repo,
                "base_branch": base_branch,
                "strategy": strategy,
                "merged": merged,
                "already_merged": already_merged,
                "failed": failed,
                "conflicts": conflicts,
                "error": f"プレビュー差分化の reset に失敗しました: {reset_error}",
            }

        return {
            "success": len(failed) == 0 and len(conflicts) == 0,
            "session_id": session_id,
            "repo_path": repo,
            "base_branch": base_branch,
            "strategy": strategy,
            "strategy_warning": strategy_warning,
            "preview_merge": True,
            "working_tree_updated": temp_commit_count > 0,
            "base_head": base_head,
            "merged": merged,
            "already_merged": already_merged,
            "failed": failed,
            "conflicts": conflicts,
            "message": (
                "統合ブランチへコミットなしで差分を展開しました。"
                f" 適用済み={len(merged)}, "
                f"既に統合済み={len(already_merged)}, 失敗={len(failed)}"
            ),
        }
