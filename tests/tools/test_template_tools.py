"""テンプレート管理ツールのテスト。"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from tests.conftest import get_tool_fn
from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.tmux_manager import TmuxManager
from src.models.agent import Agent, AgentRole, AgentStatus


@pytest.fixture
def template_test_ctx(git_repo, settings):
    """テンプレートツールテスト用の AppContext を作成する。"""
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
def template_mock_ctx(template_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = template_test_ctx
    return mock


def _add_agent(mock_ctx, agent_id: str, role: AgentRole, working_dir: str) -> None:
    """テスト用にエージェントを追加するヘルパー。"""
    app_ctx = mock_ctx.request_context.lifespan_context
    now = datetime.now()
    app_ctx.agents[agent_id] = Agent(
        id=agent_id,
        role=role,
        status=AgentStatus.IDLE,
        tmux_session="test:0.1" if role == AgentRole.WORKER else None,
        working_dir=working_dir,
        created_at=now,
        last_activity=now,
    )


def _register_tools():
    """テンプレートツールを登録した FastMCP インスタンスを返す。"""
    from mcp.server.fastmcp import FastMCP

    from src.tools.template import register_tools

    mcp = FastMCP("test")
    register_tools(mcp)
    return mcp


class TestListWorkspaceTemplates:
    """list_workspace_templates ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_list_templates_success(self, template_mock_ctx, git_repo):
        """テンプレート一覧を取得できることをテスト。"""
        mcp = _register_tools()
        list_templates = get_tool_fn(mcp, "list_workspace_templates")
        _add_agent(template_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))

        result = await list_templates(
            caller_agent_id="owner-001",
            ctx=template_mock_ctx,
        )

        assert result["success"] is True
        assert "templates" in result
        assert "names" in result
        assert isinstance(result["templates"], list)
        assert isinstance(result["names"], list)

    @pytest.mark.asyncio
    async def test_list_templates_admin_allowed(self, template_mock_ctx, git_repo):
        """Admin からの呼び出しが許可されることをテスト。"""
        mcp = _register_tools()
        list_templates = get_tool_fn(mcp, "list_workspace_templates")
        _add_agent(template_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        result = await list_templates(
            caller_agent_id="admin-001",
            ctx=template_mock_ctx,
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_list_templates_worker_denied(self, template_mock_ctx, git_repo):
        """Worker からの呼び出しが拒否されることをテスト。"""
        mcp = _register_tools()
        list_templates = get_tool_fn(mcp, "list_workspace_templates")
        _add_agent(template_mock_ctx, "worker-001", AgentRole.WORKER, str(git_repo))

        result = await list_templates(
            caller_agent_id="worker-001",
            ctx=template_mock_ctx,
        )

        assert result["success"] is False
        assert "使用禁止" in result["error"]


class TestGetWorkspaceTemplate:
    """get_workspace_template ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_template_success(self, template_mock_ctx, git_repo):
        """テンプレートを取得できることをテスト。"""
        mcp = _register_tools()
        get_template = get_tool_fn(mcp, "get_workspace_template")
        list_templates = get_tool_fn(mcp, "list_workspace_templates")
        _add_agent(template_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))

        # テンプレート名を取得
        list_result = await list_templates(
            caller_agent_id="owner-001",
            ctx=template_mock_ctx,
        )
        if not list_result["names"]:
            pytest.skip("テンプレートが定義されていない")

        template_name = list_result["names"][0]

        result = await get_template(
            template_name=template_name,
            caller_agent_id="owner-001",
            ctx=template_mock_ctx,
        )

        assert result["success"] is True
        assert "template" in result

    @pytest.mark.asyncio
    async def test_get_nonexistent_template(self, template_mock_ctx, git_repo):
        """存在しないテンプレート名でエラーを返すことをテスト。"""
        mcp = _register_tools()
        get_template = get_tool_fn(mcp, "get_workspace_template")
        _add_agent(template_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))

        result = await get_template(
            template_name="nonexistent-template",
            caller_agent_id="owner-001",
            ctx=template_mock_ctx,
        )

        assert result["success"] is False
        assert "見つかりません" in result["error"]


class TestGetRoleGuide:
    """get_role_guide ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_role_guide_owner(self, template_mock_ctx, git_repo):
        """Owner ロールガイドを取得できることをテスト。"""
        mcp = _register_tools()
        get_guide = get_tool_fn(mcp, "get_role_guide")
        _add_agent(template_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))

        result = await get_guide(
            role="owner",
            caller_agent_id="owner-001",
            ctx=template_mock_ctx,
        )

        assert result["success"] is True
        assert "guide" in result

    @pytest.mark.asyncio
    async def test_get_role_guide_worker(self, template_mock_ctx, git_repo):
        """Worker ロールガイドを取得できることをテスト。"""
        mcp = _register_tools()
        get_guide = get_tool_fn(mcp, "get_role_guide")
        _add_agent(template_mock_ctx, "worker-001", AgentRole.WORKER, str(git_repo))

        result = await get_guide(
            role="worker",
            caller_agent_id="worker-001",
            ctx=template_mock_ctx,
        )

        assert result["success"] is True
        assert "guide" in result

    @pytest.mark.asyncio
    async def test_get_role_guide_invalid_role(self, template_mock_ctx, git_repo):
        """無効なロールでエラーを返すことをテスト。"""
        mcp = _register_tools()
        get_guide = get_tool_fn(mcp, "get_role_guide")
        _add_agent(template_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))

        result = await get_guide(
            role="invalid-role",
            caller_agent_id="owner-001",
            ctx=template_mock_ctx,
        )

        assert result["success"] is False
        assert "見つかりません" in result["error"]


class TestListRoleGuides:
    """list_role_guides ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_list_role_guides_success(self, template_mock_ctx, git_repo):
        """ロールガイド一覧を取得できることをテスト。"""
        mcp = _register_tools()
        list_guides = get_tool_fn(mcp, "list_role_guides")
        _add_agent(template_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))

        result = await list_guides(
            caller_agent_id="owner-001",
            ctx=template_mock_ctx,
        )

        assert result["success"] is True
        assert "roles" in result
        assert isinstance(result["roles"], list)

    @pytest.mark.asyncio
    async def test_list_role_guides_worker_allowed(self, template_mock_ctx, git_repo):
        """Worker からの呼び出しが許可されることをテスト。"""
        mcp = _register_tools()
        list_guides = get_tool_fn(mcp, "list_role_guides")
        _add_agent(template_mock_ctx, "worker-001", AgentRole.WORKER, str(git_repo))

        result = await list_guides(
            caller_agent_id="worker-001",
            ctx=template_mock_ctx,
        )

        assert result["success"] is True
