"""AgentManagerのテスト。"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.settings import ModelProfile
from src.managers.agent_manager import AgentManager
from src.managers.tmux_manager import (
    MAIN_SESSION,
    MAIN_WINDOW_PANE_ADMIN,
    MAIN_WINDOW_WORKER_PANES,
)
from src.models.agent import Agent, AgentRole, AgentStatus


class TestAgentManagerBasicCRUD:
    """AgentManager の基本CRUD操作のテスト。"""

    def test_get_agent_existing(self, sample_agents):
        """存在するエージェントを取得できることをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        agent = manager.get_agent("agent-001")
        assert agent is not None
        assert agent.id == "agent-001"
        assert agent.role == AgentRole.OWNER

    def test_get_agent_nonexistent(self, sample_agents):
        """存在しないエージェントの取得でNoneが返ることをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        agent = manager.get_agent("nonexistent-agent")
        assert agent is None

    def test_get_agents_by_role_worker(self, sample_agents):
        """ロール別のエージェント取得をテスト（Worker）。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        workers = manager.get_agents_by_role(AgentRole.WORKER)
        assert len(workers) == 2
        for worker in workers:
            assert worker.role == AgentRole.WORKER

    def test_get_agents_by_role_owner(self, sample_agents):
        """ロール別のエージェント取得をテスト（Owner）。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        owners = manager.get_agents_by_role(AgentRole.OWNER)
        assert len(owners) == 1
        assert owners[0].id == "agent-001"

    def test_get_idle_workers(self, sample_agents):
        """待機中のWorkerエージェント取得をテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        idle_workers = manager.get_idle_workers()
        # sample_agents には IDLE の Worker が 1 つある（agent-002）
        assert len(idle_workers) == 1
        assert idle_workers[0].id == "agent-002"
        assert idle_workers[0].status == AgentStatus.IDLE

    def test_get_busy_workers(self, sample_agents):
        """作業中のWorkerエージェント取得をテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        busy_workers = manager.get_busy_workers()
        # sample_agents には BUSY の Worker が 1 つある（agent-003）
        assert len(busy_workers) == 1
        assert busy_workers[0].id == "agent-003"
        assert busy_workers[0].status == AgentStatus.BUSY


class TestWorktreeAssignment:
    """Worktree割り当て機能のテスト。"""

    @pytest.mark.asyncio
    async def test_assign_worktree_success(self, sample_agents):
        """worktree割り当てが成功することをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        success, message = await manager.assign_worktree(
            agent_id="agent-002",
            worktree_path="/tmp/worktree/feature-1",
            branch="feature-1",
        )

        assert success is True
        assert "割り当てました" in message
        assert "agent-002" in manager.assignments
        assignment = manager.assignments["agent-002"]
        assert assignment.worktree_path == "/tmp/worktree/feature-1"
        assert assignment.branch == "feature-1"

    @pytest.mark.asyncio
    async def test_assign_worktree_agent_not_found(self, sample_agents):
        """存在しないエージェントへの割り当てが失敗することをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        success, message = await manager.assign_worktree(
            agent_id="nonexistent",
            worktree_path="/tmp/worktree/feature-1",
            branch="feature-1",
        )

        assert success is False
        assert "見つかりません" in message

    @pytest.mark.asyncio
    async def test_reassign_worktree(self, sample_agents):
        """worktreeの再割り当てが成功することをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        # 最初の割り当て
        await manager.assign_worktree(
            agent_id="agent-002",
            worktree_path="/tmp/worktree/feature-1",
            branch="feature-1",
        )

        # 再割り当て
        success, message = await manager.assign_worktree(
            agent_id="agent-002",
            worktree_path="/tmp/worktree/feature-2",
            branch="feature-2",
        )

        assert success is True
        assignment = manager.assignments["agent-002"]
        assert assignment.worktree_path == "/tmp/worktree/feature-2"
        assert assignment.branch == "feature-2"

    @pytest.mark.asyncio
    async def test_unassign_worktree_success(self, sample_agents):
        """worktree割り当て解除が成功することをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        # まず割り当て
        await manager.assign_worktree(
            agent_id="agent-002",
            worktree_path="/tmp/worktree/feature-1",
            branch="feature-1",
        )

        # 解除
        success, message = await manager.unassign_worktree("agent-002")

        assert success is True
        assert "解除しました" in message
        assert "agent-002" not in manager.assignments
        assert manager.agents["agent-002"].worktree_path is None

    @pytest.mark.asyncio
    async def test_unassign_worktree_not_assigned(self, sample_agents):
        """割り当てられていないworktreeの解除が失敗することをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        success, message = await manager.unassign_worktree("agent-002")

        assert success is False
        assert "割り当てられていません" in message

    def test_get_assignment(self, sample_agents):
        """worktree割り当て情報の取得をテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        # 割り当てがない場合
        assignment = manager.get_assignment("agent-002")
        assert assignment is None

    @pytest.mark.asyncio
    async def test_get_agent_by_worktree(self, sample_agents):
        """worktreeからエージェントを取得できることをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        # 割り当て
        await manager.assign_worktree(
            agent_id="agent-002",
            worktree_path="/tmp/worktree/feature-1",
            branch="feature-1",
        )

        agent = manager.get_agent_by_worktree("/tmp/worktree/feature-1")
        assert agent is not None
        assert agent.id == "agent-002"

    def test_get_agent_by_worktree_not_found(self, sample_agents):
        """存在しないworktreeでNoneが返ることをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        agent = manager.get_agent_by_worktree("/nonexistent/worktree")
        assert agent is None


class TestStatusUpdate:
    """ステータス更新のテスト。"""

    @pytest.mark.asyncio
    async def test_update_agent_status_to_busy(self, sample_agents):
        """ステータスをBUSYに更新できることをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        success, message = await manager.update_agent_status(
            agent_id="agent-002",
            status=AgentStatus.BUSY,
            current_task="テストタスク",
        )

        assert success is True
        assert "更新しました" in message
        assert manager.agents["agent-002"].status == AgentStatus.BUSY
        assert manager.agents["agent-002"].current_task == "テストタスク"

    @pytest.mark.asyncio
    async def test_update_agent_status_nonexistent(self, sample_agents):
        """存在しないエージェントの更新が失敗することをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        success, message = await manager.update_agent_status(
            agent_id="nonexistent",
            status=AgentStatus.BUSY,
        )

        assert success is False
        assert "見つかりません" in message


class TestSummary:
    """サマリー機能のテスト。"""

    def test_get_summary_empty(self):
        """空のエージェントリストでサマリーを取得できることをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)

        summary = manager.get_summary()

        assert summary["total_agents"] == 0
        assert summary["by_role"] == {}
        assert summary["by_status"] == {}
        assert summary["assigned_worktrees"] == 0

    def test_get_summary_with_agents(self, sample_agents):
        """エージェントがある場合のサマリーをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        summary = manager.get_summary()

        assert summary["total_agents"] == 3
        # AgentRole enum は use_enum_values=True により文字列
        assert AgentRole.OWNER in summary["by_role"] or "owner" in summary["by_role"]
        assert AgentRole.WORKER in summary["by_role"] or "worker" in summary["by_role"]


class TestGridLayout:
    """グリッドレイアウト関連のテスト。"""

    def test_get_pane_for_owner_returns_none(self):
        """Ownerはtmuxペインに配置されないことをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)

        result = manager.get_pane_for_role(AgentRole.OWNER)

        assert result is None

    def test_get_pane_for_admin(self):
        """Adminのペイン位置を取得できることをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)

        result = manager.get_pane_for_role(AgentRole.ADMIN)

        assert result is not None
        session_name, window_index, pane_index = result
        assert session_name == MAIN_SESSION
        assert window_index == 0
        assert pane_index == MAIN_WINDOW_PANE_ADMIN

    def test_get_pane_for_worker_main_window(self):
        """Worker 1-6のペイン位置をテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)

        # Worker 0 (最初のWorker)
        result = manager.get_pane_for_role(AgentRole.WORKER, worker_index=0)
        assert result is not None
        session_name, window_index, pane_index = result
        assert session_name == MAIN_SESSION
        assert window_index == 0
        assert pane_index == 1  # ペイン 1

        # Worker 5 (最後のメインウィンドウWorker)
        result = manager.get_pane_for_role(AgentRole.WORKER, worker_index=5)
        assert result is not None
        session_name, window_index, pane_index = result
        assert session_name == MAIN_SESSION
        assert window_index == 0
        assert pane_index == 6  # ペイン 6

    def test_get_pane_for_worker_extra_window(self):
        """Worker 7以降は追加ウィンドウに配置されることをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)

        # Worker 6 (最初の追加ウィンドウWorker)
        result = manager.get_pane_for_role(AgentRole.WORKER, worker_index=6)
        assert result is not None
        session_name, window_index, pane_index = result
        assert session_name == MAIN_SESSION
        assert window_index == 1  # 追加ウィンドウ 1
        assert pane_index == 0

    def test_is_pane_occupied(self, sample_agents):
        """ペインが使用中かどうかの確認をテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)

        # ペイン情報を持つエージェントを追加
        now = datetime.now()
        manager.agents["pane-agent"] = Agent(
            id="pane-agent",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test-session:0.1",
            session_name="test-session",
            window_index=0,
            pane_index=1,
            created_at=now,
            last_activity=now,
        )

        assert manager.is_pane_occupied("test-session", 0, 1) is True
        assert manager.is_pane_occupied("test-session", 0, 2) is False

    def test_get_all_pane_assignments(self):
        """全ペイン割り当て状況の取得をテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)

        now = datetime.now()
        manager.agents["agent-1"] = Agent(
            id="agent-1",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            created_at=now,
            last_activity=now,
        )
        manager.agents["agent-2"] = Agent(
            id="agent-2",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test:0.2",
            session_name="test",
            window_index=0,
            pane_index=2,
            created_at=now,
            last_activity=now,
        )

        assignments = manager.get_all_pane_assignments()

        assert len(assignments) == 2
        assert assignments[("test", 0, 1)] == "agent-1"
        assert assignments[("test", 0, 2)] == "agent-2"

    def test_get_next_worker_slot(self, settings):
        """次のWorkerスロットを取得できることをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)

        slot = manager.get_next_worker_slot(settings)

        assert slot is not None
        window_index, pane_index = slot
        assert window_index == 0
        assert pane_index == MAIN_WINDOW_WORKER_PANES[0]

    def test_get_next_worker_slot_full(self, settings):
        """Workerが上限に達した場合Noneが返ることをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)

        # プロファイル上限分のWorkerを追加
        now = datetime.now()
        for i in range(settings.get_active_profile_max_workers()):
            manager.agents[f"worker-{i}"] = Agent(
                id=f"worker-{i}",
                role=AgentRole.WORKER,
                status=AgentStatus.IDLE,
                tmux_session=f"test:0.{i + 2}",
                session_name="test",
                window_index=0,
                pane_index=i + 2,
                created_at=now,
                last_activity=now,
            )

        slot = manager.get_next_worker_slot(settings)

        assert slot is None

    def test_get_next_worker_slot_uses_active_profile_limit(self, settings):
        """active profile の max_workers が上限判定に使われることをテスト。"""
        settings.model_profile_active = ModelProfile.PERFORMANCE
        settings.model_profile_performance_max_workers = 2

        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        now = datetime.now()
        for i in range(2):
            manager.agents[f"worker-{i}"] = Agent(
                id=f"worker-{i}",
                role=AgentRole.WORKER,
                status=AgentStatus.IDLE,
                tmux_session=f"test:0.{i + 2}",
                session_name="test",
                window_index=0,
                pane_index=i + 2,
                created_at=now,
                last_activity=now,
            )

        slot = manager.get_next_worker_slot(settings)
        assert slot is None

    def test_get_next_worker_slot_finds_slot_beyond_11_workers(self, settings):
        """11稼働中でも12人目のスロットを追加ウィンドウから返す。"""
        settings.model_profile_active = ModelProfile.PERFORMANCE
        settings.model_profile_performance_max_workers = 16
        settings.workers_per_extra_window = 10

        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        now = datetime.now()

        # main window: panes 1..6
        for pane in range(1, 7):
            manager.agents[f"main-{pane}"] = Agent(
                id=f"main-{pane}",
                role=AgentRole.WORKER,
                status=AgentStatus.IDLE,
                tmux_session=f"test:0.{pane}",
                session_name="test",
                window_index=0,
                pane_index=pane,
                created_at=now,
                last_activity=now,
            )
        # extra window 1: panes 0..4
        for pane in range(0, 5):
            manager.agents[f"extra-{pane}"] = Agent(
                id=f"extra-{pane}",
                role=AgentRole.WORKER,
                status=AgentStatus.IDLE,
                tmux_session=f"test:1.{pane}",
                session_name="test",
                window_index=1,
                pane_index=pane,
                created_at=now,
                last_activity=now,
            )

        slot = manager.get_next_worker_slot(settings)
        assert slot == (1, 5)

    def test_count_workers(self, sample_agents):
        """Worker数のカウントをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        manager.agents = sample_agents.copy()

        count = manager.count_workers()

        assert count == 2  # sample_agents には Worker が 2 つ

    def test_get_next_worker_slot_excludes_terminated_from_capacity(self, settings):
        """TERMINATED Worker のみでも空きスロットを返すことをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        now = datetime.now()
        manager.agents["worker-term"] = Agent(
            id="worker-term",
            role=AgentRole.WORKER,
            status=AgentStatus.TERMINATED,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=MAIN_WINDOW_WORKER_PANES[0],
            created_at=now,
            last_activity=now,
        )

        slot = manager.get_next_worker_slot(settings)

        assert slot == (0, MAIN_WINDOW_WORKER_PANES[0])

    def test_get_next_worker_slot_excludes_terminated_from_used_slots(self, settings):
        """TERMINATED が占有していたスロットを再利用できることをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        now = datetime.now()
        manager.agents["worker-term"] = Agent(
            id="worker-term",
            role=AgentRole.WORKER,
            status=AgentStatus.TERMINATED,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=MAIN_WINDOW_WORKER_PANES[0],
            created_at=now,
            last_activity=now,
        )
        manager.agents["worker-active"] = Agent(
            id="worker-active",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test:0.2",
            session_name="test",
            window_index=0,
            pane_index=MAIN_WINDOW_WORKER_PANES[1],
            created_at=now,
            last_activity=now,
        )

        slot = manager.get_next_worker_slot(settings)

        assert slot == (0, MAIN_WINDOW_WORKER_PANES[0])

    def test_count_workers_excludes_terminated(self):
        """count_workers が TERMINATED を除外することをテスト。"""
        mock_tmux = MagicMock()
        manager = AgentManager(mock_tmux)
        now = datetime.now()
        manager.agents = {
            "worker-idle": Agent(
                id="worker-idle",
                role=AgentRole.WORKER,
                status=AgentStatus.IDLE,
                created_at=now,
                last_activity=now,
            ),
            "worker-term": Agent(
                id="worker-term",
                role=AgentRole.WORKER,
                status=AgentStatus.TERMINATED,
                created_at=now,
                last_activity=now,
            ),
            "admin": Agent(
                id="admin",
                role=AgentRole.ADMIN,
                status=AgentStatus.IDLE,
                created_at=now,
                last_activity=now,
            ),
        }

        assert manager.count_workers() == 1


