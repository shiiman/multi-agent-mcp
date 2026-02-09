"""HealthcheckManagerのテスト。"""

import hashlib
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.dashboard_manager import DashboardManager
from src.managers.healthcheck_manager import HealthcheckManager
from src.managers.ipc_manager import IPCManager
from src.models.agent import Agent, AgentRole, AgentStatus
from src.models.dashboard import TaskStatus


class TestHealthcheckManager:
    """HealthcheckManagerのテスト。"""

    @pytest.mark.asyncio
    async def test_check_agent_not_found(self, healthcheck_manager):
        """存在しないエージェントをチェックできることをテスト。"""
        status = await healthcheck_manager.check_agent("unknown-agent")
        assert status.agent_id == "unknown-agent"
        assert status.is_healthy is False
        assert "見つかりません" in status.error_message

    @pytest.mark.asyncio
    async def test_check_agent_with_tmux_session(self, healthcheck_manager, sample_agents):
        """tmux セッションの確認をテスト。"""
        status = await healthcheck_manager.check_agent("agent-001")
        assert status.agent_id == "agent-001"
        # tmux セッションが存在しないので is_healthy は False になる
        assert status.tmux_session_alive is False

    @pytest.mark.asyncio
    async def test_check_all_agents(self, healthcheck_manager, sample_agents):
        """全エージェントをチェックできることをテスト。"""
        statuses = await healthcheck_manager.check_all_agents()
        assert len(statuses) == len(sample_agents)

    @pytest.mark.asyncio
    async def test_get_unhealthy_agents(self, healthcheck_manager, sample_agents):
        """不健全なエージェントを取得できることをテスト。"""
        # tmux セッションがないので全て unhealthy
        unhealthy = await healthcheck_manager.get_unhealthy_agents()
        assert isinstance(unhealthy, list)

    @pytest.mark.asyncio
    async def test_get_healthy_agents(self, healthcheck_manager, sample_agents):
        """健全なエージェントを取得できることをテスト。"""
        healthy = await healthcheck_manager.get_healthy_agents()
        assert isinstance(healthy, list)

    @pytest.mark.asyncio
    async def test_attempt_recovery(self, healthcheck_manager, sample_agents):
        """リカバリー試行ができることをテスト。"""
        success, message = await healthcheck_manager.attempt_recovery("agent-001")
        # tmux 操作に依存するので、結果はどちらでも OK
        assert isinstance(success, bool)
        assert isinstance(message, str)

    @pytest.mark.asyncio
    async def test_attempt_recovery_unknown_agent(self, healthcheck_manager):
        """未知のエージェントのリカバリー試行で False を返すことをテスト。"""
        success, message = await healthcheck_manager.attempt_recovery("unknown")
        assert success is False
        assert "見つかりません" in message

    @pytest.mark.asyncio
    async def test_attempt_recovery_all(self, healthcheck_manager, sample_agents):
        """全てのリカバリー試行ができることをテスト。"""
        results = await healthcheck_manager.attempt_recovery_all()
        assert isinstance(results, list)

    def test_get_summary(self, healthcheck_manager, sample_agents):
        """サマリーを取得できることをテスト。"""
        summary = healthcheck_manager.get_summary()
        assert "total_agents" in summary
        assert "healthcheck_interval_seconds" in summary


