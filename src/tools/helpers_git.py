"""Git ヘルパー関数。"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# プロセス内キャッシュ: 入力パス文字列 → メインリポジトリルート
# 同一パスのリポジトリ構成はプロセス生存中に変化しないため安全にキャッシュ可能
_main_repo_root_cache: dict[str, str] = {}


def clear_main_repo_root_cache() -> None:
    """resolve_main_repo_root のプロセス内キャッシュをクリアする（主にテスト用）。"""
    _main_repo_root_cache.clear()


def resolve_main_repo_root(path: str | Path) -> str:
    """パスからメインリポジトリのルートを解決する（プロセス内キャッシュ付き）。

    git worktree の場合はメインリポジトリのルートを返す。
    通常のリポジトリの場合はそのままルートを返す。
    成功結果は入力パスをキーにプロセス内キャッシュされる。

    Args:
        path: 解決するパス（worktree またはリポジトリ内のパス）

    Returns:
        メインリポジトリのルートパス
    """
    cache_key = str(Path(path))
    cached = _main_repo_root_cache.get(cache_key)
    if cached is not None:
        return cached
    resolved = _resolve_main_repo_root_uncached(path)
    _main_repo_root_cache[cache_key] = resolved
    return resolved


def _resolve_main_repo_root_uncached(path: str | Path) -> str:
    """git コマンドでメインリポジトリのルートを解決する（キャッシュ無し）。"""
    path = Path(path)

    try:
        # git rev-parse --show-toplevel でリポジトリのルートを取得
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path),
            capture_output=True,
            text=True,
            check=True,
        )
        repo_root = result.stdout.strip()

        # git rev-parse --git-common-dir でメインリポジトリの .git を取得
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(path),
            capture_output=True,
            text=True,
            check=True,
        )
        git_common_dir = result.stdout.strip()

        # .git が絶対パスでない場合は repo_root からの相対パス
        if not os.path.isabs(git_common_dir):
            git_common_dir = os.path.join(repo_root, git_common_dir)

        # .git/worktrees/xxx の形式なら、メインリポジトリは .git の親
        git_common_dir = os.path.normpath(git_common_dir)
        if git_common_dir.endswith(".git"):
            # 通常のリポジトリ（worktree ではない）
            return os.path.dirname(git_common_dir)
        else:
            # worktree: /path/to/main-repo/.git/worktrees/xxx → /path/to/main-repo
            git_dir_index = git_common_dir.find("/.git")
            if git_dir_index == -1:
                return repo_root
            return git_common_dir[:git_dir_index]

    except subprocess.CalledProcessError as e:
        raise ValueError(f"{path} は git リポジトリではありません: {e}") from e


# ---------------------------------------------------------------------------
# 汎用 Git ユーティリティ関数群（quality_gate.py から移動）
# ---------------------------------------------------------------------------


def _run_git_capture(project_root: str, args: list[str]) -> tuple[bool, str]:
    """git コマンドを実行し、成否と出力を返す。"""
    try:
        proc = subprocess.run(
            ["git", "-C", project_root, *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
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
    except (OSError, subprocess.SubprocessError) as e:
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
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("ブランチマージ状態の確認に失敗: %s", e)
        return []

    filtered = [branch for branch in branches if branch and branch != current_branch]
    return _check_branch_integration_state(project_root, filtered)
