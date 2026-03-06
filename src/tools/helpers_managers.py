"""Manager 初期化ヘルパーの互換ファサード。

実体は `src.runtime_bootstrap` に移し、このモジュールは既存 import パスを維持する。
"""

from src.runtime_bootstrap import (
    _global_memory_manager,
    ensure_dashboard_manager,
    ensure_global_memory_manager,
    ensure_healthcheck_manager,
    ensure_ipc_manager,
    ensure_memory_manager,
    ensure_persona_manager,
    ensure_scheduler_manager,
    get_gtrconfig_manager,
    get_worktree_manager,
    search_memory_context,
)

__all__ = [
    "_global_memory_manager",
    "ensure_dashboard_manager",
    "ensure_global_memory_manager",
    "ensure_healthcheck_manager",
    "ensure_ipc_manager",
    "ensure_memory_manager",
    "ensure_persona_manager",
    "ensure_scheduler_manager",
    "get_gtrconfig_manager",
    "get_worktree_manager",
    "search_memory_context",
]
