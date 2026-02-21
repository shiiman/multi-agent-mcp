"""統合テスト。

エージェントライフサイクルとダッシュボード更新の基本フローを検証する。
tmux やシステムに依存しないよう mock を使用。
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.settings import Settings, TerminalApp
from src.context import AppContext
from src.managers.agent_manager import AgentManager
from src.managers.ai_cli_manager import AiCliManager
from src.managers.dashboard_manager import DashboardManager
from src.managers.ipc_manager import IPCManager
from src.managers.memory_manager import MemoryManager
from src.managers.persona_manager import PersonaManager
from src.managers.scheduler_manager import SchedulerManager
from src.models.agent import Agent, AgentRole, AgentStatus
from src.models.dashboard import TaskStatus


@pytest.fixture
def integration_ctx(temp_dir, monkeypatch):
    """統合テスト用の AppContext を作成する。"""
    monkeypatch.delenv("MCP_PROJECT_ROOT", raising=False)

    settings = Settings(
        _env_file=None,
        model_profile_standard_max_workers=3,
        tmux_prefix="test-integration",
        default_terminal=TerminalApp.AUTO,
    )

    # モック TmuxManager
    mock_tmux = MagicMock()
    mock_tmux.settings = settings
    mock_tmux.create_session = AsyncMock(return_value=True)
    mock_tmux.kill_session = AsyncMock(return_value=True)
    mock_tmux.cleanup_sessions = AsyncMock(return_value=0)
    mock_tmux.cleanup_all_sessions = AsyncMock(return_value=0)
    mock_tmux.create_main_session = AsyncMock(return_value=True)
    mock_tmux.session_exists = AsyncMock(return_value=True)
    mock_tmux.send_keys = AsyncMock(return_value=True)
    mock_tmux.send_keys_to_pane = AsyncMock(return_value=True)
    mock_tmux.send_with_rate_limit_to_pane = AsyncMock(return_value=True)
    mock_tmux.capture_pane = AsyncMock(return_value="mock output")
    mock_tmux.capture_pane_by_index = AsyncMock(return_value="mock output")
    mock_tmux.set_pane_title = AsyncMock(return_value=True)
    mock_tmux.add_extra_worker_window = AsyncMock(return_value=True)
    mock_tmux.open_session_in_terminal = AsyncMock(return_value=True)
    mock_tmux._run = AsyncMock(return_value=(0, "", ""))
    mock_tmux._get_window_name = MagicMock(return_value=settings.window_name_main)

    ai_cli = AiCliManager(settings)

    ipc_dir = temp_dir / "ipc"
    ipc = IPCManager(str(ipc_dir))
    ipc.initialize()

    dashboard_dir = temp_dir / ".dashboard"
    dashboard = DashboardManager(
        workspace_id="test-integration",
        workspace_path=str(temp_dir),
        dashboard_dir=str(dashboard_dir),
    )
    dashboard.initialize()

    memory_dir = temp_dir / ".memory"
    memory = MemoryManager(str(memory_dir))

    persona = PersonaManager()

    agents: dict[str, Agent] = {}
    scheduler = SchedulerManager(dashboard, agents)

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
        workspace_id="test-integration",
        project_root=str(temp_dir),
        session_id="test-session",
    )
    yield ctx
    ipc.cleanup()
    dashboard.cleanup()


class TestAgentLifecycleIntegration:
    """エージェント作成 → ステータス変更 → 終了のフロー統合テスト。"""

    def test_create_agent_and_change_status(self, integration_ctx):
        """エージェントを作成してステータスを変更できること。"""
        now = datetime.now()
        agent = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            created_at=now,
            last_activity=now,
        )
        integration_ctx.agents["worker-001"] = agent

        # エージェントが登録されていること
        assert "worker-001" in integration_ctx.agents
        assert integration_ctx.agents["worker-001"].status == AgentStatus.IDLE.value

        # ステータスを BUSY に変更
        agent.status = AgentStatus.BUSY
        agent.current_task = "task-001"
        agent.last_activity = datetime.now()
        assert integration_ctx.agents["worker-001"].status == AgentStatus.BUSY.value
        assert integration_ctx.agents["worker-001"].current_task == "task-001"

        # ステータスを TERMINATED に変更
        agent.status = AgentStatus.TERMINATED
        agent.current_task = None
        assert integration_ctx.agents["worker-001"].status == AgentStatus.TERMINATED.value
        assert integration_ctx.agents["worker-001"].current_task is None

    def test_multi_agent_lifecycle(self, integration_ctx):
        """複数エージェントのライフサイクルを管理できること。"""
        now = datetime.now()

        # Owner 作成
        owner = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            created_at=now,
            last_activity=now,
        )
        integration_ctx.agents["owner-001"] = owner

        # Admin 作成
        admin = Agent(
            id="admin-001",
            role=AgentRole.ADMIN,
            status=AgentStatus.IDLE,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            created_at=now,
            last_activity=now,
        )
        integration_ctx.agents["admin-001"] = admin

        # Worker 作成
        workers = []
        for i in range(1, 4):
            w = Agent(
                id=f"worker-{i:03d}",
                role=AgentRole.WORKER,
                status=AgentStatus.IDLE,
                tmux_session=f"test:0.{i}",
                session_name="test",
                window_index=0,
                pane_index=i,
                created_at=now,
                last_activity=now,
            )
            integration_ctx.agents[w.id] = w
            workers.append(w)

        # 全エージェントが登録されていること
        assert len(integration_ctx.agents) == 5

        # Worker にタスクを割り当て
        for i, w in enumerate(workers):
            w.status = AgentStatus.BUSY
            w.current_task = f"task-{i + 1:03d}"

        busy_agents = [
            a for a in integration_ctx.agents.values()
            if a.status == AgentStatus.BUSY.value
        ]
        assert len(busy_agents) == 3

        # 全 Worker を終了
        for w in workers:
            w.status = AgentStatus.TERMINATED
            w.current_task = None

        terminated = [
            a for a in integration_ctx.agents.values()
            if a.status == AgentStatus.TERMINATED.value
        ]
        assert len(terminated) == 3

    def test_agent_role_filtering(self, integration_ctx):
        """ロールでエージェントをフィルタリングできること。"""
        now = datetime.now()
        integration_ctx.agents["owner-001"] = Agent(
            id="owner-001", role=AgentRole.OWNER, status=AgentStatus.IDLE,
            tmux_session=None, created_at=now, last_activity=now,
        )
        integration_ctx.agents["admin-001"] = Agent(
            id="admin-001", role=AgentRole.ADMIN, status=AgentStatus.IDLE,
            tmux_session="test:0.0", session_name="test",
            window_index=0, pane_index=0, created_at=now, last_activity=now,
        )
        integration_ctx.agents["worker-001"] = Agent(
            id="worker-001", role=AgentRole.WORKER, status=AgentStatus.IDLE,
            tmux_session="test:0.1", session_name="test",
            window_index=0, pane_index=1, created_at=now, last_activity=now,
        )
        integration_ctx.agents["worker-002"] = Agent(
            id="worker-002", role=AgentRole.WORKER, status=AgentStatus.IDLE,
            tmux_session="test:0.2", session_name="test",
            window_index=0, pane_index=2, created_at=now, last_activity=now,
        )

        owners = [
            a for a in integration_ctx.agents.values()
            if a.role == AgentRole.OWNER.value
        ]
        workers = [
            a for a in integration_ctx.agents.values()
            if a.role == AgentRole.WORKER.value
        ]
        assert len(owners) == 1
        assert len(workers) == 2


class TestDashboardIntegration:
    """ダッシュボード更新フローの統合テスト。"""

    def test_create_and_update_task(self, integration_ctx):
        """タスク作成 → ステータス更新のフロー。"""
        dashboard = integration_ctx.dashboard_manager

        # タスク作成
        task = dashboard.create_task(
            title="テスト機能の実装",
            description="ユニットテストを追加する",
        )
        assert task is not None
        assert task.title == "テスト機能の実装"
        assert task.status == TaskStatus.PENDING

        # タスクをエージェントに割り当て
        assigned, _ = dashboard.assign_task(task.id, "worker-001")
        assert assigned is True

        # ステータスを IN_PROGRESS に更新
        dashboard.update_task_status(task.id, TaskStatus.IN_PROGRESS, progress=50)
        updated = dashboard.get_task(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.IN_PROGRESS

        # ステータスを COMPLETED に更新
        dashboard.update_task_status(task.id, TaskStatus.COMPLETED, progress=100)
        completed = dashboard.get_task(task.id)
        assert completed is not None
        assert completed.status == TaskStatus.COMPLETED

    def test_multiple_tasks_workflow(self, integration_ctx):
        """複数タスクのワークフロー。"""
        dashboard = integration_ctx.dashboard_manager

        # 3つのタスクを作成
        tasks = []
        for i in range(3):
            t = dashboard.create_task(
                title=f"タスク {i + 1}",
                description=f"タスク {i + 1} の説明",
                assigned_agent_id=f"worker-{i + 1:03d}",
            )
            tasks.append(t)

        # 全タスクが作成されていること
        all_tasks = dashboard.list_tasks()
        assert len(all_tasks) >= 3

        # 各タスクのステータスを更新
        dashboard.update_task_status(tasks[0].id, TaskStatus.IN_PROGRESS)
        dashboard.update_task_status(tasks[1].id, TaskStatus.IN_PROGRESS)
        dashboard.update_task_status(tasks[2].id, TaskStatus.PENDING)

        # サマリーを確認
        summary = dashboard.get_summary()
        assert summary["in_progress_tasks"] >= 2
        assert summary["pending_tasks"] >= 1

        # タスク 1, 2 を完了
        dashboard.update_task_status(tasks[0].id, TaskStatus.COMPLETED)
        dashboard.update_task_status(tasks[1].id, TaskStatus.COMPLETED)

        summary = dashboard.get_summary()
        assert summary["completed_tasks"] >= 2

    def test_task_failure_workflow(self, integration_ctx):
        """タスク失敗→再割り当てのフロー。"""
        dashboard = integration_ctx.dashboard_manager

        # タスク作成
        task = dashboard.create_task(
            title="失敗するタスク",
            description="エラーが発生するタスク",
            assigned_agent_id="worker-001",
        )
        dashboard.update_task_status(task.id, TaskStatus.IN_PROGRESS)

        # タスク失敗
        dashboard.update_task_status(
            task.id,
            TaskStatus.FAILED,
            error_message="テスト実行中にエラーが発生",
        )
        failed = dashboard.get_task(task.id)
        assert failed is not None
        assert failed.status == TaskStatus.FAILED
        assert failed.error_message is not None

        summary = dashboard.get_summary()
        assert summary["failed_tasks"] >= 1

    def test_dashboard_with_agent_context(self, integration_ctx):
        """エージェントとダッシュボードの連携。"""
        now = datetime.now()
        dashboard = integration_ctx.dashboard_manager

        # Worker を追加
        worker = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            created_at=now,
            last_activity=now,
        )
        integration_ctx.agents["worker-001"] = worker

        # タスク作成・割り当て
        task = dashboard.create_task(
            title="連携テスト",
            description="エージェントとの連携を検証",
            assigned_agent_id="worker-001",
        )
        dashboard.assign_task(task.id, "worker-001")

        # エージェントのステータスとタスクを同期
        worker.status = AgentStatus.BUSY
        worker.current_task = task.id
        dashboard.update_task_status(task.id, TaskStatus.IN_PROGRESS, progress=30)

        # エージェントとタスクの状態が一致すること
        assert worker.current_task == task.id
        assert worker.status == AgentStatus.BUSY.value
        updated_task = dashboard.get_task(task.id)
        assert updated_task.status == TaskStatus.IN_PROGRESS

        # タスク完了→エージェントをアイドルに
        dashboard.update_task_status(task.id, TaskStatus.COMPLETED, progress=100)
        worker.status = AgentStatus.IDLE
        worker.current_task = None

        assert worker.status == AgentStatus.IDLE.value
        assert worker.current_task is None
        final_task = dashboard.get_task(task.id)
        assert final_task.status == TaskStatus.COMPLETED


class TestIPCIntegration:
    """IPC メッセージングの統合テスト。"""

    def test_send_and_receive_message(self, integration_ctx):
        """メッセージの送受信フロー。"""
        from src.models.message import MessagePriority, MessageType

        ipc = integration_ctx.ipc_manager

        # エージェント登録
        ipc.register_agent("admin-001")
        ipc.register_agent("worker-001")

        # メッセージ送信
        msg = ipc.send_message(
            sender_id="admin-001",
            receiver_id="worker-001",
            message_type=MessageType.TASK_ASSIGN,
            subject="タスク割り当て",
            content="テスト機能を実装してください",
            priority=MessagePriority.NORMAL,
        )
        assert msg is not None

        # メッセージ受信
        messages = ipc.read_messages("worker-001", mark_as_read=False)
        assert len(messages) >= 1
        received = messages[-1]
        assert received.subject == "タスク割り当て"
        assert received.sender_id == "admin-001"

    def test_ipc_unread_count(self, integration_ctx):
        """未読メッセージ数の追跡。"""
        from src.models.message import MessagePriority, MessageType

        ipc = integration_ctx.ipc_manager

        ipc.register_agent("admin-001")
        ipc.register_agent("worker-001")

        # 複数メッセージ送信
        for i in range(3):
            ipc.send_message(
                sender_id="admin-001",
                receiver_id="worker-001",
                message_type=MessageType.SYSTEM,
                subject=f"情報 {i + 1}",
                content=f"内容 {i + 1}",
                priority=MessagePriority.NORMAL,
            )

        unread = ipc.get_unread_count("worker-001")
        assert unread >= 3
