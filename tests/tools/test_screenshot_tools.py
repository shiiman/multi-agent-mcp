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

    @pytest.mark.asyncio
    async def test_read_screenshot_rejects_symlink(self, screenshot_mock_ctx, git_repo):
        """symlink 経由の参照を拒否することをテスト。"""
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
        real_file = screenshot_dir / "real.png"
        real_file.write_bytes(b"image",)
        link_file = screenshot_dir / "link.png"
        link_file.symlink_to(real_file)

        result = await read_screenshot(
            filename="link.png",
            caller_agent_id="owner-001",
            ctx=screenshot_mock_ctx,
        )

        assert result["success"] is False
        assert "symlink" in result["error"]


class TestListScreenshots:
    """list_screenshots ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_list_screenshots_sorts_by_mtime_and_respects_limit(
        self, screenshot_mock_ctx, git_repo
    ):
        """更新日時降順で並び、limit 件に制限されることをテスト。"""
        import os

        from mcp.server.fastmcp import FastMCP

        from src.tools.screenshot import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        list_screenshots = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "list_screenshots":
                list_screenshots = tool.fn
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
        old_file = screenshot_dir / "old.png"
        new_file = screenshot_dir / "new.jpg"
        mid_file = screenshot_dir / "mid.webp"
        ignore_file = screenshot_dir / "ignore.txt"
        old_file.write_bytes(b"old")
        new_file.write_bytes(b"new")
        mid_file.write_bytes(b"mid")
        ignore_file.write_text("ignore", encoding="utf-8")
        os.utime(old_file, (1000, 1000))
        os.utime(mid_file, (2000, 2000))
        os.utime(new_file, (3000, 3000))

        result = await list_screenshots(
            limit=2,
            caller_agent_id="owner-001",
            ctx=screenshot_mock_ctx,
        )

        assert result["success"] is True
        assert result["count"] == 2
        assert [item["filename"] for item in result["screenshots"]] == ["new.jpg", "mid.webp"]


class TestReadLatestScreenshot:
    """read_latest_screenshot ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_read_latest_screenshot_returns_error_when_no_screenshots(
        self, screenshot_mock_ctx, git_repo
    ):
        """対象ディレクトリに画像がない場合にエラーを返すことをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.screenshot import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        read_latest_screenshot = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "read_latest_screenshot":
                read_latest_screenshot = tool.fn
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
        (screenshot_dir / "readme.txt").write_text("no images", encoding="utf-8")

        result = await read_latest_screenshot(
            caller_agent_id="owner-001",
            ctx=screenshot_mock_ctx,
        )

        assert result["success"] is False
        assert "見つかりません" in result["error"]
