"""エージェント管理ツール登録モジュール。"""

from mcp.server.fastmcp import FastMCP

from src.tools.agent_batch_tools import register_batch_tools
from src.tools.agent_lifecycle_tools import register_lifecycle_tools


def register_tools(mcp: FastMCP) -> None:
    """エージェント管理ツールを登録する。"""
    register_lifecycle_tools(mcp)
    register_batch_tools(mcp)
