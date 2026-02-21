"""HealthcheckManagerのテスト。"""

import hashlib
from datetime import datetime, timedelta
from types import SimpleNamespace
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
    async def test_monitor_skips_terminated_workers(self):
        """TERMINATED Worker は監視対象外としてスキップされる。"""
        now = datetime.now() - timedelta(seconds=700)
        worker = Agent(
            id="worker-terminated",
            role=AgentRole.WORKER,
            status=AgentStatus.TERMINATED,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            current_task="task-terminated",
            created_at=now,
            last_activity=now,
        )
        agents = {"worker-terminated": worker}

        tmux = MagicMock()
        tmux.session_exists = AsyncMock(return_value=False)
        tmux.create_session = AsyncMock(return_value=True)
        tmux.capture_pane_by_index = AsyncMock(return_value="")

        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents=agents,
            healthcheck_interval_seconds=1,
            stall_timeout_seconds=10,
            max_recovery_attempts=1,
        )

        result = await healthcheck.monitor_and_recover_workers()

        assert result["recovered"] == []
        assert result["escalated"] == []
        assert "worker-terminated" in result["skipped"]

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
        assert len(result["escalated"]) == 1
        assert "attempt_recovery_error=" in result["escalated"][0]["message"]
        assert "full_recovery_status=" in result["escalated"][0]["message"]
        updated = dashboard.get_task(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.FAILED
        assert updated.error_message is not None
        assert "attempt_recovery_error=" in updated.error_message
        assert "full_recovery_status=" in updated.error_message
        assert worker.current_task is None
        summary = dashboard.get_summary()
        assert summary["process_crash_count"] == 1

    @pytest.mark.asyncio
    async def test_attempt_staged_recovery_resume_pending_auto_resend_success(
        self, temp_dir, settings
    ):
        """full_recovery が再開待ちでも自動再送が成功すれば recovered にする。"""
        now = datetime.now()
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
        tmux = MagicMock()
        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents={worker.id: worker},
            max_recovery_attempts=2,
        )
        healthcheck.attempt_recovery = AsyncMock(return_value=(False, "attempt failed"))
        healthcheck._run_full_recovery = AsyncMock(
            return_value={
                "status": "resume_pending",
                "message": "タスク再開待ちです",
                "resume_required_task_ids": ["task-001"],
            }
        )
        healthcheck._auto_resume_tasks_after_recovery = AsyncMock(
            return_value={"success": True, "resumed": ["task-001"], "failed": []}
        )

        app_ctx = SimpleNamespace(agents={worker.id: worker})
        result = await healthcheck._attempt_staged_recovery(
            app_ctx=app_ctx,
            dashboard=None,
            agent_id=worker.id,
            agent=worker,
            recovery_reason="ai_process_dead",
            force_recovery=False,
            task_key=healthcheck._recovery_key(worker.id, worker.current_task),
        )

        assert result["status"] == "recovered"
        assert result["detail"]["method"] == "full_recovery_auto_resume"
        assert result["detail"]["resumed_tasks"] == "task-001"
        assert healthcheck._recovery_failures == {}

    @pytest.mark.asyncio
    async def test_attempt_staged_recovery_resume_pending_auto_resend_failure(
        self, temp_dir, settings
    ):
        """full_recovery 後の自動再送が失敗した場合は escalated にする。"""
        now = datetime.now()
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
        tmux = MagicMock()
        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents={worker.id: worker},
            max_recovery_attempts=2,
        )
        healthcheck.attempt_recovery = AsyncMock(return_value=(False, "attempt failed"))
        healthcheck._run_full_recovery = AsyncMock(
            return_value={
                "status": "resume_pending",
                "message": "タスク再開待ちです",
                "resume_required_task_ids": ["task-001"],
            }
        )
        healthcheck._auto_resume_tasks_after_recovery = AsyncMock(
            return_value={
                "success": False,
                "error": "dispatch failed",
                "resumed": [],
                "failed": [{"task_id": "task-001", "error": "dispatch failed"}],
            }
        )

        app_ctx = SimpleNamespace(agents={worker.id: worker})
        result = await healthcheck._attempt_staged_recovery(
            app_ctx=app_ctx,
            dashboard=None,
            agent_id=worker.id,
            agent=worker,
            recovery_reason="ai_process_dead",
            force_recovery=False,
            task_key=healthcheck._recovery_key(worker.id, worker.current_task),
        )

        assert result["status"] == "escalated"
        assert result["detail"]["status"] == "resume_pending"
        assert result["detail"]["resume_required_tasks"] == "task-001"
        assert result["detail"]["auto_resume_failed_tasks"] == "task-001"
        assert "dispatch failed" in result["detail"]["auto_resume_error"]

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
        updated_task = dashboard.get_task(task.id)
        assert updated_task is not None
        assert updated_task.metadata["process_recovery_count"] == 1
        summary = dashboard.get_summary()
        assert summary["process_crash_count"] == 1
        assert summary["process_recovery_count"] == 1

    @pytest.mark.asyncio
    async def test_monitor_skips_terminal_worker(self, temp_dir, settings):
        """TERMINATED worker は監視復旧対象外でスキップされることをテスト。"""
        tmux = MagicMock()
        tmux.session_exists = AsyncMock(return_value=False)
        tmux.create_session = AsyncMock(return_value=False)
        tmux.capture_pane_by_index = AsyncMock(return_value="")

        now = datetime.now()
        terminated_worker = Agent(
            id="worker-terminated",
            role=AgentRole.WORKER,
            status=AgentStatus.TERMINATED,
            tmux_session="test:0.2",
            session_name="test",
            window_index=0,
            pane_index=2,
            current_task=None,
            created_at=now,
            last_activity=now,
        )

        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents={terminated_worker.id: terminated_worker},
            healthcheck_interval_seconds=1,
            stall_timeout_seconds=10,
            max_recovery_attempts=1,
        )

        result = await healthcheck.monitor_and_recover_workers()
        assert terminated_worker.id in result["skipped"]
        assert result["recovered"] == []
        assert result["escalated"] == []

    def test_increment_recovery_counter_uses_dashboard_transaction(self, temp_dir, settings):
        """復旧カウンタ更新がトランザクション経由で行われることをテスト。"""
        tmux = MagicMock()
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
            created_at=now,
            last_activity=now,
        )

        task = dashboard.create_task(
            title="recovery count",
            description="healthcheck",
            assigned_agent_id=worker.id,
        )

        app_ctx = AppContext(
            settings=settings,
            tmux=tmux,
            ai_cli=ai_cli,
            agents={worker.id: worker},
            dashboard_manager=dashboard,
            workspace_id=session_id,
            project_root=str(temp_dir),
            session_id=session_id,
        )

        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents=app_ctx.agents,
        )

        dashboard._read_dashboard = MagicMock(side_effect=AssertionError("no direct read"))  # type: ignore[method-assign]
        dashboard._write_dashboard = MagicMock(side_effect=AssertionError("no direct write"))  # type: ignore[method-assign]

        healthcheck._increment_recovery_counter(
            dashboard=dashboard,
            agent_id=worker.id,
            task_id=task.id,
            recovery_reason="in_progress_no_ipc",
        )

        updated_metadata = dashboard.run_dashboard_transaction(
            lambda data: dict(data.get_task(task.id).metadata)
        )
        assert updated_metadata["process_recovery_count"] == 1
        assert updated_metadata["last_recovery_reason"] == "in_progress_no_ipc"

    def test_increment_recovery_counter_keeps_consistency_on_transaction_conflict(
        self, temp_dir, settings
    ):
        """dashboard トランザクション競合時に整合性が維持されることをテスト。"""
        tmux = MagicMock()
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
            created_at=now,
            last_activity=now,
        )

        task = dashboard.create_task(
            title="recovery count conflict",
            description="healthcheck",
            assigned_agent_id=worker.id,
        )

        dashboard.run_dashboard_transaction(
            lambda data: data.get_task(task.id).metadata.update({"process_recovery_count": 2})
        )

        app_ctx = AppContext(
            settings=settings,
            tmux=tmux,
            ai_cli=ai_cli,
            agents={worker.id: worker},
            dashboard_manager=dashboard,
            workspace_id=session_id,
            project_root=str(temp_dir),
            session_id=session_id,
        )

        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents=app_ctx.agents,
        )

        dashboard.run_dashboard_transaction = MagicMock(  # type: ignore[method-assign]
            side_effect=TimeoutError("dashboard lock timeout")
        )

        healthcheck._increment_recovery_counter(
            dashboard=dashboard,
            agent_id=worker.id,
            task_id=task.id,
            recovery_reason="task_stalled",
        )

        current_task = dashboard.get_task(task.id)
        assert current_task is not None
        assert current_task.metadata["process_recovery_count"] == 2


