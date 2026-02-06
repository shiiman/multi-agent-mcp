"""エージェント管理ツールのテスト。"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import AICli, Settings, TerminalApp
from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.dashboard_manager import DashboardManager
from src.managers.ipc_manager import IPCManager
from src.managers.memory_manager import MemoryManager
from src.managers.persona_manager import PersonaManager
from src.managers.scheduler_manager import SchedulerManager
from src.managers.tmux_manager import TmuxManager
from src.models.agent import Agent, AgentRole, AgentStatus


@pytest.fixture
def tool_test_ctx(git_repo, settings):
    """ツールテスト用のAppContextを作成する（git リポジトリを使用）。"""
    # モック tmux マネージャー
    mock_tmux = MagicMock(spec=TmuxManager)
    mock_tmux.create_main_session = AsyncMock(return_value=True)
    mock_tmux.send_keys = AsyncMock(return_value=True)
    mock_tmux.send_keys_to_pane = AsyncMock(return_value=True)
    mock_tmux.session_exists = AsyncMock(return_value=True)
    mock_tmux.set_pane_title = AsyncMock(return_value=True)
    mock_tmux.add_extra_worker_window = AsyncMock(return_value=True)
    mock_tmux._get_window_name = MagicMock(return_value="main")
    mock_tmux._run = AsyncMock(return_value="")
    mock_tmux.settings = settings

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

    # クリーンアップ
    ipc.cleanup()
    dashboard.cleanup()


@pytest.fixture
def mock_ctx(tool_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = tool_test_ctx
    return mock


class TestCreateAgent:
    """create_agent ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_create_owner_success(self, mock_ctx, git_repo):
        """Ownerエージェントを作成できることをテスト。"""
        from src.tools.agent import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        # create_agent ツールを取得
        create_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_agent":
                create_agent = tool.fn
                break

        assert create_agent is not None

        result = await create_agent(
            role="owner",
            working_dir=str(git_repo),
            ctx=mock_ctx,
        )

        assert result["success"] is True
        assert "agent" in result
        assert result["agent"]["role"] == "owner"

    @pytest.mark.asyncio
    async def test_create_admin_success(self, mock_ctx, git_repo):
        """Adminエージェントを作成できることをテスト。"""
        from src.tools.agent import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        create_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_agent":
                create_agent = tool.fn
                break

        # まず Owner を作成
        app_ctx = mock_ctx.request_context.lifespan_context
        now = datetime.now()
        owner = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )
        app_ctx.agents["owner-001"] = owner

        result = await create_agent(
            role="admin",
            working_dir=str(git_repo),
            caller_agent_id="owner-001",
            ctx=mock_ctx,
        )

        assert result["success"] is True
        assert result["agent"]["role"] == "admin"

    @pytest.mark.asyncio
    async def test_create_worker_success(self, mock_ctx, git_repo):
        """Workerエージェントを作成できることをテスト。"""
        from src.tools.agent import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        create_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_agent":
                create_agent = tool.fn
                break

        # Owner を作成
        app_ctx = mock_ctx.request_context.lifespan_context
        now = datetime.now()
        owner = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )
        app_ctx.agents["owner-001"] = owner

        result = await create_agent(
            role="worker",
            working_dir=str(git_repo),
            caller_agent_id="owner-001",
            ctx=mock_ctx,
        )

        assert result["success"] is True
        assert result["agent"]["role"] == "worker"

    @pytest.mark.asyncio
    async def test_create_duplicate_owner_fails(self, mock_ctx, git_repo):
        """Ownerが既に存在する場合に失敗することをテスト。"""
        from src.tools.agent import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        create_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_agent":
                create_agent = tool.fn
                break

        # 最初の Owner を作成
        result1 = await create_agent(
            role="owner",
            working_dir=str(git_repo),
            ctx=mock_ctx,
        )
        assert result1["success"] is True

        # 2つ目の Owner を作成しようとする
        result2 = await create_agent(
            role="owner",
            working_dir=str(git_repo),
            ctx=mock_ctx,
        )
        assert result2["success"] is False
        assert "既に存在します" in result2["error"]

    @pytest.mark.asyncio
    async def test_invalid_role_fails(self, mock_ctx, git_repo):
        """無効なロールでエラーになることをテスト。"""
        from src.tools.agent import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        create_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_agent":
                create_agent = tool.fn
                break

        result = await create_agent(
            role="invalid_role",
            working_dir=str(git_repo),
            ctx=mock_ctx,
        )

        assert result["success"] is False
        assert "無効な役割" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_ai_cli_fails(self, mock_ctx, git_repo):
        """無効なAI CLIでエラーになることをテスト。"""
        from src.tools.agent import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        create_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_agent":
                create_agent = tool.fn
                break

        result = await create_agent(
            role="owner",
            working_dir=str(git_repo),
            ai_cli="invalid_cli",
            ctx=mock_ctx,
        )

        assert result["success"] is False
        assert "無効なAI CLI" in result["error"]