class TestSessionManagement:
    """セッション管理のテスト。"""

    @pytest.mark.asyncio
    async def test_ensure_sessions_exist_success(self, settings, mock_tmux_manager):
        """メインセッションの作成が成功することをテスト。"""
        manager = AgentManager(mock_tmux_manager)

        success, message = await manager.ensure_sessions_exist(settings, "/tmp/test")

        assert success is True
        assert "作成しました" in message
        mock_tmux_manager.create_main_session.assert_called_once_with("/tmp/test")

    @pytest.mark.asyncio
    async def test_ensure_sessions_exist_failure(self, settings):
        """メインセッションの作成が失敗した場合のテスト。"""
        mock_tmux = MagicMock()
        mock_tmux.create_main_session = AsyncMock(return_value=False)
        manager = AgentManager(mock_tmux)

        success, message = await manager.ensure_sessions_exist(settings, "/tmp/test")

        assert success is False
        assert "失敗" in message

    @pytest.mark.asyncio
    async def test_ensure_worker_window_exists_main_window(
        self, settings, mock_tmux_manager
    ):
        """メインウィンドウの場合はTrueを返すことをテスト。"""
        manager = AgentManager(mock_tmux_manager)

        result = await manager.ensure_worker_window_exists("test-project", 0, settings)

        assert result is True
        # メインウィンドウは create_main_session で作成済みなので追加処理なし
        mock_tmux_manager.add_extra_worker_window.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_worker_window_exists_extra_window(
        self, settings, mock_tmux_manager
    ):
        """追加ウィンドウの作成をテスト。"""
        manager = AgentManager(mock_tmux_manager)

        result = await manager.ensure_worker_window_exists("test-project", 1, settings)

        assert result is True
        mock_tmux_manager.add_extra_worker_window.assert_called_once()