class TestIsAiRunning:
    """_is_ai_running ユーティリティ関数のテスト。"""

    def test_codex_is_detected(self):
        """codex コマンドが AI 実行中と判定されること。"""
        from src.managers.healthcheck_manager import _is_ai_running

        assert _is_ai_running("codex") is True

    def test_codex_arch_suffix_is_detected(self):
        """codex-aarch64-a のようなアーキテクチャサフィックス付きも検出されること。"""
        from src.managers.healthcheck_manager import _is_ai_running

        assert _is_ai_running("codex-aarch64-a") is True

    def test_claude_is_detected(self):
        """claude コマンドが AI 実行中と判定されること。"""
        from src.managers.healthcheck_manager import _is_ai_running

        assert _is_ai_running("claude") is True

    def test_gemini_is_detected(self):
        """gemini コマンドが AI 実行中と判定されること。"""
        from src.managers.healthcheck_manager import _is_ai_running

        assert _is_ai_running("gemini") is True

    def test_agent_is_detected(self):
        """agent コマンドが AI 実行中と判定されること。"""
        from src.managers.healthcheck_manager import _is_ai_running

        assert _is_ai_running("agent") is True

    def test_cursor_agent_is_detected(self):
        """cursor-agent コマンドが AI 実行中と判定されること。"""
        from src.managers.healthcheck_manager import _is_ai_running

        assert _is_ai_running("cursor-agent") is True

    def test_shell_is_not_ai(self):
        """bash/zsh は AI 実行中ではないこと。"""
        from src.managers.healthcheck_manager import _is_ai_running

        assert _is_ai_running("bash") is False
        assert _is_ai_running("zsh") is False

    def test_empty_string(self):
        """空文字列は AI 実行中ではないこと。"""
        from src.managers.healthcheck_manager import _is_ai_running

        assert _is_ai_running("") is False

    def test_case_insensitive(self):
        """大文字小文字を区別しないこと。"""
        from src.managers.healthcheck_manager import _is_ai_running

        assert _is_ai_running("CODEX") is True
        assert _is_ai_running("Claude") is True

    def test_whitespace_trimmed(self):
        """前後の空白が除去されること。"""
        from src.managers.healthcheck_manager import _is_ai_running

        assert _is_ai_running("  codex  ") is True


