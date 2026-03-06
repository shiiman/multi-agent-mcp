"""MCP Tools モジュール。"""

from importlib import import_module

from mcp.server.fastmcp import FastMCP

_TOOL_MODULES = (
    "session",
    "agent",
    "command",
    "worktree",
    "merge",
    "ipc",
    "dashboard",
    "dashboard_cost_tools",
    "gtrconfig",
    "template",
    "scheduler",
    "healthcheck",
    "persona",
    "memory",
    "memory_global",
    "screenshot",
    "model_profile",
)


def register_all_tools(mcp: FastMCP) -> None:
    """全ツールをMCPサーバーに登録する。

    Args:
        mcp: FastMCPインスタンス
    """
    for module_name in _TOOL_MODULES:
        module = import_module(f"src.tools.{module_name}")
        module.register_tools(mcp)
