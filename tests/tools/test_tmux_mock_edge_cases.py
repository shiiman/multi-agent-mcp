"""tmux 操作のモック化テストとエッジケース。

tmux send_keys/capture_pane の失敗パターン、権限チェックのエッジケース、
空入力・不正入力への堅牢性をテストする。
"""

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
from src.models.agent import AgentRole, AgentStatus
from tests.conftest import add_test_agent, get_tool_fn


@pytest.fixture
def edge_test_ctx(git_repo, settings):
    """エッジケーステスト用の AppContext を作成する。"""
    mock_tmux = MagicMock(spec=TmuxManager)
    mock_tmux.settings = settings
    mock_tmux.create_main_session = AsyncMock(return_value=True)
    mock_tmux.send_keys = AsyncMock(return_value=True)
    mock_tmux.send_keys_to_pane = AsyncMock(return_value=True)
    mock_tmux.send_with_rate_limit_to_pane = AsyncMock(return_value=True)
    mock_tmux.capture_pane_by_index = AsyncMock(return_value="mock output")
    mock_tmux.session_exists = AsyncMock(return_value=True)
    mock_tmux.set_pane_title = AsyncMock(return_value=True)
    mock_tmux.add_extra_worker_window = AsyncMock(return_value=True)
    mock_tmux.open_session_in_terminal = AsyncMock(return_value=True)
    mock_tmux._get_window_name = MagicMock(return_value="main")
    mock_tmux._run = AsyncMock(return_value="")

    ai_cli = AiCliManager(settings)

    ipc_dir = git_repo / "ipc"
    ipc = IPCManager(str(ipc_dir))
    ipc.initialize()

    dashboard_dir = git_repo / ".dashboard"
    dashboard = DashboardManager(
        workspace_id="test-workspace",
        workspace_path=str(git_repo),
        dashboard_dir=str(dashboard_dir),
    )
    dashboard.initialize()

    memory = MemoryManager(str(git_repo / ".memory"))
    persona = PersonaManager()
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
    ipc.cleanup()
    dashboard.cleanup()


@pytest.fixture
def edge_mock_ctx(edge_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = edge_test_ctx
    return mock


def _register_command_tools():
    """コマンドツールを登録した FastMCP インスタンスを返す。"""
    from mcp.server.fastmcp import FastMCP

    from src.tools.command import register_tools

    mcp = FastMCP("test")
    register_tools(mcp)
    return mcp


class TestTmuxSendFailure:
    """tmux send 操作が失敗する場合のテスト。"""

    @pytest.mark.asyncio
    async def test_send_command_tmux_failure_returns_false(self, edge_mock_ctx, git_repo):
        """tmux send_with_rate_limit_to_pane が False を返した場合に success=False。"""
        mcp = _register_command_tools()
        send_command = get_tool_fn(mcp, "send_command")

        add_test_agent(edge_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))
        add_test_agent(
            edge_mock_ctx, "worker-001", AgentRole.WORKER, str(git_repo),
            tmux_session="test:0.1", session_name="test",
            window_index=0, pane_index=1,
        )

        # tmux 送信を失敗させる
        app_ctx = edge_mock_ctx.request_context.lifespan_context
        app_ctx.tmux.send_with_rate_limit_to_pane = AsyncMock(return_value=False)

        result = await send_command(
            agent_id="worker-001",
            command="echo test",
            caller_agent_id="owner-001",
            ctx=edge_mock_ctx,
        )

        assert result["success"] is False
        assert "失敗" in result["message"]

    @pytest.mark.asyncio
    async def test_get_output_capture_empty_returns_success(self, edge_mock_ctx, git_repo):
        """capture が空文字列を返しても success=True を返す。"""
        mcp = _register_command_tools()
        get_output = get_tool_fn(mcp, "get_output")

        add_test_agent(edge_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))
        add_test_agent(
            edge_mock_ctx, "worker-001", AgentRole.WORKER, str(git_repo),
            status=AgentStatus.BUSY,
            tmux_session="test:0.1", session_name="test",
            window_index=0, pane_index=1,
        )

        # 空出力を返すモック
        app_ctx = edge_mock_ctx.request_context.lifespan_context
        app_ctx.tmux.capture_pane_by_index = AsyncMock(return_value="")

        result = await get_output(
            agent_id="worker-001",
            lines=50,
            caller_agent_id="owner-001",
            ctx=edge_mock_ctx,
        )

        assert result["success"] is True
        assert result["output"] == ""