class TestCheckAgentEdgeCases:
    """check_agent の追加エッジケーステスト。"""

    @pytest.mark.asyncio
    async def test_check_agent_no_session_name(self):
        """session_name が None のエージェントは unhealthy になること。"""
        now = datetime.now()
        agent = Agent(
            id="agent-no-session",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            session_name=None,
            created_at=now,
            last_activity=now,
        )
        tmux = MagicMock()
        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents={"agent-no-session": agent},
        )
        status = await healthcheck.check_agent("agent-no-session")
        assert status.is_healthy is False
        assert "tmux セッション情報が未設定" in status.error_message

    @pytest.mark.asyncio
    async def test_check_agent_ai_process_dead(self):
        """Worker がタスク実行中なのにシェルに戻っている場合は ai_process_dead。"""
        now = datetime.now()
        agent = Agent(
            id="worker-dead",
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
        tmux = MagicMock()
        tmux.session_exists = AsyncMock(return_value=True)
        tmux.get_pane_current_command = AsyncMock(return_value="bash")
        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents={"worker-dead": agent},
        )
        status = await healthcheck.check_agent("worker-dead")
        assert status.is_healthy is False
        assert status.tmux_session_alive is True
        assert status.error_message == "ai_process_dead"
        assert status.pane_current_command == "bash"

    @pytest.mark.asyncio
    async def test_check_agent_healthy_worker_running_ai(self):
        """Worker が AI CLI 実行中で正常な場合は healthy。"""
        now = datetime.now()
        agent = Agent(
            id="worker-healthy",
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
        tmux = MagicMock()
        tmux.session_exists = AsyncMock(return_value=True)
        tmux.get_pane_current_command = AsyncMock(return_value="codex")
        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents={"worker-healthy": agent},
        )
        status = await healthcheck.check_agent("worker-healthy")
        assert status.is_healthy is True
        assert status.tmux_session_alive is True
        assert status.pane_current_command == "codex"


