"""アプリケーションコンテキストの定義。"""

from dataclasses import dataclass, field

from src.config.settings import Settings
from src.managers.ai_cli_manager import AiCliManager
from src.managers.cost_manager import CostManager
from src.managers.dashboard_manager import DashboardManager
from src.managers.gtrconfig_manager import GtrconfigManager
from src.managers.healthcheck_manager import HealthcheckManager
from src.managers.ipc_manager import IPCManager
from src.managers.memory_manager import MemoryManager
from src.managers.metrics_manager import MetricsManager
from src.managers.persona_manager import PersonaManager
from src.managers.scheduler_manager import SchedulerManager
from src.managers.tmux_manager import TmuxManager
from src.managers.worktree_manager import WorktreeManager
from src.models.agent import Agent


@dataclass
class AppContext:
    """アプリケーションコンテキスト。"""

    settings: Settings
    tmux: TmuxManager
    ai_cli: AiCliManager
    agents: dict[str, Agent] = field(default_factory=dict)
    worktree_managers: dict[str, WorktreeManager] = field(default_factory=dict)
    gtrconfig_managers: dict[str, GtrconfigManager] = field(default_factory=dict)
    ipc_manager: IPCManager | None = None
    dashboard_manager: DashboardManager | None = None
    scheduler_manager: SchedulerManager | None = None
    healthcheck_manager: HealthcheckManager | None = None
    metrics_manager: MetricsManager | None = None
    cost_manager: CostManager | None = None
    persona_manager: PersonaManager | None = None
    memory_manager: MemoryManager | None = None
    workspace_id: str | None = None
    project_root: str | None = None
    """プロジェクトルート（.multi-agent-mcp/ の親ディレクトリ）"""
    session_id: str | None = None
    """セッションID（タスクディレクトリ名として使用）"""
