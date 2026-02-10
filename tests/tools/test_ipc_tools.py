"""IPC/メッセージングツールのテスト。"""

import subprocess
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
from src.models.dashboard import TaskStatus


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
    async def test_admin_task_complete_passes_when_branch_files_covered_by_diff(
        self, ipc_mock_ctx, git_repo
    ):
        """branch の変更ファイルが diff に含まれていれば task_complete が通ることをテスト。"""
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

        feature_branch = "feature/task-impl"
        target_file = git_repo / "feature_impl.txt"
        target_file.write_text("base\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(git_repo), "add", "feature_impl.txt"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(git_repo), "commit", "-m", "add base file"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(git_repo), "checkout", "-b", feature_branch],
            capture_output=True,
            check=True,
        )
        target_file.write_text("feature change\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(git_repo), "commit", "-am", "feature change"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(git_repo), "checkout", "main"],
            capture_output=True,
            check=True,
        )
        # no-commit preview と同様に統合ブランチへ差分を展開した状態を作る
        target_file.write_text("preview applied\n", encoding="utf-8")

        impl_task = app_ctx.dashboard_manager.create_task(
            title="実装タスク",
            branch=feature_branch,
        )
        app_ctx.dashboard_manager.update_task_status(impl_task.id, TaskStatus.COMPLETED)
        quality_task = app_ctx.dashboard_manager.create_task(
            title="test smoke",
            branch=None,
        )
        app_ctx.dashboard_manager.update_task_status(quality_task.id, TaskStatus.COMPLETED)

        result = await send_message(
            sender_id="admin-001",
            receiver_id="owner-001",
            message_type="task_complete",
            content="実装完了しました",
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert result["gate"]["status"] == "passed"

    @pytest.mark.asyncio
    async def test_admin_task_complete_fails_when_diff_missing_branch_files(
        self, ipc_mock_ctx, git_repo
    ):
        """branch 変更の一部が diff に無いと task_complete がブロックされることをテスト。"""
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

        feature_branch = "feature/task-partial"
        first_file = git_repo / "a.txt"
        second_file = git_repo / "b.txt"
        first_file.write_text("a-base\n", encoding="utf-8")
        second_file.write_text("b-base\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(git_repo), "add", "a.txt", "b.txt"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(git_repo), "commit", "-m", "base files"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(git_repo), "checkout", "-b", feature_branch],
            capture_output=True,
            check=True,
        )
        first_file.write_text("a-feature\n", encoding="utf-8")
        second_file.write_text("b-feature\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(git_repo), "commit", "-am", "feature update"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(git_repo), "checkout", "main"],
            capture_output=True,
            check=True,
        )
        # 片方のファイルだけ差分化（もう片方は不足）
        first_file.write_text("a-preview\n", encoding="utf-8")

        impl_task = app_ctx.dashboard_manager.create_task(
            title="実装修正",
            branch=feature_branch,
        )
        app_ctx.dashboard_manager.update_task_status(impl_task.id, TaskStatus.COMPLETED)
        quality_task = app_ctx.dashboard_manager.create_task(
            title="qa test",
            branch=None,
        )
        app_ctx.dashboard_manager.update_task_status(quality_task.id, TaskStatus.COMPLETED)

        result = await send_message(
            sender_id="admin-001",
            receiver_id="owner-001",
            message_type="task_complete",
            content="実装完了しました",
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert result["gate"]["status"] == "needs_replan"
        assert "未統合の完了タスクブランチがあります" in " ".join(result["gate"]["reasons"])
        assert result["gate"]["branch_integration"][0]["missing_files"] == ["b.txt"]

    @pytest.mark.asyncio
    async def test_admin_task_complete_reports_branch_not_found(
        self, ipc_mock_ctx, git_repo
    ):
        """存在しない branch の completed タスクが branch_not_found で報告されることをテスト。"""
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

        missing_task = app_ctx.dashboard_manager.create_task(
            title="実装タスク",
            branch="feature/not-found",
        )
        app_ctx.dashboard_manager.update_task_status(missing_task.id, TaskStatus.COMPLETED)
        quality_task = app_ctx.dashboard_manager.create_task(title="test verify")
        app_ctx.dashboard_manager.update_task_status(quality_task.id, TaskStatus.COMPLETED)

        result = await send_message(
            sender_id="admin-001",
            receiver_id="owner-001",
            message_type="task_complete",
            content="実装完了しました",
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert result["gate"]["status"] == "needs_replan"
        assert any("branch_not_found" in reason for reason in result["gate"]["reasons"])
        assert result["gate"]["branch_integration"][0]["branch_not_found"] is True

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

    @pytest.mark.asyncio
    async def test_send_message_rejects_sender_caller_mismatch(
        self, ipc_mock_ctx, git_repo
    ):
        """sender_id と caller_agent_id が不一致の場合は拒否される。"""
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
            receiver_id="owner-001",
            message_type="system",
            content="spoof",
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert "sender_id と caller_agent_id が一致しない" in result["error"]

    @pytest.mark.asyncio
    async def test_admin_to_owner_non_complete_uses_macos_fallback(
        self, ipc_mock_ctx, git_repo
    ):
        """admin→owner の task_complete 以外でも通知が欠落しないことをテスト。"""
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

        with patch("src.tools.helpers._send_macos_notification", new=AsyncMock(return_value=True)):
            result = await send_message(
                sender_id="admin-001",
                receiver_id="owner-001",
                message_type="task_failed",
                content="検証失敗",
                caller_agent_id="admin-001",
                ctx=ipc_mock_ctx,
            )

        assert result["success"] is True
        assert result["notification_sent"] is True
        assert result["notification_method"] == "macos"


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
    async def test_worker_read_messages_blocks_other_agent(
        self, ipc_mock_ctx, git_repo
    ):
        """Worker は他 agent の read_messages を実行できない。"""
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
            caller_agent_id="worker-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert "自分自身の agent_id" in result["error"]

    @pytest.mark.asyncio
    async def test_worker_read_messages_allows_self(self, ipc_mock_ctx, git_repo):
        """Worker は自分自身の read_messages は実行できる。"""
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

        result = await read_messages(
            agent_id="worker-001",
            unread_only=True,
            caller_agent_id="worker-001",
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

    @pytest.mark.asyncio
    async def test_read_messages_admin_auto_updates_dashboard_from_task_progress(
        self, ipc_mock_ctx, git_repo
    ):
        """Admin read_messages 時に task_progress から Dashboard が自動更新されることをテスト。"""
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
        assert read_messages is not None

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

        task = app_ctx.dashboard_manager.create_task(
            title="progress target",
            description="auto update",
            assigned_agent_id="worker-001",
        )

        app_ctx.ipc_manager.send_message(
            sender_id="worker-001",
            receiver_id="admin-001",
            message_type=MessageType.TASK_PROGRESS,
            content="50% reached",
            metadata={
                "task_id": f"task:{task.id}",
                "progress": 50,
                "message": "50% reached",
                "reporter": "worker-001",
            },
        )

        result = await read_messages(
            agent_id="admin-001",
            unread_only=True,
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert result["dashboard_updated"] is True
        assert result["dashboard_updates_applied"] == 1
        updated = app_ctx.dashboard_manager.get_task(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.IN_PROGRESS
        assert updated.progress == 50

    @pytest.mark.asyncio
    async def test_read_messages_admin_auto_updates_dashboard_from_task_failed(
        self, ipc_mock_ctx, git_repo
    ):
        """Admin read_messages 時に task_failed から Dashboard が自動更新されることをテスト。"""
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
        assert read_messages is not None

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

        task = app_ctx.dashboard_manager.create_task(
            title="failure target",
            description="auto update",
            assigned_agent_id="worker-001",
        )
        app_ctx.agents["worker-001"].current_task = task.id

        app_ctx.ipc_manager.send_message(
            sender_id="worker-001",
            receiver_id="admin-001",
            message_type=MessageType.TASK_FAILED,
            content="failed",
            metadata={
                "task_id": f"task:{task.id}",
                "reporter": "worker-001",
            },
        )

        result = await read_messages(
            agent_id="admin-001",
            unread_only=True,
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert result["dashboard_updated"] is True
        assert result["dashboard_updates_applied"] == 1
        updated = app_ctx.dashboard_manager.get_task(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.FAILED


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

    @pytest.mark.asyncio
    async def test_worker_get_unread_count_blocks_other_agent(
        self, ipc_mock_ctx, git_repo
    ):
        """Worker は他 agent の未読数を取得できない。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        get_unread_count = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_unread_count":
                get_unread_count = tool.fn
                break

        app_ctx = ipc_mock_ctx.request_context.lifespan_context
        now = datetime.now()
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
            caller_agent_id="worker-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert "自分自身の agent_id" in result["error"]


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
