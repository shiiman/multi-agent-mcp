"""ダッシュボードモデル。"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


def normalize_task_id(task_id: str | None) -> str:
    """task_id を比較用に正規化する。

    プレフィックス（task:, task_, task-）を除去し、小文字に統一する。

    Args:
        task_id: 正規化対象のタスクID

    Returns:
        正規化されたタスクID文字列（None/空の場合は空文字列）
    """
    if not task_id:
        return ""
    normalized = task_id.strip().lower()
    for prefix in ("task:", "task_", "task-"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized


class TaskStatus(str, Enum):
    """タスクのステータス。"""

    PENDING = "pending"  # 未着手
    IN_PROGRESS = "in_progress"  # 進行中
    COMPLETED = "completed"  # 完了
    FAILED = "failed"  # 失敗
    BLOCKED = "blocked"  # ブロック中
    CANCELLED = "cancelled"  # キャンセル


class ChecklistItem(BaseModel):
    """チェックリストアイテム。"""

    text: str = Field(..., description="アイテムのテキスト")
    completed: bool = Field(default=False, description="完了フラグ")


class TaskLog(BaseModel):
    """タスクログエントリ。"""

    timestamp: datetime = Field(default_factory=datetime.now, description="タイムスタンプ")
    message: str = Field(..., description="ログメッセージ")


class TaskInfo(BaseModel):
    """タスク情報。"""

    id: str = Field(..., description="タスクID")
    title: str = Field(..., description="タスクタイトル")
    description: str = Field(default="", description="タスク参照情報（task_file_path）")
    task_file_path: str | None = Field(default=None, description="タスク指示ファイルパス")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="ステータス")
    assigned_agent_id: str | None = Field(None, description="割り当てられたエージェントID")
    branch: str | None = Field(None, description="関連ブランチ")
    worktree_path: str | None = Field(None, description="worktreeパス")
    progress: int = Field(default=0, ge=0, le=100, description="進捗率（0-100）")
    checklist: list[ChecklistItem] = Field(default_factory=list, description="チェックリスト")
    logs: list[TaskLog] = Field(default_factory=list, description="進捗ログ（最新5件を保持）")
    created_at: datetime = Field(default_factory=datetime.now, description="作成日時")
    started_at: datetime | None = Field(None, description="開始日時")
    completed_at: datetime | None = Field(None, description="完了日時")
    error_message: str | None = Field(None, description="エラーメッセージ")
    metadata: dict = Field(default_factory=dict, description="追加メタデータ")


class AgentSummary(BaseModel):
    """エージェントサマリー情報。"""

    agent_id: str = Field(..., description="エージェントID")
    name: str | None = Field(None, description="表示名")
    role: str = Field(..., description="役割")
    status: str = Field(..., description="ステータス")
    current_task_id: str | None = Field(None, description="現在のタスクID")
    worktree_path: str | None = Field(None, description="worktreeパス")
    branch: str | None = Field(None, description="ブランチ")
    last_activity: datetime | None = Field(None, description="最終活動日時")


class MessageSummary(BaseModel):
    """メッセージサマリー（Dashboard 表示用）。"""

    sender_id: str = Field(..., description="送信元エージェントID")
    receiver_id: str | None = Field(None, description="宛先エージェントID")
    message_type: str = Field(..., description="メッセージタイプ")
    subject: str = Field(default="", description="件名")
    content: str = Field(default="", description="メッセージ内容")
    created_at: datetime | None = Field(None, description="作成日時")


class ApiCallRecord(BaseModel):
    """API呼び出し記録。"""

    ai_cli: str = Field(..., description="使用したAI CLI（claude/codex/gemini）")
    model: str | None = Field(default=None, description="使用モデル")
    tokens: int = Field(..., description="推定トークン数")
    estimated_cost_usd: float = Field(default=0.0, description="推定コスト（USD）")
    actual_cost_usd: float | None = Field(default=None, description="実測コスト（USD）")
    cost_source: str = Field(default="estimated", description="コスト取得元（actual/estimated）")
    status_line: str | None = Field(default=None, description="コスト抽出に使用した statusLine")
    timestamp: datetime = Field(default_factory=datetime.now, description="呼び出し時刻")
    agent_id: str | None = Field(None, description="エージェントID")
    task_id: str | None = Field(None, description="タスクID")


class CostInfo(BaseModel):
    """コスト情報。"""

    total_api_calls: int = Field(default=0, description="総API呼び出し回数")
    estimated_tokens: int = Field(default=0, description="推定総トークン数")
    estimated_cost_usd: float = Field(default=0.0, description="推定総コスト（USD, 参考値）")
    actual_cost_usd: float = Field(
        default=0.0, description="実測総コスト（USD, Claude statusLine）"
    )
    total_cost_usd: float = Field(default=0.0, description="合算コスト（実測優先 + 推定）")
    actual_cost_by_agent: dict[str, float] = Field(
        default_factory=dict,
        description="Claude 実測コストの最新スナップショット（agent_id -> USD）",
    )
    warning_threshold_usd: float = Field(default=10.0, description="コスト警告閾値（USD）")
    calls: list[ApiCallRecord] = Field(default_factory=list, description="呼び出し記録")


class Dashboard(BaseModel):
    """ダッシュボード情報。"""

    workspace_id: str = Field(..., description="ワークスペースID")
    workspace_path: str = Field(..., description="ワークスペースパス")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新日時")
    session_started_at: datetime | None = Field(default=None, description="セッション開始時刻")
    session_finished_at: datetime | None = Field(default=None, description="セッション終了時刻")
    process_crash_count: int = Field(default=0, description="プロセスクラッシュ回数")
    process_recovery_count: int = Field(default=0, description="プロセス復旧回数")

    # エージェント情報
    agents: list[AgentSummary] = Field(default_factory=list, description="エージェント一覧")

    # タスク情報
    tasks: list[TaskInfo] = Field(default_factory=list, description="タスク一覧")

    # 統計情報
    total_agents: int = Field(default=0, description="エージェント総数")
    active_agents: int = Field(default=0, description="アクティブエージェント数")
    total_tasks: int = Field(default=0, description="タスク総数")
    completed_tasks: int = Field(default=0, description="完了タスク数")
    failed_tasks: int = Field(default=0, description="失敗タスク数")

    # Worktree情報
    total_worktrees: int = Field(default=0, description="worktree総数")
    active_worktrees: int = Field(default=0, description="アクティブworktree数")

    # コスト情報
    cost: CostInfo = Field(default_factory=CostInfo, description="コスト情報")

    # メッセージ履歴（Dashboard 表示用、YAML には保存しない）
    messages: list[MessageSummary] = Field(default_factory=list, description="メッセージ履歴")

    def get_task(self, task_id: str) -> TaskInfo | None:
        """タスクを取得する。"""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def get_agent(self, agent_id: str) -> AgentSummary | None:
        """エージェントサマリーを取得する。"""
        for agent in self.agents:
            if agent.agent_id == agent_id:
                return agent
        return None

    def get_tasks_by_status(self, status: TaskStatus) -> list[TaskInfo]:
        """指定ステータスのタスクを取得する。"""
        return [t for t in self.tasks if t.status == status]

    def get_tasks_by_agent(self, agent_id: str) -> list[TaskInfo]:
        """指定エージェントのタスクを取得する。"""
        return [t for t in self.tasks if t.assigned_agent_id == agent_id]

    def calculate_stats(self) -> None:
        """統計情報を再計算する。"""
        self.total_agents = len(self.agents)
        self.active_agents = len([a for a in self.agents if a.status in ("busy", "idle")])
        self.total_tasks = len(self.tasks)
        self.completed_tasks = len([t for t in self.tasks if t.status == TaskStatus.COMPLETED])
        self.failed_tasks = len([t for t in self.tasks if t.status == TaskStatus.FAILED])
        self.updated_at = datetime.now()
