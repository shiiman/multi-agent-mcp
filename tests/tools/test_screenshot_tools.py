"""スクリーンショットツールのテスト。"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.tmux_manager import TmuxManager
from src.models.agent import Agent, AgentRole, AgentStatus


@pytest.fixture
def screenshot_test_ctx(git_repo, settings):
    """スクリーンショットツールテスト用の AppContext を作成する。"""
    mock_tmux = MagicMock(spec=TmuxManager)
    mock_tmux.settings = settings
    ai_cli = AiCliManager(settings)
    ctx = AppContext(
        settings=settings,
        tmux=mock_tmux,
        ai_cli=ai_cli,
        agents={},
        project_root=str(git_repo),
        session_id="test-session",
    )
    return ctx


@pytest.fixture
def screenshot_mock_ctx(screenshot_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = screenshot_test_ctx
    return mock


class TestReadScreenshot:
    """read_screenshot ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_read_screenshot_rejects_path_traversal(
        self, screenshot_mock_ctx, git_repo
    ):
        """path traversal を拒否することをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.screenshot import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        read_screenshot = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "read_screenshot":
                read_screenshot = tool.fn
                break

        app_ctx = screenshot_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        screenshot_dir = git_repo / app_ctx.settings.mcp_dir / "screenshot"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        (git_repo / "secret.txt").write_text("secret", encoding="utf-8")

        result = await read_screenshot(
            filename="../secret.txt",
            caller_agent_id="owner-001",
            ctx=screenshot_mock_ctx,
        )

        assert result["success"] is False
        assert "path traversal" in result["error"]

