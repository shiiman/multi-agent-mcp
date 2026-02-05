"""エージェント間メッセージモデル。"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """メッセージの種類。"""

    # タスク関連
    TASK_ASSIGN = "task_assign"  # タスク割り当て
    TASK_COMPLETE = "task_complete"  # タスク完了報告
    TASK_APPROVED = "task_approved"  # タスク承認（Owner → Admin）
    TASK_FAILED = "task_failed"  # タスク失敗報告
    TASK_PROGRESS = "task_progress"  # 進捗報告

    # 状態関連
    STATUS_UPDATE = "status_update"  # ステータス更新

    # 通信関連
    REQUEST = "request"  # リクエスト
    RESPONSE = "response"  # レスポンス
    BROADCAST = "broadcast"  # ブロードキャスト

    # システム関連
    SYSTEM = "system"  # システムメッセージ
    ERROR = "error"  # エラーメッセージ


class MessagePriority(str, Enum):
    """メッセージの優先度。"""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Message(BaseModel):
    """エージェント間メッセージ。"""

    id: str = Field(..., description="メッセージID")
    sender_id: str = Field(..., description="送信元エージェントID")
    receiver_id: str | None = Field(
        None, description="宛先エージェントID（Noneの場合はブロードキャスト）"
    )
    message_type: MessageType = Field(..., description="メッセージ種類")
    priority: MessagePriority = Field(
        default=MessagePriority.NORMAL, description="優先度"
    )
    subject: str = Field(default="", description="件名")
    content: str = Field(..., description="メッセージ内容")
    metadata: dict = Field(default_factory=dict, description="追加メタデータ")
    created_at: datetime = Field(
        default_factory=datetime.now, description="作成日時"
    )
    read_at: datetime | None = Field(None, description="既読日時")

    @property
    def is_broadcast(self) -> bool:
        """ブロードキャストメッセージかどうか。"""
        return self.receiver_id is None

    @property
    def is_read(self) -> bool:
        """既読かどうか。"""
        return self.read_at is not None


class MessageQueue(BaseModel):
    """エージェントのメッセージキュー。"""

    agent_id: str = Field(..., description="エージェントID")
    messages: list[Message] = Field(
        default_factory=list, description="メッセージリスト"
    )

    @property
    def unread_count(self) -> int:
        """未読メッセージ数。"""
        return len([m for m in self.messages if not m.is_read])

    def get_unread(self) -> list[Message]:
        """未読メッセージを取得する。"""
        return [m for m in self.messages if not m.is_read]

    def get_by_type(self, message_type: MessageType) -> list[Message]:
        """指定タイプのメッセージを取得する。"""
        return [m for m in self.messages if m.message_type == message_type]

    def get_by_priority(self, priority: MessagePriority) -> list[Message]:
        """指定優先度のメッセージを取得する。"""
        return [m for m in self.messages if m.priority == priority]