class TestPermissionEdgeCases:
    """権限チェックのエッジケーステスト。"""

    @pytest.mark.asyncio
    async def test_caller_agent_id_none_for_non_owner_tool(self, edge_mock_ctx, git_repo):
        """caller_agent_id=None で Owner 以外のツールを呼ぶとエラー。"""
        mcp = _register_command_tools()
        send_command = get_tool_fn(mcp, "send_command")

        result = await send_command(
            agent_id="worker-001",
            command="echo test",
            caller_agent_id=None,
            ctx=edge_mock_ctx,
        )

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_send_command_to_terminated_agent_still_sends(self, edge_mock_ctx, git_repo):
        """TERMINATED 状態のエージェントにもコマンド送信自体は可能（ステータスチェックなし）。"""
        mcp = _register_command_tools()
        send_command = get_tool_fn(mcp, "send_command")

        add_test_agent(edge_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))
        add_test_agent(
            edge_mock_ctx, "worker-001", AgentRole.WORKER, str(git_repo),
            status=AgentStatus.TERMINATED,
            tmux_session="test:0.1", session_name="test",
            window_index=0, pane_index=1,
        )

        result = await send_command(
            agent_id="worker-001",
            command="echo hello",
            caller_agent_id="owner-001",
            ctx=edge_mock_ctx,
        )

        # send_command は状態チェックせずに tmux 送信を行う
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_worker_cannot_use_broadcast_command(self, edge_mock_ctx, git_repo):
        """Worker は broadcast_command を使用できない。"""
        mcp = _register_command_tools()
        broadcast_command = get_tool_fn(mcp, "broadcast_command")

        add_test_agent(
            edge_mock_ctx, "worker-001", AgentRole.WORKER, str(git_repo),
            tmux_session="test:0.1", session_name="test",
            window_index=0, pane_index=1,
        )

        result = await broadcast_command(
            command="echo hello",
            caller_agent_id="worker-001",
            ctx=edge_mock_ctx,
        )

        assert result["success"] is False
        assert "使用禁止" in result["error"]


class TestEmptyInputEdgeCases:
    """空入力や不正入力に対するエッジケーステスト。"""

    @pytest.mark.asyncio
    async def test_send_empty_command(self, edge_mock_ctx, git_repo):
        """空コマンドでも送信可能（コマンド内容の検証はツール側で行わない）。"""
        mcp = _register_command_tools()
        send_command = get_tool_fn(mcp, "send_command")

        add_test_agent(edge_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))
        add_test_agent(
            edge_mock_ctx, "worker-001", AgentRole.WORKER, str(git_repo),
            tmux_session="test:0.1", session_name="test",
            window_index=0, pane_index=1,
        )

        result = await send_command(
            agent_id="worker-001",
            command="",
            caller_agent_id="owner-001",
            ctx=edge_mock_ctx,
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_get_output_zero_lines(self, edge_mock_ctx, git_repo):
        """lines=0 でもエラーにならない。"""
        mcp = _register_command_tools()
        get_output = get_tool_fn(mcp, "get_output")

        add_test_agent(edge_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))
        add_test_agent(
            edge_mock_ctx, "worker-001", AgentRole.WORKER, str(git_repo),
            status=AgentStatus.BUSY,
            tmux_session="test:0.1", session_name="test",
            window_index=0, pane_index=1,
        )

        result = await get_output(
            agent_id="worker-001",
            lines=0,
            caller_agent_id="owner-001",
            ctx=edge_mock_ctx,
        )

        assert result["success"] is True


