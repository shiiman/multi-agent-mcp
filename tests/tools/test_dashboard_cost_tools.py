"""ダッシュボード コスト管理ツールのテスト。"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.dashboard_manager import DashboardManager
from src.managers.ipc_manager import IPCManager
from src.managers.memory_manager import MemoryManager
from src.managers.persona_manager import PersonaManager
from src.managers.scheduler_manager import SchedulerManager
from src.managers.tmux_manager import TmuxManager
from src.models.agent import Agent, AgentRole, AgentStatus


def _get_tool_fn(mcp, tool_name: str):
    """MCP ツール関数をツール名から取得するヘルパー。"""
    for tool in mcp._tool_manager._tools.values():
        if tool.name == tool_name:
            return tool.fn
    return None


@pytest.fixture
def cost_test_ctx(git_repo, settings):
    """コストツールテスト用の AppContext を作成する。"""
    mock_tmux = MagicMock(spec=TmuxManager)
    mock_tmux.settings = settings
    ai_cli = AiCliManager(settings)

    ipc_dir = git_repo / ".ipc"
    ipc = IPCManager(str(ipc_dir))
    ipc.initialize()

    dashboard_dir = git_repo / ".dashboard"
    dashboard = DashboardManager(
        workspace_id="test-workspace",
        workspace_path=str(git_repo),
        dashboard_dir=str(dashboard_dir),
    )
    dashboard.initialize()

    memory_dir = git_repo / ".memory"
    memory = MemoryManager(str(memory_dir))
    persona = PersonaManager()
    scheduler = SchedulerManager(dashboard, {})

    ctx = AppContext(
        settings=settings,
        tmux=mock_tmux,
        ai_cli=ai_cli,
        agents={},
        ipc_manager=ipc,
        dashboard_manager=dashboard,
        scheduler_manager=scheduler,
        memory_manager=memory,
        persona_manager=persona,
        workspace_id="test-workspace",
        project_root=str(git_repo),
        session_id="test-session",
    )

    yield ctx

    ipc.cleanup()
    dashboard.cleanup()


@pytest.fixture
def cost_mock_ctx(cost_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = cost_test_ctx
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
    """コストツールを登録した FastMCP インスタンスを返す。"""
    from mcp.server.fastmcp import FastMCP

    from src.tools.dashboard_cost_tools import register_tools

    mcp = FastMCP("test")
    register_tools(mcp)
    return mcp


class TestGetCostEstimate:
    """get_cost_estimate ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_cost_estimate_success(self, cost_mock_ctx, git_repo):
        """コスト推定を取得できることをテスト。"""
        mcp = _register_tools()
        get_estimate = _get_tool_fn(mcp, "get_cost_estimate")
        _add_agent(cost_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))

        result = await get_estimate(
            caller_agent_id="owner-001",
            ctx=cost_mock_ctx,
        )

        assert result["success"] is True
        assert "estimate" in result
        assert "warning" in result

    @pytest.mark.asyncio
    async def test_get_cost_estimate_admin_allowed(self, cost_mock_ctx, git_repo):
        """Admin からの呼び出しが許可されることをテスト。"""
        mcp = _register_tools()
        get_estimate = _get_tool_fn(mcp, "get_cost_estimate")
        _add_agent(cost_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        result = await get_estimate(
            caller_agent_id="admin-001",
            ctx=cost_mock_ctx,
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_get_cost_estimate_worker_denied(self, cost_mock_ctx, git_repo):
        """Worker からの呼び出しが拒否されることをテスト。"""
        mcp = _register_tools()
        get_estimate = _get_tool_fn(mcp, "get_cost_estimate")
        _add_agent(cost_mock_ctx, "worker-001", AgentRole.WORKER, str(git_repo))

        result = await get_estimate(
            caller_agent_id="worker-001",
            ctx=cost_mock_ctx,
        )

        assert result["success"] is False
        assert "使用禁止" in result["error"]


class TestSetCostWarningThreshold:
    """set_cost_warning_threshold ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_set_threshold_success(self, cost_mock_ctx, git_repo):
        """閾値を設定できることをテスト。"""
        mcp = _register_tools()
        set_threshold = _get_tool_fn(mcp, "set_cost_warning_threshold")
        _add_agent(cost_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))

        result = await set_threshold(
            threshold_usd=25.0,
            caller_agent_id="owner-001",
            ctx=cost_mock_ctx,
        )

        assert result["success"] is True
        assert result["threshold"] == 25.0
        assert "$25.00" in result["message"]

    @pytest.mark.asyncio
    async def test_set_threshold_admin_denied(self, cost_mock_ctx, git_repo):
        """Admin からの呼び出しが拒否されることをテスト。"""
        mcp = _register_tools()
        set_threshold = _get_tool_fn(mcp, "set_cost_warning_threshold")
        _add_agent(cost_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        result = await set_threshold(
            threshold_usd=25.0,
            caller_agent_id="admin-001",
            ctx=cost_mock_ctx,
        )

        assert result["success"] is False
        assert "使用禁止" in result["error"]


class TestResetCostCounter:
    """reset_cost_counter ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_reset_counter_success(self, cost_mock_ctx, git_repo):
        """コストカウンターをリセットできることをテスト。"""
        mcp = _register_tools()
        reset = _get_tool_fn(mcp, "reset_cost_counter")
        _add_agent(cost_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))

        result = await reset(
            caller_agent_id="owner-001",
            ctx=cost_mock_ctx,
        )

        assert result["success"] is True
        assert "deleted_count" in result
        assert "リセット" in result["message"]

    @pytest.mark.asyncio
    async def test_reset_counter_admin_denied(self, cost_mock_ctx, git_repo):
        """Admin からのリセットが拒否されることをテスト。"""
        mcp = _register_tools()
        reset = _get_tool_fn(mcp, "reset_cost_counter")
        _add_agent(cost_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        result = await reset(
            caller_agent_id="admin-001",
            ctx=cost_mock_ctx,
        )

        assert result["success"] is False
        assert "使用禁止" in result["error"]


class TestGetCostSummary:
    """get_cost_summary ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_summary_success(self, cost_mock_ctx, git_repo):
        """コストサマリーを取得できることをテスト。"""
        mcp = _register_tools()
        get_summary = _get_tool_fn(mcp, "get_cost_summary")
        _add_agent(cost_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))

        result = await get_summary(
            caller_agent_id="owner-001",
            ctx=cost_mock_ctx,
        )

        assert result["success"] is True
        assert "summary" in result
        assert "estimated_cost_usd" in result["summary"]

    @pytest.mark.asyncio
    async def test_get_summary_worker_allowed(self, cost_mock_ctx, git_repo):
        """Worker からの呼び出しが許可されることをテスト。"""
        mcp = _register_tools()
        get_summary = _get_tool_fn(mcp, "get_cost_summary")
        _add_agent(cost_mock_ctx, "worker-001", AgentRole.WORKER, str(git_repo))

        result = await get_summary(
            caller_agent_id="worker-001",
            ctx=cost_mock_ctx,
        )

        assert result["success"] is True
        assert "summary" in result