class TestListAgents:
    """list_agents ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_list_all_agents(self, mock_ctx, git_repo):
        """全エージェントを取得できることをテスト。"""
        from src.tools.agent import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        list_agents = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "list_agents":
                list_agents = tool.fn
                break

        # エージェントを追加
        app_ctx = mock_ctx.request_context.lifespan_context
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
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await list_agents(
            caller_agent_id="owner-001",
            ctx=mock_ctx,
        )

        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["agents"]) == 2

    @pytest.mark.asyncio
    async def test_list_empty_agents(self, mock_ctx):
        """エージェントがない場合に空リストを返すことをテスト。"""
        from src.tools.agent import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        list_agents = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "list_agents":
                list_agents = tool.fn
                break

        # Owner を追加（caller_agent_id 用）
        app_ctx = mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            created_at=now,
            last_activity=now,
        )

        result = await list_agents(
            caller_agent_id="owner-001",
            ctx=mock_ctx,
        )

        assert result["success"] is True
        assert result["count"] == 1  # Owner のみ


class TestGetAgentStatus:
    """get_agent_status ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_existing_agent_status(self, mock_ctx, git_repo):
        """存在するエージェントのステータスを取得できることをテスト。"""
        from src.tools.agent import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        get_agent_status = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_agent_status":
                get_agent_status = tool.fn
                break

        # エージェントを追加
        app_ctx = mock_ctx.request_context.lifespan_context
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
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await get_agent_status(
            agent_id="worker-001",
            caller_agent_id="owner-001",
            ctx=mock_ctx,
        )

        assert result["success"] is True
        assert result["agent"]["id"] == "worker-001"
        assert result["agent"]["status"] == "busy"

    @pytest.mark.asyncio
    async def test_get_nonexistent_agent_fails(self, mock_ctx, git_repo):
        """存在しないエージェントでエラーになることをテスト。"""
        from src.tools.agent import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        get_agent_status = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_agent_status":
                get_agent_status = tool.fn
                break

        # Owner を追加
        app_ctx = mock_ctx.request_context.lifespan_context
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

        result = await get_agent_status(
            agent_id="nonexistent",
            caller_agent_id="owner-001",
            ctx=mock_ctx,
        )

        assert result["success"] is False
        assert "見つかりません" in result["error"]


class TestTerminateAgent:
    """terminate_agent ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_terminate_worker_success(self, mock_ctx, git_repo):
        """Workerエージェントを終了できることをテスト。"""
        from src.tools.agent import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        terminate_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "terminate_agent":
                terminate_agent = tool.fn
                break

        # エージェントを追加
        app_ctx = mock_ctx.request_context.lifespan_context
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
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await terminate_agent(
            agent_id="worker-001",
            caller_agent_id="owner-001",
            ctx=mock_ctx,
        )

        assert result["success"] is True
        assert result["status"] == "terminated"
        assert app_ctx.agents["worker-001"].status == "terminated"

    @pytest.mark.asyncio
    async def test_terminate_nonexistent_agent_fails(self, mock_ctx, git_repo):
        """存在しないエージェントの終了が失敗することをテスト。"""
        from src.tools.agent import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        terminate_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "terminate_agent":
                terminate_agent = tool.fn
                break

        # Owner を追加
        app_ctx = mock_ctx.request_context.lifespan_context
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

        result = await terminate_agent(
            agent_id="nonexistent",
            caller_agent_id="owner-001",
            ctx=mock_ctx,
        )

        assert result["success"] is False
        assert "見つかりません" in result["error"]


class TestGetNextWorkerSlot:
    """_get_next_worker_slot 関数のテスト。"""

    def test_empty_agents(self, settings):
        """エージェントがない場合に最初のスロットを返すことをテスト。"""
        from src.tools.agent import _get_next_worker_slot

        slot = _get_next_worker_slot({}, settings, "test-project")

        assert slot is not None
        window_index, pane_index = slot
        assert window_index == 0
        assert pane_index == 1  # 最初の Worker スロット

    def test_some_workers_exist(self, settings):
        """いくつかのWorkerがある場合に次のスロットを返すことをテスト。"""
        from src.tools.agent import _get_next_worker_slot

        now = datetime.now()
        agents = {
            "worker-1": Agent(
                id="worker-1",
                role=AgentRole.WORKER,
                status=AgentStatus.IDLE,
                tmux_session="test-project:0.1",
                session_name="test-project",
                window_index=0,
                pane_index=1,
                created_at=now,
                last_activity=now,
            ),
        }

        slot = _get_next_worker_slot(agents, settings, "test-project")

        assert slot is not None
        window_index, pane_index = slot
        assert window_index == 0
        assert pane_index == 2  # 次の Worker スロット

    def test_max_workers_reached(self, settings):
        """Worker数が上限に達した場合にNoneを返すことをテスト。"""
        from src.tools.agent import _get_next_worker_slot

        now = datetime.now()
        agents = {}
        for i in range(settings.max_workers):
            agents[f"worker-{i}"] = Agent(
                id=f"worker-{i}",
                role=AgentRole.WORKER,
                status=AgentStatus.IDLE,
                tmux_session=f"test-project:0.{i + 1}",
                session_name="test-project",
                window_index=0,
                pane_index=i + 1,
                created_at=now,
                last_activity=now,
            )

        slot = _get_next_worker_slot(agents, settings, "test-project")

        assert slot is None
