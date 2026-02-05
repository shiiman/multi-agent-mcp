"""ダッシュボード/タスク管理ツールのテスト。"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import Settings, TerminalApp
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
def dashboard_test_ctx(git_repo, settings):
    """ダッシュボードツールテスト用のAppContextを作成する。"""
    # モック tmux マネージャー
    mock_tmux = MagicMock(spec=TmuxManager)
    mock_tmux.create_main_session = AsyncMock(return_value=True)
    mock_tmux.send_keys = AsyncMock(return_value=True)
    mock_tmux.send_keys_to_pane = AsyncMock(return_value=True)
    mock_tmux.session_exists = AsyncMock(return_value=True)
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
def dashboard_mock_ctx(dashboard_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = dashboard_test_ctx
    return mock


class TestCreateTask:
    """create_task ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_create_task_success(self, dashboard_mock_ctx, git_repo):
        """タスクを作成できることをテスト。"""
        from src.tools.dashboard import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        create_task = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_task":
                create_task = tool.fn
                break

        # Owner を追加
        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
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

        result = await create_task(
            title="テストタスク",
            description="タスクの説明",
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is True
        assert "task" in result
        assert result["task"]["title"] == "テストタスク"

    @pytest.mark.asyncio
    async def test_create_task_with_assignment(self, dashboard_mock_ctx, git_repo):
        """エージェント割り当て付きでタスクを作成できることをテスト。"""
        from src.tools.dashboard import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        create_task = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_task":
                create_task = tool.fn
                break

        # エージェントを追加
        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
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

        result = await create_task(
            title="割り当て付きタスク",
            description="説明",
            assigned_agent_id="worker-001",
            branch="feature/test",
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is True
        assert result["task"]["assigned_agent_id"] == "worker-001"
        assert result["task"]["branch"] == "feature/test"


class TestUpdateTaskStatus:
    """update_task_status ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_update_to_in_progress(self, dashboard_mock_ctx, git_repo):
        """タスクステータスを in_progress に更新できることをテスト。"""
        from src.tools.dashboard import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        create_task = None
        update_task_status = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_task":
                create_task = tool.fn
            elif tool.name == "update_task_status":
                update_task_status = tool.fn

        # エージェントを追加
        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
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
        app_ctx.agents["admin-001"] = Agent(
            id="admin-001",
            role=AgentRole.ADMIN,
            status=AgentStatus.IDLE,
            tmux_session="test:0.0",
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        # タスク作成
        create_result = await create_task(
            title="テストタスク",
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )
        task_id = create_result["task"]["id"]

        # ステータス更新（Admin のみ許可）
        result = await update_task_status(
            task_id=task_id,
            status="in_progress",
            progress=50,
            caller_agent_id="admin-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is True
        assert result["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_update_invalid_status_fails(self, dashboard_mock_ctx, git_repo):
        """無効なステータスでエラーになることをテスト。"""
        from src.tools.dashboard import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        update_task_status = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "update_task_status":
                update_task_status = tool.fn
                break

        # Admin を追加
        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["admin-001"] = Agent(
            id="admin-001",
            role=AgentRole.ADMIN,
            status=AgentStatus.IDLE,
            tmux_session="test:0.0",
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await update_task_status(
            task_id="task-001",
            status="invalid_status",
            caller_agent_id="admin-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is False
        assert "無効なステータス" in result["error"]


class TestAssignTaskToAgent:
    """assign_task_to_agent ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_assign_to_existing_agent(self, dashboard_mock_ctx, git_repo):
        """タスクをエージェントに割り当てできることをテスト。"""
        from src.tools.dashboard import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        create_task = None
        assign_task_to_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_task":
                create_task = tool.fn
            elif tool.name == "assign_task_to_agent":
                assign_task_to_agent = tool.fn

        # エージェントを追加
        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
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
        app_ctx.agents["admin-001"] = Agent(
            id="admin-001",
            role=AgentRole.ADMIN,
            status=AgentStatus.IDLE,
            tmux_session="test:0.0",
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

        # タスク作成
        create_result = await create_task(
            title="テストタスク",
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )
        task_id = create_result["task"]["id"]

        # 割り当て（Admin のみ許可）
        result = await assign_task_to_agent(
            task_id=task_id,
            agent_id="worker-001",
            branch="feature/test",
            caller_agent_id="admin-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is True
        assert result["agent_id"] == "worker-001"

    @pytest.mark.asyncio
    async def test_assign_to_nonexistent_agent_fails(self, dashboard_mock_ctx, git_repo):
        """存在しないエージェントへの割り当てが失敗することをテスト。"""
        from src.tools.dashboard import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        create_task = None
        assign_task_to_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_task":
                create_task = tool.fn
            elif tool.name == "assign_task_to_agent":
                assign_task_to_agent = tool.fn

        # Admin を追加
        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
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
        app_ctx.agents["admin-001"] = Agent(
            id="admin-001",
            role=AgentRole.ADMIN,
            status=AgentStatus.IDLE,
            tmux_session="test:0.0",
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        # タスク作成
        create_result = await create_task(
            title="テストタスク",
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )
        task_id = create_result["task"]["id"]

        # 存在しないエージェントに割り当て
        result = await assign_task_to_agent(
            task_id=task_id,
            agent_id="nonexistent",
            caller_agent_id="admin-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is False
        assert "見つかりません" in result["error"]


class TestListTasks:
    """list_tasks ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_list_all_tasks(self, dashboard_mock_ctx, git_repo):
        """全タスクを取得できることをテスト。"""
        from src.tools.dashboard import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        create_task = None
        list_tasks = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_task":
                create_task = tool.fn
            elif tool.name == "list_tasks":
                list_tasks = tool.fn

        # Owner を追加
        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
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

        # 複数のタスクを作成
        await create_task(
            title="タスク1",
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )
        await create_task(
            title="タスク2",
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )

        # タスク一覧を取得
        result = await list_tasks(
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["tasks"]) == 2


class TestGetTask:
    """get_task ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_existing_task(self, dashboard_mock_ctx, git_repo):
        """存在するタスクを取得できることをテスト。"""
        from src.tools.dashboard import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        create_task = None
        get_task = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_task":
                create_task = tool.fn
            elif tool.name == "get_task":
                get_task = tool.fn

        # Owner を追加
        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
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

        # タスク作成
        create_result = await create_task(
            title="テストタスク",
            description="詳細説明",
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )
        task_id = create_result["task"]["id"]

        # タスク取得
        result = await get_task(
            task_id=task_id,
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is True
        assert result["task"]["id"] == task_id
        assert result["task"]["title"] == "テストタスク"

    @pytest.mark.asyncio
    async def test_get_nonexistent_task_fails(self, dashboard_mock_ctx, git_repo):
        """存在しないタスクでエラーになることをテスト。"""
        from src.tools.dashboard import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        get_task = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_task":
                get_task = tool.fn
                break

        # Owner を追加
        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
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

        result = await get_task(
            task_id="nonexistent-task",
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is False
        assert "見つかりません" in result["error"]


class TestGetDashboard:
    """get_dashboard ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_full_dashboard(self, dashboard_mock_ctx, git_repo):
        """ダッシュボード全体を取得できることをテスト。"""
        from src.tools.dashboard import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        get_dashboard = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_dashboard":
                get_dashboard = tool.fn
                break

        # Owner を追加
        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
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

        result = await get_dashboard(
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is True
        assert "dashboard" in result


class TestCostTools:
    """コスト関連ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_cost_summary(self, dashboard_mock_ctx, git_repo):
        """コストサマリーを取得できることをテスト。"""
        from src.tools.dashboard import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        get_cost_summary = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_cost_summary":
                get_cost_summary = tool.fn
                break

        # Owner を追加
        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
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

        result = await get_cost_summary(
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is True
        # コストサマリーは summary キー内に含まれる
        assert "summary" in result
        assert "estimated_cost_usd" in result["summary"]
