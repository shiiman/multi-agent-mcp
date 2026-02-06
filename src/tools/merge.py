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

        ok, err = _run_git(repo, ["checkout", base_branch])
        if not ok:
            return {
                "success": False,
                "error": f"base ブランチへの checkout に失敗しました: {err}",
            }

        for branch in branches:
            if _is_branch_merged(repo, branch, base_branch):
                already_merged.append(branch)
                continue

            if strategy == "merge":
                ok, out = _run_git(repo, ["merge", "--no-ff", branch, "-m", f"merge: {branch}"])
            elif strategy == "squash":
                ok, out = _run_git(repo, ["merge", "--squash", branch])
                if ok:
                    ok, out = _run_git(repo, ["commit", "-m", f"squash merge: {branch}"])
            else:
                ok, out = _run_git(repo, ["rebase", branch])

            if ok:
                merged.append(branch)
                continue

            lower = out.lower()
            if "conflict" in lower:
                conflicts.append({"branch": branch, "error": out})
                _run_git(repo, ["merge", "--abort"])
                _run_git(repo, ["rebase", "--abort"])
            else:
                failed.append({"branch": branch, "error": out})

        # マージ結果を messages に残す
        dashboard.add_message(
            sender_id=caller_agent_id or "system",
            receiver_id=None,
            message_type="task_complete",
            subject=f"merge_completed_tasks: {session_id}",
            content=(
                f"merged={len(merged)}, already_merged={len(already_merged)}, "
                f"failed={len(failed)}, conflicts={len(conflicts)}"
            ),
        )

        return {
            "success": len(failed) == 0 and len(conflicts) == 0,
            "session_id": session_id,
            "repo_path": repo,
            "base_branch": base_branch,
            "strategy": strategy,
            "merged": merged,
            "already_merged": already_merged,
            "failed": failed,
            "conflicts": conflicts,
            "message": (
                f"merged={len(merged)}, already_merged={len(already_merged)}, "
                f"failed={len(failed)}, conflicts={len(conflicts)}"
            ),
        }

