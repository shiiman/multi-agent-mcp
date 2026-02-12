"""Git ヘルパー関数。"""

import os
import subprocess
from pathlib import Path


def resolve_main_repo_root(path: str | Path) -> str:
    """パスからメインリポジトリのルートを解決する。

    git worktree の場合はメインリポジトリのルートを返す。
    通常のリポジトリの場合はそのままルートを返す。

    Args:
        path: 解決するパス（worktree またはリポジトリ内のパス）

    Returns:
        メインリポジトリのルートパス
    """
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
