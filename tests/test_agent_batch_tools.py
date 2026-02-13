"""agent_batch_tools のユニットテスト。"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import AICli
from src.models.agent import Agent, AgentRole, AgentStatus
from src.tools.agent_batch_tools import (
    MAX_IMAGE_TASK_PARALLEL,
    _reuse_single_worker,
    _setup_worker_tmux_pane,
    _validate_batch_capacity,
)
from src.tools.agent_helpers import build_worker_task_branch


def _make_worker_agent(
    agent_id="worker-001",
    status=AgentStatus.IDLE,
    ai_cli=None,
    pane_index=1,
) -> Agent:
    now = datetime.now()
    return Agent(
        id=agent_id,
        role=AgentRole.WORKER,
        status=status,
        tmux_session=f"test:0.{pane_index}",
        session_name="test",
        window_index=0,
        pane_index=pane_index,
        working_dir="/tmp",
        ai_cli=ai_cli,
        created_at=now,
        last_activity=now,
    )


class TestValidateBatchCapacity:
    """_validate_batch_capacity のテスト。"""

    def test_excludes_terminated_from_capacity(self):
        """T19: TERMINATED Worker がキャパシティ計算から除外される。"""
        agents = {}
        # 2 IDLE Workers
        agents["w-1"] = _make_worker_agent("w-1", status=AgentStatus.IDLE)
        agents["w-2"] = _make_worker_agent("w-2", status=AgentStatus.IDLE)
        # 1 TERMINATED Worker（カウント対象外）
        agents["w-3"] = _make_worker_agent("w-3", status=AgentStatus.TERMINATED)

        worker_configs = [
            {"task_id": "t1", "task_content": "task 1"},
        ]

        # profile_max_workers=3 だが、TERMINATED を除外すると現在 2 名のため新規 1 名作成可能
        reusable, reuse_count, error = _validate_batch_capacity(
            agents, worker_configs, reuse_idle_workers=False, profile_max_workers=3
        )
        assert error is None
        assert reuse_count == 0

    def test_capacity_error_when_limit_reached(self):
        """TERMINATED を除外した後に上限に達している場合はエラーを返す。"""
        agents = {}
        # 3 IDLE Workers
        for i in range(1, 4):
            agents[f"w-{i}"] = _make_worker_agent(f"w-{i}", status=AgentStatus.IDLE)
        # 1 TERMINATED Worker（カウント対象外）
        agents["w-term"] = _make_worker_agent("w-term", status=AgentStatus.TERMINATED)

        worker_configs = [
            {"task_id": "t1", "task_content": "task 1"},
        ]

        # profile_max_workers=3 で実質 3 名稼働中のため新規作成不可
        reusable, reuse_count, error = _validate_batch_capacity(
            agents, worker_configs, reuse_idle_workers=False, profile_max_workers=3
        )
        assert error is not None
        assert "上限を超えます" in error["error"]


class TestWorkerBranchNaming:
    """Worker ブランチ命名のテスト。"""

    def test_feature_prefix_is_not_duplicated(self):
        """feature/ 起点でも feature/feature- が重複しないことをテスト。"""
        branch = build_worker_task_branch("feature/add-skill", 3, "task-123")
        assert branch.startswith("feature/add-skill-worker-3-")
        assert not branch.startswith("feature/feature-")


class TestPreferredCliNewWorker:
    """preferred_cli による新規 Worker 作成のテスト。"""

    @pytest.mark.asyncio
    async def test_preferred_cli_cursor_creates_worker_with_cursor_cli(self):
        """preferred_cli='cursor' 指定時に AICli.CURSOR で Worker が作成される。"""
        mock_tmux = AsyncMock()
        mock_tmux.create_main_session.return_value = True
        mock_ctx = MagicMock()
        mock_ctx.tmux = mock_tmux

        mock_settings = MagicMock()
        mock_settings.get_worker_cli.return_value = AICli.CLAUDE

        agent, error = await _setup_worker_tmux_pane(
            app_ctx=mock_ctx,
            settings=mock_settings,
            project_name="test",
            repo_path="/tmp/repo",
            window_index=0,
            pane_index=1,
            worker_no=1,
            worktree_path="/tmp/repo",
            enable_worktree=False,
            worker_index=0,
            preferred_cli="cursor",
        )

        assert error is None
        assert agent is not None
        assert agent.ai_cli == AICli.CURSOR
        # get_worker_cli はフォールバック時のみ呼ばれるため、ここでは呼ばれない
        mock_settings.get_worker_cli.assert_not_called()

    @pytest.mark.asyncio
    async def test_preferred_cli_not_specified_uses_default(self):
        """preferred_cli 未指定時はデフォルト CLI（get_worker_cli）が使われる。"""
        mock_tmux = AsyncMock()
        mock_tmux.create_main_session.return_value = True
        mock_ctx = MagicMock()
        mock_ctx.tmux = mock_tmux

        mock_settings = MagicMock()
        mock_settings.get_worker_cli.return_value = AICli.CLAUDE

        agent, error = await _setup_worker_tmux_pane(
            app_ctx=mock_ctx,
            settings=mock_settings,
            project_name="test",
            repo_path="/tmp/repo",
            window_index=0,
            pane_index=1,
            worker_no=1,
            worktree_path="/tmp/repo",
            enable_worktree=False,
            worker_index=0,
            # preferred_cli 未指定（デフォルト None）
        )

        assert error is None
        assert agent is not None
        assert agent.ai_cli == AICli.CLAUDE
        mock_settings.get_worker_cli.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_invalid_preferred_cli_falls_back_to_default(self):
        """無効な preferred_cli はデフォルト CLI にフォールバックする。"""
        mock_tmux = AsyncMock()
        mock_tmux.create_main_session.return_value = True
        mock_ctx = MagicMock()
        mock_ctx.tmux = mock_tmux

        mock_settings = MagicMock()
        mock_settings.get_worker_cli.return_value = AICli.CLAUDE

        agent, error = await _setup_worker_tmux_pane(
            app_ctx=mock_ctx,
            settings=mock_settings,
            project_name="test",
            repo_path="/tmp/repo",
            window_index=0,
            pane_index=1,
            worker_no=1,
            worktree_path="/tmp/repo",
            enable_worktree=False,
            worker_index=0,
            preferred_cli="invalid",
        )

        assert error is None
        assert agent is not None
        assert agent.ai_cli == AICli.CLAUDE
        mock_settings.get_worker_cli.assert_called_once_with(1)


class TestPreferredCliReuse:
    """preferred_cli による Worker 再利用のテスト。"""

    @pytest.mark.asyncio
    async def test_reuse_rejected_when_cli_mismatch(self):
        """idle Worker が Claude CLI、preferred_cli='cursor' → 再利用拒否。"""
        worker = _make_worker_agent("w-1", status=AgentStatus.IDLE, ai_cli=AICli.CLAUDE)
        config = {"preferred_cli": "cursor"}

        mock_ctx = MagicMock()
        mock_settings = MagicMock()

        result = await _reuse_single_worker(
            app_ctx=mock_ctx,
            settings=mock_settings,
            config=config,
            worker_index=0,
            worker=worker,
            repo_path="/tmp/repo",
            base_branch="main",
            enable_worktree=False,
            session_id=None,
            profile_settings={},
            caller_agent_id=None,
        )

        assert result["success"] is False
        assert "CLI が異なる" in result["error"]

    @pytest.mark.asyncio
    @patch("src.tools.agent_batch_tools.save_agent_to_file")
    @patch("src.tools.agent_batch_tools._assign_and_dispatch_task")
    @patch("src.tools.agent_batch_tools.resolve_worker_number_from_slot")
    async def test_reuse_success_when_cli_match(
        self,
        mock_resolve,
        mock_dispatch,
        mock_save,
    ):
        """idle Worker が Cursor CLI、preferred_cli='cursor' → 再利用成功。"""
        worker = _make_worker_agent("w-1", status=AgentStatus.IDLE, ai_cli=AICli.CURSOR)
        config = {"preferred_cli": "cursor"}

        mock_resolve.return_value = 1
        mock_dispatch.return_value = (False, None, False, "none", None)

        mock_ctx = MagicMock()
        mock_settings = MagicMock()
        mock_settings.get_worker_cli.return_value = AICli.CURSOR

        result = await _reuse_single_worker(
            app_ctx=mock_ctx,
            settings=mock_settings,
            config=config,
            worker_index=0,
            worker=worker,
            repo_path="/tmp/repo",
            base_branch="main",
            enable_worktree=False,
            session_id=None,
            profile_settings={},
            caller_agent_id=None,
        )

        assert result["success"] is True
        assert result["reused"] is True


class TestImageTaskParallelLimit:
    """画像生成タスク（Cursor CLI）の並列実行数上限チェック。

    create_workers_batch 内のカウントロジックと同等のロジックを検証する。
    """

    @staticmethod
    def _count_busy_cursor(agents: dict[str, Agent]) -> int:
        """BUSY な Cursor Worker の数をカウントする（ソースコードと同じロジック）。"""
        return sum(
            1
            for a in agents.values()
            if a.role == AgentRole.WORKER
            and a.status == AgentStatus.BUSY
            and a.ai_cli == AICli.CURSOR
        )

    @staticmethod
    def _count_cursor_requests(worker_configs: list[dict]) -> int:
        """Cursor CLI リクエスト数をカウントする。"""
        return sum(1 for c in worker_configs if c.get("preferred_cli") == "cursor")

    def test_busy_2_plus_request_1_exceeds_limit(self):
        """BUSY Cursor Worker 2 台 + 新規 cursor 1 台 → 上限超過でエラー。"""
        agents = {
            "w-1": _make_worker_agent(
                "w-1", status=AgentStatus.BUSY, ai_cli=AICli.CURSOR, pane_index=1
            ),
            "w-2": _make_worker_agent(
                "w-2", status=AgentStatus.BUSY, ai_cli=AICli.CURSOR, pane_index=2
            ),
        }
        configs = [{"preferred_cli": "cursor"}]

        busy = self._count_busy_cursor(agents)
        req = self._count_cursor_requests(configs)

        assert busy == 2
        assert req == 1
        assert busy + req > MAX_IMAGE_TASK_PARALLEL

    def test_busy_1_plus_request_1_within_limit(self):
        """BUSY Cursor Worker 1 台 + 新規 cursor 1 台 → 上限以内で成功。"""
        agents = {
            "w-1": _make_worker_agent(
                "w-1", status=AgentStatus.BUSY, ai_cli=AICli.CURSOR, pane_index=1
            ),
        }
        configs = [{"preferred_cli": "cursor"}]

        busy = self._count_busy_cursor(agents)
        req = self._count_cursor_requests(configs)

        assert busy == 1
        assert req == 1
        assert busy + req <= MAX_IMAGE_TASK_PARALLEL

    def test_idle_cursor_not_counted_as_busy(self):
        """IDLE Cursor Worker 2 台 + 新規 cursor 1 台 → 成功（idle はカウント外）。"""
        agents = {
            "w-1": _make_worker_agent(
                "w-1", status=AgentStatus.IDLE, ai_cli=AICli.CURSOR, pane_index=1
            ),
            "w-2": _make_worker_agent(
                "w-2", status=AgentStatus.IDLE, ai_cli=AICli.CURSOR, pane_index=2
            ),
        }
        configs = [{"preferred_cli": "cursor"}]

        busy = self._count_busy_cursor(agents)
        req = self._count_cursor_requests(configs)

        assert busy == 0
        assert req == 1
        assert busy + req <= MAX_IMAGE_TASK_PARALLEL
