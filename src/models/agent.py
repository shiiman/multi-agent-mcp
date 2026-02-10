"""エージェントモデル定義。"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from src.config.settings import AICli


class AgentRole(str, Enum):
    """エージェントの役割。"""

    OWNER = "owner"
    """全体指揮、タスク分解、Issue作成"""

    ADMIN = "admin"
    """Worker管理、進捗管理、ダッシュボード更新"""

    WORKER = "worker"
    """割り当てられたタスクのdev-flow実行"""


class AgentStatus(str, Enum):
    """エージェントの状態。"""

    IDLE = "idle"
    """待機中"""

    BUSY = "busy"
    """作業中"""

    ERROR = "error"
    """エラー発生"""

    TERMINATED = "terminated"
    """終了済み"""


class Agent(BaseModel):
    """エージェント情報。"""

    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(description="エージェントの一意識別子")
    role: AgentRole = Field(description="エージェントの役割")
    status: AgentStatus = Field(default=AgentStatus.IDLE, description="エージェントの状態")
    tmux_session: str | None = Field(default=None, description="tmuxセッション名（Owner は None）")
    working_dir: str | None = Field(default=None, description="作業ディレクトリのパス")
    worktree_path: str | None = Field(default=None, description="割り当てられたworktreeのパス")
    branch: str | None = Field(default=None, description="現在割り当て中のブランチ")
    current_task: str | None = Field(default=None, description="現在実行中のタスク")
    created_at: datetime = Field(description="作成日時")
    last_activity: datetime = Field(description="最終活動日時")

    # グリッドレイアウト用フィールド
    session_name: str | None = Field(
        default=None, description="セッション名（command または workers）"
    )
    window_index: int | None = Field(default=None, description="ウィンドウ番号（0, 1, 2, ...）")
    pane_index: int | None = Field(default=None, description="ウィンドウ内のペインインデックス")
    cli_session_name: str | None = Field(
        default=None, description="AI CLI セッション名（必要時のみ）"
    )
    cli_session_target: str | None = Field(
        default=None, description="AI CLI セッションの接続先識別子"
    )
    ai_cli: AICli | None = Field(default=None, description="使用するAI CLI（None=デフォルト）")
    ai_bootstrapped: bool = Field(
        default=False,
        description="Worker が AI 起動済みかどうか（初回タスク送信後に True）",
    )

    @property
    def resolved_session_name(self) -> str | None:
        """tmux のセッション名を解決する。

        session_name フィールドを優先し、なければ tmux_session から抽出する。

        Returns:
            セッション名、または解決できない場合は None
        """
        if self.session_name:
            return self.session_name
        if self.tmux_session:
            return str(self.tmux_session).split(":", 1)[0]
        return None
