"""セッション管理ツールのテスト。"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.dashboard_manager import DashboardManager
from src.managers.tmux_manager import TmuxManager
from src.models.agent import Agent, AgentRole, AgentStatus
from src.models.dashboard import TaskStatus


@pytest.fixture
def session_test_ctx(git_repo, settings):
    """セッションツールテスト用の AppContext を作成する。"""
    mock_tmux = MagicMock(spec=TmuxManager)
    mock_tmux.cleanup_sessions = AsyncMock(return_value=1)
    mock_tmux.cleanup_all_sessions = AsyncMock(return_value=99)
    mock_tmux.settings = settings

    ai_cli = AiCliManager(settings)

    dashboard_dir = git_repo / ".dashboard"
    dashboard = DashboardManager(
        workspace_id="test-workspace",
        workspace_path=str(git_repo),
        dashboard_dir=str(dashboard_dir),
    )
    dashboard.initialize()

    ctx = AppContext(
        settings=settings,
        tmux=mock_tmux,
        ai_cli=ai_cli,
        agents={},
        dashboard_manager=dashboard,
        workspace_id="test-workspace",
        project_root=None,
        session_id="test-session",
    )

    yield ctx
    dashboard.cleanup()


@pytest.fixture
def session_mock_ctx(session_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = session_test_ctx
    return mock


class TestCleanupSessionScope:
    """cleanup 系ツールが対象セッションのみ終了することをテストする。"""

    @pytest.mark.asyncio
    async def test_cleanup_workspace_uses_scoped_sessions(self, session_mock_ctx, git_repo):
        """cleanup_workspace が対象セッションのみ終了することをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.session import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        cleanup_workspace = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "cleanup_workspace":
                cleanup_workspace = tool.fn
                break

        assert cleanup_workspace is not None

        app_ctx = session_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            session_name="scoped-session",
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )
        app_ctx.agents["admin-001"] = Agent(
            id="admin-001",
            role=AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="scoped-session:0.0",
            session_name="scoped-session",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await cleanup_workspace(
            caller_agent_id="owner-001",
            ctx=session_mock_ctx,
        )

        assert result["success"] is True
        app_ctx.tmux.cleanup_sessions.assert_awaited_once_with(["scoped-session"])
        app_ctx.tmux.cleanup_all_sessions.assert_not_awaited()


class TestSessionHelpers:
    """session helper 関数のテスト。"""

    def test_collect_session_names_mixed_sources(self):
        """session_name と tmux_session の混在から重複なく収集できることをテスト。"""
        from src.tools.session import _collect_session_names

        agents = {
            "a": type("A", (), {"session_name": "alpha", "tmux_session": None})(),
            "b": type("B", (), {"session_name": None, "tmux_session": "beta:0.1"})(),
            "c": type("C", (), {"session_name": "alpha", "tmux_session": "ignored:0.2"})(),
        }

        assert _collect_session_names(agents) == ["alpha", "beta"]

    def test_reset_app_context_clears_managers_and_maps(self, session_test_ctx):
        """_reset_app_context が状態をクリアすることをテスト。"""
        from src.tools.session import _reset_app_context

        app_ctx = session_test_ctx
        app_ctx.project_root = "/tmp/repo"
        app_ctx.workspace_id = "ws-1"
        app_ctx.worktree_managers["/tmp/repo"] = object()
        app_ctx.gtrconfig_managers["/tmp/repo"] = object()

        _reset_app_context(app_ctx)

        assert app_ctx.session_id is None
        assert app_ctx.project_root is None
        assert app_ctx.workspace_id is None
        assert app_ctx.dashboard_manager is None
        assert app_ctx.worktree_managers == {}
        assert app_ctx.gtrconfig_managers == {}

    def test_check_completion_status_returns_error_without_dashboard(self, session_test_ctx):
        """dashboard 未初期化時に error を返すことをテスト。"""
        from src.tools.session import _check_completion_status

        app_ctx = session_test_ctx
        app_ctx.dashboard_manager = None
        status = _check_completion_status(app_ctx)

        assert status["is_all_completed"] is False
        assert status["error"] == "ワークスペースが初期化されていません"

    @pytest.mark.asyncio
    async def test_cleanup_on_completion_uses_scoped_sessions(
        self, session_mock_ctx, monkeypatch, git_repo
    ):
        """cleanup_on_completion が対象セッションのみ終了することをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.session import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        cleanup_on_completion = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "cleanup_on_completion":
                cleanup_on_completion = tool.fn
                break

        assert cleanup_on_completion is not None

        app_ctx = session_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            session_name="scoped-session",
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )
        app_ctx.agents["worker-001"] = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="scoped-session:0.1",
            session_name="scoped-session",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        task = app_ctx.dashboard_manager.create_task(title="done-task")
        app_ctx.dashboard_manager.update_task_status(task.id, TaskStatus.COMPLETED)

        monkeypatch.setattr("src.tools.helpers.remove_agents_by_owner", lambda _owner_id: 1)

        result = await cleanup_on_completion(
            caller_agent_id="owner-001",
            ctx=session_mock_ctx,
        )

        assert result["success"] is True
        app_ctx.tmux.cleanup_sessions.assert_awaited_once_with(["scoped-session"])
        app_ctx.tmux.cleanup_all_sessions.assert_not_awaited()


class TestInitTmuxWorkspace:
    """init_tmux_workspace のテスト。"""

    @pytest.mark.asyncio
    async def test_init_tmux_workspace_cleans_orphan_provisional_dirs(
        self, session_mock_ctx, git_repo
    ):
        """正式 session_id 設定時に孤立 provisional-* が削除されることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.session import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        init_tmux_workspace = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "init_tmux_workspace":
                init_tmux_workspace = tool.fn
                break
        assert init_tmux_workspace is not None

        app_ctx = session_mock_ctx.request_context.lifespan_context
        app_ctx.session_id = "provisional-old0001"
        app_ctx.project_root = str(git_repo)
        app_ctx.tmux.session_exists = AsyncMock(return_value=False)
        app_ctx.tmux.create_main_session = AsyncMock(return_value=True)

        mcp_dir = git_repo / app_ctx.settings.mcp_dir
        source = mcp_dir / "provisional-old0001"
        orphan = mcp_dir / "provisional-orphan9999"
        source.mkdir(parents=True, exist_ok=True)
        orphan.mkdir(parents=True, exist_ok=True)
        (source / "agents.json").write_text("{}", encoding="utf-8")
        (orphan / "agents.json").write_text("{}", encoding="utf-8")

        result = await init_tmux_workspace(
            working_dir=str(git_repo),
            open_terminal=False,
            auto_setup_gtr=False,
            session_id="issue-123",
            ctx=session_mock_ctx,
        )

        assert result["success"] is True
        assert result["provisional_migration"]["executed"] is True
        assert result["provisional_cleanup"]["removed_count"] == 0
        assert result["provisional_cleanup"]["removed_dirs"] == []
        assert not source.exists()
        assert orphan.exists()
