"""アプリケーションコンテキストの定義。

マネージャーフィールドは機能ごとにグループ化されている:
- core: コアマネージャー (settings, tmux, ai_cli, agents)
- workflow: ワークフローマネージャー (ipc, dashboard, scheduler)
- monitoring: 監視マネージャー (healthcheck, daemon関連)
- optional: オプショナルマネージャー (persona, memory)

後方互換性のため、全フィールドは AppContext から直接アクセス可能。
グループ経由のアクセスも可能（例: app_ctx.core.settings）。

設計メモ: マネージャーの遅延初期化は ensure_*_manager() 関数で行う。
__getattr__ による自動初期化は dataclass の None デフォルト値と
互換性がないため不採用（詳細は helpers_managers.py 参照）。
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.config.settings import Settings
from src.managers.ai_cli_manager import AiCliManager
from src.managers.dashboard_manager import DashboardManager
from src.managers.gtrconfig_manager import GtrconfigManager
from src.managers.healthcheck_manager import HealthcheckManager
from src.managers.ipc_manager import IPCManager
from src.managers.memory_manager import MemoryManager
from src.managers.persona_manager import PersonaManager
from src.managers.scheduler_manager import SchedulerManager
from src.managers.tmux_manager import TmuxManager
from src.managers.worktree_manager import WorktreeManager
from src.models.agent import Agent


@dataclass
class CoreManagers:
    """コアマネージャーグループ: サーバー起動に必須のマネージャー。"""

    settings: Settings
    tmux: TmuxManager
    ai_cli: AiCliManager
    agents: dict[str, Agent] = field(default_factory=dict)


@dataclass
class WorkflowManagers:
    """ワークフローマネージャーグループ: タスク実行・通信・ダッシュボード。"""

    ipc_manager: IPCManager | None = None
    dashboard_manager: DashboardManager | None = None
    scheduler_manager: SchedulerManager | None = None


@dataclass
class MonitoringManagers:
    """監視マネージャーグループ: ヘルスチェック・デーモン関連。"""

    healthcheck_manager: HealthcheckManager | None = None
    healthcheck_daemon_task: asyncio.Task | None = None
    healthcheck_daemon_stop_event: asyncio.Event | None = None
    healthcheck_daemon_lock: asyncio.Lock | None = None
    healthcheck_idle_cycles: int = 0


@dataclass
class OptionalManagers:
    """オプショナルマネージャーグループ: ペルソナ・メモリ。"""

    persona_manager: PersonaManager | None = None
    memory_manager: MemoryManager | None = None


@dataclass
class AppContext:
    """アプリケーションコンテキスト。

    マネージャーフィールドはグループ化されており、グループ経由でもアクセス可能:
    - app_ctx.core.settings / app_ctx.settings（後方互換）
    - app_ctx.workflow.ipc_manager / app_ctx.ipc_manager（後方互換）
    - app_ctx.monitoring.healthcheck_manager / app_ctx.healthcheck_manager（後方互換）
    - app_ctx.optional.persona_manager / app_ctx.persona_manager（後方互換）
    """

    # --- コアマネージャー（必須） ---
    settings: Settings
    tmux: TmuxManager
    ai_cli: AiCliManager
    agents: dict[str, Agent] = field(default_factory=dict)

    # --- ワークスペース管理 ---
    worktree_managers: dict[str, WorktreeManager] = field(default_factory=dict)
    gtrconfig_managers: dict[str, GtrconfigManager] = field(default_factory=dict)

    # --- ワークフローマネージャー ---
    ipc_manager: IPCManager | None = None
    dashboard_manager: DashboardManager | None = None
    scheduler_manager: SchedulerManager | None = None

    # --- 監視マネージャー ---
    healthcheck_manager: HealthcheckManager | None = None
    healthcheck_daemon_task: asyncio.Task | None = None
    healthcheck_daemon_stop_event: asyncio.Event | None = None
    healthcheck_daemon_lock: asyncio.Lock | None = None
    healthcheck_idle_cycles: int = 0

    # --- オプショナルマネージャー ---
    persona_manager: PersonaManager | None = None
    memory_manager: MemoryManager | None = None

    # --- セッション情報 ---
    workspace_id: str | None = None
    project_root: str | None = None
    """プロジェクトルート（.multi-agent-mcp/ の親ディレクトリ）"""
    session_id: str | None = None
    """セッションID（タスクディレクトリ名として使用）"""

    # --- 内部状態 ---
    _admin_poll_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Admin ごとのポーリングガード状態"""
    _owner_wait_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Owner ごとの待機ロック状態"""
    _admin_last_healthcheck_at: dict[str, datetime] = field(default_factory=dict)
    """Admin ごとの最終ヘルスチェック実行時刻"""

    def __post_init__(self) -> None:
        """マネージャーグループを初期化する。

        各グループは AppContext のフィールドへの参照を保持する。
        ミュータブルオブジェクト（dict 等）は同一参照を共有するため、
        AppContext 側の変更がグループ経由でも反映される。
        """
        object.__setattr__(
            self,
            "_core",
            CoreManagers(
                settings=self.settings,
                tmux=self.tmux,
                ai_cli=self.ai_cli,
                agents=self.agents,
            ),
        )
        object.__setattr__(
            self,
            "_workflow",
            WorkflowManagers(
                ipc_manager=self.ipc_manager,
                dashboard_manager=self.dashboard_manager,
                scheduler_manager=self.scheduler_manager,
            ),
        )
        object.__setattr__(
            self,
            "_monitoring",
            MonitoringManagers(
                healthcheck_manager=self.healthcheck_manager,
                healthcheck_daemon_task=self.healthcheck_daemon_task,
                healthcheck_daemon_stop_event=self.healthcheck_daemon_stop_event,
                healthcheck_daemon_lock=self.healthcheck_daemon_lock,
                healthcheck_idle_cycles=self.healthcheck_idle_cycles,
            ),
        )
        object.__setattr__(
            self,
            "_optional",
            OptionalManagers(
                persona_manager=self.persona_manager,
                memory_manager=self.memory_manager,
            ),
        )

    @property
    def core(self) -> CoreManagers:
        """コアマネージャーグループへのアクセス。"""
        return self._core

    @property
    def workflow(self) -> WorkflowManagers:
        """ワークフローマネージャーグループへのアクセス。"""
        return self._workflow

    @property
    def monitoring(self) -> MonitoringManagers:
        """監視マネージャーグループへのアクセス。"""
        return self._monitoring

    @property
    def optional(self) -> OptionalManagers:
        """オプショナルマネージャーグループへのアクセス。"""
        return self._optional
