"""プロセス間通信（IPC）管理モジュール。

個別ファイルベースのメッセージキューを使用してエージェント間通信を実現する。

保存先: {project_root}/{mcp_dir}/{session_id}/ipc/{agent_id}/
形式: YAML Front Matter + Markdown（各メッセージは個別の .md ファイル）
"""

import json
import logging
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src.config.constants import PRIVATE_FILE_MODE
from src.managers.atomic_io import atomic_write_text
from src.models.message import (
    Message,
    MessagePriority,
    MessageType,
)

logger = logging.getLogger(__name__)

try:
    import fcntl
except ImportError:  # pragma: no cover - 非POSIX環境のフォールバック
    fcntl = None
    logger.warning(
        "fcntl が利用できないため、IPC ファイルロックは無効化されます。"
        " 非 POSIX 環境では並行書き込み時にデータ競合が発生する可能性があります。"
    )


def _sanitize_filename(value: str) -> str:
    """ファイル名として安全な形式に変換する。"""
    safe = re.sub(r'[<>:"/\\|?*]', "_", value)
    safe = safe.strip(" .")
    return safe or "message"


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

    def _get_index_path(self, agent_id: str) -> Path:
        """エージェント未読インデックスのパスを取得する。"""
        return self._get_agent_dir(agent_id) / ".unread_index.json"

    def _get_index_lock_path(self, agent_id: str) -> Path:
        """未読インデックス更新用ロックファイルのパスを取得する。"""
        return self._get_agent_dir(agent_id) / ".unread_index.lock"

    @contextmanager
    def _index_lock(self, agent_id: str):
        """未読インデックス更新を排他制御する。"""
        lock_path = self._get_index_lock_path(agent_id)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            try:
                os.chmod(lock_path, PRIVATE_FILE_MODE)
            except OSError:
                logger.debug("lock ファイルの chmod に失敗: %s", lock_path)
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _new_index() -> dict[str, Any]:
        """未読インデックスの初期データを返す。"""
        return {
            "version": 1,
            "entries": [],
            "unread_count": 0,
            "cursor": 0,
        }

    @staticmethod
    def _normalize_index_file_name(raw_file_name: str) -> str | None:
        """未読インデックス内の file_name を安全な basename に正規化する。"""
        file_name = raw_file_name.strip()
        if not file_name:
            return None
        if file_name in {".", ".."}:
            return None
        path = Path(file_name)
        if path.name != file_name:
            return None
        if "/" in file_name or "\\" in file_name:
            return None
        return file_name

    @staticmethod
    def _resolve_agent_message_path(agent_dir: Path, file_name: str) -> Path | None:
        """agent_dir 配下に限定したメッセージファイルパスを解決する。"""
        normalized = IPCManager._normalize_index_file_name(file_name)
        if normalized is None:
            return None
        candidate = (agent_dir / normalized).resolve()
        root = agent_dir.resolve()
        if not candidate.is_relative_to(root):
            return None
        return candidate

    @staticmethod
    def _normalize_index(index: dict[str, Any]) -> dict[str, Any]:
        """インデックス形式を正規化する。"""
        entries_raw = index.get("entries")
        entries = entries_raw if isinstance(entries_raw, list) else []
        normalized_entries: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            message_id = str(entry.get("id", "")).strip()
            file_name = IPCManager._normalize_index_file_name(str(entry.get("file_name", "")))
            created_at = str(entry.get("created_at", "")).strip()
            message_type = str(entry.get("message_type", "")).strip()
            read_at = entry.get("read_at")
            if not message_id or not file_name or not created_at or not message_type:
                continue
            if read_at is not None:
                read_at = str(read_at).strip() or None
            normalized_entries.append(
                {
                    "id": message_id,
                    "file_name": file_name,
                    "created_at": created_at,
                    "message_type": message_type,
                    "read_at": read_at,
                }
            )

        unread_count = 0
        first_unread = len(normalized_entries)
        for i, entry in enumerate(normalized_entries):
            if entry["read_at"] is None:
                unread_count += 1
                if first_unread == len(normalized_entries):
                    first_unread = i

        cursor_raw = index.get("cursor", first_unread)
        if isinstance(cursor_raw, int):
            cursor = max(0, min(cursor_raw, len(normalized_entries)))
        else:
            cursor = first_unread

        return {
            "version": 1,
            "entries": normalized_entries,
            "unread_count": unread_count,
            "cursor": cursor,
        }

    def _load_index(self, agent_id: str) -> dict[str, Any] | None:
        """未読インデックスを読み込む。"""
        index_path = self._get_index_path(agent_id)
        if not index_path.exists():
            return None
        try:
            with open(index_path, encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                return None
            return self._normalize_index(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as e:
            logger.warning("IPC インデックス読み込みに失敗 (%s): %s", index_path, e)
            return None

    def _save_index(self, agent_id: str, index: dict[str, Any]) -> None:
        """未読インデックスを保存する。"""
        index_path = self._get_index_path(agent_id)
        normalized = self._normalize_index(index)
        payload = json.dumps(normalized, ensure_ascii=False, indent=2)
        self._atomic_write(index_path, payload)

    @staticmethod
    def _recalculate_index_state(index: dict[str, Any]) -> None:
        """未読件数・カーソルを再計算する。"""
        entries = index.get("entries", [])
        unread_count = 0
        first_unread = len(entries)
        for i, entry in enumerate(entries):
            if entry.get("read_at") is None:
                unread_count += 1
                if first_unread == len(entries):
                    first_unread = i
        index["unread_count"] = unread_count
        index["cursor"] = first_unread

    @staticmethod
    def _list_message_files(agent_dir: Path) -> list[Path]:
        """メッセージファイル一覧を時系列順で取得する。"""
        return sorted(agent_dir.glob("*.md"))

    def _rebuild_index(self, agent_id: str) -> dict[str, Any]:
        """既存メッセージファイルから未読インデックスを再構築する。"""
        agent_dir = self._get_agent_dir(agent_id)
        index = self._new_index()
        if not agent_dir.exists():
            self._save_index(agent_id, index)
            return index

        entries: list[dict[str, Any]] = []
        for file_path in self._list_message_files(agent_dir):
            message = self._parse_message_file(file_path)
            if not message:
                continue
            entries.append(
                {
                    "id": message.id,
                    "file_name": file_path.name,
                    "created_at": message.created_at.isoformat(),
                    "message_type": message.message_type.value,
                    "read_at": message.read_at.isoformat() if message.read_at else None,
                }
            )
        index["entries"] = entries
        self._recalculate_index_state(index)
        self._save_index(agent_id, index)
        return index

    def _get_or_rebuild_index(self, agent_id: str) -> dict[str, Any]:
        """未読インデックスを取得し、なければ再構築する。"""
        index = self._load_index(agent_id)
        if index is None:
            return self._rebuild_index(agent_id)
        return index

    def _append_index_entry(self, agent_id: str, message: Message, file_path: Path) -> None:
        """送信メッセージを未読インデックスへ追記する。"""
        with self._index_lock(agent_id):
            index = self._load_index(agent_id)
            if index is None:
                # 既存セッションからの移行時は再構築を優先し、重複追記を避ける
                self._rebuild_index(agent_id)
                return
            index["entries"].append(
                {
                    "id": message.id,
                    "file_name": file_path.name,
                    "created_at": message.created_at.isoformat(),
                    "message_type": message.message_type.value,
                    "read_at": message.read_at.isoformat() if message.read_at else None,
                }
            )
            self._recalculate_index_state(index)
            self._save_index(agent_id, index)

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
                read_at=datetime.fromisoformat(front_matter["read_at"])
                if front_matter.get("read_at")
                else None,
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
            front_matter,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        return f"---\n{yaml_str}---\n\n{message.content}\n"

    def _atomic_write(self, file_path: Path, content: str) -> None:
        """アトミック書き込み（tmpfile + os.replace）でファイルを安全に保存する。"""
        atomic_write_text(file_path, content)

    def _write_message_file(self, agent_id: str, message: Message) -> Path:
        """メッセージを Markdown ファイルとしてアトミックに保存する。"""
        agent_dir = self._get_agent_dir(agent_id)
        agent_dir.mkdir(parents=True, exist_ok=True)

        file_path = self._get_message_path(agent_id, message.id, message.created_at)
        content = self._build_message_content(message)
        self._atomic_write(file_path, content)
        self._append_index_entry(agent_id, message, file_path)
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

        messages: list[Message] = []
        if unread_only:
            index = self._get_or_rebuild_index(agent_id)
            entries = index.get("entries", [])
            cursor = int(index.get("cursor", 0))
            for entry in entries[cursor:]:
                if entry.get("read_at") is not None:
                    continue
                if (
                    message_type is not None
                    and entry.get("message_type") != message_type.value
                ):
                    continue
                file_name = str(entry.get("file_name", "")).strip()
                if not file_name:
                    continue
                file_path = self._resolve_agent_message_path(agent_dir, file_name)
                if file_path is None:
                    continue
                message = self._parse_message_file(file_path)
                if message:
                    messages.append(message)
        else:
            for file_path in self._list_message_files(agent_dir):
                message = self._parse_message_file(file_path)
                if not message:
                    continue
                if message_type is not None and message.message_type != message_type:
                    continue
                messages.append(message)
            messages.sort(key=lambda m: m.created_at)

        if mark_as_read:
            mark_ids = [msg.id for msg in messages if not msg.is_read]
            marked_at = self.mark_messages_as_read(agent_id, mark_ids)
            if marked_at is not None:
                for msg in messages:
                    if msg.id in mark_ids and not msg.is_read:
                        msg.read_at = marked_at

        return messages

    def mark_messages_as_read(self, agent_id: str, message_ids: list[str]) -> datetime | None:
        """指定メッセージを既読にする。

        Args:
            agent_id: エージェントID
            message_ids: 既読化するメッセージID

        Returns:
            既読化時刻。更新対象がない場合は None
        """
        if not message_ids:
            return None

        agent_dir = self._get_agent_dir(agent_id)
        if not agent_dir.exists():
            return None

        target_ids = {message_id for message_id in message_ids if message_id}
        if not target_ids:
            return None

        with self._index_lock(agent_id):
            index = self._get_or_rebuild_index(agent_id)
            now = datetime.now()
            marked = False

            for entry in index.get("entries", []):
                message_id = str(entry.get("id", "")).strip()
                if message_id not in target_ids:
                    continue
                if entry.get("read_at") is not None:
                    continue

                file_name = str(entry.get("file_name", "")).strip()
                if not file_name:
                    continue
                file_path = self._resolve_agent_message_path(agent_dir, file_name)
                if file_path is None:
                    continue
                message = self._parse_message_file(file_path)
                if message is None or message.is_read:
                    continue

                message.read_at = now
                self._update_message_file(file_path, message)
                entry["read_at"] = now.isoformat()
                marked = True

            if not marked:
                return None

            self._recalculate_index_state(index)
            self._save_index(agent_id, index)
            return now

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

        index = self._get_or_rebuild_index(agent_id)
        unread_count = index.get("unread_count")
        if isinstance(unread_count, int):
            return unread_count
        self._recalculate_index_state(index)
        self._save_index(agent_id, index)
        return int(index.get("unread_count", 0))

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
