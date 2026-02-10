"""pytest設定とフィクスチャ。"""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.settings import Settings
from src.context import AppContext
from src.managers.agent_manager import AgentManager
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
from src.models.agent import Agent, AgentRole, AgentStatus


@pytest.fixture(autouse=True)
def disable_macos_notifications(monkeypatch):
    """テスト中の macOS 通知送信を無効化する。"""

    async def _noop_send_macos_notification(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(
        "src.tools.helpers._send_macos_notification",
        _noop_send_macos_notification,
    )


@pytest.fixture
def temp_dir():
    """一時ディレクトリを作成する。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def settings(temp_dir, monkeypatch):
    """テスト用の設定を作成する。"""
    from src.config.settings import TerminalApp

    # 実行環境の MCP_PROJECT_ROOT/.env をテストへ持ち込まない
    monkeypatch.delenv("MCP_PROJECT_ROOT", raising=False)

    return Settings(
        _env_file=None,
        max_workers=3,
        tmux_prefix="test-mcp-agent",
        default_terminal=TerminalApp.AUTO,
    )


@pytest.fixture
async def tmux_manager(settings):
    """tmux 非依存テスト用のモック TmuxManager を作成する。"""
    manager = MagicMock(spec=TmuxManager)
    manager.settings = settings
    manager.create_session = AsyncMock(return_value=True)
    manager.kill_session = AsyncMock(return_value=True)
    manager.cleanup_sessions = AsyncMock(return_value=0)
    manager.cleanup_all_sessions = AsyncMock(return_value=0)
    manager.create_main_session = AsyncMock(return_value=True)
    manager.session_exists = AsyncMock(return_value=False)
    manager.send_keys = AsyncMock(return_value=True)
    manager.send_keys_to_pane = AsyncMock(return_value=True)

    async def _send_with_rate_limit_to_pane(
        session_name,
        window_index,
        pane_index,
        command,
        **_kwargs,
    ):
        return await manager.send_keys_to_pane(
            session_name,
            window_index,
            pane_index,
            command,
        )

    manager.send_with_rate_limit_to_pane = AsyncMock(side_effect=_send_with_rate_limit_to_pane)
    manager.capture_pane = AsyncMock(return_value="mock output")
    manager.capture_pane_by_index = AsyncMock(return_value="mock output")
    manager.capture_pane_by_position = AsyncMock(return_value="mock output")
    manager.get_pane_current_command = AsyncMock(return_value=None)
    manager.set_pane_title = AsyncMock(return_value=True)
    manager.add_extra_worker_window = AsyncMock(return_value=True)
    manager.open_session_in_terminal = AsyncMock(return_value=True)
    manager._run = AsyncMock(return_value=(0, "", ""))
    manager._run_exec = AsyncMock(return_value=(0, "", ""))
    manager._get_window_name = MagicMock(return_value=settings.window_name_main)
    yield manager


@pytest.fixture
def ipc_manager(temp_dir):
    """IPCManagerインスタンスを作成する。"""
    ipc_dir = temp_dir / "ipc"
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
    import subprocess
    subprocess.run(
        ["git", "init"], cwd=str(repo_path), capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(repo_path), capture_output=True, check=True,
    )
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
    return HealthcheckManager(tmux_manager, sample_agents, healthcheck_interval_seconds=60)


@pytest.fixture
def worktree_manager(git_repo):
    """WorktreeManagerインスタンスを作成する。"""
    return WorktreeManager(str(git_repo))


@pytest.fixture
def agent_manager(tmux_manager, worktree_manager):
    """AgentManagerインスタンスを作成する。"""
    return AgentManager(tmux_manager, worktree_manager)


@pytest.fixture
def memory_manager(temp_dir):
    """MemoryManagerインスタンスを作成する。"""
    memory_dir = temp_dir / ".memory"
    manager = MemoryManager(str(memory_dir))
    yield manager


@pytest.fixture
def persona_manager():
    """PersonaManagerインスタンスを作成する。"""
    return PersonaManager()


@pytest.fixture
def app_ctx(
    settings,
    tmux_manager,
    ai_cli_manager,
    sample_agents,
    temp_dir,
):
    """テスト用のAppContextを作成する。"""
    # IPC マネージャー
    ipc_dir = temp_dir / "ipc"
    ipc = IPCManager(str(ipc_dir))
    ipc.initialize()

    # ダッシュボードマネージャー
    dashboard_dir = temp_dir / ".dashboard"
    dashboard = DashboardManager(
        workspace_id="test-workspace",
        workspace_path=str(temp_dir),
        dashboard_dir=str(dashboard_dir),
    )
    dashboard.initialize()

    # メモリマネージャー
    memory_dir = temp_dir / ".memory"
    memory = MemoryManager(str(memory_dir))

    # ペルソナマネージャー
    persona = PersonaManager()

    # スケジューラーマネージャー
    scheduler = SchedulerManager(dashboard, sample_agents)

    ctx = AppContext(
        settings=settings,
        tmux=tmux_manager,
        ai_cli=ai_cli_manager,
        agents=sample_agents.copy(),
        ipc_manager=ipc,
        dashboard_manager=dashboard,
        scheduler_manager=scheduler,
        memory_manager=memory,
        persona_manager=persona,
        workspace_id="test-workspace",
        project_root=str(temp_dir),
        session_id="test-session",
    )
    yield ctx
    # クリーンアップ
    ipc.cleanup()
    dashboard.cleanup()


@pytest.fixture
def mock_mcp_context(app_ctx):
    """MCPツールのContextをモックする。"""
    mock_ctx = MagicMock()
    mock_ctx.request_context.lifespan_context = app_ctx
    return mock_ctx


@pytest.fixture
def mock_terminal_executor():
    """TerminalExecutorのモック。"""
    mock = MagicMock()
    mock.name = "MockTerminal"
    mock.is_available = AsyncMock(return_value=True)
    mock.execute_script = AsyncMock(return_value=(True, "成功"))
    return mock


@pytest.fixture
def mock_tmux_manager():
    """TmuxManagerのモック（tmux 不要なテスト用）。"""
    mock = MagicMock()
    mock.create_main_session = AsyncMock(return_value=True)
    mock.send_keys = AsyncMock(return_value=True)
    mock.send_keys_to_pane = AsyncMock(return_value=True)

    async def _send_with_rate_limit_to_pane(
        session_name,
        window_index,
        pane_index,
        command,
        **_kwargs,
    ):
        return await mock.send_keys_to_pane(
            session_name,
            window_index,
            pane_index,
            command,
        )

    mock.send_with_rate_limit_to_pane = AsyncMock(side_effect=_send_with_rate_limit_to_pane)
    mock.capture_pane = AsyncMock(return_value="mock output")
    mock.capture_pane_by_position = AsyncMock(return_value="mock output")
    mock.session_exists = AsyncMock(return_value=True)
    mock.set_pane_title = AsyncMock(return_value=True)
    mock.add_extra_worker_window = AsyncMock(return_value=True)
    mock.cleanup_all_sessions = AsyncMock()
    mock._get_window_name = MagicMock(return_value="main")
    mock._run = AsyncMock(return_value="")
    return mock
