"""セッション状態操作ヘルパー。"""

from typing import Any

from src.context import AppContext


def _check_completion_status(app_ctx: AppContext) -> dict[str, Any]:
    """タスク完了状態を計算する。"""
    if app_ctx.dashboard_manager is None:
        return {
            "is_all_completed": False,
            "total_tasks": 0,
            "pending_tasks": 0,
            "in_progress_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "error": "ワークスペースが初期化されていません",
        }

    summary = app_ctx.dashboard_manager.get_summary()

    total = summary["total_tasks"]
    pending = summary["pending_tasks"]
    in_progress = summary["in_progress_tasks"]
    completed = summary["completed_tasks"]
    failed = summary["failed_tasks"]

    is_completed = (total > 0) and (pending == 0) and (in_progress == 0) and (failed == 0)

    return {
        "is_all_completed": is_completed,
        "total_tasks": total,
        "pending_tasks": pending,
        "in_progress_tasks": in_progress,
        "completed_tasks": completed,
        "failed_tasks": failed,
    }

def _reset_app_context(app_ctx: AppContext) -> None:
    """アプリケーションコンテキストのインメモリ状態をリセットする。

    cleanup_workspace / cleanup_on_completion から呼び出される。
    session_id, project_root, 各種 manager をリセットすることで、
    次のセッションで古い値が使われることを防ぐ。
    """
    app_ctx.session_id = None
    app_ctx.project_root = None
    app_ctx.workspace_id = None
    app_ctx.ipc_manager = None
    app_ctx.dashboard_manager = None
    app_ctx.scheduler_manager = None
    app_ctx.healthcheck_manager = None
    app_ctx.persona_manager = None
    app_ctx.memory_manager = None
    app_ctx.worktree_managers.clear()
    app_ctx.gtrconfig_managers.clear()


def _collect_session_names(agents: dict[str, Any]) -> list[str]:
    """エージェント一覧から tmux セッション名を収集する。"""
    session_names: set[str] = set()
    for agent in agents.values():
        session_name = getattr(agent, "session_name", None)
        if session_name:
            session_names.add(session_name)
            continue

        tmux_session = getattr(agent, "tmux_session", None)
        if tmux_session:
            session_names.add(str(tmux_session).split(":", 1)[0])

    return sorted(session_names)