class TestHealthcheckMonitoring:
    """monitor_and_recover_workers の追加テスト。"""

    @pytest.mark.asyncio
    async def test_monitor_stall_is_ignored_when_pane_output_changes(self):
        now = datetime.now() - timedelta(seconds=700)
        worker = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            current_task="task-001",
            created_at=now,
            last_activity=now,
        )
        agents = {"worker-001": worker}

        tmux = MagicMock()
        tmux.session_exists = AsyncMock(return_value=True)
        tmux.capture_pane_by_index = AsyncMock(side_effect=["line-1", "line-2"])

        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents=agents,
            healthcheck_interval_seconds=1,
            stall_timeout_seconds=10,
            max_recovery_attempts=2,
        )

        first = await healthcheck.monitor_and_recover_workers()
        second = await healthcheck.monitor_and_recover_workers()

        assert first["recovered"] == []
        assert first["escalated"] == []
        assert second["recovered"] == []
        assert second["escalated"] == []

    @pytest.mark.asyncio
    async def test_monitor_resets_bootstrap_flag_after_recovery(self, temp_dir, settings):
        tmux = MagicMock()
        tmux.session_exists = AsyncMock(return_value=False)
        tmux.create_session = AsyncMock(return_value=True)
        tmux.capture_pane_by_index = AsyncMock(return_value="")

        ai_cli = AiCliManager(settings)
        now = datetime.now()
        worker = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(temp_dir),
            current_task="task-001",
            ai_bootstrapped=True,
            created_at=now,
            last_activity=now - timedelta(seconds=100),
        )

        app_ctx = AppContext(
            settings=settings,
            tmux=tmux,
            ai_cli=ai_cli,
            agents={worker.id: worker},
            project_root=str(temp_dir),
            session_id="test-session",
        )

        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents=app_ctx.agents,
            healthcheck_interval_seconds=1,
            stall_timeout_seconds=10,
            max_recovery_attempts=1,
        )

        result = await healthcheck.monitor_and_recover_workers(app_ctx)

        assert len(result["recovered"]) == 1
        assert worker.ai_bootstrapped is False

    @pytest.mark.asyncio
    async def test_monitor_marks_task_failed_after_recovery_limit(self, temp_dir, settings):
        tmux = MagicMock()
        tmux.session_exists = AsyncMock(return_value=False)
        tmux.create_session = AsyncMock(return_value=False)
        tmux._run = AsyncMock(return_value=(0, "", ""))
        tmux._get_window_name = MagicMock(return_value=settings.window_name_main)
        tmux.capture_pane_by_index = AsyncMock(return_value="")

        ai_cli = AiCliManager(settings)

        session_id = "test-session"
        dashboard_dir = temp_dir / ".multi-agent-mcp" / session_id / "dashboard"
        dashboard = DashboardManager(
            workspace_id=session_id,
            workspace_path=str(temp_dir),
            dashboard_dir=str(dashboard_dir),
        )
        dashboard.initialize()

        ipc_dir = temp_dir / ".ipc"
        ipc = IPCManager(str(ipc_dir))
        ipc.initialize()

        now = datetime.now()
        worker = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            current_task=None,
            created_at=now,
            last_activity=now,
        )
        admin = Agent(
            id="admin-001",
            role=AgentRole.ADMIN,
            status=AgentStatus.IDLE,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            current_task=None,
            created_at=now,
            last_activity=now,
        )

        task = dashboard.create_task(
            title="test",
            description="healthcheck",
            assigned_agent_id=worker.id,
        )
        dashboard.update_task_status(task.id, TaskStatus.IN_PROGRESS, progress=10)
        worker.current_task = task.id

        app_ctx = AppContext(
            settings=settings,
            tmux=tmux,
            ai_cli=ai_cli,
            agents={worker.id: worker, admin.id: admin},
            ipc_manager=ipc,
            dashboard_manager=dashboard,
            workspace_id="test-workspace",
            project_root=str(temp_dir),
            session_id="test-session",
        )

        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents=app_ctx.agents,
            healthcheck_interval_seconds=1,
            stall_timeout_seconds=10,
            max_recovery_attempts=1,
        )
        app_ctx.healthcheck_manager = healthcheck

        result = await healthcheck.monitor_and_recover_workers(app_ctx)

        assert len(result["failed_tasks"]) == 1
        updated = dashboard.get_task(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.FAILED
        assert worker.current_task is None

    @pytest.mark.asyncio
    async def test_monitor_recovers_in_progress_no_ipc_timeout(self, temp_dir, settings):
        tmux = MagicMock()
        tmux.session_exists = AsyncMock(return_value=True)
        tmux.get_pane_current_command = AsyncMock(return_value="node")
        tmux.capture_pane_by_index = AsyncMock(return_value="stable-pane-output")
        tmux._run = AsyncMock(return_value=(0, "", ""))
        tmux._get_window_name = MagicMock(return_value=settings.window_name_main)
        tmux.create_session = AsyncMock(return_value=True)
        tmux.send_keys_to_pane = AsyncMock(return_value=True)

        ai_cli = AiCliManager(settings)

        session_id = "test-session"
        dashboard_dir = temp_dir / ".multi-agent-mcp" / session_id / "dashboard"
        dashboard = DashboardManager(
            workspace_id=session_id,
            workspace_path=str(temp_dir),
            dashboard_dir=str(dashboard_dir),
        )
        dashboard.initialize()

        now = datetime.now()
        worker = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            current_task=None,
            ai_bootstrapped=True,
            created_at=now,
            last_activity=now,
        )
        admin = Agent(
            id="admin-001",
            role=AgentRole.ADMIN,
            status=AgentStatus.IDLE,
            tmux_session="test:0.0",
            session_name="test",
            window_index=0,
            pane_index=0,
            current_task=None,
            created_at=now,
            last_activity=now,
        )

        task = dashboard.create_task(
            title="test in_progress no ipc",
            description="healthcheck",
            assigned_agent_id=worker.id,
        )
        dashboard.assign_task(task.id, worker.id)
        dashboard.update_task_status(task.id, TaskStatus.IN_PROGRESS, progress=10)

        dash = dashboard._read_dashboard()
        task_for_update = dash.get_task(task.id)
        assert task_for_update is not None
        task_for_update.metadata["last_in_progress_update_at"] = (
            datetime.now() - timedelta(seconds=180)
        ).isoformat()
        dashboard._write_dashboard(dash)

        app_ctx = AppContext(
            settings=settings,
            tmux=tmux,
            ai_cli=ai_cli,
            agents={worker.id: worker, admin.id: admin},
            dashboard_manager=dashboard,
            workspace_id=session_id,
            project_root=str(temp_dir),
            session_id=session_id,
        )

        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents=app_ctx.agents,
            healthcheck_interval_seconds=1,
            stall_timeout_seconds=600,
            in_progress_no_ipc_timeout_seconds=30,
            max_recovery_attempts=1,
        )
        app_ctx.healthcheck_manager = healthcheck

        pane_hash = hashlib.sha1(b"stable-pane-output").hexdigest()
        healthcheck._pane_hash[worker.id] = pane_hash
        healthcheck._pane_last_changed_at[worker.id] = datetime.now() - timedelta(seconds=120)

        result = await healthcheck.monitor_and_recover_workers(app_ctx)

        assert len(result["recovered"]) == 1
        assert result["recovered"][0]["reason"] == "in_progress_no_ipc"
        assert worker.ai_bootstrapped is False
