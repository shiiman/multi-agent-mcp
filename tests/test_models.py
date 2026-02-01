"""モデルのテスト。"""

from datetime import datetime

from src.config.settings import AICli
from src.models.agent import Agent, AgentRole, AgentStatus
from src.models.dashboard import Dashboard, TaskInfo, TaskStatus
from src.models.message import Message, MessageQueue, MessageType
from src.models.workspace import WorktreeInfo


class TestAgent:
    """Agent モデルのテスト。"""

    def test_create_agent(self):
        """エージェントの作成をテスト。"""
        now = datetime.now()
        agent = Agent(
            id="test-001",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test-session",
            created_at=now,
            last_activity=now,
        )

        assert agent.id == "test-001"
        assert agent.role == AgentRole.WORKER
        assert agent.status == AgentStatus.IDLE
        assert agent.worktree_path is None

    def test_agent_role_enum(self):
        """AgentRole enumの値をテスト。"""
        assert AgentRole.OWNER.value == "owner"
        assert AgentRole.ADMIN.value == "admin"
        assert AgentRole.WORKER.value == "worker"

    def test_agent_status_enum(self):
        """AgentStatus enumの値をテスト。"""
        assert AgentStatus.IDLE.value == "idle"
        assert AgentStatus.BUSY.value == "busy"
        assert AgentStatus.ERROR.value == "error"
        assert AgentStatus.TERMINATED.value == "terminated"

    def test_agent_with_ai_cli(self):
        """Agent に ai_cli フィールドが設定できることをテスト。"""
        now = datetime.now()
        agent = Agent(
            id="test-002",
            role=AgentRole.WORKER,
            ai_cli=AICli.CODEX,
            created_at=now,
            last_activity=now,
        )
        assert agent.ai_cli == AICli.CODEX

    def test_agent_ai_cli_default_none(self):
        """Agent の ai_cli がデフォルトで None であることをテスト。"""
        now = datetime.now()
        agent = Agent(
            id="test-003",
            role=AgentRole.WORKER,
            created_at=now,
            last_activity=now,
        )
        assert agent.ai_cli is None


class TestMessage:
    """Message モデルのテスト。"""

    def test_create_message(self):
        """メッセージの作成をテスト。"""
        msg = Message(
            id="msg-001",
            sender_id="agent-001",
            receiver_id="agent-002",
            message_type=MessageType.TASK_ASSIGN,
            content="Test message content",
        )

        assert msg.id == "msg-001"
        assert msg.sender_id == "agent-001"
        assert msg.receiver_id == "agent-002"
        assert msg.is_broadcast is False
        assert msg.is_read is False

    def test_broadcast_message(self):
        """ブロードキャストメッセージをテスト。"""
        msg = Message(
            id="msg-002",
            sender_id="agent-001",
            receiver_id=None,
            message_type=MessageType.BROADCAST,
            content="Broadcast message",
        )

        assert msg.is_broadcast is True

    def test_message_queue(self):
        """MessageQueueをテスト。"""
        queue = MessageQueue(agent_id="agent-001")
        assert queue.unread_count == 0

        # メッセージを追加
        msg = Message(
            id="msg-001",
            sender_id="agent-002",
            receiver_id="agent-001",
            message_type=MessageType.REQUEST,
            content="Test",
        )
        queue.messages.append(msg)

        assert queue.unread_count == 1
        assert len(queue.get_unread()) == 1


class TestTaskInfo:
    """TaskInfo モデルのテスト。"""

    def test_create_task(self):
        """タスクの作成をテスト。"""
        task = TaskInfo(
            id="task-001",
            title="Test Task",
            description="Test description",
        )

        assert task.id == "task-001"
        assert task.status == TaskStatus.PENDING
        assert task.progress == 0
        assert task.assigned_agent_id is None

    def test_task_status_enum(self):
        """TaskStatus enumの値をテスト。"""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.IN_PROGRESS.value == "in_progress"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"


class TestDashboard:
    """Dashboard モデルのテスト。"""

    def test_create_dashboard(self):
        """ダッシュボードの作成をテスト。"""
        dashboard = Dashboard(
            workspace_id="ws-001",
            workspace_path="/tmp/workspace",
        )

        assert dashboard.workspace_id == "ws-001"
        assert dashboard.total_agents == 0
        assert dashboard.total_tasks == 0

    def test_dashboard_calculate_stats(self):
        """統計計算をテスト。"""
        dashboard = Dashboard(
            workspace_id="ws-001",
            workspace_path="/tmp/workspace",
        )

        # タスクを追加
        dashboard.tasks.append(
            TaskInfo(id="t1", title="Task 1", status=TaskStatus.PENDING)
        )
        dashboard.tasks.append(
            TaskInfo(id="t2", title="Task 2", status=TaskStatus.COMPLETED)
        )
        dashboard.tasks.append(
            TaskInfo(id="t3", title="Task 3", status=TaskStatus.FAILED)
        )

        dashboard.calculate_stats()

        assert dashboard.total_tasks == 3
        assert dashboard.completed_tasks == 1
        assert dashboard.failed_tasks == 1


class TestWorktreeInfo:
    """WorktreeInfo モデルのテスト。"""

    def test_create_worktree_info(self):
        """WorktreeInfoの作成をテスト。"""
        wt = WorktreeInfo(
            path="/path/to/worktree",
            branch="feature/test",
            commit="abc123",
        )

        assert wt.path == "/path/to/worktree"
        assert wt.branch == "feature/test"
        assert wt.is_bare is False
        assert wt.is_detached is False
