"""コマンド実行ツールのテスト。"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

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
def command_test_ctx(git_repo, settings):
    """コマンドツールテスト用のAppContextを作成する。"""
    # モック tmux マネージャー
    mock_tmux = MagicMock(spec=TmuxManager)
    mock_tmux.create_main_session = AsyncMock(return_value=True)
    mock_tmux.send_keys = AsyncMock(return_value=True)
    mock_tmux.send_keys_to_pane = AsyncMock(return_value=True)
    mock_tmux.capture_pane_by_index = AsyncMock(
        return_value="mock output line 1\nmock output line 2"
    )
    mock_tmux.session_exists = AsyncMock(return_value=True)
    mock_tmux.set_pane_title = AsyncMock(return_value=True)
    mock_tmux.add_extra_worker_window = AsyncMock(return_value=True)
    mock_tmux.open_session_in_terminal = AsyncMock(return_value=True)
    mock_tmux._get_window_name = MagicMock(return_value="main")
    mock_tmux._run = AsyncMock(return_value="")
    mock_tmux.settings = settings

    # AI CLI マネージャー
    ai_cli = AiCliManager(settings)

    # IPC マネージャー
    ipc_dir = git_repo / "ipc"
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
def command_mock_ctx(command_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = command_test_ctx
    return mock


class TestSendCommand:
    """send_command ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_send_command_to_worker(self, command_mock_ctx, git_repo):
        """Workerにコマンドを送信できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.command import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        send_command = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "send_command":
                send_command = tool.fn
                break

        # エージェントを追加
        app_ctx = command_mock_ctx.request_context.lifespan_context
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

        result = await send_command(
            agent_id="worker-001",
            command="ls -la",
            caller_agent_id="owner-001",
            ctx=command_mock_ctx,
        )

        assert result["success"] is True
        assert result["command"] == "ls -la"
        assert "送信しました" in result["message"]

    @pytest.mark.asyncio
    async def test_send_command_to_nonexistent_agent_fails(
        self, command_mock_ctx, git_repo
    ):
        """存在しないエージェントへのコマンド送信が失敗することをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.command import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        send_command = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "send_command":
                send_command = tool.fn
                break

        # Owner を追加
        app_ctx = command_mock_ctx.request_context.lifespan_context
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

        result = await send_command(
            agent_id="nonexistent",
            command="ls -la",
            caller_agent_id="owner-001",
            ctx=command_mock_ctx,
        )

        assert result["success"] is False
        assert "見つかりません" in result["error"]

    @pytest.mark.asyncio
    async def test_send_command_to_owner_fails(self, command_mock_ctx, git_repo):
        """Ownerへのコマンド送信が失敗することをテスト（tmuxペインなし）。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.command import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        send_command = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "send_command":
                send_command = tool.fn
                break

        # Owner を追加（tmuxペインなし）
        app_ctx = command_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            session_name=None,
            window_index=None,
            pane_index=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await send_command(
            agent_id="owner-001",
            command="ls -la",
            caller_agent_id="owner-001",
            ctx=command_mock_ctx,
        )

        assert result["success"] is False
        assert "tmux ペインに配置されていません" in result["error"]


class TestGetOutput:
    """get_output ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_capture_pane_output(self, command_mock_ctx, git_repo):
        """ペイン出力を取得できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.command import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        get_output = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_output":
                get_output = tool.fn
                break

        # エージェントを追加
        app_ctx = command_mock_ctx.request_context.lifespan_context
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

        result = await get_output(
            agent_id="worker-001",
            lines=50,
            caller_agent_id="owner-001",
            ctx=command_mock_ctx,
        )

        assert result["success"] is True
        assert result["lines"] == 50
        assert "mock output" in result["output"]

    @pytest.mark.asyncio
    async def test_get_output_with_custom_lines(self, command_mock_ctx, git_repo):
        """カスタム行数で出力を取得できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.command import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        get_output = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_output":
                get_output = tool.fn
                break

        # エージェントを追加
        app_ctx = command_mock_ctx.request_context.lifespan_context
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

        result = await get_output(
            agent_id="worker-001",
            lines=100,
            caller_agent_id="owner-001",
            ctx=command_mock_ctx,
        )

        assert result["success"] is True
        assert result["lines"] == 100


