"""MCP ツール用共通ヘルパーの互換ファサード。"""

from importlib import import_module

_SYMBOL_TO_MODULE = {
    "ADMIN_DASHBOARD_GRANT_SECONDS": "src.tools.helpers_permissions",
    "BOOTSTRAP_TOOLS": "src.tools.helpers_permissions",
    "InvalidConfigError": "src.tools.helpers_registry",
    "OWNER_WAIT_ALLOWED_TOOLS": "src.tools.helpers_permissions",
    "_get_agent_registry_dir": "src.tools.helpers_registry",
    "_get_agents_file_path": "src.tools.helpers_persistence",
    "_get_from_config": "src.tools.helpers_registry",
    "_get_global_mcp_dir": "src.tools.helpers_registry",
    "_global_memory_manager": "src.tools.helpers_managers",
    "_owner_polling_blocked_response": "src.tools.helpers_permissions",
    "_send_macos_notification": "src.tools.helpers_notifications",
    "check_tool_permission": "src.tools.helpers_permissions",
    "clear_owner_wait_state": "src.tools.helpers_permissions",
    "delete_agents_file": "src.tools.helpers_persistence",
    "ensure_dashboard_manager": "src.tools.helpers_managers",
    "ensure_global_memory_manager": "src.tools.helpers_managers",
    "ensure_healthcheck_manager": "src.tools.helpers_managers",
    "ensure_ipc_manager": "src.tools.helpers_managers",
    "ensure_memory_manager": "src.tools.helpers_managers",
    "ensure_persona_manager": "src.tools.helpers_managers",
    "ensure_project_root_from_caller": "src.tools.helpers_permissions",
    "ensure_scheduler_manager": "src.tools.helpers_managers",
    "ensure_session_id": "src.tools.helpers_registry",
    "find_agents_by_role": "src.tools.helpers_permissions",
    "get_admin_poll_state": "src.tools.helpers_permissions",
    "get_agent_role": "src.tools.helpers_permissions",
    "get_app_ctx": "src.tools.helpers_permissions",
    "get_authenticated_agent_id": "src.tools.helpers_permissions",
    "get_enable_git_from_config": "src.tools.helpers_registry",
    "get_gtrconfig_manager": "src.tools.helpers_managers",
    "get_mcp_tool_prefix_from_config": "src.tools.helpers_registry",
    "get_owner_wait_state": "src.tools.helpers_permissions",
    "get_project_root_from_config": "src.tools.helpers_registry",
    "get_project_root_from_registry": "src.tools.helpers_registry",
    "get_session_id_from_config": "src.tools.helpers_registry",
    "get_session_id_from_registry": "src.tools.helpers_registry",
    "get_worktree_manager": "src.tools.helpers_managers",
    "load_agents_from_file": "src.tools.helpers_persistence",
    "mark_owner_waiting_for_admin": "src.tools.helpers_permissions",
    "notify_agent_via_tmux": "src.tools.helpers_notifications",
    "refresh_app_settings": "src.runtime_bootstrap",
    "remove_agent_from_file": "src.tools.helpers_persistence",
    "remove_agent_from_registry": "src.tools.helpers_registry",
    "remove_agents_by_owner": "src.tools.helpers_registry",
    "require_permission": "src.tools.helpers_permissions",
    "reset_agent_to_idle": "src.tools.helpers_permissions",
    "resolve_effective_caller_agent_id": "src.tools.helpers_permissions",
    "resolve_main_repo_root": "src.tools.helpers_git",
    "resolve_project_root": "src.runtime_bootstrap",
    "save_agent_to_file": "src.tools.helpers_persistence",
    "save_agent_to_registry": "src.tools.helpers_registry",
    "search_memory_context": "src.tools.helpers_managers",
    "sync_agents_from_file": "src.tools.helpers_persistence",
    "validate_sender_caller_match": "src.tools.helpers_permissions",
}

__all__ = sorted(_SYMBOL_TO_MODULE)


def __getattr__(name: str):
    """必要になったシンボルだけを遅延 import する。"""
    module_name = _SYMBOL_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module 'src.tools.helpers' has no attribute {name!r}")
    module = import_module(module_name)
    return getattr(module, name)
