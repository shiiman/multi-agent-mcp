"""Git worktree管理ツールのテスト。"""

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


@pytest.fixture
def worktree_test_ctx(git_repo, settings):
    """Worktreeツールテスト用のAppContextを作成する。"""
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
def worktree_mock_ctx(worktree_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = worktree_test_ctx
    return mock


class TestListWorktrees:
    """list_worktrees ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_list_worktrees_success(self, worktree_mock_ctx, git_repo):
        """worktree一覧の取得が成功することをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.worktree import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        list_worktrees = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "list_worktrees":
                list_worktrees = tool.fn
                break

        # Owner を追加
        app_ctx = worktree_mock_ctx.request_context.lifespan_context
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

        result = await list_worktrees(
            repo_path=str(git_repo),
            caller_agent_id="owner-001",
            ctx=worktree_mock_ctx,
        )

        assert result["success"] is True
        assert "worktrees" in result
        assert "count" in result

    @pytest.mark.asyncio
    async def test_list_worktrees_invalid_repo(self, worktree_mock_ctx, git_repo, tmp_path):
        """無効なリポジトリでエラーになることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.worktree import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        list_worktrees = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "list_worktrees":
                list_worktrees = tool.fn
                break

        # Owner を追加
        app_ctx = worktree_mock_ctx.request_context.lifespan_context
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

        # gitリポジトリでないディレクトリ
        non_git_dir = tmp_path / "non-git"
        non_git_dir.mkdir()

        result = await list_worktrees(
            repo_path=str(non_git_dir),
            caller_agent_id="owner-001",
            ctx=worktree_mock_ctx,
        )

        assert result["success"] is False
        assert "gitリポジトリではありません" in result["error"]


class TestAssignWorktree:
    """assign_worktree ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_assign_worktree_success(self, worktree_mock_ctx, git_repo):
        """worktreeの割り当てが成功することをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.worktree import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        assign_worktree = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "assign_worktree":
                assign_worktree = tool.fn
                break

        # Owner と Worker を追加
        app_ctx = worktree_mock_ctx.request_context.lifespan_context
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

        result = await assign_worktree(
            agent_id="worker-001",
            worktree_path="/tmp/test-worktree",
            branch="feature/test",
            caller_agent_id="owner-001",
            ctx=worktree_mock_ctx,
        )

        assert result["success"] is True
        assert result["agent_id"] == "worker-001"
        assert result["worktree_path"] == "/tmp/test-worktree"

    @pytest.mark.asyncio
    async def test_assign_worktree_nonexistent_agent(self, worktree_mock_ctx, git_repo):
        """存在しないエージェントへの割り当てでエラーになることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.worktree import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        assign_worktree = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "assign_worktree":
                assign_worktree = tool.fn
                break

        # Owner を追加
        app_ctx = worktree_mock_ctx.request_context.lifespan_context
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

        result = await assign_worktree(
            agent_id="nonexistent-agent",
            worktree_path="/tmp/test-worktree",
            branch="feature/test",
            caller_agent_id="owner-001",
            ctx=worktree_mock_ctx,
        )

        assert result["success"] is False
        assert "見つかりません" in result["error"]


class TestGetWorktreeStatus:
    """get_worktree_status ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_worktree_status_main_repo(self, worktree_mock_ctx, git_repo):
        """メインリポジトリのステータス取得をテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.worktree import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        get_worktree_status = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_worktree_status":
                get_worktree_status = tool.fn
                break

        # Owner を追加
        app_ctx = worktree_mock_ctx.request_context.lifespan_context
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

        result = await get_worktree_status(
            repo_path=str(git_repo),
            worktree_path=str(git_repo),
            caller_agent_id="owner-001",
            ctx=worktree_mock_ctx,
        )

        assert result["success"] is True
        assert "status" in result


class TestCheckGtrAvailable:
    """check_gtr_available ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_check_gtr_available(self, worktree_mock_ctx, git_repo):
        """gtr利用可否のチェックをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.worktree import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        check_gtr_available = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "check_gtr_available":
                check_gtr_available = tool.fn
                break

        # Owner を追加
        app_ctx = worktree_mock_ctx.request_context.lifespan_context
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

        result = await check_gtr_available(
            repo_path=str(git_repo),
            caller_agent_id="owner-001",
            ctx=worktree_mock_ctx,
        )

        assert result["success"] is True
        assert "gtr_available" in result


class TestCreateWorktree:
    """create_worktree ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_create_worktree_disabled(self, worktree_mock_ctx, git_repo):
        """worktreeが無効時にスキップされることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.worktree import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        create_worktree = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_worktree":
                create_worktree = tool.fn
                break

        # Owner を追加
        app_ctx = worktree_mock_ctx.request_context.lifespan_context
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

        # worktree を無効にして実行
        app_ctx.settings.enable_worktree = False
        result = await create_worktree(
            repo_path=str(git_repo),
            worktree_path="/tmp/test-worktree",
            branch="feature/test",
            caller_agent_id="owner-001",
            ctx=worktree_mock_ctx,
        )

        assert result["success"] is True
        assert result.get("skipped") is True

    @pytest.mark.asyncio
    async def test_create_worktree_returns_error_when_git_disabled(
        self, worktree_mock_ctx, git_repo
    ):
        """enable_git=false のとき create_worktree がエラーになることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.worktree import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        create_worktree = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_worktree":
                create_worktree = tool.fn
                break
        assert create_worktree is not None

        app_ctx = worktree_mock_ctx.request_context.lifespan_context
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

        app_ctx.settings.enable_git = False
        app_ctx.settings.enable_worktree = True
        result = await create_worktree(
            repo_path=str(git_repo),
            worktree_path="/tmp/test-worktree",
            branch="feature/test",
            caller_agent_id="owner-001",
            ctx=worktree_mock_ctx,
        )

        assert result["success"] is False
        assert "MCP_ENABLE_GIT=false" in result["error"]


class TestRemoveWorktree:
    """remove_worktree ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_remove_worktree_disabled(self, worktree_mock_ctx, git_repo):
        """worktreeが無効時にスキップされることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.worktree import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        remove_worktree = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "remove_worktree":
                remove_worktree = tool.fn
                break

        # Owner を追加
        app_ctx = worktree_mock_ctx.request_context.lifespan_context
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

        # worktree を無効にして実行
        app_ctx.settings.enable_worktree = False
        result = await remove_worktree(
            repo_path=str(git_repo),
            worktree_path="/tmp/test-worktree",
            caller_agent_id="owner-001",
            ctx=worktree_mock_ctx,
        )

        assert result["success"] is True
        assert result.get("skipped") is True
