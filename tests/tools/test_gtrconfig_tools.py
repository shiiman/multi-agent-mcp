"""Gtrconfig管理ツールのテスト。"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.config.settings import Settings
from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.gtrconfig_manager import GtrconfigManager
from src.managers.tmux_manager import TmuxManager
from src.models.agent import Agent, AgentRole, AgentStatus


def _get_tool_fn(mcp, tool_name: str):
    """MCP ツール関数をツール名から取得するヘルパー。"""
    for tool in mcp._tool_manager._tools.values():
        if tool.name == tool_name:
            return tool.fn
    return None


@pytest.fixture
def gtrconfig_test_ctx(git_repo, settings):
    """Gtrconfig ツールテスト用の AppContext を作成する。"""
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
    yield ctx


@pytest.fixture
def gtrconfig_mock_ctx(gtrconfig_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = gtrconfig_test_ctx
    return mock


def _add_owner(mock_ctx, working_dir: str) -> None:
    """テスト用に Owner エージェントを追加するヘルパー。"""
    app_ctx = mock_ctx.request_context.lifespan_context
    now = datetime.now()
    app_ctx.agents["owner-001"] = Agent(
        id="owner-001",
        role=AgentRole.OWNER,
        status=AgentStatus.IDLE,
        tmux_session=None,
        working_dir=working_dir,
        created_at=now,
        last_activity=now,
    )


def _add_worker(mock_ctx, working_dir: str) -> None:
    """テスト用に Worker エージェントを追加するヘルパー。"""
    app_ctx = mock_ctx.request_context.lifespan_context
    now = datetime.now()
    app_ctx.agents["worker-001"] = Agent(
        id="worker-001",
        role=AgentRole.WORKER,
        status=AgentStatus.IDLE,
        tmux_session="test:0.1",
        working_dir=working_dir,
        created_at=now,
        last_activity=now,
    )


def _register_tools():
    """Gtrconfig ツールを登録した FastMCP インスタンスを返す。"""
    from mcp.server.fastmcp import FastMCP

    from src.tools.gtrconfig import register_tools

    mcp = FastMCP("test")
    register_tools(mcp)
    return mcp


class TestCheckGtrconfig:
    """check_gtrconfig ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_check_gtrconfig_success(self, gtrconfig_mock_ctx, git_repo):
        """Gtrconfig の状態を取得できることをテスト。"""
        mcp = _register_tools()
        check_gtrconfig = _get_tool_fn(mcp, "check_gtrconfig")
        _add_owner(gtrconfig_mock_ctx, str(git_repo))

        result = await check_gtrconfig(
            project_path=str(git_repo),
            caller_agent_id="owner-001",
            ctx=gtrconfig_mock_ctx,
        )

        assert result["success"] is True
        assert "status" in result
        assert result["status"]["exists"] is False

    @pytest.mark.asyncio
    async def test_check_gtrconfig_existing_file(self, gtrconfig_mock_ctx, git_repo):
        """既存の .gtrconfig ファイルを検出できることをテスト。"""
        mcp = _register_tools()
        check_gtrconfig = _get_tool_fn(mcp, "check_gtrconfig")
        _add_owner(gtrconfig_mock_ctx, str(git_repo))

        # .gtrconfig を作成
        gtrconfig = GtrconfigManager(str(git_repo))
        gtrconfig.write({"copy": {"include": ["*.md"]}})

        result = await check_gtrconfig(
            project_path=str(git_repo),
            caller_agent_id="owner-001",
            ctx=gtrconfig_mock_ctx,
        )

        assert result["success"] is True
        assert result["status"]["exists"] is True
        assert result["status"]["config"] is not None

    @pytest.mark.asyncio
    async def test_check_gtrconfig_worker_denied(self, gtrconfig_mock_ctx, git_repo):
        """Worker からの呼び出しが拒否されることをテスト。"""
        mcp = _register_tools()
        check_gtrconfig = _get_tool_fn(mcp, "check_gtrconfig")
        _add_worker(gtrconfig_mock_ctx, str(git_repo))

        result = await check_gtrconfig(
            project_path=str(git_repo),
            caller_agent_id="worker-001",
            ctx=gtrconfig_mock_ctx,
        )

        assert result["success"] is False
        assert "使用禁止" in result["error"]

    @pytest.mark.asyncio
    async def test_check_gtrconfig_git_disabled(self, gtrconfig_mock_ctx, git_repo):
        """enable_git=false の場合にエラーを返すことをテスト。"""
        mcp = _register_tools()
        check_gtrconfig = _get_tool_fn(mcp, "check_gtrconfig")
        _add_owner(gtrconfig_mock_ctx, str(git_repo))

        app_ctx = gtrconfig_mock_ctx.request_context.lifespan_context
        app_ctx.settings.enable_git = False

        result = await check_gtrconfig(
            project_path=str(git_repo),
            caller_agent_id="owner-001",
            ctx=gtrconfig_mock_ctx,
        )

        assert result["success"] is False
        assert "MCP_ENABLE_GIT=false" in result["error"]


