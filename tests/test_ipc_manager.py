"""IPCManagerのテスト。"""


from src.models.message import MessagePriority, MessageType


class TestIPCManager:
    """IPCManagerのテスト。"""

    def test_register_agent(self, ipc_manager):
        """エージェント登録をテスト。"""
        ipc_manager.register_agent("agent-001")

        assert "agent-001" in ipc_manager.get_all_agent_ids()

    def test_unregister_agent(self, ipc_manager):
        """エージェント登録解除をテスト。"""
        ipc_manager.register_agent("agent-002")
        ipc_manager.unregister_agent("agent-002")

        assert "agent-002" not in ipc_manager.get_all_agent_ids()

    def test_send_message(self, ipc_manager):
        """メッセージ送信をテスト。"""
        ipc_manager.register_agent("sender")
        ipc_manager.register_agent("receiver")

        message = ipc_manager.send_message(
            sender_id="sender",
            receiver_id="receiver",
            message_type=MessageType.REQUEST,
            content="Test message",
            subject="Test Subject",
        )

        assert message.id is not None
        assert message.sender_id == "sender"
        assert message.receiver_id == "receiver"

    def test_read_messages(self, ipc_manager):
        """メッセージ読み取りをテスト。"""
        ipc_manager.register_agent("sender")
        ipc_manager.register_agent("receiver")

        ipc_manager.send_message(
            sender_id="sender",
            receiver_id="receiver",
            message_type=MessageType.REQUEST,
            content="Test message",
        )

        messages = ipc_manager.read_messages("receiver")

        assert len(messages) == 1
        assert messages[0].content == "Test message"

    def test_unread_count(self, ipc_manager):
        """未読数をテスト。"""
        ipc_manager.register_agent("sender")
        ipc_manager.register_agent("receiver")

        # 初期状態
        assert ipc_manager.get_unread_count("receiver") == 0

        # メッセージ送信
        ipc_manager.send_message(
            sender_id="sender",
            receiver_id="receiver",
            message_type=MessageType.REQUEST,
            content="Message 1",
        )
        ipc_manager.send_message(
            sender_id="sender",
            receiver_id="receiver",
            message_type=MessageType.REQUEST,
            content="Message 2",
        )

        assert ipc_manager.get_unread_count("receiver") == 2

        # 既読にする
        ipc_manager.read_messages("receiver", mark_as_read=True)

        assert ipc_manager.get_unread_count("receiver") == 0

    def test_broadcast_message(self, ipc_manager):
        """ブロードキャストメッセージをテスト。"""
        ipc_manager.register_agent("sender")
        ipc_manager.register_agent("receiver1")
        ipc_manager.register_agent("receiver2")

        ipc_manager.send_message(
            sender_id="sender",
            receiver_id=None,  # ブロードキャスト
            message_type=MessageType.BROADCAST,
            content="Broadcast message",
        )

        # 両方の受信者にメッセージが届いているか確認
        messages1 = ipc_manager.read_messages("receiver1")
        messages2 = ipc_manager.read_messages("receiver2")

        assert len(messages1) == 1
        assert len(messages2) == 1
        assert messages1[0].content == "Broadcast message"

    def test_filter_by_message_type(self, ipc_manager):
        """メッセージタイプでのフィルタリングをテスト。"""
        ipc_manager.register_agent("sender")
        ipc_manager.register_agent("receiver")

        ipc_manager.send_message(
            sender_id="sender",
            receiver_id="receiver",
            message_type=MessageType.REQUEST,
            content="Request",
        )
        ipc_manager.send_message(
            sender_id="sender",
            receiver_id="receiver",
            message_type=MessageType.TASK_ASSIGN,
            content="Task",
        )

        # REQUEST のみ取得
        requests = ipc_manager.read_messages(
            "receiver",
            message_type=MessageType.REQUEST,
            mark_as_read=False,
        )

        assert len(requests) == 1
        assert requests[0].message_type == MessageType.REQUEST

    def test_send_task_assignment(self, ipc_manager):
        """タスク割り当てメッセージをテスト。"""
        ipc_manager.register_agent("admin")
        ipc_manager.register_agent("worker")

        message = ipc_manager.send_task_assignment(
            sender_id="admin",
            worker_id="worker",
            task_id="task-001",
            task_description="Implement feature X",
            branch="feature/x",
        )

        assert message.message_type == MessageType.TASK_ASSIGN
        assert message.priority == MessagePriority.HIGH
        assert message.metadata["task_id"] == "task-001"
        assert message.metadata["branch"] == "feature/x"
