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


@pytest.fixture
def ipc_no_git_ctx(tmp_path, settings):
    """enable_git=false の IPCツールテスト用 AppContext。"""
    settings.enable_git = False

    mock_tmux = MagicMock(spec=TmuxManager)
    mock_tmux.settings = settings
    mock_tmux.send_keys_to_pane = AsyncMock(return_value=True)

    ai_cli = AiCliManager(settings)

    work_dir = tmp_path / "no_git_project"
    work_dir.mkdir()

    ipc_dir = work_dir / ".ipc"
    ipc = IPCManager(str(ipc_dir))
    ipc.initialize()

    dashboard_dir = work_dir / ".dashboard"
    dashboard = DashboardManager(
        workspace_id="test-workspace",
        workspace_path=str(work_dir),
        dashboard_dir=str(dashboard_dir),
    )
    dashboard.initialize()

    memory_dir = work_dir / ".memory"
    memory = MemoryManager(str(memory_dir))
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
        project_root=str(work_dir),
        session_id="test-session",
    )

    yield ctx

    ipc.cleanup()
    dashboard.cleanup()


@pytest.fixture
def ipc_no_git_mock_ctx(ipc_no_git_ctx):
    """No-git モード用 MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = ipc_no_git_ctx
    return mock


def _make_agent(
    agent_id: str,
    role: AgentRole,
    *,
    status: AgentStatus = AgentStatus.IDLE,
    working_dir: str = "/tmp",
    tmux_session: str | None = None,
    session_name: str | None = None,
    window_index: int | None = None,
    pane_index: int | None = None,
) -> Agent:
    """テスト用 Agent を生成するファクトリ関数。"""
    now = datetime.now()
    return Agent(
        id=agent_id,
        role=role,
        status=status,
        tmux_session=tmux_session,
        session_name=session_name,
        window_index=window_index,
        pane_index=pane_index,
        working_dir=working_dir,
        created_at=now,
        last_activity=now,
    )


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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
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

        with patch(
            "src.tools.helpers._send_macos_notification",
            new=AsyncMock(return_value=True),
        ):
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
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
    async def test_admin_task_complete_non_ui_e2e_task_does_not_require_playwright(
        self, ipc_mock_ctx, git_repo
    ):
        """非UIの e2e 文脈だけでは Playwright 必須判定が発火しないことをテスト。"""
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )

        impl_task = app_ctx.dashboard_manager.create_task(title="API e2e hardening")
        app_ctx.dashboard_manager.update_task_status(impl_task.id, TaskStatus.COMPLETED)
        quality_task = app_ctx.dashboard_manager.create_task(title="qa test")
        app_ctx.dashboard_manager.update_task_status(quality_task.id, TaskStatus.COMPLETED)

        with patch(
            "src.tools.helpers._send_macos_notification",
            new=AsyncMock(return_value=True),
        ):
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
    async def test_admin_task_complete_prioritizes_requires_playwright_metadata(
        self, ipc_mock_ctx, git_repo
    ):
        """metadata.requires_playwright の明示指定を優先することをテスト。"""
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )

        ui_task = app_ctx.dashboard_manager.create_task(
            title="backend batch job",
            metadata={"requires_playwright": True},
        )
        app_ctx.dashboard_manager.update_task_status(ui_task.id, TaskStatus.COMPLETED)
        quality_task = app_ctx.dashboard_manager.create_task(title="qa test")
        app_ctx.dashboard_manager.update_task_status(quality_task.id, TaskStatus.COMPLETED)

        blocked = await send_message(
            sender_id="admin-001",
            receiver_id="owner-001",
            message_type="task_complete",
            content="実装完了しました",
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )

        assert blocked["success"] is False
        assert "Playwright 証跡が不足" in " ".join(blocked["gate"]["reasons"])

        pw_task = app_ctx.dashboard_manager.create_task(
            title="playwright qa check",
            metadata={"requires_playwright": True},
        )
        app_ctx.dashboard_manager.update_task_status(pw_task.id, TaskStatus.COMPLETED)

        with patch(
            "src.tools.helpers._send_macos_notification",
            new=AsyncMock(return_value=True),
        ):
            passed = await send_message(
                sender_id="admin-001",
                receiver_id="owner-001",
                message_type="task_complete",
                content="再確認済み",
                caller_agent_id="admin-001",
                ctx=ipc_mock_ctx,
            )

        assert passed["success"] is True
        assert passed["gate"]["status"] == "passed"

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
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx.agents["worker-001"] = _make_agent(
            "worker-001", AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
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
    async def test_worker_send_message_allows_admin_receiver(
        self, ipc_mock_ctx, git_repo
    ):
        """Worker が Admin 宛へ送信できることをテスト。"""
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
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx.agents["worker-001"] = _make_agent(
            "worker-001", AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
        )

        result = await send_message(
            sender_id="worker-001",
            receiver_id="admin-001",
            message_type="request",
            content="確認お願いします",
            caller_agent_id="worker-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert result["receiver_id"] == "admin-001"
        assert result["rerouted_receiver_id"] is None

    @pytest.mark.asyncio
    async def test_worker_send_message_rejects_owner_receiver(
        self, ipc_mock_ctx, git_repo
    ):
        """Worker から Owner 宛の send_message は拒否されることをテスト。"""
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
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["worker-001"] = _make_agent(
            "worker-001", AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
        )

        result = await send_message(
            sender_id="worker-001",
            receiver_id="owner-001",
            message_type="request",
            content="owner へ送ってしまうケース",
            caller_agent_id="worker-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert "Worker は Admin にのみ send_message" in result["error"]

    @pytest.mark.asyncio
    async def test_worker_send_message_rejects_other_worker_receiver(
        self, ipc_mock_ctx, git_repo
    ):
        """Worker から他 Worker 宛の send_message は拒否されることをテスト。"""
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
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx.agents["worker-001"] = _make_agent(
            "worker-001", AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
        )
        app_ctx.agents["worker-002"] = _make_agent(
            "worker-002", AgentRole.WORKER,
            tmux_session="test:0.2",
            session_name="test",
            window_index=0,
            pane_index=2,
            working_dir=str(git_repo),
        )

        result = await send_message(
            sender_id="worker-001",
            receiver_id="worker-002",
            message_type="request",
            content="worker 間送信ケース",
            caller_agent_id="worker-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert "Worker は Admin にのみ send_message" in result["error"]

    @pytest.mark.asyncio
    async def test_worker_send_message_rejects_broadcast(
        self, ipc_mock_ctx, git_repo
    ):
        """Worker のブロードキャスト送信は拒否されることをテスト。"""
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
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx.agents["worker-001"] = _make_agent(
            "worker-001", AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
        )

        result = await send_message(
            sender_id="worker-001",
            receiver_id=None,
            message_type="request",
            content="broadcast ケース",
            caller_agent_id="worker-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert "ブロードキャストできません" in result["error"]

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
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
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
        """admin→owner の task_complete 以外でも macOS 通知することをテスト。"""
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
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )

        with patch(
            "src.tools.helpers._send_macos_notification",
            new=AsyncMock(return_value=True),
        ) as mock_macos:
            result = await send_message(
                sender_id="admin-001",
                receiver_id="owner-001",
                message_type="task_failed",
                content="検証失敗",
                caller_agent_id="admin-001",
                ctx=ipc_mock_ctx,
            )

        assert result["success"] is True
        assert result["delivery_state"] == "delivered"
        assert result["notification_sent"] is True
        assert result["notification_method"] == "macos"
        mock_macos.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_message_returns_failed_delivery_when_tmux_notify_fails(
        self, ipc_mock_ctx, git_repo
    ):
        """通知失敗時は success=False と delivery_state を返すことをテスト。"""
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )

        with patch("src.tools.ipc.notify_agent_via_tmux", new=AsyncMock(return_value=False)):
            result = await send_message(
                sender_id="owner-001",
                receiver_id="admin-001",
                message_type="system",
                content="通知失敗を想定",
                caller_agent_id="owner-001",
                ctx=ipc_mock_ctx,
            )

        assert result["success"] is False
        assert result["delivery_state"] == "queued_unnotified"
        assert result["message_saved"] is True
        assert result["notification_sent"] is False
        assert "delivery_failed" in result["error"]
        assert app_ctx.ipc_manager.get_unread_count("admin-001") == 1


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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
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
        app_ctx.agents["worker-001"] = _make_agent(
            "worker-001", AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
        )
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
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
        app_ctx.agents["worker-001"] = _make_agent(
            "worker-001", AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
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
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": datetime.now(),
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
        assert result["next_action"] == "wait_for_user_input_or_unlock_owner_wait"

    @pytest.mark.asyncio
    async def test_read_messages_blocks_owner_polling_even_without_unread_only(
        self, ipc_mock_ctx, git_repo
    ):
        """Owner 待機ロック中は unread_only=False の空読みもブロックされることをテスト。"""
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": datetime.now(),
            "unlocked_at": None,
            "unlock_reason": None,
        }

        result = await read_messages(
            agent_id="owner-001",
            unread_only=False,
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert "polling_blocked" in result["error"]
        assert result["next_action"] == "wait_for_user_input_or_unlock_owner_wait"

    @pytest.mark.asyncio
    async def test_read_messages_blocks_owner_polling_for_other_inbox_while_waiting(
        self, ipc_mock_ctx, git_repo
    ):
        """Owner 待機ロック中は他エージェント inbox の監視呼び出しをブロックする。"""
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": datetime.now(),
            "unlocked_at": None,
            "unlock_reason": None,
        }
        app_ctx.ipc_manager.send_message(
            sender_id="admin-001",
            receiver_id="admin-001",
            message_type=MessageType.SYSTEM,
            content="admin inbox message",
        )

        result = await read_messages(
            agent_id="admin-001",
            unread_only=True,
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert "polling_blocked" in result["error"]
        assert result["next_action"] == "wait_for_user_input_or_unlock_owner_wait"

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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": datetime.now(),
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
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx.agents["worker-001"] = _make_agent(
            "worker-001", AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
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
        assert app_ctx.ipc_manager.get_unread_count("admin-001") == 0

    @pytest.mark.asyncio
    async def test_read_messages_uses_authenticated_caller_for_admin_flow(
        self, ipc_mock_ctx, git_repo
    ):
        """caller_agent_id 省略時でも認証済み主体で Admin 分岐できることをテスト。"""
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
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx.agents["worker-001"] = _make_agent(
            "worker-001", AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
        )

        task = app_ctx.dashboard_manager.create_task(
            title="authenticated caller target",
            description="auto update",
            assigned_agent_id="worker-001",
        )
        app_ctx.ipc_manager.send_message(
            sender_id="worker-001",
            receiver_id="admin-001",
            message_type=MessageType.TASK_PROGRESS,
            content="40% reached",
            metadata={
                "task_id": f"task:{task.id}",
                "progress": 40,
                "message": "40% reached",
                "reporter": "worker-001",
            },
        )

        ipc_mock_ctx.request_context.meta = {"authenticated_agent_id": "admin-001"}
        result = await read_messages(
            agent_id="admin-001",
            unread_only=True,
            caller_agent_id=None,
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert result["dashboard_updated"] is True
        assert result["dashboard_updates_applied"] == 1
        updated = app_ctx.dashboard_manager.get_task(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.IN_PROGRESS
        assert updated.progress == 40
        assert app_ctx.ipc_manager.get_unread_count("admin-001") == 0

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
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx.agents["worker-001"] = _make_agent(
            "worker-001", AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
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
        assert app_ctx.ipc_manager.get_unread_count("admin-001") == 0

    @pytest.mark.asyncio
    async def test_read_messages_admin_acks_already_completed_message(
        self, ipc_mock_ctx, git_repo
    ):
        """既に完了済みタスクの task_complete メッセージは既読化されることをテスト。"""
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
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx.agents["worker-001"] = _make_agent(
            "worker-001", AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
        )

        task = app_ctx.dashboard_manager.create_task(
            title="already completed",
            description="idempotent completion",
            assigned_agent_id="worker-001",
        )
        app_ctx.dashboard_manager.update_task_status(task.id, TaskStatus.COMPLETED, progress=100)

        app_ctx.ipc_manager.send_message(
            sender_id="worker-001",
            receiver_id="admin-001",
            message_type=MessageType.TASK_COMPLETE,
            content="done again",
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
        assert result["dashboard_updates_applied"] == 0
        assert app_ctx.ipc_manager.get_unread_count("admin-001") == 0

    @pytest.mark.asyncio
    async def test_read_messages_admin_defers_ack_until_dashboard_apply_success(
        self, ipc_mock_ctx, git_repo
    ):
        """Dashboard 反映に失敗した task メッセージは未読維持され、再試行で既読化される。"""
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
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx.agents["worker-001"] = _make_agent(
            "worker-001", AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
        )

        task = app_ctx.dashboard_manager.create_task(
            title="retry target",
            description="auto update retry",
            assigned_agent_id="worker-001",
        )
        sent = app_ctx.ipc_manager.send_message(
            sender_id="worker-001",
            receiver_id="admin-001",
            message_type=MessageType.TASK_PROGRESS,
            content="30% reached",
            metadata={
                "task_id": f"task:{task.id}",
                "progress": 30,
                "message": "30% reached",
                "reporter": "worker-001",
            },
        )

        app_ctx.dashboard_manager.apply_task_messages = MagicMock(
            side_effect=[
                (True, 0, [f"update_error:{task.id}"], [], [sent.id]),
                (True, 1, [], [sent.id], []),
            ]
        )

        first = await read_messages(
            agent_id="admin-001",
            unread_only=True,
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )
        assert first["success"] is True
        assert first["dashboard_updates_applied"] == 0
        assert app_ctx.ipc_manager.get_unread_count("admin-001") == 1

        second = await read_messages(
            agent_id="admin-001",
            unread_only=True,
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )
        assert second["success"] is True
        assert second["dashboard_updates_applied"] == 1
        assert app_ctx.ipc_manager.get_unread_count("admin-001") == 0


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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )

        result = await get_unread_count(
            agent_id="owner-001",
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert "unread_count" in result

    @pytest.mark.asyncio
    async def test_get_unread_count_blocks_admin_polling_after_empty_check(
        self, ipc_mock_ctx, git_repo
    ):
        """Admin が unread=0 で get_unread_count を連続実行するとブロックされる。"""
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
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )

        first = await get_unread_count(
            agent_id="admin-001",
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )
        second = await get_unread_count(
            agent_id="admin-001",
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )

        assert first["success"] is True
        assert first["unread_count"] == 0
        assert second["success"] is False
        assert "polling_blocked" in second["error"]
        assert second["next_action"] == "wait_for_ipc_notification"

    @pytest.mark.asyncio
    async def test_get_unread_count_blocks_owner_polling_while_waiting(
        self, ipc_mock_ctx, git_repo
    ):
        """Owner 待機ロック中は unread=0 の get_unread_count をブロックする。"""
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": datetime.now(),
            "unlocked_at": None,
            "unlock_reason": None,
        }

        result = await get_unread_count(
            agent_id="owner-001",
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert "polling_blocked" in result["error"]
        assert result["next_action"] == "wait_for_user_input_or_unlock_owner_wait"

    @pytest.mark.asyncio
    async def test_get_unread_count_owner_allows_when_unread_exists(
        self, ipc_mock_ctx, git_repo
    ):
        """Owner 待機ロック中でも未読がある場合は件数取得できる。"""
        from mcp.server.fastmcp import FastMCP

        from src.models.message import MessageType
        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        get_unread_count = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_unread_count":
                get_unread_count = tool.fn
                break

        app_ctx = ipc_mock_ctx.request_context.lifespan_context
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": datetime.now(),
            "unlocked_at": None,
            "unlock_reason": None,
        }
        app_ctx.ipc_manager.send_message(
            sender_id="admin-001",
            receiver_id="owner-001",
            message_type=MessageType.SYSTEM,
            content="進捗通知",
        )

        result = await get_unread_count(
            agent_id="owner-001",
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert result["unread_count"] == 1

    @pytest.mark.asyncio
    async def test_get_unread_count_blocks_owner_polling_for_other_inbox_while_waiting(
        self, ipc_mock_ctx, git_repo
    ):
        """Owner 待機ロック中は他エージェント inbox の未読数監視をブロックする。"""
        from mcp.server.fastmcp import FastMCP

        from src.models.message import MessageType
        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        get_unread_count = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_unread_count":
                get_unread_count = tool.fn
                break
        assert get_unread_count is not None

        app_ctx = ipc_mock_ctx.request_context.lifespan_context
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": datetime.now(),
            "unlocked_at": None,
            "unlock_reason": None,
        }
        app_ctx.ipc_manager.send_message(
            sender_id="admin-001",
            receiver_id="admin-001",
            message_type=MessageType.SYSTEM,
            content="admin unread message",
        )

        result = await get_unread_count(
            agent_id="admin-001",
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is False
        assert "polling_blocked" in result["error"]
        assert result["next_action"] == "wait_for_user_input_or_unlock_owner_wait"

    @pytest.mark.asyncio
    async def test_get_unread_count_uses_authenticated_caller_for_admin_poll_guard(
        self, ipc_mock_ctx, git_repo
    ):
        """認証済み主体を使って Admin ポーリングガードが適用されることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        get_unread_count = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_unread_count":
                get_unread_count = tool.fn
                break
        assert get_unread_count is not None

        app_ctx = ipc_mock_ctx.request_context.lifespan_context
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(git_repo),
        )
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )

        ipc_mock_ctx.request_context.meta = {"authenticated_agent_id": "admin-001"}
        first = await get_unread_count(
            agent_id="owner-001",
            caller_agent_id=None,
            ctx=ipc_mock_ctx,
        )
        second = await get_unread_count(
            agent_id="admin-001",
            caller_agent_id="admin-001",
            ctx=ipc_mock_ctx,
        )

        assert first["success"] is True
        assert first["unread_count"] == 0
        assert second["success"] is False
        assert "polling_blocked" in second["error"]

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
        app_ctx.agents["worker-001"] = _make_agent(
            "worker-001", AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(git_repo),
        )
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": datetime.now(),
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
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(git_repo),
        )

        result = await register_agent_to_ipc(
            agent_id="new-agent-001",
            caller_agent_id="owner-001",
            ctx=ipc_mock_ctx,
        )

        assert result["success"] is True
        assert result["agent_id"] == "new-agent-001"


