"""IPC/メッセージングツールのテスト。"""

from datetime import datetime
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
    async def test_task_approved_triggers_auto_cleanup(self, ipc_mock_ctx, git_repo):
        """task_approved 送信時に自動クリーンアップが実行されることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        send_message = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "send_message":
                send_message = tool.fn
                break
        assert send_message is not None

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

        cleanup_result = {
            "terminated_sessions": 1,
            "cleared_agents": 2,
            "removed_worktrees": 1,
            "registry_removed": 2,
        }
        with patch(
            "src.tools.ipc.cleanup_session_resources",
            new=AsyncMock(return_value=cleanup_result),
        ) as mock_cleanup:
            result = await send_message(
                sender_id="owner-001",
                receiver_id="admin-001",
                message_type="task_approved",
                content="承認します",
                caller_agent_id="owner-001",
                ctx=ipc_mock_ctx,
            )

            assert result["success"] is True
            assert result["auto_cleanup_executed"] is True
            assert result["auto_cleanup_result"] == cleanup_result
            assert result["auto_cleanup_error"] is None
            mock_cleanup.assert_awaited_once()

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

    @pytest.mark.asyncio
    async def test_worker_request_reroutes_invalid_receiver_to_admin(
        self, ipc_mock_ctx, git_repo
    ):
        """Worker の request は不正 receiver_id 指定時に Admin へ補正されることをテスト。"""
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

        result = await send_message(
            sender_id="worker-001",
            receiver_id="stale-admin-id",
            message_type="request",
            content="判断をお願いします",
            caller_agent_id="worker-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert result["receiver_id"] == "admin-001"
        assert result["rerouted_receiver_id"] == "admin-001"


class TestReadMessages:
    """read_messages ツールのテスト。"""

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

    @pytest.mark.asyncio
    async def test_read_messages_blocks_admin_polling_after_empty_read(
        self, ipc_mock_ctx, git_repo
    ):
        """Admin が unread=0 で read_messages を連続実行するとブロックされることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        read_messages = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "read_messages":
                read_messages = tool.fn
                break

        app_ctx = ipc_mock_ctx.request_context.lifespan_context
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

        first = await read_messages(
            agent_id="admin-001",
            unread_only=True,
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )
        second = await read_messages(
            agent_id="admin-001",
            unread_only=True,
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )

        assert first["success"] is True
        assert first["count"] == 0
        assert second["success"] is False
        assert "polling_blocked" in second["error"]

    @pytest.mark.asyncio
    async def test_read_messages_blocks_owner_polling_while_waiting(
        self, ipc_mock_ctx, git_repo
    ):
        """Owner が待機ロック中に unread=0 を連続確認するとブロックされることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        read_messages = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "read_messages":
                read_messages = tool.fn
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
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": now,
            "unlocked_at": None,
            "unlock_reason": None,
        }

        result = await read_messages(
            agent_id="owner-001",
            unread_only=True,
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert "polling_blocked" in result["error"]

    @pytest.mark.asyncio
    async def test_read_messages_owner_unlocked_after_admin_message(
        self, ipc_mock_ctx, git_repo
    ):
        """待機中 Owner が Admin メッセージを読むと待機ロック解除されることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.models.message import MessageType
        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        read_messages = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "read_messages":
                read_messages = tool.fn
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
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": now,
            "unlocked_at": None,
            "unlock_reason": None,
        }
        app_ctx.ipc_manager.send_message(
            sender_id="admin-001",
            receiver_id="owner-001",
            message_type=MessageType.SYSTEM,
            content="進捗報告です",
        )

        result = await read_messages(
            agent_id="owner-001",
            unread_only=True,
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert result["count"] == 1
        assert result["owner_wait_unlocked"] is True
        state = app_ctx._owner_wait_state["owner-001"]
        assert state["waiting_for_admin"] is False
        assert state["unlock_reason"] == "admin_notification_consumed"


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


class TestUnlockOwnerWait:
    """unlock_owner_wait ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_unlock_owner_wait_idempotent(self, ipc_mock_ctx, git_repo):
        """unlock_owner_wait が冪等に動作することをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        unlock_owner_wait = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "unlock_owner_wait":
                unlock_owner_wait = tool.fn
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
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": now,
            "unlocked_at": None,
            "unlock_reason": None,
        }

        first = await unlock_owner_wait(
            reason="manual_recovery",
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )
        second = await unlock_owner_wait(
            reason="manual_recovery_again",
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert first["success"] is True
        assert first["waiting_before"] is True
        assert first["waiting_after"] is False
        assert second["success"] is True
        assert second["waiting_before"] is False
        assert second["waiting_after"] is False


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


class TestMacOSNotificationRestriction:
    """macOS 通知が admin→owner の task_complete のみに制限されることをテスト。"""

    @pytest.fixture
    def _setup_agents(self, ipc_mock_ctx, git_repo):
        """テスト用エージェントをセットアップする。"""
        app_ctx = ipc_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        # Owner（tmux ペインなし）
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )
        # Admin
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
        # Worker
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
        # 品質ゲートを緩和して task_complete を通す
        app_ctx.settings.quality_gate_strict = False
        return app_ctx

    def _get_send_message(self):
        """send_message ツール関数を取得する。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        for tool in mcp._tool_manager._tools.values():
            if tool.name == "send_message":
                return tool.fn
        raise RuntimeError("send_message ツールが見つかりません")

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_setup_agents")
    async def test_admin_to_owner_task_complete_sends_macos_notification(
        self, ipc_mock_ctx
    ):
        """admin→owner の task_complete で macOS 通知が送信されることをテスト。"""
        send_message = self._get_send_message()

        with patch(
            "src.tools.helpers._send_macos_notification",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_notify:
            result = await send_message(
                sender_id="admin-001",
                receiver_id="owner-001",
                message_type="task_complete",
                content="全タスク完了しました",
                caller_agent_id="admin-001",
                ctx=ipc_mock_ctx,
            )

            assert result["success"] is True
            assert result["notification_method"] == "macos"
            mock_notify.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_setup_agents")
    async def test_worker_to_owner_does_not_send_macos_notification(
        self, ipc_mock_ctx
    ):
        """worker→owner のメッセージで macOS 通知が送信されないことをテスト。"""
        send_message = self._get_send_message()

        with patch(
            "src.tools.helpers._send_macos_notification",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_notify:
            result = await send_message(
                sender_id="worker-001",
                receiver_id="owner-001",
                message_type="task_complete",
                content="タスク完了しました",
                caller_agent_id="worker-001",
                ctx=ipc_mock_ctx,
            )

            assert result["success"] is True
            assert result["notification_method"] is None
            mock_notify.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_setup_agents")
    async def test_admin_to_owner_non_complete_does_not_send_macos_notification(
        self, ipc_mock_ctx
    ):
        """admin→owner の task_complete 以外で macOS 通知が送信されないことをテスト。"""
        send_message = self._get_send_message()

        with patch(
            "src.tools.helpers._send_macos_notification",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_notify:
            result = await send_message(
                sender_id="admin-001",
                receiver_id="owner-001",
                message_type="system",
                content="システムメッセージ",
                caller_agent_id="admin-001",
                ctx=ipc_mock_ctx,
            )

            assert result["success"] is True
            assert result["notification_method"] is None
            mock_notify.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_setup_agents")
    async def test_worker_to_admin_tmux_fallback_does_not_send_macos(
        self, ipc_mock_ctx
    ):
        """worker→admin の tmux 失敗時に macOS フォールバックが発火しないことをテスト。"""
        send_message = self._get_send_message()
        app_ctx = ipc_mock_ctx.request_context.lifespan_context
        # tmux 送信を常に失敗させる
        app_ctx.tmux.send_with_rate_limit_to_pane = AsyncMock(return_value=False)

        with patch(
            "src.tools.helpers._send_macos_notification",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_notify:
            result = await send_message(
                sender_id="worker-001",
                receiver_id="admin-001",
                message_type="task_complete",
                content="タスク完了",
                caller_agent_id="worker-001",
                ctx=ipc_mock_ctx,
            )

            assert result["success"] is True
            # tmux 失敗しても macOS フォールバックは発火しない（admin→owner 以外）
            mock_notify.assert_not_called()