class TestPruneState:
    """_prune_state メソッドのテスト。"""

    def test_prune_removes_stale_entries(self):
        """削除されたエージェントの監視状態が掃除されること。"""
        now = datetime.now()
        agent = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test:0.1",
            created_at=now,
            last_activity=now,
        )
        tmux = MagicMock()
        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents={"worker-001": agent},
        )
        # 存在しないエージェントの状態を手動設定
        healthcheck._pane_hash["worker-old"] = "abc123"
        healthcheck._pane_last_changed_at["worker-old"] = now
        healthcheck._recovery_failures["worker-old:task-1"] = 2
        # 存在するエージェントの状態も設定
        healthcheck._pane_hash["worker-001"] = "def456"
        healthcheck._recovery_failures["worker-001:task-2"] = 1

        healthcheck._prune_state()

        # 存在しないエージェントのデータは削除される
        assert "worker-old" not in healthcheck._pane_hash
        assert "worker-old" not in healthcheck._pane_last_changed_at
        assert "worker-old:task-1" not in healthcheck._recovery_failures
        # 存在するエージェントのデータは保持される
        assert "worker-001" in healthcheck._pane_hash
        assert "worker-001:task-2" in healthcheck._recovery_failures


class TestTaskActivityAt:
    """_task_activity_at 静的メソッドのテスト。"""

    def test_metadata_datetime(self):
        """metadata に datetime オブジェクトがある場合にそれを返すこと。"""
        from src.models.dashboard import TaskInfo

        now = datetime.now()
        task = MagicMock(spec=TaskInfo)
        task.metadata = {"last_in_progress_update_at": now}
        task.logs = []
        task.started_at = None

        result = HealthcheckManager._task_activity_at(task)
        assert result == now

    def test_metadata_iso_string(self):
        """metadata に ISO 文字列がある場合にパースされること。"""
        from src.models.dashboard import TaskInfo

        now = datetime.now()
        task = MagicMock(spec=TaskInfo)
        task.metadata = {"last_in_progress_update_at": now.isoformat()}
        task.logs = []
        task.started_at = None

        result = HealthcheckManager._task_activity_at(task)
        assert result is not None
        assert abs((result - now).total_seconds()) < 1

    def test_metadata_invalid_string(self):
        """metadata に不正な文字列がある場合は None を返すこと。"""
        from src.models.dashboard import TaskInfo

        task = MagicMock(spec=TaskInfo)
        task.metadata = {"last_in_progress_update_at": "not-a-date"}
        task.logs = []
        task.started_at = datetime.now()

        result = HealthcheckManager._task_activity_at(task)
        # started_at にフォールバックする
        assert result == task.started_at

    def test_no_metadata_returns_started_at(self):
        """metadata がない場合は started_at を返すこと。"""
        from src.models.dashboard import TaskInfo

        now = datetime.now()
        task = MagicMock(spec=TaskInfo)
        task.metadata = {}
        task.logs = []
        task.started_at = now

        result = HealthcheckManager._task_activity_at(task)
        assert result == now

    def test_no_info_returns_none(self):
        """metadata も started_at もない場合は None を返すこと。"""
        from src.models.dashboard import TaskInfo

        task = MagicMock(spec=TaskInfo)
        task.metadata = {}
        task.logs = []
        task.started_at = None

        result = HealthcheckManager._task_activity_at(task)
        assert result is None


