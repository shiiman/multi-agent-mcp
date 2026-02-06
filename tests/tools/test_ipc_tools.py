"""IPC/メッセージングツールのテスト。"""

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
def ipc_test_ctx(git_repo, settings):
    """IPCツールテスト用のAppContextを作成する。"""
    # モック tmux マネージャー
    mock_tmux = MagicMock(spec=TmuxManager)
    mock_tmux.settings = settings
    mock_tmux.send_keys_to_pane = AsyncMock(return_value=True)

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
def ipc_mock_ctx(ipc_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = ipc_test_ctx
    return mock


class TestSendMessage:
    """send_message ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_send_message_success(self, ipc_mock_ctx, git_repo):
        """メッセージ送信が成功することをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        send_message = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "send_message":
                send_message = tool.fn
                break

        # Owner を追加
        app_ctx = ipc_mock_ctx.request_context.lifespan_context
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

        result = await send_message(
            sender_id="owner-001",
            receiver_id="worker-001",
            message_type="task_assign",
            content="タスクを割り当てます",
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert "message_id" in result

    @pytest.mark.asyncio
    async def test_send_message_invalid_type(self, ipc_mock_ctx, git_repo):
        """無効なメッセージタイプでエラーになることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        send_message = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "send_message":
                send_message = tool.fn
                break

        # Owner を追加
        app_ctx = ipc_mock_ctx.request_context.lifespan_context
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

        result = await send_message(
            sender_id="owner-001",
            receiver_id="worker-001",
            message_type="invalid_type",
            content="テスト",
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert "無効なメッセージタイプ" in result["error"]

    @pytest.mark.asyncio
    async def test_send_broadcast_message(self, ipc_mock_ctx, git_repo):
        """ブロードキャストメッセージの送信をテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        send_message = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "send_message":
                send_message = tool.fn
                break

        # Owner を追加
        app_ctx = ipc_mock_ctx.request_context.lifespan_context
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

        result = await send_message(
            sender_id="owner-001",
            receiver_id=None,  # ブロードキャスト
            message_type="system",
            content="全員へのお知らせ",
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert "ブロードキャスト" in result["message"]

    @pytest.mark.asyncio
    async def test_admin_task_complete_is_blocked_when_quality_gate_not_met(
        self, ipc_mock_ctx, git_repo
    ):
        """Admin→Owner の task_complete は品質ゲート未達時に抑止されることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        send_message = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "send_message":
                send_message = tool.fn
                break

        app_ctx = ipc_mock_ctx.request_context.lifespan_context
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

        result = await send_message(
            sender_id="admin-001",
            receiver_id="owner-001",
            message_type="task_complete",
            content="実装完了しました",
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert result["next_action"] == "replan_and_reassign"
        assert result["gate"]["status"] == "needs_replan"


class TestReadMessages:
    """read_messages ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_read_messages_success(self, ipc_mock_ctx, git_repo):
        """メッセージの読み取りが成功することをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        send_message = None
        read_messages = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "send_message":
                send_message = tool.fn
            elif tool.name == "read_messages":
                read_messages = tool.fn

        # Owner を追加
        app_ctx = ipc_mock_ctx.request_context.lifespan_context
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

        # まずメッセージを送信
        await send_message(
            sender_id="owner-001",
            receiver_id="worker-001",
            message_type="task_assign",
            content="タスクを割り当てます",
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        # メッセージを読み取り
        result = await read_messages(
            agent_id="worker-001",
            caller_agent_id="worker-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert result["count"] >= 1

    @pytest.mark.asyncio
    async def test_read_messages_unread_only(self, ipc_mock_ctx, git_repo):
        """未読メッセージのみの読み取りをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        read_messages = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "read_messages":
                read_messages = tool.fn
                break

        # Owner を追加
        app_ctx = ipc_mock_ctx.request_context.lifespan_context
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

        result = await read_messages(
            agent_id="owner-001",
            unread_only=True,
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True


class TestGetUnreadCount:
    """get_unread_count ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_unread_count(self, ipc_mock_ctx, git_repo):
        """未読数の取得をテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        get_unread_count = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_unread_count":
                get_unread_count = tool.fn
                break

        # Owner を追加
        app_ctx = ipc_mock_ctx.request_context.lifespan_context
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

        result = await get_unread_count(
            agent_id="owner-001",
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert "unread_count" in result


class TestRegisterAgentToIpc:
    """register_agent_to_ipc ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_register_agent_to_ipc(self, ipc_mock_ctx, git_repo):
        """エージェントのIPC登録をテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        register_agent_to_ipc = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "register_agent_to_ipc":
                register_agent_to_ipc = tool.fn
                break

        # Owner を追加
        app_ctx = ipc_mock_ctx.request_context.lifespan_context
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

        result = await register_agent_to_ipc(
            agent_id="new-agent-001",
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert result["agent_id"] == "new-agent-001"
