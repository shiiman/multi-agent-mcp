"""エージェント管理ツールのテスト。"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import AICli
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
    mock_tmux.send_with_rate_limit_to_pane = AsyncMock(return_value=True)
    mock_tmux.session_exists = AsyncMock(return_value=True)
    mock_tmux.get_pane_current_command = AsyncMock(return_value="zsh")
    mock_tmux.set_pane_title = AsyncMock(return_value=True)
    mock_tmux.add_extra_worker_window = AsyncMock(return_value=True)
    mock_tmux.open_session_in_terminal = AsyncMock(return_value=True)
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
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

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
    async def test_create_owner_refreshes_settings_from_project_env(self, mock_ctx, git_repo):
        """Owner 作成時に project .env の設定へ再同期されることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        create_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_agent":
                create_agent = tool.fn
                break

        assert create_agent is not None

        mcp_dir = git_repo / ".multi-agent-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)
        env_file = mcp_dir / ".env"
        env_file.write_text(
            "MCP_MODEL_PROFILE_STANDARD_CLI=codex\n"
            "MCP_MODEL_PROFILE_STANDARD_ADMIN_MODEL=gpt-5.3-codex\n",
            encoding="utf-8",
        )

        app_ctx = mock_ctx.request_context.lifespan_context
        app_ctx.project_root = None

        result = await create_agent(
            role="owner",
            working_dir=str(git_repo),
            ctx=mock_ctx,
        )

        assert result["success"] is True
        assert app_ctx.settings.model_profile_standard_cli == AICli.CODEX
        assert app_ctx.ai_cli.settings.model_profile_standard_cli == AICli.CODEX

    @pytest.mark.asyncio
    async def test_create_admin_success(self, mock_ctx, git_repo):
        """Adminエージェントを作成できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

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
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

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


class TestSendTaskToWorker:
    """_send_task_to_worker ヘルパーのテスト。"""

    @pytest.mark.asyncio
    async def test_worker_task_file_does_not_embed_role_guide(self, mock_ctx, git_repo):
        """Worker task ファイルに role 本文が混入しないことをテスト。"""
        from src.tools.agent import _send_task_to_worker

        app_ctx = mock_ctx.request_context.lifespan_context
        now = datetime.now()

        worker = Agent(
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
        app_ctx.agents["worker-001"] = worker

        profile_settings = {
            "worker_model": "gpt-5.3-codex",
            "worker_thinking_tokens": 4000,
        }

        result = await _send_task_to_worker(
            app_ctx=app_ctx,
            agent=worker,
            task_content="テスト実装を進めてください",
            task_id="task-001",
            branch="feature/test",
            worktree_path=str(git_repo),
            session_id="issue-worker-role-separation",
            worker_index=0,
            enable_worktree=False,
            profile_settings=profile_settings,
            caller_agent_id="admin-001",
        )

        assert result["task_sent"] is True
        assert result["dispatch_mode"] == "bootstrap"
        assert result["dispatch_error"] is None
        assert worker.ai_bootstrapped is True
        task_path = (
            Path(git_repo)
            / ".multi-agent-mcp"
            / "issue-worker-role-separation"
            / "tasks"
            / "worker1_task-001.md"
        )
        task_text = task_path.read_text(encoding="utf-8")
        assert "# Multi-Agent MCP - Worker Agent" not in task_text
        assert "# タスク: task-001" in task_text
        assert 'task_id="task-001"' in task_text

    @pytest.mark.asyncio
    async def test_send_task_to_worker_fails_without_task_id(self, mock_ctx, git_repo):
        """task_id 未指定時は Worker 送信が失敗することをテスト。"""
        from src.tools.agent import _send_task_to_worker

        app_ctx = mock_ctx.request_context.lifespan_context
        now = datetime.now()

        worker = Agent(
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
        app_ctx.agents["worker-002"] = worker

        profile_settings = {
            "worker_model": "gpt-5.3-codex",
            "worker_thinking_tokens": 4000,
        }

        result = await _send_task_to_worker(
            app_ctx=app_ctx,
            agent=worker,
            task_content="テスト実装を進めてください",
            task_id=None,
            branch="feature/test",
            worktree_path=str(git_repo),
            session_id="issue-worker-role-separation",
            worker_index=1,
            enable_worktree=False,
            profile_settings=profile_settings,
            caller_agent_id="admin-001",
        )

        assert result["task_sent"] is False
        assert result["dispatch_mode"] == "none"
        assert result["dispatch_error"] == "task_id が必要です"

    @pytest.mark.asyncio
    async def test_send_task_to_worker_uses_followup_for_running_ai(self, mock_ctx, git_repo):
        """ai_bootstrapped=True の Worker では followup モードで指示送信することをテスト。"""
        from src.tools.agent import _send_task_to_worker

        app_ctx = mock_ctx.request_context.lifespan_context
        now = datetime.now()

        worker = Agent(
            id="worker-003",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test:0.3",
            session_name="test",
            window_index=0,
            pane_index=3,
            working_dir=str(git_repo),
            ai_bootstrapped=True,
            created_at=now,
            last_activity=now,
        )
        app_ctx.agents["worker-003"] = worker

        profile_settings = {
            "worker_model": "opus",
            "worker_thinking_tokens": 4000,
            "worker_reasoning_effort": "none",
        }

        result = await _send_task_to_worker(
            app_ctx=app_ctx,
            agent=worker,
            task_content="フォローアップタスク",
            task_id="task-followup",
            branch="feature/followup",
            worktree_path=str(git_repo),
            session_id="issue-followup",
            worker_index=2,
            enable_worktree=False,
            profile_settings=profile_settings,
            caller_agent_id="admin-001",
        )

        assert result["task_sent"] is True
        assert result["dispatch_mode"] == "followup"
        assert result["dispatch_error"] is None
        app_ctx.tmux.get_pane_current_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_task_to_worker_resets_bootstrap_on_followup_failure(
        self, mock_ctx, git_repo
    ):
        """followup 失敗時に shell 判定なら ai_bootstrapped を False に戻すことをテスト。"""
        from src.tools.agent import _send_task_to_worker

        app_ctx = mock_ctx.request_context.lifespan_context
        # followup も bootstrap リトライも失敗させる
        app_ctx.tmux.send_with_rate_limit_to_pane = AsyncMock(return_value=False)
        app_ctx.tmux.get_pane_current_command = AsyncMock(return_value="zsh")
        now = datetime.now()

        worker = Agent(
            id="worker-004",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test:0.4",
            session_name="test",
            window_index=0,
            pane_index=4,
            working_dir=str(git_repo),
            ai_bootstrapped=True,
            created_at=now,
            last_activity=now,
        )
        app_ctx.agents["worker-004"] = worker

        profile_settings = {
            "worker_model": "opus",
            "worker_thinking_tokens": 4000,
            "worker_reasoning_effort": "none",
        }

        result = await _send_task_to_worker(
            app_ctx=app_ctx,
            agent=worker,
            task_content="unknown pane command test",
            task_id="task-unknown",
            branch="feature/unknown",
            worktree_path=str(git_repo),
            session_id="issue-unknown",
            worker_index=3,
            enable_worktree=False,
            profile_settings=profile_settings,
            caller_agent_id="admin-001",
        )

        assert result["task_sent"] is False
        # followup 失敗→shell 検出→bootstrap 再試行→再試行も失敗
        assert result["dispatch_mode"] == "followup"
        assert "bootstrap_retry_failed" in result["dispatch_error"]
        assert worker.ai_bootstrapped is False


class TestAgentHelperFunctions:
    """agent helper 関数のテスト。"""

    def test_validate_agent_creation_duplicate_owner(self):
        """owner 重複時にエラーを返すことをテスト。"""
        from src.tools.agent import _validate_agent_creation

        now = datetime.now()
        agents = {
            "owner-001": Agent(
                id="owner-001",
                role=AgentRole.OWNER,
                status=AgentStatus.IDLE,
                tmux_session=None,
                created_at=now,
                last_activity=now,
            )
        }

        role, cli, error = _validate_agent_creation(agents, "owner", None, 10)
        assert role is None
        assert cli is None
        assert error is not None
        assert "既に存在します" in error["error"]

    def test_resolve_tmux_session_name_prefers_session_name(self):
        """session_name が優先されることをテスト。"""
        from src.tools.agent import _resolve_tmux_session_name

        now = datetime.now()
        agent = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="fallback:0.1",
            session_name="primary",
            created_at=now,
            last_activity=now,
        )
        assert _resolve_tmux_session_name(agent) == "primary"

    def test_resolve_tmux_session_name_falls_back_to_tmux_session(self):
        """tmux_session からセッション名を抽出できることをテスト。"""
        from src.tools.agent import _resolve_tmux_session_name

        now = datetime.now()
        agent = Agent(
            id="worker-002",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="fallback:0.2",
            created_at=now,
            last_activity=now,
        )
        assert _resolve_tmux_session_name(agent) == "fallback"

    def test_resolve_tmux_session_name_returns_none_without_values(self):
        """session 情報がない場合は None を返すことをテスト。"""
        from src.tools.agent import _resolve_tmux_session_name

        now = datetime.now()
        agent = Agent(
            id="worker-003",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            created_at=now,
            last_activity=now,
        )
        assert _resolve_tmux_session_name(agent) is None

    def test_build_change_directory_command_by_cli(self):
        """CLI に応じた cd コマンド分岐をテスト。"""
        from src.tools.agent import _build_change_directory_command

        assert _build_change_directory_command("claude", "/tmp/wt") == "!cd /tmp/wt"
        assert _build_change_directory_command("codex", "/tmp/wt") == "cd /tmp/wt"


class TestCreateWorkersBatchBehavior:
    """create_workers_batch の追加挙動テスト。"""

    @pytest.mark.asyncio
    async def test_create_workers_batch_reuses_idle_worker(self, mock_ctx, git_repo, monkeypatch):
        """idle Worker が再利用されることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        create_workers_batch = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_workers_batch":
                create_workers_batch = tool.fn
                break
        assert create_workers_batch is not None

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
        app_ctx.agents["worker-idle"] = Agent(
            id="worker-idle",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="repo:0.1",
            session_name="repo",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        monkeypatch.setattr(
            "src.tools.agent_batch_tools.get_current_profile_settings",
            lambda _ctx: {"max_workers": 20, "worker_thinking_tokens": 4000},
        )
        app_ctx.settings.enable_worktree = False

        result = await create_workers_batch(
            worker_configs=[{"branch": "feature/reuse-only"}],
            repo_path=str(git_repo),
            base_branch="main",
            reuse_idle_workers=True,
            caller_agent_id="owner-001",
            ctx=mock_ctx,
        )

        assert result["success"] is True
        assert result["failed_count"] == 0
        assert result["workers"][0]["agent_id"] == "worker-idle"
        assert result["workers"][0]["reused"] is True

    @pytest.mark.asyncio
    async def test_create_workers_batch_reports_preassigned_slot_failure(
        self, mock_ctx, git_repo, monkeypatch
    ):
        """事前スロット割り当て失敗時にエラーになることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.managers.tmux_shared import get_project_name
        from src.tools.agent import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        create_workers_batch = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_workers_batch":
                create_workers_batch = tool.fn
                break
        assert create_workers_batch is not None

        app_ctx = mock_ctx.request_context.lifespan_context
        app_ctx.settings.enable_worktree = False
        session_name = get_project_name(str(git_repo), enable_git=app_ctx.settings.enable_git)
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

        for i in range(6):
            pane = i + 1
            app_ctx.agents[f"worker-{pane:03d}"] = Agent(
                id=f"worker-{pane:03d}",
                role=AgentRole.WORKER,
                status=AgentStatus.BUSY,
                tmux_session=f"{session_name}:0.{pane}",
                session_name=session_name,
                window_index=0,
                pane_index=pane,
                working_dir=str(git_repo),
                created_at=now,
                last_activity=now,
            )

        monkeypatch.setattr(
            "src.tools.agent_batch_tools.get_current_profile_settings",
            lambda _ctx: {"max_workers": 20, "worker_thinking_tokens": 4000},
        )

        result = await create_workers_batch(
            worker_configs=[{"branch": "feature/no-slot"}],
            repo_path=str(git_repo),
            base_branch="main",
            reuse_idle_workers=False,
            caller_agent_id="owner-001",
            ctx=mock_ctx,
        )

        assert result["success"] is False
        assert result["failed_count"] == 1
        assert "利用可能なスロットがありません" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_create_workers_batch_reuse_updates_agent_current_task(
        self, mock_ctx, git_repo, monkeypatch
    ):
        """再利用 worker へタスク割り当て時に current_task/status が同期されることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        create_workers_batch = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_workers_batch":
                create_workers_batch = tool.fn
                break
        assert create_workers_batch is not None

        app_ctx = mock_ctx.request_context.lifespan_context
        app_ctx.project_root = str(git_repo)
        app_ctx.session_id = "test-session"
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
        app_ctx.agents["worker-idle"] = Agent(
            id="worker-idle",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="repo:0.1",
            session_name="repo",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        monkeypatch.setattr(
            "src.tools.agent_batch_tools.get_current_profile_settings",
            lambda _ctx: {"max_workers": 20, "worker_thinking_tokens": 4000},
        )

        mock_dashboard = MagicMock()
        mock_dashboard.assign_task.return_value = (True, "ok")
        monkeypatch.setattr(
            "src.tools.agent_batch_tools.ensure_dashboard_manager",
            lambda _ctx: mock_dashboard,
        )

        result = await create_workers_batch(
            worker_configs=[{"branch": "feature/reuse-only", "task_id": "task-123"}],
            repo_path=str(git_repo),
            base_branch="main",
            reuse_idle_workers=True,
            caller_agent_id="owner-001",
            ctx=mock_ctx,
        )

        assert result["success"] is True
        worker = app_ctx.agents["worker-idle"]
        assert worker.current_task == "task-123"
        assert worker.status == AgentStatus.BUSY


class TestInitializeAgent:
    """initialize_agent ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_initialize_agent_uses_tmux_attach_and_pane_dispatch(self, mock_ctx, git_repo):
        """initialize_agent が tmux attach + pane 送信で起動することをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.config.settings import TerminalApp
        from src.tools.agent import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        initialize_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "initialize_agent":
                initialize_agent = tool.fn
                break
        assert initialize_agent is not None

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
        app_ctx.agents["admin-001"] = Agent(
            id="admin-001",
            role=AgentRole.ADMIN,
            status=AgentStatus.IDLE,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
            ai_cli=AICli.CODEX,
            created_at=now,
            last_activity=now,
        )

        with (
            patch.object(
                app_ctx.ai_cli, "open_worktree_in_terminal", new_callable=AsyncMock
            ) as mock_open_terminal,
            patch.object(app_ctx.ai_cli, "is_available", return_value=True),
        ):
            result = await initialize_agent(
                agent_id="admin-001",
                prompt_type="custom",
                custom_prompt="review this task",
                terminal="iterm2",
                caller_agent_id="owner-001",
                ctx=mock_ctx,
            )

        assert result["success"] is True
        app_ctx.tmux.open_session_in_terminal.assert_awaited_once_with(
            "test", terminal=TerminalApp.ITERM2
        )
        assert app_ctx.tmux.send_with_rate_limit_to_pane.await_count == 1
        send_args, send_kwargs = app_ctx.tmux.send_with_rate_limit_to_pane.await_args
        assert send_args[:3] == ("test", 0, 0)
        assert "cd " in send_args[3]
        assert "codex" in send_args[3]
        assert "--dangerously-bypass-approvals-and-sandbox" in send_args[3]
        assert send_kwargs["confirm_codex_prompt"] is True
        mock_open_terminal.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_agent_fails_when_tmux_attach_fails(self, mock_ctx, git_repo):
        """tmux attach 失敗時は起動せずエラーを返すことをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        initialize_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "initialize_agent":
                initialize_agent = tool.fn
                break
        assert initialize_agent is not None

        app_ctx = mock_ctx.request_context.lifespan_context
        app_ctx.tmux.open_session_in_terminal = AsyncMock(return_value=False)

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
            ai_cli=AICli.CLAUDE,
            created_at=now,
            last_activity=now,
        )

        with patch.object(app_ctx.ai_cli, "is_available", return_value=True):
            result = await initialize_agent(
                agent_id="worker-001",
                prompt_type="custom",
                custom_prompt="run",
                terminal="iterm2",
                caller_agent_id="owner-001",
                ctx=mock_ctx,
            )

        assert result["success"] is False
        assert "tmux セッション" in result["error"]
        app_ctx.tmux.send_with_rate_limit_to_pane.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_initialize_agent_fails_when_cli_is_unavailable(self, mock_ctx, git_repo):
        """CLI が利用不可の場合は success=false を返す。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.agent import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        initialize_agent = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "initialize_agent":
                initialize_agent = tool.fn
                break
        assert initialize_agent is not None

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
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
            ai_cli=AICli.CODEX,
            created_at=now,
            last_activity=now,
        )

        with patch.object(app_ctx.ai_cli, "is_available", return_value=False):
            result = await initialize_agent(
                agent_id="worker-001",
                prompt_type="custom",
                custom_prompt="run",
                terminal="iterm2",
                caller_agent_id="owner-001",
                ctx=mock_ctx,
            )

        assert result["success"] is False
        assert "利用できません" in result["error"]
