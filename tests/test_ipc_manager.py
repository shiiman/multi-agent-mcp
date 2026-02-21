"""IPCManagerのテスト。"""

import json
import os

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

    def test_send_message_sets_0600_permissions(self, ipc_manager):
        """メッセージと未読インデックスが 0600 権限で保存されることをテスト。"""
        ipc_manager.register_agent("sender")
        ipc_manager.register_agent("receiver")

        ipc_manager.send_message(
            sender_id="sender",
            receiver_id="receiver",
            message_type=MessageType.REQUEST,
            content="permission test",
        )

        receiver_dir = ipc_manager._get_agent_dir("receiver")
        message_files = list(receiver_dir.glob("*.md"))
        index_path = receiver_dir / ".unread_index.json"

        assert len(message_files) == 1
        assert index_path.exists()
        assert (message_files[0].stat().st_mode & 0o777) == 0o600
        assert (index_path.stat().st_mode & 0o777) == 0o600

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

    def test_mark_as_read_keeps_0600_permissions(self, ipc_manager):
        """既読更新後もメッセージとインデックスが 0600 のままであることをテスト。"""
        ipc_manager.register_agent("sender")
        ipc_manager.register_agent("receiver")
        ipc_manager.send_message(
            sender_id="sender",
            receiver_id="receiver",
            message_type=MessageType.REQUEST,
            content="Message 1",
        )

        ipc_manager.read_messages("receiver", unread_only=True, mark_as_read=True)

        receiver_dir = ipc_manager._get_agent_dir("receiver")
        message_files = list(receiver_dir.glob("*.md"))
        index_path = receiver_dir / ".unread_index.json"

        assert len(message_files) == 1
        assert index_path.exists()
        assert (message_files[0].stat().st_mode & 0o777) == 0o600
        assert (index_path.stat().st_mode & 0o777) == 0o600
        lock_path = receiver_dir / ".unread_index.lock"
        assert lock_path.exists()
        assert (lock_path.stat().st_mode & 0o777) == 0o600

    def test_get_unread_count_uses_index_without_scanning(self, ipc_manager, monkeypatch):
        """未読数取得がメッセージ全件走査に依存しないことをテスト。"""
        ipc_manager.register_agent("sender")
        ipc_manager.register_agent("receiver")

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

        def _fail_scan(_agent_dir):
            raise AssertionError("message file scan should not be called")

        monkeypatch.setattr(ipc_manager, "_list_message_files", _fail_scan)

        assert ipc_manager.get_unread_count("receiver") == 2

    def test_read_messages_unread_only_uses_index_without_scanning(self, ipc_manager, monkeypatch):
        """未読読み出しがメッセージ全件走査に依存しないことをテスト。"""
        ipc_manager.register_agent("sender")
        ipc_manager.register_agent("receiver")

        ipc_manager.send_message(
            sender_id="sender",
            receiver_id="receiver",
            message_type=MessageType.REQUEST,
            content="Message 1",
        )
        ipc_manager.send_message(
            sender_id="sender",
            receiver_id="receiver",
            message_type=MessageType.TASK_ASSIGN,
            content="Message 2",
        )

        def _fail_scan(_agent_dir):
            raise AssertionError("message file scan should not be called")

        monkeypatch.setattr(ipc_manager, "_list_message_files", _fail_scan)

        unread_requests = ipc_manager.read_messages(
            "receiver",
            unread_only=True,
            message_type=MessageType.REQUEST,
            mark_as_read=False,
        )
        assert len(unread_requests) == 1
        assert unread_requests[0].content == "Message 1"

    def test_read_messages_unread_only_ignores_path_traversal_index_entry(self, ipc_manager):
        """改ざんインデックスの path traversal エントリを無視することをテスト。"""
        ipc_manager.register_agent("sender")
        ipc_manager.register_agent("receiver")

        sent = ipc_manager.send_message(
            sender_id="sender",
            receiver_id="receiver",
            message_type=MessageType.REQUEST,
            content="safe message",
        )

        receiver_dir = ipc_manager._get_agent_dir("receiver")
        outside_path = ipc_manager.ipc_dir / "outside.md"
        outside_path.write_text(
            (receiver_dir / next(receiver_dir.glob("*.md")).name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        index_path = receiver_dir / ".unread_index.json"
        index_payload = {
            "version": 1,
            "entries": [
                {
                    "id": sent.id,
                    "file_name": "../outside.md",
                    "created_at": sent.created_at.isoformat(),
                    "message_type": MessageType.REQUEST.value,
                    "read_at": None,
                }
            ],
            "unread_count": 1,
            "cursor": 0,
        }
        index_path.write_text(json.dumps(index_payload, ensure_ascii=False), encoding="utf-8")

        unread = ipc_manager.read_messages(
            "receiver",
            unread_only=True,
            mark_as_read=False,
        )
        assert unread == []
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

    def test_mark_as_read_corrupted_index_recovers(self, ipc_manager):
        """未読インデックスが破損している場合でも既読処理が回復することをテスト。"""
        ipc_manager.register_agent("sender")
        ipc_manager.register_agent("receiver")

        ipc_manager.send_message(
            sender_id="sender",
            receiver_id="receiver",
            message_type=MessageType.REQUEST,
            content="Test message",
        )

        # インデックスを破損させる
        receiver_dir = ipc_manager._get_agent_dir("receiver")
        index_path = receiver_dir / ".unread_index.json"
        index_path.write_text("{{invalid json", encoding="utf-8")

        # 破損インデックスでも read_messages は例外を投げない
        messages = ipc_manager.read_messages("receiver", mark_as_read=True)
        assert len(messages) >= 1

    def test_mark_as_read_missing_index_file(self, ipc_manager):
        """未読インデックスファイルが存在しない場合の既読処理をテスト。"""
        ipc_manager.register_agent("sender")
        ipc_manager.register_agent("receiver")

        ipc_manager.send_message(
            sender_id="sender",
            receiver_id="receiver",
            message_type=MessageType.REQUEST,
            content="Test message",
        )

        # インデックスファイルを削除
        receiver_dir = ipc_manager._get_agent_dir("receiver")
        index_path = receiver_dir / ".unread_index.json"
        if index_path.exists():
            os.unlink(index_path)

        # インデックスが無くてもメッセージは読める
        messages = ipc_manager.read_messages("receiver")
        assert len(messages) == 1

    def test_read_messages_nonexistent_agent(self, ipc_manager):
        """未登録エージェントの read_messages が空リストを返すことをテスト。"""
        messages = ipc_manager.read_messages("nonexistent-agent")
        assert messages == []

    def test_get_unread_count_nonexistent_agent(self, ipc_manager):
        """未登録エージェントの get_unread_count が 0 を返すことをテスト。"""
        count = ipc_manager.get_unread_count("nonexistent-agent")
        assert count == 0
