"""ロールごとのツール権限定義。

各ロールが使用可能な MCP ツールを定義する。
"""

from enum import Enum


class Role(str, Enum):
    """エージェントのロール。"""

    OWNER = "owner"
    ADMIN = "admin"
    WORKER = "worker"


# ロールごとの許可ツール
# キー: ツール名、値: 許可されたロールのリスト
TOOL_PERMISSIONS: dict[str, list[str]] = {
    # ========== セッション管理 ==========
    "init_tmux_workspace": ["owner"],
    "cleanup_workspace": ["owner"],
    "cleanup_on_completion": ["owner"],
    "check_all_tasks_completed": ["owner", "admin"],
    # ========== エージェント管理 ==========
    "create_agent": ["owner", "admin"],
    "create_workers_batch": ["owner", "admin"],
    "list_agents": ["owner", "admin", "worker"],
    "get_agent_status": ["owner", "admin", "worker"],
    "terminate_agent": ["owner", "admin"],
    "healthcheck_agent": ["owner", "admin"],
    "healthcheck_all": ["owner", "admin"],
    "get_unhealthy_agents": ["owner", "admin"],
    "monitor_and_recover_workers": ["owner", "admin"],
    "attempt_recovery": ["owner", "admin"],
    "full_recovery": ["admin"],
    "initialize_agent": ["owner", "admin"],
    "register_agent_to_ipc": ["owner", "admin"],
    # ========== Worktree 管理 ==========
    "create_worktree": ["owner", "admin"],
    "list_worktrees": ["owner", "admin", "worker"],
    "remove_worktree": ["owner", "admin"],
    "assign_worktree": ["owner", "admin"],
    "merge_completed_tasks": ["owner", "admin"],
    "get_worktree_status": ["owner", "admin", "worker"],
    "check_gtr_available": ["owner", "admin"],
    "check_gtrconfig": ["owner", "admin"],
    "generate_gtrconfig": ["owner", "admin"],
    "analyze_project_for_gtrconfig": ["owner", "admin"],
    "open_worktree_with_ai": ["owner", "admin"],
    "open_session": ["owner", "admin"],
    # ========== タスク管理 ==========
    "create_task": ["owner", "admin"],
    "get_task": ["owner", "admin", "worker"],
    "list_tasks": ["owner", "admin", "worker"],
    "assign_task_to_agent": ["admin"],
    "update_task_status": ["admin"],
    "remove_task": ["owner", "admin"],
    "report_task_progress": ["worker"],
    "report_task_completion": ["worker"],
    # ========== タスクキュー ==========
    "enqueue_task": ["owner", "admin"],
    "get_task_queue": ["owner", "admin"],
    "auto_assign_tasks": ["admin"],
    "detect_task_type": ["owner", "admin"],
    "get_optimal_persona": ["owner", "admin"],
    # ========== コマンド送信 ==========
    "send_task": ["owner", "admin"],
    "send_command": ["owner", "admin"],
    "broadcast_command": ["admin"],
    "get_output": ["owner", "admin", "worker"],
    # ========== メッセージング ==========
    "send_message": ["owner", "admin", "worker"],
    "read_messages": ["owner", "admin", "worker"],
    "get_unread_count": ["owner", "admin", "worker"],
    # ========== ダッシュボード ==========
    "get_dashboard": ["owner", "admin", "worker"],
    "get_dashboard_summary": ["owner", "admin", "worker"],
    # ========== メモリ管理 ==========
    "save_to_memory": ["owner", "admin", "worker"],
    "retrieve_from_memory": ["owner", "admin", "worker"],
    "list_memory_entries": ["owner", "admin", "worker"],
    "get_memory_entry": ["owner", "admin", "worker"],
    "delete_memory_entry": ["owner", "admin"],
    "get_memory_summary": ["owner", "admin", "worker"],
    "list_memory_archive": ["owner", "admin", "worker"],
    "search_memory_archive": ["owner", "admin", "worker"],
    "restore_from_memory_archive": ["owner", "admin"],
    "get_memory_archive_summary": ["owner", "admin", "worker"],
    # ========== グローバルメモリ ==========
    "save_to_global_memory": ["owner", "admin", "worker"],
    "retrieve_from_global_memory": ["owner", "admin", "worker"],
    "list_global_memory_entries": ["owner", "admin", "worker"],
    "delete_global_memory_entry": ["owner", "admin"],
    "get_global_memory_summary": ["owner", "admin", "worker"],
    "list_global_memory_archive": ["owner", "admin", "worker"],
    "search_global_memory_archive": ["owner", "admin", "worker"],
    "restore_from_global_memory_archive": ["owner", "admin"],
    "get_global_memory_archive_summary": ["owner", "admin", "worker"],
    # ========== コスト ==========
    "get_cost_estimate": ["owner", "admin"],
    "get_cost_summary": ["owner", "admin", "worker"],
    "reset_cost_counter": ["owner"],
    "set_cost_warning_threshold": ["owner"],
    # ========== スクリーンショット ==========
    "list_screenshots": ["owner", "admin", "worker"],
    "read_screenshot": ["owner", "admin", "worker"],
    "read_latest_screenshot": ["owner", "admin", "worker"],
    "get_screenshot_dir": ["owner", "admin", "worker"],
    # ========== ペルソナ ==========
    "list_personas": ["owner", "admin"],
    "get_role_guide": ["owner", "admin", "worker"],
    "list_role_guides": ["owner", "admin", "worker"],
    # ========== モデルプロファイル ==========
    "get_model_profile": ["owner", "admin"],
    "switch_model_profile": ["owner"],
    "get_model_profile_settings": ["owner", "admin"],
    # ========== ワークスペーステンプレート ==========
    "list_workspace_templates": ["owner", "admin"],
    "get_workspace_template": ["owner", "admin"],
}


def get_allowed_roles(tool_name: str) -> list[str]:
    """指定されたツールの許可ロールを取得する。

    Args:
        tool_name: ツール名

    Returns:
        許可されたロールのリスト、未定義の場合は空リスト
    """
    return TOOL_PERMISSIONS.get(tool_name, [])


def is_tool_allowed(tool_name: str, role: str) -> bool:
    """指定されたロールがツールを使用できるか確認する。

    Args:
        tool_name: ツール名
        role: ロール

    Returns:
        許可されている場合 True
    """
    allowed = get_allowed_roles(tool_name)
    return role in allowed


def get_role_error_message(tool_name: str, current_role: str) -> str:
    """ロール権限エラーメッセージを生成する。

    Args:
        tool_name: ツール名
        current_role: 現在のロール

    Returns:
        エラーメッセージ
    """
    allowed = get_allowed_roles(tool_name)
    allowed_str = ", ".join(allowed) if allowed else "なし"
    return (
        f"あなたのロール ({current_role}) では `{tool_name}` は使用禁止です。"
        f"許可されたロール: {allowed_str}。"
        f"`get_role_guide(role=\"{current_role}\")` で自身の役割を確認してください。"
    )