class TestSchedulerEdgeCases:
    """スケジューラーツールのエッジケーステスト。"""

    @pytest.mark.asyncio
    async def test_enqueue_task_with_invalid_priority(self, edge_mock_ctx, git_repo):
        """無効な優先度でのスケジュールが適切に処理される。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.scheduler import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)
        enqueue_task = get_tool_fn(mcp, "enqueue_task")

        add_test_agent(edge_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        # Dashboard にタスクを作成
        app_ctx = edge_mock_ctx.request_context.lifespan_context
        task = app_ctx.dashboard_manager.create_task(title="テストタスク")

        result = await enqueue_task(
            task_id=task.id,
            priority="invalid_priority",
            caller_agent_id="admin-001",
            ctx=edge_mock_ctx,
        )

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_get_task_queue_when_empty(self, edge_mock_ctx, git_repo):
        """キューが空の時の get_task_queue。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.scheduler import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)
        get_task_queue = get_tool_fn(mcp, "get_task_queue")

        add_test_agent(edge_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        result = await get_task_queue(
            caller_agent_id="admin-001",
            ctx=edge_mock_ctx,
        )

        assert result["success"] is True
        assert "queue" in result


class TestHealthcheckEdgeCases:
    """ヘルスチェックツールのエッジケーステスト。"""

    @pytest.mark.asyncio
    async def test_healthcheck_all_with_no_workers(self, edge_mock_ctx, git_repo):
        """Worker がいない状態での healthcheck_all。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.healthcheck import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)
        healthcheck_all = get_tool_fn(mcp, "healthcheck_all")

        add_test_agent(edge_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))

        result = await healthcheck_all(
            caller_agent_id="owner-001",
            ctx=edge_mock_ctx,
        )

        assert result["success"] is True
        # Owner 1人のみ（Worker なし）
        assert result["summary"]["total"] == 1


class TestDashboardEdgeCases:
    """ダッシュボードツールのエッジケーステスト。"""

    @pytest.mark.asyncio
    async def test_create_task_with_empty_title(self, edge_mock_ctx, git_repo):
        """空タイトルでタスク作成を試みる。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)
        create_task = get_tool_fn(mcp, "create_task")

        add_test_agent(edge_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))

        result = await create_task(
            title="",
            caller_agent_id="owner-001",
            ctx=edge_mock_ctx,
        )

        # 空タイトルでもタスクは作成される（バリデーションは呼び出し側の責務）
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_nonexistent_task(self, edge_mock_ctx, git_repo):
        """存在しないタスクの更新がエラーを返す。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.dashboard import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)
        update_status = get_tool_fn(mcp, "update_task_status")

        add_test_agent(edge_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        result = await update_status(
            task_id="nonexistent-task-id",
            status="completed",
            caller_agent_id="admin-001",
            ctx=edge_mock_ctx,
        )

        assert result["success"] is False


class TestIPCEdgeCases:
    """IPC ツールのエッジケーステスト。"""

    @pytest.mark.asyncio
    async def test_send_message_with_invalid_type(self, edge_mock_ctx, git_repo):
        """無効なメッセージタイプでの送信がエラーになる。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)
        send_message = get_tool_fn(mcp, "send_message")

        add_test_agent(edge_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))

        result = await send_message(
            sender_id="owner-001",
            receiver_id="admin-001",
            message_type="invalid_type",
            content="テストメッセージ",
            caller_agent_id="owner-001",
            ctx=edge_mock_ctx,
        )

        assert result["success"] is False
        assert "無効なメッセージタイプ" in result["error"]

    @pytest.mark.asyncio
    async def test_read_messages_empty_inbox(self, edge_mock_ctx, git_repo):
        """メッセージがないエージェントの受信ボックスを読む。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)
        read_messages = get_tool_fn(mcp, "read_messages")

        add_test_agent(edge_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        result = await read_messages(
            agent_id="admin-001",
            caller_agent_id="admin-001",
            ctx=edge_mock_ctx,
        )

        assert result["success"] is True
        assert result["count"] == 0
