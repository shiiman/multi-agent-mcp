"""tmux 管理で共有する定数とユーティリティ。"""

MAIN_SESSION = "main"
MAIN_WINDOW_PANE_ADMIN = 0
MAIN_WINDOW_WORKER_PANES = [1, 2, 3, 4, 5, 6]


def escape_applescript(value: str) -> str:
    """AppleScript 文字列リテラル用にエスケープする。

    バックスラッシュとダブルクォートをエスケープして
    AppleScript インジェクションを防止する。
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def get_project_name(working_dir: str, enable_git: bool = True) -> str:
    """作業ディレクトリからプロジェクト名を取得する。"""
    import hashlib
    import subprocess
    from pathlib import Path

    normalized_dir = str(Path(working_dir).expanduser().resolve())
    if not enable_git:
        base = Path(normalized_dir).name or "workspace"
        short_hash = hashlib.sha1(normalized_dir.encode("utf-8")).hexdigest()[:6]
        return f"{base}-{short_hash}"

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
