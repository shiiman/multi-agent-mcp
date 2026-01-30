"""pytest設定とフィクスチャ。"""

import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.managers.ai_cli_manager import AiCliManager
from src.managers.cost_manager import CostManager
from src.managers.dashboard_manager import DashboardManager
from src.managers.gtrconfig_manager import GtrconfigManager
from src.managers.healthcheck_manager import HealthcheckManager
from src.managers.ipc_manager import IPCManager
from src.managers.metrics_manager import MetricsManager
from src.managers.scheduler_manager import SchedulerManager
from src.managers.tmux_manager import TmuxManager
from src.managers.worktree_manager import WorktreeManager
from src.models.agent import Agent, AgentRole, AgentStatus


@pytest.fixture
def temp_dir():
    """一時ディレクトリを作成する。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def settings(temp_dir):
    """テスト用の設定を作成する。"""
    from src.config.settings import TerminalApp

    return Settings(
        workspace_base_dir=str(temp_dir / "workspaces"),
        max_workers=3,
        tmux_prefix="test-mcp-agent",
        default_terminal=TerminalApp.AUTO,
    )


@pytest.fixture
def tmux_manager(settings):
    """TmuxManagerインスタンスを作成する。"""
    return TmuxManager(settings)


@pytest.fixture
def ipc_manager(temp_dir):
    """IPCManagerインスタンスを作成する。"""
    ipc_dir = temp_dir / ".ipc"
    manager = IPCManager(str(ipc_dir))
    manager.initialize()
    yield manager
    manager.cleanup()


@pytest.fixture
def dashboard_manager(temp_dir):
    """DashboardManagerインスタンスを作成する。"""
    dashboard_dir = temp_dir / ".dashboard"
    manager = DashboardManager(
        workspace_id="test-workspace",
        workspace_path=str(temp_dir),
        dashboard_dir=str(dashboard_dir),
    )
    manager.initialize()
    yield manager
    manager.cleanup()


@pytest.fixture
def git_repo(temp_dir):
    """テスト用のgitリポジトリを作成する。"""
    repo_path = temp_dir / "repo"
    repo_path.mkdir()
    os.system(f"cd {repo_path} && git init && git commit --allow-empty -m 'init'")
    return repo_path


@pytest.fixture
def ai_cli_manager(settings):
    """AiCliManagerインスタンスを作成する。"""
    return AiCliManager(settings)


@pytest.fixture
def gtrconfig_manager(temp_dir):
    """GtrconfigManagerインスタンスを作成する。"""
    return GtrconfigManager(str(temp_dir))


@pytest.fixture
def sample_agents():
    """テスト用のエージェント辞書を作成する。"""
    now = datetime.now()
    return {
        "agent-001": Agent(
            id="agent-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session="agent-001",
            created_at=now,
            last_activity=now,
        ),
        "agent-002": Agent(
            id="agent-002",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="agent-002",
            created_at=now,
            last_activity=now,
        ),
        "agent-003": Agent(
            id="agent-003",
            role=AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="agent-003",
            created_at=now,
            last_activity=now,
        ),
    }


@pytest.fixture
def scheduler_manager(dashboard_manager, sample_agents):
    """SchedulerManagerインスタンスを作成する。"""
    return SchedulerManager(dashboard_manager, sample_agents)


@pytest.fixture
def healthcheck_manager(tmux_manager, sample_agents):
    """HealthcheckManagerインスタンスを作成する。"""
    return HealthcheckManager(tmux_manager, sample_agents, heartbeat_timeout_seconds=60)


@pytest.fixture
def metrics_manager(temp_dir):
    """MetricsManagerインスタンスを作成する。"""
    return MetricsManager(str(temp_dir / ".metrics"))


@pytest.fixture
def cost_manager():
    """CostManagerインスタンスを作成する。"""
    return CostManager(warning_threshold_usd=10.0)


@pytest.fixture
def worktree_manager(git_repo):
    """WorktreeManagerインスタンスを作成する。"""
    return WorktreeManager(str(git_repo))
