"""プロセス間通信（IPC）管理モジュール。

ファイルベースのメッセージキューを使用してエージェント間通信を実現する。
"""

import fcntl
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from src.models.message import (
    Message,
    MessagePriority,
    MessageQueue,
    MessageType,
)

logger = logging.getLogger(__name__)


class IPCManager:
    """ファイルベースのプロセス間通信を管理するクラス。

    各エージェントのメッセージキューをJSONファイルとして管理する。
    """

    def __init__(self, ipc_dir: str) -> None:
        """IPCManagerを初期化する。

        Args:
            ipc_dir: IPCファイルを保存するディレクトリ
        """
        self.ipc_dir = Path(ipc_dir)
        self.queues: dict[str, MessageQueue] = {}

    def initialize(self) -> None:
        """IPC環境を初期化する。"""
        self.ipc_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"IPC環境を初期化しました: {self.ipc_dir}")

    def cleanup(self) -> None:
        """IPC環境をクリーンアップする。"""
        if self.ipc_dir.exists():
            for file in self.ipc_dir.glob("*.json"):
                try:
                    file.unlink()
                except OSError as e:
                    logger.warning(f"ファイル削除エラー: {file}: {e}")
        logger.info("IPC環境をクリーンアップしました")

    def _get_queue_path(self, agent_id: str) -> Path:
        """エージェントのキューファイルパスを取得する。"""
        return self.ipc_dir / f"queue_{agent_id}.json"

    def _load_queue(self, agent_id: str) -> MessageQueue:
        """エージェントのメッセージキューをロードする。

        🔴 マルチプロセス対応: 常にファイルから読み込む
        （各 MCP サーバープロセスは独立しているため、メモリキャッシュは同期されない）
        """
        queue_path = self._get_queue_path(agent_id)
        if queue_path.exists():
            try:
                with open(queue_path, encoding="utf-8") as f:
                    data = json.load(f)
                    queue = MessageQueue(**data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"キューファイルの読み込みエラー: {e}")
                queue = MessageQueue(agent_id=agent_id)
        else:
            queue = MessageQueue(agent_id=agent_id)

        self.queues[agent_id] = queue
        return queue

    def _save_queue(self, queue: MessageQueue) -> None:
        """メッセージキューをファイルに保存する。"""
        queue_path = self._get_queue_path(queue.agent_id)
        try:
            with open(queue_path, "w", encoding="utf-8") as f:
                json.dump(queue.model_dump(mode="json"), f, ensure_ascii=False)
        except OSError as e:
            logger.error(f"キューファイルの保存エラー: {e}")

    def register_agent(self, agent_id: str) -> None:
        """エージェントのメッセージキューを登録する。

        Args:
            agent_id: エージェントID
        """
        if agent_id not in self.queues:
            queue = MessageQueue(agent_id=agent_id)
            self.queues[agent_id] = queue
            self._save_queue(queue)
            logger.info(f"エージェント {agent_id} のキューを登録しました")

    def unregister_agent(self, agent_id: str) -> None:
        """エージェントのメッセージキューを削除する。

        Args:
            agent_id: エージェントID
        """
        if agent_id in self.queues:
            del self.queues[agent_id]

        queue_path = self._get_queue_path(agent_id)
        if queue_path.exists():
            try:
                queue_path.unlink()
            except OSError as e:
                logger.warning(f"キューファイル削除エラー: {e}")

        logger.info(f"エージェント {agent_id} のキューを削除しました")

    def _append_message_atomic(self, agent_id: str, message: Message) -> None:
        """メッセージをアトミックにキューに追加する。

        🔴 マルチプロセス対応: ファイルロックを使用して race condition を防止
        """
        queue_path = self._get_queue_path(agent_id)
        lock_path = queue_path.with_suffix(".lock")

        # ロックファイルを作成/開く
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as lock_file:
            try:
                # 排他ロックを取得
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

                # ファイルから最新のキューを読み込む
                if queue_path.exists():
                    try:
                        with open(queue_path, encoding="utf-8") as f:
                            data = json.load(f)
                            queue = MessageQueue(**data)
                    except (json.JSONDecodeError, OSError) as e:
                        logger.warning(f"キューファイルの読み込みエラー: {e}")
                        queue = MessageQueue(agent_id=agent_id)
                else:
                    queue = MessageQueue(agent_id=agent_id)

                # メッセージを追加
                queue.messages.append(message)

                # ファイルに保存
                with open(queue_path, "w", encoding="utf-8") as f:
                    json.dump(queue.model_dump(mode="json"), f, ensure_ascii=False)

            finally:
                # ロックを解放
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def send_message(
        self,
        sender_id: str,
        receiver_id: str | None,
        message_type: MessageType,
        content: str,
        subject: str = "",
        priority: MessagePriority = MessagePriority.NORMAL,
        metadata: dict | None = None,
    ) -> Message:
        """メッセージを送信する。

        🔴 マルチプロセス対応: ファイルロックを使用してアトミックに保存

        Args:
            sender_id: 送信元エージェントID
            receiver_id: 宛先エージェントID（Noneでブロードキャスト）
            message_type: メッセージ種類
            content: メッセージ内容
            subject: 件名
            priority: 優先度
            metadata: 追加メタデータ

        Returns:
            送信されたMessage
        """
        message = Message(
            id=str(uuid.uuid4()),
            sender_id=sender_id,
            receiver_id=receiver_id,
            message_type=message_type,
            content=content,
            subject=subject,
            priority=priority,
            metadata=metadata or {},
            created_at=datetime.now(),
        )

        if receiver_id is None:
            # ブロードキャスト: 全エージェントのキューに追加
            for agent_id in self.queues:
                if agent_id != sender_id:  # 送信者自身には送らない
                    self._append_message_atomic(agent_id, message)
            logger.info(
                f"ブロードキャストメッセージを送信: {sender_id} -> all"
            )
        else:
            # 特定エージェントへの送信（アトミック操作）
            self._append_message_atomic(receiver_id, message)
            logger.info(
                f"メッセージを送信: {sender_id} -> {receiver_id}"
            )

        return message

    def read_messages(
        self,
        agent_id: str,
        unread_only: bool = False,
        message_type: MessageType | None = None,
        mark_as_read: bool = True,
    ) -> list[Message]:
        """メッセージを読み取る。

        Args:
            agent_id: エージェントID
            unread_only: 未読のみ取得するか
            message_type: フィルターするメッセージタイプ
            mark_as_read: 既読としてマークするか

        Returns:
            メッセージのリスト
        """
        queue = self._load_queue(agent_id)
        messages = queue.messages

        # フィルタリング
        if unread_only:
            messages = [m for m in messages if not m.is_read]

        if message_type is not None:
            messages = [m for m in messages if m.message_type == message_type]

        # 既読マーク
        if mark_as_read:
            now = datetime.now()
            for msg in messages:
                if not msg.is_read:
                    msg.read_at = now
            self._save_queue(queue)

        return messages

    def get_unread_count(self, agent_id: str) -> int:
        """未読メッセージ数を取得する。

        Args:
            agent_id: エージェントID

        Returns:
            未読メッセージ数
        """
        queue = self._load_queue(agent_id)
        return queue.unread_count

    def clear_messages(self, agent_id: str, older_than: datetime | None = None) -> int:
        """メッセージをクリアする。

        Args:
            agent_id: エージェントID
            older_than: この日時より古いメッセージのみ削除（Noneで全削除）

        Returns:
            削除されたメッセージ数
        """
        queue = self._load_queue(agent_id)
        original_count = len(queue.messages)

        if older_than is None:
            queue.messages = []
        else:
            queue.messages = [
                m for m in queue.messages if m.created_at >= older_than
            ]

        deleted_count = original_count - len(queue.messages)
        self._save_queue(queue)

        logger.info(
            f"エージェント {agent_id} のメッセージを {deleted_count} 件削除"
        )
        return deleted_count

    def get_all_agent_ids(self) -> list[str]:
        """登録済み全エージェントIDを取得する。

        Returns:
            エージェントIDのリスト
        """
        # メモリから取得
        agent_ids = list(self.queues.keys())

        # ファイルからも確認
        for queue_file in self.ipc_dir.glob("queue_*.json"):
            agent_id = queue_file.stem.replace("queue_", "")
            if agent_id not in agent_ids:
                agent_ids.append(agent_id)

        return agent_ids

    def send_task_assignment(
        self,
        sender_id: str,
        worker_id: str,
        task_id: str,
        task_description: str,
        branch: str | None = None,
    ) -> Message:
        """タスク割り当てメッセージを送信する。

        Args:
            sender_id: 送信元エージェントID（AdminまたはOwner）
            worker_id: 割り当て先WorkerID
            task_id: タスクID
            task_description: タスク説明
            branch: 作業ブランチ

        Returns:
            送信されたMessage
        """
        return self.send_message(
            sender_id=sender_id,
            receiver_id=worker_id,
            message_type=MessageType.TASK_ASSIGN,
            subject=f"タスク割り当て: {task_id}",
            content=task_description,
            priority=MessagePriority.HIGH,
            metadata={
                "task_id": task_id,
                "branch": branch,
            },
        )

    def send_task_complete(
        self,
        worker_id: str,
        admin_id: str,
        task_id: str,
        result: str,
    ) -> Message:
        """タスク完了報告メッセージを送信する。

        Args:
            worker_id: Worker ID
            admin_id: 報告先Admin ID
            task_id: タスクID
            result: 結果の説明

        Returns:
            送信されたMessage
        """
        return self.send_message(
            sender_id=worker_id,
            receiver_id=admin_id,
            message_type=MessageType.TASK_COMPLETE,
            subject=f"タスク完了: {task_id}",
            content=result,
            priority=MessagePriority.NORMAL,
            metadata={
                "task_id": task_id,
            },
        )

    def send_progress_update(
        self,
        worker_id: str,
        admin_id: str,
        task_id: str,
        progress: int,
        status_message: str,
    ) -> Message:
        """進捗更新メッセージを送信する。

        Args:
            worker_id: Worker ID
            admin_id: 報告先Admin ID
            task_id: タスクID
            progress: 進捗率（0-100）
            status_message: 状況説明

        Returns:
            送信されたMessage
        """
        return self.send_message(
            sender_id=worker_id,
            receiver_id=admin_id,
            message_type=MessageType.TASK_PROGRESS,
            subject=f"進捗報告: {task_id} ({progress}%)",
            content=status_message,
            priority=MessagePriority.LOW,
            metadata={
                "task_id": task_id,
                "progress": progress,
            },
        )
