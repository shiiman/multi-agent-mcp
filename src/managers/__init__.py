"""マネージャーモジュールの互換エントリ。"""

from importlib import import_module

_LAZY_EXPORTS = {
    "AgentManager": "src.managers.agent_manager",
    "AiCliManager": "src.managers.ai_cli_manager",
    "DashboardManager": "src.managers.dashboard_manager",
    "GtrconfigManager": "src.managers.gtrconfig_manager",
    "HealthcheckManager": "src.managers.healthcheck_manager",
    "IPCManager": "src.managers.ipc_manager",
    "MemoryManager": "src.managers.memory_manager",
    "PersonaManager": "src.managers.persona_manager",
    "SchedulerManager": "src.managers.scheduler_manager",
    "TmuxManager": "src.managers.tmux_manager",
    "WorktreeManager": "src.managers.worktree_manager",
}

__all__ = sorted([* _LAZY_EXPORTS.keys(), "tmux_shared"])


def __getattr__(name: str):
    """必要になったときだけ manager 実装を import する。"""
    if name == "tmux_shared":
        return import_module("src.managers.tmux_shared")
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module 'src.managers' has no attribute {name!r}")
    module = import_module(module_name)
    return getattr(module, name)
