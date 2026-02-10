"""ダッシュボード/タスク管理ツールのテスト。"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

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

    @pytest.mark.asyncio
    async def test_create_task_with_metadata(self, dashboard_mock_ctx, git_repo):
        """メタデータ付きでタスク作成できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        create_task = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_task":
                create_task = tool.fn
                break

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
            title="メタデータ付きタスク",
            description="説明",
            metadata={"task_kind": "docs", "requires_playwright": False},
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is True
        assert result["task"]["metadata"]["task_kind"] == "docs"
        assert result["task"]["metadata"]["requires_playwright"] is False


class TestUpdateTaskStatus:
    """update_task_status ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_update_to_in_progress(self, dashboard_mock_ctx, git_repo):
        """タスクステータスを in_progress に更新できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

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

    @pytest.mark.asyncio
    async def test_terminal_to_in_progress_is_rejected(self, dashboard_mock_ctx, git_repo):
        """終端状態からの直接再開は拒否されることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        create_task = None
        update_task_status = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_task":
                create_task = tool.fn
            elif tool.name == "update_task_status":
                update_task_status = tool.fn

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

        create_result = await create_task(
            title="完了タスク",
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )
        task_id = create_result["task"]["id"]

        done_result = await update_task_status(
            task_id=task_id,
            status="completed",
            caller_agent_id="admin-001",
            ctx=dashboard_mock_ctx,
        )
        assert done_result["success"] is True

        resume_result = await update_task_status(
            task_id=task_id,
            status="in_progress",
            caller_agent_id="admin-001",
            ctx=dashboard_mock_ctx,
        )
        assert resume_result["success"] is False
        assert "reopen_task" in resume_result["message"]


class TestReopenTask:
    """reopen_task ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_reopen_task_success(self, dashboard_mock_ctx, git_repo):
        """終端タスクを再開できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        create_task = None
        update_task_status = None
        reopen_task = None
        get_task = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_task":
                create_task = tool.fn
            elif tool.name == "update_task_status":
                update_task_status = tool.fn
            elif tool.name == "reopen_task":
                reopen_task = tool.fn
            elif tool.name == "get_task":
                get_task = tool.fn

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

        create_result = await create_task(
            title="再開対象タスク",
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )
        task_id = create_result["task"]["id"]

        await update_task_status(
            task_id=task_id,
            status="completed",
            caller_agent_id="admin-001",
            ctx=dashboard_mock_ctx,
        )

        reopen_result = await reopen_task(
            task_id=task_id,
            reset_progress=True,
            caller_agent_id="admin-001",
            ctx=dashboard_mock_ctx,
        )
        assert reopen_result["success"] is True

        task_result = await get_task(
            task_id=task_id,
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )
        assert task_result["task"]["status"] == "pending"
        assert task_result["task"]["progress"] == 0


class TestAssignTaskToAgent:
    """assign_task_to_agent ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_assign_to_existing_agent(self, dashboard_mock_ctx, git_repo):
        """タスクをエージェントに割り当てできることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

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

    @pytest.mark.asyncio
    async def test_get_dashboard_blocks_admin_polling_while_waiting(
        self, dashboard_mock_ctx, git_repo
    ):
        """Admin が IPC 待機中に dashboard を連続参照するとブロックされることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        get_dashboard = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_dashboard":
                get_dashboard = tool.fn
                break

        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["admin-001"] = Agent(
            id="admin-001",
            role=AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )
        app_ctx.ipc_manager.register_agent("admin-001")
        app_ctx._admin_poll_state = {
            "admin-001": {
                "waiting_for_ipc": True,
                "allow_dashboard_until": now - timedelta(seconds=1),
            }
        }

        result = await get_dashboard(
            caller_agent_id="admin-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is False
        assert "polling_blocked" in result["error"]


class TestOwnerWaitLockPolling:
    """Owner 待機ロック中の dashboard 系ポーリング抑止テスト。"""

    @pytest.mark.asyncio
    async def test_get_dashboard_returns_polling_blocked_for_owner_wait_lock(
        self, dashboard_mock_ctx, git_repo
    ):
        """Owner 待機ロック中は get_dashboard が polling_blocked になる。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        get_dashboard = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_dashboard":
                get_dashboard = tool.fn
                break
        assert get_dashboard is not None

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
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": now,
            "unlocked_at": None,
            "unlock_reason": None,
        }

        result = await get_dashboard(
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is False
        assert "polling_blocked" in result["error"]
        assert result["next_action"] == "wait_for_user_input_or_unlock_owner_wait"
        assert result["waiting_for_admin_id"] == "admin-001"

    @pytest.mark.asyncio
    async def test_get_dashboard_summary_returns_polling_blocked_for_owner_wait_lock(
        self, dashboard_mock_ctx, git_repo
    ):
        """Owner 待機ロック中は get_dashboard_summary が polling_blocked になる。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        get_dashboard_summary = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_dashboard_summary":
                get_dashboard_summary = tool.fn
                break
        assert get_dashboard_summary is not None

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
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": now,
            "unlocked_at": None,
            "unlock_reason": None,
        }

        result = await get_dashboard_summary(
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is False
        assert "polling_blocked" in result["error"]
        assert result["next_action"] == "wait_for_user_input_or_unlock_owner_wait"
        assert result["waiting_for_admin_id"] == "admin-001"

    @pytest.mark.asyncio
    async def test_list_tasks_returns_polling_blocked_for_owner_wait_lock(
        self, dashboard_mock_ctx, git_repo
    ):
        """Owner 待機ロック中は list_tasks が polling_blocked になる。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        list_tasks = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "list_tasks":
                list_tasks = tool.fn
                break
        assert list_tasks is not None

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
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": now,
            "unlocked_at": None,
            "unlock_reason": None,
        }

        result = await list_tasks(
            caller_agent_id="owner-001",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is False
        assert "polling_blocked" in result["error"]
        assert result["next_action"] == "wait_for_user_input_or_unlock_owner_wait"
        assert result["waiting_for_admin_id"] == "admin-001"


class TestReportTaskProgress:
    """report_task_progress ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_progress_default_message_is_japanese(
        self, dashboard_mock_ctx, git_repo
    ):
        """message 未指定時の進捗報告本文が日本語デフォルトになることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.models.message import MessageType
        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        report_task_progress = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "report_task_progress":
                report_task_progress = tool.fn
                break
        assert report_task_progress is not None

        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
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
        task = app_ctx.dashboard_manager.create_task(
            title="進捗報告タスク",
            assigned_agent_id="worker-001",
        )
        app_ctx.agents["worker-001"].current_task = task.id

        with (
            patch(
                "src.tools.dashboard.capture_claude_actual_cost_for_agent",
                AsyncMock(return_value=None),
            ),
            patch(
                "src.tools.dashboard.notify_agent_via_tmux",
                AsyncMock(return_value=True),
            ),
        ):
            result = await report_task_progress(
                task_id=task.id,
                progress=40,
                message=None,
                caller_agent_id="worker-001",
                ctx=dashboard_mock_ctx,
            )

        assert result["success"] is True
        assert result["progress"] == 40
        assert result["admin_notified"] is True
        assert result["notification_sent"] is True

        messages = app_ctx.ipc_manager.read_messages(
            agent_id="admin-001",
            unread_only=True,
            mark_as_read=False,
        )
        assert len(messages) == 1
        assert messages[0].message_type == MessageType.TASK_PROGRESS
        assert messages[0].subject == f"進捗報告: {task.id} (40%)"
        assert messages[0].content == f"タスク {task.id} の進捗: 40%"
        assert messages[0].metadata["progress"] == 40

    @pytest.mark.asyncio
    async def test_rejects_progress_for_unassigned_task(
        self, dashboard_mock_ctx, git_repo
    ):
        """割り当てられていない Worker からの進捗報告を拒否することをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        report_task_progress = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "report_task_progress":
                report_task_progress = tool.fn
                break
        assert report_task_progress is not None

        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
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
        app_ctx.agents["worker-002"] = Agent(
            id="worker-002",
            role=AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.2",
            session_name="test",
            window_index=0,
            pane_index=2,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )
        task = app_ctx.dashboard_manager.create_task(
            title="割り当て済みタスク",
            assigned_agent_id="worker-001",
        )

        result = await report_task_progress(
            task_id=task.id,
            progress=40,
            caller_agent_id="worker-002",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is False
        assert "割り当て先と caller_agent_id が一致しません" in result["error"]
        messages = app_ctx.ipc_manager.read_messages(
            agent_id="admin-001",
            unread_only=True,
            mark_as_read=False,
        )
        assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_returns_error_when_progress_notification_fails(
        self, dashboard_mock_ctx, git_repo
    ):
        """tmux 通知失敗時に success=False で返すことをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        report_task_progress = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "report_task_progress":
                report_task_progress = tool.fn
                break
        assert report_task_progress is not None

        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
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
        task = app_ctx.dashboard_manager.create_task(
            title="通知失敗テスト",
            assigned_agent_id="worker-001",
        )
        app_ctx.agents["worker-001"].current_task = task.id

        with (
            patch(
                "src.tools.dashboard.capture_claude_actual_cost_for_agent",
                AsyncMock(return_value=None),
            ),
            patch(
                "src.tools.dashboard.notify_agent_via_tmux",
                AsyncMock(return_value=False),
            ),
        ):
            result = await report_task_progress(
                task_id=task.id,
                progress=50,
                caller_agent_id="worker-001",
                ctx=dashboard_mock_ctx,
            )

        assert result["success"] is False
        assert "tmux 通知に失敗しました" in result["error"]
        assert result["admin_notified"] is True
        assert result["notification_sent"] is False


class TestReportTaskCompletion:
    """report_task_completion ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_saves_result_to_project_memory_directory(
        self, dashboard_mock_ctx, git_repo
    ):
        """完了結果が session 配下ではなく .multi-agent-mcp/memory に保存されることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.models.message import MessageType
        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        report_task_completion = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "report_task_completion":
                report_task_completion = tool.fn
                break
        assert report_task_completion is not None

        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
        app_ctx.session_id = "issue-001"
        app_ctx.project_root = str(git_repo)
        session_memory_dir = git_repo / app_ctx.settings.mcp_dir / app_ctx.session_id / "memory"
        app_ctx.memory_manager = MemoryManager(str(session_memory_dir))

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
        task = app_ctx.dashboard_manager.create_task(
            title="完了報告タスク",
            assigned_agent_id="worker-001",
        )
        app_ctx.agents["worker-001"].current_task = task.id

        with (
            patch(
                "src.tools.dashboard.capture_claude_actual_cost_for_agent",
                AsyncMock(return_value=None),
            ),
            patch(
                "src.tools.dashboard.notify_agent_via_tmux",
                AsyncMock(return_value=True),
            ),
        ):
            result = await report_task_completion(
                task_id=task.id,
                status="completed",
                message="完了しました",
                summary="summary text",
                caller_agent_id="worker-001",
                ctx=dashboard_mock_ctx,
            )

        assert result["success"] is True
        assert result["memory_saved"] is True

        key = f"task:{task.id}:result"
        project_memory_dir = git_repo / app_ctx.settings.mcp_dir / "memory"
        project_memory = MemoryManager(str(project_memory_dir))
        entry = project_memory.get(key)
        assert entry is not None
        assert entry.content == "[completed] summary text"

        session_memory = MemoryManager(str(session_memory_dir))
        assert session_memory.get(key) is None

        messages = app_ctx.ipc_manager.read_messages(
            agent_id="admin-001",
            unread_only=True,
            mark_as_read=False,
        )
        assert len(messages) == 1
        assert messages[0].message_type == MessageType.TASK_COMPLETE
        assert "(完了)" in messages[0].subject

    @pytest.mark.asyncio
    async def test_reports_failed_completion_with_task_failed_message_type(
        self, dashboard_mock_ctx, git_repo
    ):
        """失敗報告時は task_failed メッセージ種別で Admin に通知することをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.models.message import MessageType
        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        report_task_completion = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "report_task_completion":
                report_task_completion = tool.fn
                break
        assert report_task_completion is not None

        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
        app_ctx.session_id = "issue-001"
        app_ctx.project_root = str(git_repo)

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
        task = app_ctx.dashboard_manager.create_task(
            title="失敗報告タスク",
            assigned_agent_id="worker-001",
        )
        app_ctx.agents["worker-001"].current_task = task.id

        with (
            patch(
                "src.tools.dashboard.capture_claude_actual_cost_for_agent",
                AsyncMock(return_value=None),
            ),
            patch(
                "src.tools.dashboard.notify_agent_via_tmux",
                AsyncMock(return_value=True),
            ),
        ):
            result = await report_task_completion(
                task_id=task.id,
                status="failed",
                message="失敗しました",
                caller_agent_id="worker-001",
                ctx=dashboard_mock_ctx,
            )

        assert result["success"] is True
        assert result["reported_status"] == "failed"
        assert result["notification_sent"] is True

        messages = app_ctx.ipc_manager.read_messages(
            agent_id="admin-001",
            unread_only=True,
            mark_as_read=False,
        )
        assert len(messages) == 1
        assert messages[0].message_type == MessageType.TASK_FAILED
        assert "(失敗)" in messages[0].subject

    @pytest.mark.asyncio
    async def test_rejects_completion_for_unassigned_task(
        self, dashboard_mock_ctx, git_repo
    ):
        """割り当てられていない Worker からの完了報告を拒否することをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        report_task_completion = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "report_task_completion":
                report_task_completion = tool.fn
                break
        assert report_task_completion is not None

        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
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
        app_ctx.agents["worker-002"] = Agent(
            id="worker-002",
            role=AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.2",
            session_name="test",
            window_index=0,
            pane_index=2,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )
        task = app_ctx.dashboard_manager.create_task(
            title="完了偽装テスト",
            assigned_agent_id="worker-001",
        )

        result = await report_task_completion(
            task_id=task.id,
            status="completed",
            message="不正完了",
            caller_agent_id="worker-002",
            ctx=dashboard_mock_ctx,
        )

        assert result["success"] is False
        assert "割り当て先と caller_agent_id が一致しません" in result["error"]
        messages = app_ctx.ipc_manager.read_messages(
            agent_id="admin-001",
            unread_only=True,
            mark_as_read=False,
        )
        assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_returns_error_when_completion_notification_fails(
        self, dashboard_mock_ctx, git_repo
    ):
        """完了報告の tmux 通知失敗時に success=False で返すことをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        report_task_completion = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "report_task_completion":
                report_task_completion = tool.fn
                break
        assert report_task_completion is not None

        app_ctx = dashboard_mock_ctx.request_context.lifespan_context
        app_ctx.session_id = "issue-001"
        app_ctx.project_root = str(git_repo)
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
        task = app_ctx.dashboard_manager.create_task(
            title="完了通知失敗テスト",
            assigned_agent_id="worker-001",
        )
        app_ctx.agents["worker-001"].current_task = task.id

        with (
            patch(
                "src.tools.dashboard.capture_claude_actual_cost_for_agent",
                AsyncMock(return_value=None),
            ),
            patch(
                "src.tools.dashboard.notify_agent_via_tmux",
                AsyncMock(return_value=False),
            ),
        ):
            result = await report_task_completion(
                task_id=task.id,
                status="completed",
                message="完了しました",
                caller_agent_id="worker-001",
                ctx=dashboard_mock_ctx,
            )

        assert result["success"] is False
        assert "tmux 通知に失敗しました" in result["error"]
        assert result["notification_sent"] is False


class TestCostTools:
    """コスト関連ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_cost_summary(self, dashboard_mock_ctx, git_repo):
        """コストサマリーを取得できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard_cost_tools import register_tools

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
