"""アプリケーションコンテキストの定義。

マネージャーフィールドは機能ごとにグループ化されている:
- core: コアマネージャー (settings, tmux, ai_cli, agents)
- workflow: ワークフローマネージャー (ipc, dashboard, scheduler)
- monitoring: 監視マネージャー (healthcheck, daemon関連)
- optional: オプショナルマネージャー (persona, memory)

後方互換性のため、全フィールドは AppContext から直接アクセス可能。
グループ経由のアクセスも可能（例: app_ctx.core.settings）。

グループ API は AppContext 本体を参照する live view として実装し、
トップレベル属性とグループ属性が乖離しないようにする。

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


class CoreManagers:
    """コアマネージャーグループの live view。"""

    def __init__(self, ctx: "AppContext") -> None:
        self._ctx = ctx

    @property
    def settings(self) -> Settings:
        return self._ctx.settings

    @settings.setter
    def settings(self, value: Settings) -> None:
        self._ctx.settings = value

    @property
    def tmux(self) -> TmuxManager:
        return self._ctx.tmux

    @tmux.setter
    def tmux(self, value: TmuxManager) -> None:
        self._ctx.tmux = value

    @property
    def ai_cli(self) -> AiCliManager:
        return self._ctx.ai_cli

    @ai_cli.setter
    def ai_cli(self, value: AiCliManager) -> None:
        self._ctx.ai_cli = value

    @property
    def agents(self) -> dict[str, Agent]:
        return self._ctx.agents

    @agents.setter
    def agents(self, value: dict[str, Agent]) -> None:
        self._ctx.agents = value


class WorkflowManagers:
    """ワークフローマネージャーグループの live view。"""

    def __init__(self, ctx: "AppContext") -> None:
        self._ctx = ctx

    @property
    def ipc_manager(self) -> IPCManager | None:
        return self._ctx.ipc_manager

    @ipc_manager.setter
    def ipc_manager(self, value: IPCManager | None) -> None:
        self._ctx.ipc_manager = value

    @property
    def dashboard_manager(self) -> DashboardManager | None:
        return self._ctx.dashboard_manager

    @dashboard_manager.setter
    def dashboard_manager(self, value: DashboardManager | None) -> None:
        self._ctx.dashboard_manager = value

    @property
    def scheduler_manager(self) -> SchedulerManager | None:
        return self._ctx.scheduler_manager

    @scheduler_manager.setter
    def scheduler_manager(self, value: SchedulerManager | None) -> None:
        self._ctx.scheduler_manager = value


class MonitoringManagers:
    """監視マネージャーグループの live view。"""

    def __init__(self, ctx: "AppContext") -> None:
        self._ctx = ctx

    @property
    def healthcheck_manager(self) -> HealthcheckManager | None:
        return self._ctx.healthcheck_manager

    @healthcheck_manager.setter
    def healthcheck_manager(self, value: HealthcheckManager | None) -> None:
        self._ctx.healthcheck_manager = value

    @property
    def healthcheck_daemon_task(self) -> asyncio.Task | None:
        return self._ctx.healthcheck_daemon_task

    @healthcheck_daemon_task.setter
    def healthcheck_daemon_task(self, value: asyncio.Task | None) -> None:
        self._ctx.healthcheck_daemon_task = value

    @property
    def healthcheck_daemon_stop_event(self) -> asyncio.Event | None:
        return self._ctx.healthcheck_daemon_stop_event

    @healthcheck_daemon_stop_event.setter
    def healthcheck_daemon_stop_event(self, value: asyncio.Event | None) -> None:
        self._ctx.healthcheck_daemon_stop_event = value

    @property
    def healthcheck_daemon_lock(self) -> asyncio.Lock | None:
        return self._ctx.healthcheck_daemon_lock

    @healthcheck_daemon_lock.setter
    def healthcheck_daemon_lock(self, value: asyncio.Lock | None) -> None:
        self._ctx.healthcheck_daemon_lock = value

    @property
    def healthcheck_idle_cycles(self) -> int:
        return self._ctx.healthcheck_idle_cycles

    @healthcheck_idle_cycles.setter
    def healthcheck_idle_cycles(self, value: int) -> None:
        self._ctx.healthcheck_idle_cycles = value


class OptionalManagers:
    """オプショナルマネージャーグループの live view。"""

    def __init__(self, ctx: "AppContext") -> None:
        self._ctx = ctx

    @property
    def persona_manager(self) -> PersonaManager | None:
        return self._ctx.persona_manager

    @persona_manager.setter
    def persona_manager(self, value: PersonaManager | None) -> None:
        self._ctx.persona_manager = value

    @property
    def memory_manager(self) -> MemoryManager | None:
        return self._ctx.memory_manager

    @memory_manager.setter
    def memory_manager(self, value: MemoryManager | None) -> None:
        self._ctx.memory_manager = value


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

        各グループは AppContext 本体を参照する live view を保持する。
        これによりトップレベル属性の差し替え後も、
        グループ経由の参照が stale にならない。
        """
        object.__setattr__(self, "_core", CoreManagers(self))
        object.__setattr__(self, "_workflow", WorkflowManagers(self))
        object.__setattr__(self, "_monitoring", MonitoringManagers(self))
        object.__setattr__(self, "_optional", OptionalManagers(self))

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
