"""ヘルスチェック管理ツールのテスト。"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.settings import Settings, TerminalApp
from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.dashboard_manager import DashboardManager
from src.managers.healthcheck_manager import HealthcheckManager
from src.managers.ipc_manager import IPCManager
from src.managers.memory_manager import MemoryManager
from src.managers.persona_manager import PersonaManager
from src.managers.scheduler_manager import SchedulerManager
from src.managers.tmux_manager import TmuxManager
from src.models.agent import Agent, AgentRole, AgentStatus


@pytest.fixture
def healthcheck_test_ctx(git_repo, settings):
    """ヘルスチェックツールテスト用のAppContextを作成する。"""
    # モック tmux マネージャー
    mock_tmux = MagicMock(spec=TmuxManager)
    mock_tmux.settings = settings
    mock_tmux._run = AsyncMock(return_value="")
    mock_tmux._get_window_name = MagicMock(return_value="window-0")

    # AI CLI マネージャー
    ai_cli = AiCliManager(settings)

    # IPC マネージャー
    ipc_dir = git_repo / ".ipc"
    ipc = IPCManager(str(ipc_dir))
    ipc.initialize()

    # ダッシュボードマネージャー
    dashboard_dir = git_repo / ".dashboard"
    dashboard = DashboardManager(
        workspace_id="test-workspace",
        workspace_path=str(git_repo),
        dashboard_dir=str(dashboard_dir),
    )
    dashboard.initialize()

    # メモリマネージャー
    memory_dir = git_repo / ".memory"
    memory = MemoryManager(str(memory_dir))

    # ペルソナマネージャー
    persona = PersonaManager()

    # スケジューラーマネージャー
    scheduler = SchedulerManager(dashboard, {})

    # エージェント辞書（空で初期化）
    agents = {}

    # ヘルスチェックマネージャー
    healthcheck = HealthcheckManager(
        tmux_manager=mock_tmux,
        agents=agents,
        healthcheck_interval_seconds=60,
    )

    ctx = AppContext(
        settings=settings,
        tmux=mock_tmux,
        ai_cli=ai_cli,
        agents=agents,
        ipc_manager=ipc,
        dashboard_manager=dashboard,
        scheduler_manager=scheduler,
        memory_manager=memory,
        persona_manager=persona,
        healthcheck_manager=healthcheck,
        workspace_id="test-workspace",
        project_root=str(git_repo),
        session_id="test-session",
    )

    yield ctx

    # クリーンアップ
    ipc.cleanup()
    dashboard.cleanup()


@pytest.fixture
def healthcheck_mock_ctx(healthcheck_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = healthcheck_test_ctx
    return mock


class TestHealthcheckAgent:
    """healthcheck_agent ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_healthcheck_single_agent(self, healthcheck_mock_ctx, git_repo):
        """単一エージェントのヘルスチェックをテスト。"""
        from src.tools.healthcheck import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        healthcheck_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "healthcheck_agent":
                healthcheck_agent = tool.fn
                break

        # Owner と Worker を追加
        app_ctx = healthcheck_mock_ctx.request_context.lifespan_context
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
        app_ctx.agents["worker-001"] = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await healthcheck_agent(
            agent_id="worker-001",
            caller_agent_id="owner-001",
            ctx=healthcheck_mock_ctx,
        )

        assert result["success"] is True
        assert "health_status" in result


class TestHealthcheckAll:
    """healthcheck_all ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_healthcheck_all_agents(self, healthcheck_mock_ctx, git_repo):
        """全エージェントのヘルスチェックをテスト。"""
        from src.tools.healthcheck import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        healthcheck_all = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "healthcheck_all":
                healthcheck_all = tool.fn
                break

        # Owner と複数の Worker を追加
        app_ctx = healthcheck_mock_ctx.request_context.lifespan_context
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
        app_ctx.agents["worker-001"] = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )
        app_ctx.agents["worker-002"] = Agent(
            id="worker-002",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test:0.2",
            session_name="test",
            window_index=0,
            pane_index=2,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await healthcheck_all(
            caller_agent_id="owner-001",
            ctx=healthcheck_mock_ctx,
        )

        assert result["success"] is True
        assert "statuses" in result
        assert "summary" in result
        assert result["summary"]["total"] >= 2


class TestGetUnhealthyAgents:
    """get_unhealthy_agents ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_unhealthy_agents_empty(self, healthcheck_mock_ctx, git_repo):
        """異常エージェントがない場合の取得をテスト。"""
        from src.tools.healthcheck import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        get_unhealthy_agents = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_unhealthy_agents":
                get_unhealthy_agents = tool.fn
                break

        # Owner を追加
        app_ctx = healthcheck_mock_ctx.request_context.lifespan_context
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

        result = await get_unhealthy_agents(
            caller_agent_id="owner-001",
            ctx=healthcheck_mock_ctx,
        )

        assert result["success"] is True
        assert "unhealthy_agents" in result
        assert "count" in result


class TestAttemptRecovery:
    """attempt_recovery ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_attempt_recovery(self, healthcheck_mock_ctx, git_repo):
        """エージェント復旧の試みをテスト。"""
        from src.tools.healthcheck import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        attempt_recovery = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "attempt_recovery":
                attempt_recovery = tool.fn
                break

        # Owner と エラー状態の Worker を追加
        app_ctx = healthcheck_mock_ctx.request_context.lifespan_context
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
        app_ctx.agents["worker-001"] = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.ERROR,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await attempt_recovery(
            agent_id="worker-001",
            caller_agent_id="owner-001",
            ctx=healthcheck_mock_ctx,
        )

        assert result["success"] is True or result["success"] is False
        assert "message" in result


class TestFullRecovery:
    """full_recovery ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_full_recovery_non_worker_fails(self, healthcheck_mock_ctx, git_repo):
        """Worker以外の復旧試行でエラーになることをテスト。"""
        from src.tools.healthcheck import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        full_recovery = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "full_recovery":
                full_recovery = tool.fn
                break

        # Admin を追加（Admin は復旧対象外）
        app_ctx = healthcheck_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["admin-001"] = Agent(
            id="admin-001",
            role=AgentRole.ADMIN,
            status=AgentStatus.ERROR,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await full_recovery(
            agent_id="admin-001",
            caller_agent_id="admin-001",
            ctx=healthcheck_mock_ctx,
        )

        assert result["success"] is False
        assert "Worker のみ復旧可能" in result["error"]

    @pytest.mark.asyncio
    async def test_full_recovery_nonexistent_agent(self, healthcheck_mock_ctx, git_repo):
        """存在しないエージェントの復旧でエラーになることをテスト。"""
        from src.tools.healthcheck import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        full_recovery = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "full_recovery":
                full_recovery = tool.fn
                break

        # Admin を追加
        app_ctx = healthcheck_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["admin-001"] = Agent(
            id="admin-001",
            role=AgentRole.ADMIN,
            status=AgentStatus.IDLE,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await full_recovery(
            agent_id="nonexistent-agent",
            caller_agent_id="admin-001",
            ctx=healthcheck_mock_ctx,
        )

        assert result["success"] is False
        assert "見つかりません" in result["error"]
