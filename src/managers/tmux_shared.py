"""tmux 管理で共有する定数とユーティリティ。"""

MAIN_SESSION = "main"
MAIN_WINDOW_PANE_ADMIN = 0
MAIN_WINDOW_WORKER_PANES = [1, 2, 3, 4, 5, 6]


def get_project_name(working_dir: str) -> str:
    """作業ディレクトリからプロジェクト名を取得する。"""
    import subprocess
    from pathlib import Path

    result = subprocess.run(
        ["git", "-C", working_dir, "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise ValueError(f"{working_dir} は git リポジトリではありません")

    git_common_dir = Path(result.stdout.strip())
    if not git_common_dir.is_absolute():
        git_common_dir = (Path(working_dir) / git_common_dir).resolve()
    return git_common_dir.parent.name
