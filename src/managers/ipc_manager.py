"""プロセス間通信（IPC）管理モジュール。

個別ファイルベースのメッセージキューを使用してエージェント間通信を実現する。

保存先: {project_root}/{mcp_dir}/{session_id}/ipc/{agent_id}/
形式: YAML Front Matter + Markdown（各メッセージは個別の .md ファイル）
"""

import logging
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import yaml

from src.models.message import (
    Message,
    MessagePriority,
    MessageType,
)

logger = logging.getLogger(__name__)


def _sanitize_filename(value: str) -> str:
    """ファイル名として安全な形式に変換する。"""
    safe = re.sub(r'[<>:"/\\|?*]', '_', value)
    safe = safe.strip(' .')
    return safe or 'message'


class IPCManager:
    """個別ファイルベースのプロセス間通信を管理するクラス。

    各エージェントのメッセージをディレクトリ内の個別ファイルとして管理する。
    """

    def __init__(self, ipc_dir: str | Path) -> None:
        """IPCManagerを初期化する。

        Args:
            ipc_dir: IPCファイルを保存するディレクトリ
        """
        self.ipc_dir = Path(ipc_dir)

    def initialize(self) -> None:
        """IPC環境を初期化する。"""
        self.ipc_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"IPC環境を初期化しました: {self.ipc_dir}")

    def cleanup(self) -> None:
        """IPC環境をクリーンアップする。"""
        if self.ipc_dir.exists():
            import shutil
            shutil.rmtree(self.ipc_dir)
        logger.info("IPC環境をクリーンアップしました")

    def _get_agent_dir(self, agent_id: str) -> Path:
        """エージェントのメッセージディレクトリを取得する。"""
        return self.ipc_dir / _sanitize_filename(agent_id)

    def _get_message_path(self, agent_id: str, message_id: str, created_at: datetime) -> Path:
        """メッセージのファイルパスを取得する。"""
        agent_dir = self._get_agent_dir(agent_id)
        timestamp = created_at.strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}_{_sanitize_filename(message_id)[:8]}.md"
        return agent_dir / filename

    def _parse_message_file(self, file_path: Path) -> Message | None:
        """Markdown ファイルからメッセージを読み込む。"""
        try:
            content = file_path.read_text(encoding="utf-8")

            if not content.startswith("---"):
                return None

            parts = content.split("---", 2)
            if len(parts) < 3:
                return None

            front_matter = yaml.safe_load(parts[1])
            if not front_matter or "id" not in front_matter:
                return None

            body = parts[2].strip()

            return Message(
                id=front_matter["id"],
                sender_id=front_matter["sender_id"],
                receiver_id=front_matter.get("receiver_id"),
                message_type=MessageType(front_matter["message_type"]),
                priority=MessagePriority(front_matter.get("priority", "normal")),
                subject=front_matter.get("subject", ""),
                content=body,
                metadata=front_matter.get("metadata", {}),
                created_at=datetime.fromisoformat(front_matter["created_at"]),
                read_at=datetime.fromisoformat(
                    front_matter["read_at"]
                ) if front_matter.get("read_at") else None,
            )
        except (OSError, yaml.YAMLError, KeyError, ValueError) as e:
            logger.warning(f"メッセージの読み込みに失敗 ({file_path}): {e}")
            return None

    def _build_message_content(self, message: Message) -> str:
        """メッセージの Markdown コンテンツを組み立てる。"""
        front_matter = {
            "id": message.id,
            "sender_id": message.sender_id,
            "receiver_id": message.receiver_id,
            "message_type": message.message_type.value,
            "priority": message.priority.value,
            "subject": message.subject,
            "created_at": message.created_at.isoformat(),
            "read_at": message.read_at.isoformat() if message.read_at else None,
        }
        if message.metadata:
            front_matter["metadata"] = message.metadata

        yaml_str = yaml.dump(
            front_matter, allow_unicode=True,
            default_flow_style=False, sort_keys=False,
        )
        return f"---\n{yaml_str}---\n\n{message.content}\n"

    def _atomic_write(self, file_path: Path, content: str) -> None:
        """アトミック書き込み（tmpfile + os.replace）でファイルを安全に保存する。"""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(file_path.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, str(file_path))
        except BaseException:
            # 書き込み失敗時に一時ファイルを削除
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _write_message_file(self, agent_id: str, message: Message) -> Path:
        """メッセージを Markdown ファイルとしてアトミックに保存する。"""
        agent_dir = self._get_agent_dir(agent_id)
        agent_dir.mkdir(parents=True, exist_ok=True)

        file_path = self._get_message_path(agent_id, message.id, message.created_at)
        content = self._build_message_content(message)
        self._atomic_write(file_path, content)
        return file_path

    def _update_message_file(self, file_path: Path, message: Message) -> None:
        """既存のメッセージファイルをアトミックに更新する。"""
        content = self._build_message_content(message)
        self._atomic_write(file_path, content)

    def register_agent(self, agent_id: str) -> None:
        """エージェントのメッセージディレクトリを登録する。

        ディレクトリを作成するだけで、既存のメッセージは上書きしない。

        Args:
            agent_id: エージェントID
        """
        agent_dir = self._get_agent_dir(agent_id)
        if not agent_dir.exists():
            agent_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"エージェント {agent_id} のディレクトリを登録しました")

    def unregister_agent(self, agent_id: str) -> None:
        """エージェントのメッセージディレクトリを削除する。

        Args:
            agent_id: エージェントID
        """
        agent_dir = self._get_agent_dir(agent_id)
        if agent_dir.exists():
            import shutil
            shutil.rmtree(agent_dir)
            logger.info(f"エージェント {agent_id} のディレクトリを削除しました")

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

        各メッセージは受信者のディレクトリに個別ファイルとして保存される。

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
            # ブロードキャスト: 全エージェントのディレクトリに追加
            for agent_id in self.get_all_agent_ids():
                if agent_id != sender_id:
                    self._write_message_file(agent_id, message)
            logger.info(f"ブロードキャストメッセージを送信: {sender_id} -> all")
        else:
            # 特定エージェントへの送信
            self._write_message_file(receiver_id, message)
            logger.info(f"メッセージを送信: {sender_id} -> {receiver_id}")

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
            メッセージのリスト（時系列順）
        """
        agent_dir = self._get_agent_dir(agent_id)
        if not agent_dir.exists():
            return []

        messages: list[tuple[Path, Message]] = []
        for file_path in agent_dir.glob("*.md"):
            message = self._parse_message_file(file_path)
            if message:
                messages.append((file_path, message))

        # 時系列順にソート
        messages.sort(key=lambda x: x[1].created_at)

        # フィルタリング
        if unread_only:
            messages = [(p, m) for p, m in messages if not m.is_read]

        if message_type is not None:
            messages = [(p, m) for p, m in messages if m.message_type == message_type]

        # 既読マーク
        if mark_as_read:
            now = datetime.now()
            for file_path, msg in messages:
                if not msg.is_read:
                    msg.read_at = now
                    self._update_message_file(file_path, msg)

        return [m for _, m in messages]

    def get_unread_count(self, agent_id: str) -> int:
        """未読メッセージ数を取得する。

        Args:
            agent_id: エージェントID

        Returns:
            未読メッセージ数
        """
        agent_dir = self._get_agent_dir(agent_id)
        if not agent_dir.exists():
            return 0

        count = 0
        for file_path in agent_dir.glob("*.md"):
            message = self._parse_message_file(file_path)
            if message and not message.is_read:
                count += 1

        return count

    def get_all_agent_ids(self) -> list[str]:
        """登録済み全エージェントIDを取得する。

        Returns:
            エージェントIDのリスト
        """
        if not self.ipc_dir.exists():
            return []

        agent_ids = []
        for agent_dir in self.ipc_dir.iterdir():
            if agent_dir.is_dir():
                agent_ids.append(agent_dir.name)

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
