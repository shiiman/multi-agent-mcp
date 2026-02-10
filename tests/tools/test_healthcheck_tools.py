"""ヘルスチェック管理ツールのテスト。"""

import shlex
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

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
    mock_tmux.session_exists = AsyncMock(return_value=True)
    mock_tmux.get_pane_current_command = AsyncMock(return_value="claude")
    mock_tmux.send_keys_to_pane = AsyncMock(return_value=True)
    mock_tmux.capture_pane_by_index = AsyncMock(return_value="")

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.healthcheck import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.healthcheck import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.healthcheck import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.healthcheck import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.healthcheck import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.healthcheck import register_tools

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

    @pytest.mark.asyncio
    async def test_execute_full_recovery_no_git_preserves_working_dir(
        self, healthcheck_mock_ctx, git_repo
    ):
        """enable_git=false では worktree 再作成せず working_dir を維持して復旧する。"""
        from src.models.dashboard import TaskStatus
        from src.tools.healthcheck import execute_full_recovery

        app_ctx = healthcheck_mock_ctx.request_context.lifespan_context
        app_ctx.settings.enable_git = False

        now = datetime.now()
        worker = Agent(
            id="worker-no-git",
            role=AgentRole.WORKER,
            status=AgentStatus.ERROR,
            tmux_session=None,
            session_name=None,
            window_index=None,
            pane_index=None,
            working_dir=str(git_repo),
            worktree_path=None,
            created_at=now,
            last_activity=now,
        )
        app_ctx.agents[worker.id] = worker

        task = app_ctx.dashboard_manager.create_task(
            title="no-git recovery",
            description="healthcheck",
            assigned_agent_id=worker.id,
        )
        app_ctx.dashboard_manager.update_task_status(
            task.id, TaskStatus.IN_PROGRESS, progress=5
        )

        result = await execute_full_recovery(app_ctx, worker.id)

        assert result["success"] is True
        assert result["new_worktree_path"] == str(git_repo)
        recovered = app_ctx.agents[worker.id]
        assert recovered.working_dir == str(git_repo)
        assert recovered.worktree_path is None

    @pytest.mark.asyncio
    async def test_execute_full_recovery_quotes_cd_path_for_tmux_send_keys(
        self, healthcheck_mock_ctx, git_repo
    ):
        """full_recovery の cd コマンドは特殊文字パスを quote して送信する。"""
        from src.tools.healthcheck import execute_full_recovery

        app_ctx = healthcheck_mock_ctx.request_context.lifespan_context
        app_ctx.settings.enable_git = False

        now = datetime.now()
        special_path = str(git_repo / "dir with space/it's;danger")
        worker = Agent(
            id="worker-quoted-path",
            role=AgentRole.WORKER,
            status=AgentStatus.ERROR,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=special_path,
            worktree_path=None,
            created_at=now,
            last_activity=now,
        )
        app_ctx.agents[worker.id] = worker

        result = await execute_full_recovery(app_ctx, worker.id)

        assert result["success"] is True
        expected_target = "test:window-0.1"
        expected_command = f"cd {shlex.quote(special_path)}"
        app_ctx.tmux._run.assert_any_await(
            "send-keys", "-t", expected_target, expected_command, "Enter"
        )

    @pytest.mark.asyncio
    async def test_execute_full_recovery_worktree_create_failure_returns_failed(
        self, healthcheck_mock_ctx, git_repo, monkeypatch
    ):
        """worktree 作成が両方失敗した場合、fallback せず failed を返す。"""
        from src.tools.healthcheck import execute_full_recovery

        app_ctx = healthcheck_mock_ctx.request_context.lifespan_context
        app_ctx.settings.enable_git = True

        now = datetime.now()
        worker = Agent(
            id="worker-create-fail",
            role=AgentRole.WORKER,
            status=AgentStatus.ERROR,
            tmux_session=None,
            session_name=None,
            window_index=None,
            pane_index=None,
            working_dir=str(git_repo / "worker-create-fail"),
            worktree_path=str(git_repo / "worker-create-fail"),
            branch="worker-create-fail",
            created_at=now,
            last_activity=now,
        )
        app_ctx.agents[worker.id] = worker

        class StubWorktreeManager:
            create_calls = 0

            def __init__(self, _repo_path: str) -> None:
                pass

            async def remove_worktree(self, _path: str, force: bool = False) -> tuple[bool, str]:
                return True, "removed"

            async def create_worktree(
                self,
                path: str,
                branch: str,
                create_branch: bool = True,
                base_branch: str | None = None,
            ) -> tuple[bool, str, str | None]:
                _ = (path, branch, create_branch, base_branch)
                StubWorktreeManager.create_calls += 1
                return False, "create failed", None

        monkeypatch.setattr(
            "src.managers.worktree_manager.WorktreeManager",
            StubWorktreeManager,
        )

        result = await execute_full_recovery(app_ctx, worker.id)

        assert result["success"] is False
        assert result["status"] == "failed"
        assert result["new_worktree_path"] is None
        assert "project_root" not in result.get("error", "")
        assert StubWorktreeManager.create_calls == 2
        assert worker.id in app_ctx.agents
        assert app_ctx.agents[worker.id].worktree_path == str(git_repo / "worker-create-fail")

    @pytest.mark.asyncio
    async def test_execute_full_recovery_worktree_exception_returns_blocked(
        self, healthcheck_mock_ctx, git_repo, monkeypatch
    ):
        """worktree 操作例外時は blocked を返し、fallback しない。"""
        from src.tools.healthcheck import execute_full_recovery

        app_ctx = healthcheck_mock_ctx.request_context.lifespan_context
        app_ctx.settings.enable_git = True

        now = datetime.now()
        worker = Agent(
            id="worker-worktree-error",
            role=AgentRole.WORKER,
            status=AgentStatus.ERROR,
            tmux_session=None,
            session_name=None,
            window_index=None,
            pane_index=None,
            working_dir=str(git_repo / "worker-worktree-error"),
            worktree_path=str(git_repo / "worker-worktree-error"),
            branch="worker-worktree-error",
            created_at=now,
            last_activity=now,
        )
        app_ctx.agents[worker.id] = worker

        class StubWorktreeManager:
            def __init__(self, _repo_path: str) -> None:
                pass

            async def remove_worktree(self, _path: str, force: bool = False) -> tuple[bool, str]:
                _ = force
                raise RuntimeError("boom")

        monkeypatch.setattr(
            "src.managers.worktree_manager.WorktreeManager",
            StubWorktreeManager,
        )

        result = await execute_full_recovery(app_ctx, worker.id)

        assert result["success"] is False
        assert result["status"] == "blocked"
        assert result["new_worktree_path"] is None
        assert "worktree 操作に失敗しました" in result["error"]
        assert worker.id in app_ctx.agents