class TestAnalyzeProjectForGtrconfig:
    """analyze_project_for_gtrconfig ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_analyze_project_success(self, gtrconfig_mock_ctx, git_repo):
        """プロジェクト解析が成功することをテスト。"""
        mcp = _register_tools()
        analyze = _get_tool_fn(mcp, "analyze_project_for_gtrconfig")
        _add_owner(gtrconfig_mock_ctx, str(git_repo))

        result = await analyze(
            project_path=str(git_repo),
            caller_agent_id="owner-001",
            ctx=gtrconfig_mock_ctx,
        )

        assert result["success"] is True
        assert "recommended_config" in result
        assert "copy" in result["recommended_config"]
        assert "hooks" in result["recommended_config"]

    @pytest.mark.asyncio
    async def test_analyze_project_detects_python(self, gtrconfig_mock_ctx, git_repo):
        """Python プロジェクトが検出されることをテスト。"""
        mcp = _register_tools()
        analyze = _get_tool_fn(mcp, "analyze_project_for_gtrconfig")
        _add_owner(gtrconfig_mock_ctx, str(git_repo))

        # pyproject.toml を作成
        (git_repo / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        (git_repo / "uv.lock").write_text("")

        result = await analyze(
            project_path=str(git_repo),
            caller_agent_id="owner-001",
            ctx=gtrconfig_mock_ctx,
        )

        assert result["success"] is True
        hooks = result["recommended_config"]["hooks"]["postCreate"]
        assert "uv sync" in hooks

    @pytest.mark.asyncio
    async def test_analyze_project_git_disabled(self, gtrconfig_mock_ctx, git_repo):
        """enable_git=false の場合にエラーを返すことをテスト。"""
        mcp = _register_tools()
        analyze = _get_tool_fn(mcp, "analyze_project_for_gtrconfig")
        _add_owner(gtrconfig_mock_ctx, str(git_repo))

        app_ctx = gtrconfig_mock_ctx.request_context.lifespan_context
        app_ctx.settings.enable_git = False

        result = await analyze(
            project_path=str(git_repo),
            caller_agent_id="owner-001",
            ctx=gtrconfig_mock_ctx,
        )

        assert result["success"] is False
        assert "MCP_ENABLE_GIT=false" in result["error"]


class TestGenerateGtrconfig:
    """generate_gtrconfig ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_generate_success(self, gtrconfig_mock_ctx, git_repo):
        """Gtrconfig を生成できることをテスト。"""
        mcp = _register_tools()
        generate = _get_tool_fn(mcp, "generate_gtrconfig")
        _add_owner(gtrconfig_mock_ctx, str(git_repo))

        result = await generate(
            project_path=str(git_repo),
            caller_agent_id="owner-001",
            ctx=gtrconfig_mock_ctx,
        )

        assert result["success"] is True
        assert "config" in result
        assert ".gtrconfig を生成しました" in result["message"]

        # ファイルが実際に作成されたか確認
        assert (git_repo / ".gtrconfig").exists()

    @pytest.mark.asyncio
    async def test_generate_already_exists(self, gtrconfig_mock_ctx, git_repo):
        """既存 .gtrconfig がある場合にエラーになることをテスト。"""
        mcp = _register_tools()
        generate = _get_tool_fn(mcp, "generate_gtrconfig")
        _add_owner(gtrconfig_mock_ctx, str(git_repo))

        # 既に .gtrconfig を作成
        gtrconfig = GtrconfigManager(str(git_repo))
        gtrconfig.write({"copy": {"include": []}})

        result = await generate(
            project_path=str(git_repo),
            overwrite=False,
            caller_agent_id="owner-001",
            ctx=gtrconfig_mock_ctx,
        )

        assert result["success"] is False
        assert "既に存在" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_overwrite(self, gtrconfig_mock_ctx, git_repo):
        """overwrite=True の場合に上書き生成できることをテスト。"""
        mcp = _register_tools()
        generate = _get_tool_fn(mcp, "generate_gtrconfig")
        _add_owner(gtrconfig_mock_ctx, str(git_repo))

        # 既に .gtrconfig を作成
        gtrconfig = GtrconfigManager(str(git_repo))
        gtrconfig.write({"copy": {"include": []}})

        result = await generate(
            project_path=str(git_repo),
            overwrite=True,
            caller_agent_id="owner-001",
            ctx=gtrconfig_mock_ctx,
        )

        assert result["success"] is True
        assert "config" in result

    @pytest.mark.asyncio
    async def test_generate_git_disabled(self, gtrconfig_mock_ctx, git_repo):
        """enable_git=false の場合にエラーを返すことをテスト。"""
        mcp = _register_tools()
        generate = _get_tool_fn(mcp, "generate_gtrconfig")
        _add_owner(gtrconfig_mock_ctx, str(git_repo))

        app_ctx = gtrconfig_mock_ctx.request_context.lifespan_context
        app_ctx.settings.enable_git = False

        result = await generate(
            project_path=str(git_repo),
            caller_agent_id="owner-001",
            ctx=gtrconfig_mock_ctx,
        )

        assert result["success"] is False
        assert "MCP_ENABLE_GIT=false" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_worker_denied(self, gtrconfig_mock_ctx, git_repo):
        """Worker からの生成が拒否されることをテスト。"""
        mcp = _register_tools()
        generate = _get_tool_fn(mcp, "generate_gtrconfig")
        _add_worker(gtrconfig_mock_ctx, str(git_repo))

        result = await generate(
            project_path=str(git_repo),
            caller_agent_id="worker-001",
            ctx=gtrconfig_mock_ctx,
        )

        assert result["success"] is False
        assert "使用禁止" in result["error"]
