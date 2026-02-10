"""グローバルメモリ管理ツールのテスト。"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.memory_manager import MemoryManager
from src.managers.tmux_manager import TmuxManager
from src.models.agent import Agent, AgentRole, AgentStatus


@pytest.fixture
def memory_global_test_ctx(git_repo, settings):
    """memory_global ツール検証用の AppContext を作成する。"""
    mock_tmux = MagicMock(spec=TmuxManager)
    mock_tmux.settings = settings
    ai_cli = AiCliManager(settings)

    return AppContext(
        settings=settings,
        tmux=mock_tmux,
        ai_cli=ai_cli,
        agents={},
        project_root=str(git_repo),
        session_id="test-session",
    )


@pytest.fixture
def memory_global_mock_ctx(memory_global_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = memory_global_test_ctx
    return mock


def _get_tool_fn(mcp, tool_name: str):
    for tool in mcp._tool_manager._tools.values():
        if tool.name == tool_name:
            return tool.fn
    return None


class TestMemoryGlobalTools:
    """memory_global ツール群の回帰テスト。"""

    @pytest.mark.asyncio
    async def test_save_and_retrieve_global_memory(self, memory_global_mock_ctx, git_repo):
        """保存したグローバルメモリを検索できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.memory_global import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        save_to_global_memory = _get_tool_fn(mcp, "save_to_global_memory")
        retrieve_from_global_memory = _get_tool_fn(mcp, "retrieve_from_global_memory")

        app_ctx = memory_global_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            created_at=now,
            last_activity=now,
            working_dir=str(git_repo),
        )

        memory = MemoryManager(str(git_repo / ".global-memory-test"))
        with patch("src.tools.memory_global.ensure_global_memory_manager", return_value=memory):
            save_result = await save_to_global_memory(
                key="global-test-key",
                content="global memory test content",
                tags=["global", "test"],
                caller_agent_id="owner-001",
                ctx=memory_global_mock_ctx,
            )
            retrieve_result = await retrieve_from_global_memory(
                query="memory test",
                caller_agent_id="owner-001",
                ctx=memory_global_mock_ctx,
            )

        assert save_result["success"] is True
        assert save_result["entry"]["key"] == "global-test-key"
        assert retrieve_result["success"] is True
        assert retrieve_result["count"] >= 1

    @pytest.mark.asyncio
    async def test_list_global_memory_entries_with_tags(self, memory_global_mock_ctx, git_repo):
        """タグ指定でグローバルメモリを絞り込みできることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.memory_global import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        save_to_global_memory = _get_tool_fn(mcp, "save_to_global_memory")
        list_global_memory_entries = _get_tool_fn(mcp, "list_global_memory_entries")

        app_ctx = memory_global_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            created_at=now,
            last_activity=now,
            working_dir=str(git_repo),
        )

        memory = MemoryManager(str(git_repo / ".global-memory-test-tags"))
        with patch("src.tools.memory_global.ensure_global_memory_manager", return_value=memory):
            await save_to_global_memory(
                key="global-tag-a",
                content="content-a",
                tags=["audit"],
                caller_agent_id="owner-001",
                ctx=memory_global_mock_ctx,
            )
            await save_to_global_memory(
                key="global-tag-b",
                content="content-b",
                tags=["ops"],
                caller_agent_id="owner-001",
                ctx=memory_global_mock_ctx,
            )

            list_result = await list_global_memory_entries(
                tags=["audit"],
                caller_agent_id="owner-001",
                ctx=memory_global_mock_ctx,
            )

        assert list_result["success"] is True
        assert list_result["count"] == 1
        assert list_result["entries"][0]["key"] == "global-tag-a"

    @pytest.mark.asyncio
    async def test_delete_global_memory_entry_requires_admin_or_owner(
        self, memory_global_mock_ctx, git_repo
    ):
        """delete_global_memory_entry は worker から実行不可であることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.memory_global import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)
        delete_global_memory_entry = _get_tool_fn(mcp, "delete_global_memory_entry")

        app_ctx = memory_global_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["worker-001"] = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            created_at=now,
            last_activity=now,
            working_dir=str(git_repo),
        )

        result = await delete_global_memory_entry(
            key="global-test-key",
            caller_agent_id="worker-001",
            ctx=memory_global_mock_ctx,
        )

        assert result["success"] is False
        assert "使用禁止" in result["error"]