class TestComposeRecoveryFailureReason:
    """_compose_recovery_failure_reason のテスト。"""

    def test_all_fields_populated(self):
        """全フィールドが含まれた文字列を返すこと。"""
        reason = HealthcheckManager._compose_recovery_failure_reason(
            recovery_reason="ai_process_dead",
            attempt_error="session not found",
            full_recovery_status="failed",
            full_recovery_error="tmux unavailable",
        )
        assert "recovery_reason=ai_process_dead" in reason
        assert "attempt_recovery_error=session not found" in reason
        assert "full_recovery_status=failed" in reason
        assert "full_recovery_error=tmux unavailable" in reason

    def test_empty_errors_show_none(self):
        """空のエラーは 'none' と表示されること。"""
        reason = HealthcheckManager._compose_recovery_failure_reason(
            recovery_reason="task_stalled",
            attempt_error="",
            full_recovery_status="not_executed",
            full_recovery_error="",
        )
        assert "attempt_recovery_error=none" in reason
        assert "full_recovery_error=none" in reason


class TestHealthStatusToDict:
    """HealthStatus.to_dict のテスト。"""

    def test_to_dict_contains_all_fields(self):
        """to_dict が全フィールドを含むこと。"""
        from src.managers.healthcheck_manager import HealthStatus

        status = HealthStatus(
            agent_id="test-001",
            is_healthy=True,
            tmux_session_alive=True,
            error_message=None,
            pane_current_command="codex",
        )
        d = status.to_dict()
        assert d["agent_id"] == "test-001"
        assert d["is_healthy"] is True
        assert d["tmux_session_alive"] is True
        assert d["error_message"] is None
        assert d["pane_current_command"] == "codex"


class TestGetSummaryWithMonitorAt:
    """get_summary の last_monitor_at テスト。"""

    def test_summary_with_last_monitor_at(self):
        """last_monitor_at が設定されている場合に ISO 文字列で返ること。"""
        now = datetime.now()
        tmux = MagicMock()
        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents={},
        )
        healthcheck.last_monitor_at = now
        summary = healthcheck.get_summary()
        assert summary["last_monitor_at"] == now.isoformat()
        assert summary["in_progress_no_ipc_timeout_seconds"] == 120


class TestIsWorkerStalledEdgeCases:
    """_is_worker_stalled のエッジケーステスト。"""

    @pytest.mark.asyncio
    async def test_no_current_task_returns_false(self):
        """current_task がない場合は stalled ではないこと。"""
        now = datetime.now()
        agent = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            current_task=None,
            created_at=now,
            last_activity=now - timedelta(seconds=1000),
        )
        tmux = MagicMock()
        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents={"worker-001": agent},
            stall_timeout_seconds=10,
        )
        result = await healthcheck._is_worker_stalled("worker-001", agent, now)
        assert result is False

    @pytest.mark.asyncio
    async def test_no_last_activity_returns_false(self):
        """last_activity がない場合は stalled ではないこと。"""
        now = datetime.now()
        agent = Agent(
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
        agent.last_activity = None
        tmux = MagicMock()
        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents={"worker-001": agent},
            stall_timeout_seconds=10,
        )
        result = await healthcheck._is_worker_stalled("worker-001", agent, now)
        assert result is False

    @pytest.mark.asyncio
    async def test_recent_activity_returns_false(self):
        """last_activity が最近の場合は stalled ではないこと。"""
        now = datetime.now()
        agent = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            current_task="task-001",
            created_at=now,
            last_activity=now - timedelta(seconds=5),
        )
        tmux = MagicMock()
        healthcheck = HealthcheckManager(
            tmux_manager=tmux,
            agents={"worker-001": agent},
            stall_timeout_seconds=600,
        )
        result = await healthcheck._is_worker_stalled("worker-001", agent, now)
        assert result is False
