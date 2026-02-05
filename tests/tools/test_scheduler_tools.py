"""スケジューラー管理ツールのテスト。"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

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
def scheduler_test_ctx(git_repo, settings):
    """スケジューラーツールテスト用のAppContextを作成する。"""
    # モック tmux マネージャー
    mock_tmux = MagicMock(spec=TmuxManager)
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

    # エージェント辞書
    agents = {}

    # スケジューラーマネージャー
    scheduler = SchedulerManager(dashboard, agents)

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
        workspace_id="test-workspace",
        project_root=str(git_repo),
        session_id="test-session",
    )

    yield ctx

    # クリーンアップ
    ipc.cleanup()
    dashboard.cleanup()


@pytest.fixture
def scheduler_mock_ctx(scheduler_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = scheduler_test_ctx
    return mock


class TestEnqueueTask:
    """enqueue_task ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_enqueue_task_success(self, scheduler_mock_ctx, git_repo):
        """タスクのキュー追加が成功することをテスト。"""
        from src.tools.scheduler import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        enqueue_task = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "enqueue_task":
                enqueue_task = tool.fn
                break

        # Admin を追加（enqueue_task は Admin のみ使用可能）
        app_ctx = scheduler_mock_ctx.request_context.lifespan_context
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

        result = await enqueue_task(
            task_id="task-001",
            priority="high",
            caller_agent_id="admin-001",
            ctx=scheduler_mock_ctx,
        )

        assert result["success"] is True
        assert result["task_id"] == "task-001"
        assert result["priority"] == "high"

    @pytest.mark.asyncio
    async def test_enqueue_task_invalid_priority(self, scheduler_mock_ctx, git_repo):
        """無効な優先度でエラーになることをテスト。"""
        from src.tools.scheduler import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        enqueue_task = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "enqueue_task":
                enqueue_task = tool.fn
                break

        # Admin を追加
        app_ctx = scheduler_mock_ctx.request_context.lifespan_context
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

        result = await enqueue_task(
            task_id="task-001",
            priority="invalid_priority",
            caller_agent_id="admin-001",
            ctx=scheduler_mock_ctx,
        )

        assert result["success"] is False
        assert "無効な優先度" in result["error"]

    @pytest.mark.asyncio
    async def test_enqueue_duplicate_task(self, scheduler_mock_ctx, git_repo):
        """重複タスクのキュー追加でエラーになることをテスト。"""
        from src.tools.scheduler import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        enqueue_task = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "enqueue_task":
                enqueue_task = tool.fn
                break

        # Admin を追加
        app_ctx = scheduler_mock_ctx.request_context.lifespan_context
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

        # 最初のタスク追加
        await enqueue_task(
            task_id="task-duplicate",
            priority="medium",
            caller_agent_id="admin-001",
            ctx=scheduler_mock_ctx,
        )

        # 重複タスク追加
        result = await enqueue_task(
            task_id="task-duplicate",
            priority="medium",
            caller_agent_id="admin-001",
            ctx=scheduler_mock_ctx,
        )

        assert result["success"] is False
        assert "既にキューに存在" in result["error"]

    @pytest.mark.asyncio
    async def test_enqueue_task_owner_allowed(self, scheduler_mock_ctx, git_repo):
        """Ownerによるキュー追加が許可されることをテスト。

        enqueue_task は Owner と Admin の両方が使用可能。
        """
        from src.tools.scheduler import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        enqueue_task = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "enqueue_task":
                enqueue_task = tool.fn
                break

        # Owner を追加
        app_ctx = scheduler_mock_ctx.request_context.lifespan_context
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

        result = await enqueue_task(
            task_id="task-owner-001",
            priority="high",
            caller_agent_id="owner-001",
            ctx=scheduler_mock_ctx,
        )

        assert result["success"] is True
        assert result["task_id"] == "task-owner-001"


class TestAutoAssignTasks:
    """auto_assign_tasks ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_auto_assign_no_tasks(self, scheduler_mock_ctx, git_repo):
        """タスクがない場合の自動割り当てをテスト。"""
        from src.tools.scheduler import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        auto_assign_tasks = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "auto_assign_tasks":
                auto_assign_tasks = tool.fn
                break

        # Admin を追加
        app_ctx = scheduler_mock_ctx.request_context.lifespan_context
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

        result = await auto_assign_tasks(
            caller_agent_id="admin-001",
            ctx=scheduler_mock_ctx,
        )

        assert result["success"] is True
        assert result["count"] == 0


class TestGetTaskQueue:
    """get_task_queue ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_task_queue_empty(self, scheduler_mock_ctx, git_repo):
        """空のキュー取得をテスト。"""
        from src.tools.scheduler import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        get_task_queue = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_task_queue":
                get_task_queue = tool.fn
                break

        # Owner を追加（get_task_queue は Owner と Admin が使用可能）
        app_ctx = scheduler_mock_ctx.request_context.lifespan_context
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

        result = await get_task_queue(
            caller_agent_id="owner-001",
            ctx=scheduler_mock_ctx,
        )

        assert result["success"] is True
        assert "queue" in result

    @pytest.mark.asyncio
    async def test_get_task_queue_with_tasks(self, scheduler_mock_ctx, git_repo):
        """タスクが存在する場合のキュー取得をテスト。"""
        from src.tools.scheduler import register_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp)

        enqueue_task = None
        get_task_queue = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "enqueue_task":
                enqueue_task = tool.fn
            elif tool.name == "get_task_queue":
                get_task_queue = tool.fn

        # Admin を追加
        app_ctx = scheduler_mock_ctx.request_context.lifespan_context
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

        # タスクを追加
        await enqueue_task(
            task_id="task-queue-001",
            priority="high",
            caller_agent_id="admin-001",
            ctx=scheduler_mock_ctx,
        )
        await enqueue_task(
            task_id="task-queue-002",
            priority="low",
            caller_agent_id="admin-001",
            ctx=scheduler_mock_ctx,
        )

        # キュー取得
        result = await get_task_queue(
            caller_agent_id="admin-001",
            ctx=scheduler_mock_ctx,
        )

        assert result["success"] is True
        assert "queue" in result