class TestOpenSession:
    """open_session ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_open_session_in_terminal(self, command_mock_ctx, git_repo):
        """ターミナルでセッションを開けることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.command import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        open_session = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "open_session":
                open_session = tool.fn
                break

        # エージェントを追加
        app_ctx = command_mock_ctx.request_context.lifespan_context
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
            created_at=now,
            last_activity=now,
        )

        result = await open_session(
            agent_id="admin-001",
            caller_agent_id="owner-001",
            ctx=command_mock_ctx,
        )

        assert result["success"] is True
        assert result["session"] == "test"
        assert "ターミナルでセッションを開きました" in result["message"]

    @pytest.mark.asyncio
    async def test_open_session_for_agent_without_pane_fails(
        self, command_mock_ctx, git_repo
    ):
        """tmuxペインがないエージェントでエラーになることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.command import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        open_session = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "open_session":
                open_session = tool.fn
                break

        # Owner のみ追加（tmuxペインなし）
        app_ctx = command_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            session_name=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await open_session(
            agent_id="owner-001",
            caller_agent_id="owner-001",
            ctx=command_mock_ctx,
        )

        assert result["success"] is False
        assert "tmux ペインに配置されていません" in result["error"]


class TestBroadcastCommand:
    """broadcast_command ツールのテスト。

    注意: broadcast_command は Admin のみ使用可能。
    """

    @pytest.mark.asyncio
    async def test_broadcast_to_all_agents(self, command_mock_ctx, git_repo):
        """全エージェントにブロードキャストできることをテスト（Admin から）。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.command import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        broadcast_command = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "broadcast_command":
                broadcast_command = tool.fn
                break

        # エージェントを追加
        app_ctx = command_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            session_name=None,
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

        # Admin から呼び出し（broadcast_command は Admin のみ許可）
        result = await broadcast_command(
            command="echo hello",
            caller_agent_id="admin-001",
            ctx=command_mock_ctx,
        )

        assert result["success"] is True
        # Owner は tmux ペインがないのでスキップされる
        assert "2/2" in result["summary"]  # Admin + Worker

    @pytest.mark.asyncio
    async def test_broadcast_to_role_filter(self, command_mock_ctx, git_repo):
        """特定ロールにのみブロードキャストできることをテスト（Admin から）。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.command import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        broadcast_command = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "broadcast_command":
                broadcast_command = tool.fn
                break

        # エージェントを追加
        app_ctx = command_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            session_name=None,
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

        # Admin から呼び出し
        result = await broadcast_command(
            command="echo hello",
            role="worker",
            caller_agent_id="admin-001",
            ctx=command_mock_ctx,
        )

        assert result["success"] is True
        assert result["role_filter"] == "worker"
        # Worker のみ（2人）
        assert len(result["results"]) == 2
        assert "worker-001" in result["results"]
        assert "worker-002" in result["results"]
        assert "admin-001" not in result["results"]

    @pytest.mark.asyncio
    async def test_broadcast_invalid_role_fails(self, command_mock_ctx, git_repo):
        """無効なロールでエラーになることをテスト（Admin から）。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.command import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        broadcast_command = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "broadcast_command":
                broadcast_command = tool.fn
                break

        # エージェントを追加（Admin を追加）
        app_ctx = command_mock_ctx.request_context.lifespan_context
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
            created_at=now,
            last_activity=now,
        )

        # Admin から呼び出し
        result = await broadcast_command(
            command="echo hello",
            role="invalid_role",
            caller_agent_id="admin-001",
            ctx=command_mock_ctx,
        )

        assert result["success"] is False
        assert "無効な役割" in result["error"]


class TestSendTask:
    """send_task ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_send_task_uses_codex_command_from_project_env(
        self, command_mock_ctx, git_repo
    ):
        """project .env 設定に従って codex コマンドを生成できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.command import register_tools
        from src.tools.helpers import refresh_app_settings

        mcp = FastMCP("test")
        register_tools(mcp)

        send_task = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "send_task":
                send_task = tool.fn
                break

        assert send_task is not None

        mcp_dir = git_repo / ".multi-agent-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)
        env_file = mcp_dir / ".env"
        env_file.write_text(
            "MCP_MODEL_PROFILE_STANDARD_CLI=codex\n"
            "MCP_MODEL_PROFILE_STANDARD_ADMIN_MODEL=gpt-5.3-codex\n"
            "MCP_MODEL_PROFILE_STANDARD_WORKER_MODEL=gpt-5.3-codex\n",
            encoding="utf-8",
        )

        app_ctx = command_mock_ctx.request_context.lifespan_context
        refresh_app_settings(app_ctx, str(git_repo))

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
            created_at=now,
            last_activity=now,
        )

        result = await send_task(
            agent_id="admin-001",
            task_content="test task",
            session_id="issue-001",
            auto_enhance=False,
            caller_agent_id="owner-001",
            ctx=command_mock_ctx,
        )

        assert result["success"] is True
        assert "codex --model gpt-5.3-codex" in result["command_sent"]
        assert "codex exec" not in result["command_sent"]