class TestQualityGateNoGitMode:
    """enable_git=false 時の品質ゲートテスト。"""

    @staticmethod
    def _get_send_message_fn():
        """send_message ツール関数を取得する。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.ipc import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "send_message":
                return tool.fn
        raise RuntimeError("send_message ツールが見つかりません")

    @staticmethod
    def _setup_admin_owner(app_ctx, work_dir):
        """Admin と Owner エージェントをセットアップする。"""
        app_ctx.agents["admin-001"] = _make_agent(
            "admin-001", AgentRole.ADMIN,
            status=AgentStatus.BUSY,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            working_dir=str(work_dir),
        )
        app_ctx.agents["owner-001"] = _make_agent(
            "owner-001", AgentRole.OWNER, working_dir=str(work_dir),
        )

    @pytest.mark.asyncio
    async def test_quality_gate_skips_branch_check_when_git_disabled(
        self, ipc_no_git_mock_ctx
    ):
        """enable_git=false + branch 付き完了タスクで品質ゲートが通過することをテスト。"""
        send_message = self._get_send_message_fn()
        app_ctx = ipc_no_git_mock_ctx.request_context.lifespan_context
        self._setup_admin_owner(app_ctx, app_ctx.project_root)

        # IPC に admin と owner を登録
        app_ctx.ipc_manager.register_agent("admin-001")
        app_ctx.ipc_manager.register_agent("owner-001")

        # branch 付きタスクを完了状態にする
        dashboard = app_ctx.dashboard_manager
        impl_task = dashboard.create_task(
            title="実装タスク",
            branch="feature/no-git-task",
        )
        dashboard.update_task_status(impl_task.id, TaskStatus.COMPLETED)
        quality_task = dashboard.create_task(title="test verify")
        dashboard.update_task_status(quality_task.id, TaskStatus.COMPLETED)

        with patch(
            "src.tools.helpers._send_macos_notification",
            new=AsyncMock(return_value=True),
        ):
            result = await send_message(
                sender_id="admin-001",
                receiver_id="owner-001",
                message_type="task_complete",
                content="実装完了しました",
                caller_agent_id="admin-001",
                ctx=ipc_no_git_mock_ctx,
            )

        # enable_git=false ならブランチチェックをスキップして通過する
        assert result["success"] is True
        assert "branch_integration" not in result.get("gate", {})

    @pytest.mark.asyncio
    async def test_quality_gate_still_checks_pending_tasks_in_no_git_mode(
        self, ipc_no_git_mock_ctx
    ):
        """enable_git=false でも未完了タスクチェックは動作することをテスト。"""
        send_message = self._get_send_message_fn()
        app_ctx = ipc_no_git_mock_ctx.request_context.lifespan_context
        self._setup_admin_owner(app_ctx, app_ctx.project_root)

        app_ctx.ipc_manager.register_agent("admin-001")
        app_ctx.ipc_manager.register_agent("owner-001")

        # 未完了タスクを作成（pending 状態のまま）
        dashboard = app_ctx.dashboard_manager
        dashboard.create_task(title="未完了タスク")
        quality_task = dashboard.create_task(title="test verify")
        dashboard.update_task_status(quality_task.id, TaskStatus.COMPLETED)

        result = await send_message(
            sender_id="admin-001",
            receiver_id="owner-001",
            message_type="task_complete",
            content="完了報告",
            caller_agent_id="admin-001",
            ctx=ipc_no_git_mock_ctx,
        )

        # 未完了タスクがあるためブロックされる
        assert result["success"] is False
        assert "品質ゲート未達" in result["error"]
        assert any("未完了タスク" in r for r in result["gate"]["reasons"])

    @pytest.mark.asyncio
    async def test_admin_to_owner_status_update_uses_macos_fallback(
        self, ipc_no_git_mock_ctx
    ):
        """admin→owner の status_update で macOS フォールバックが動作することをテスト。"""
        send_message = self._get_send_message_fn()
        app_ctx = ipc_no_git_mock_ctx.request_context.lifespan_context
        self._setup_admin_owner(app_ctx, app_ctx.project_root)

        app_ctx.ipc_manager.register_agent("admin-001")
        app_ctx.ipc_manager.register_agent("owner-001")

        with patch(
            "src.tools.helpers._send_macos_notification",
            new=AsyncMock(return_value=True),
        ) as mock_macos:
            result = await send_message(
                sender_id="admin-001",
                receiver_id="owner-001",
                message_type="status_update",
                content="進捗報告です",
                caller_agent_id="admin-001",
                ctx=ipc_no_git_mock_ctx,
            )

        assert result["success"] is True
        assert result["delivery_state"] == "delivered"
        assert result["notification_sent"] is True
        assert result["notification_method"] == "macos"
        mock_macos.assert_awaited_once()
