"""agent_batch_tools のユニットテスト。"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import AICli
from src.models.agent import Agent, AgentRole, AgentStatus
from src.tools.agent_batch_tools import (
    _align_create_configs_with_slots,
    _pre_assign_pane_slots,
    _reuse_single_worker,
    _setup_worker_tmux_pane,
    _validate_batch_capacity,
    _validate_cursor_image_task_parallel_limit,
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


class TestPreAssignPaneSlots:
    """_pre_assign_pane_slots のテスト。"""

    def test_assigns_extra_window_slots_when_main_is_full(self):
        """メインウィンドウが埋まっている場合は追加ウィンドウへ割り当てる。"""
        agents = {}
        for pane in range(1, 7):
            agents[f"w-{pane}"] = _make_worker_agent(
                agent_id=f"w-{pane}",
                status=AgentStatus.BUSY,
                pane_index=pane,
            )

        settings = MagicMock()
        settings.workers_per_extra_window = 10
        slots = _pre_assign_pane_slots(
            agents=agents,
            settings=settings,
            project_name="test",
            create_count=2,
            profile_max_workers=16,
        )
        assert slots == [(1, 0), (1, 1)]

    def test_returns_none_when_profile_limit_is_fully_used(self):
        """プロファイル上限まで使用済みなら None を返す。"""
        agents = {}
        for pane in range(1, 7):
            agents[f"w-{pane}"] = _make_worker_agent(
                agent_id=f"w-{pane}",
                status=AgentStatus.BUSY,
                pane_index=pane,
            )

        settings = MagicMock()
        settings.workers_per_extra_window = 10
        slots = _pre_assign_pane_slots(
            agents=agents,
            settings=settings,
            project_name="test",
            create_count=1,
            profile_max_workers=6,
        )
        assert slots == [None]


class TestAlignCreateConfigsWithSlots:
    """_align_create_configs_with_slots のテスト。"""

    def test_pref_cli_task_is_aligned_to_matching_default_slot(self):
        """preferred_cli=cursor のタスクが cursor 既定 slot に寄ることをテスト。"""
        settings = MagicMock()
        # worker 1..4: codex, codex, gemini, cursor
        cli_map = {
            1: AICli.CODEX,
            2: AICli.CODEX,
            3: AICli.GEMINI,
            4: AICli.CURSOR,
        }
        settings.get_worker_cli.side_effect = lambda worker_no: cli_map[worker_no]
        create_configs = [
            {"task_title": "generic-1"},
            {"task_title": "generic-2"},
            {"task_title": "image-task", "preferred_cli": "cursor"},
            {"task_title": "generic-3"},
        ]
        pre_assigned_slots = [(0, 1), (0, 2), (0, 3), (0, 4)]

        aligned = _align_create_configs_with_slots(
            settings=settings,
            create_configs=create_configs,
            pre_assigned_slots=pre_assigned_slots,
        )

        assert [c["task_title"] for c in aligned] == [
            "generic-1",
            "generic-2",
            "generic-3",
            "image-task",
        ]

    def test_keeps_order_when_no_matching_slot(self):
        """一致する既定 CLI slot がない場合は元順序を維持する。"""
        settings = MagicMock()
        cli_map = {
            1: AICli.CODEX,
            2: AICli.GEMINI,
        }
        settings.get_worker_cli.side_effect = lambda worker_no: cli_map[worker_no]
        create_configs = [
            {"task_title": "image-task", "preferred_cli": "cursor"},
            {"task_title": "generic"},
        ]
        pre_assigned_slots = [(0, 1), (0, 2)]

        aligned = _align_create_configs_with_slots(
            settings=settings,
            create_configs=create_configs,
            pre_assigned_slots=pre_assigned_slots,
        )

        assert [c["task_title"] for c in aligned] == ["image-task", "generic"]


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
        assert agent.ai_cli_pinned is True
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
        assert agent.ai_cli_pinned is False
        mock_settings.get_worker_cli.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_main_session_is_created_once_per_project(self):
        """同一プロジェクトの main session 初期化を 1 回に抑える。"""
        mock_tmux = AsyncMock()
        mock_tmux.create_main_session.return_value = True
        mock_ctx = MagicMock()
        mock_ctx.tmux = mock_tmux

        mock_settings = MagicMock()
        mock_settings.get_worker_cli.return_value = AICli.CLAUDE

        first_agent, first_error = await _setup_worker_tmux_pane(
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
        )
        second_agent, second_error = await _setup_worker_tmux_pane(
            app_ctx=mock_ctx,
            settings=mock_settings,
            project_name="test",
            repo_path="/tmp/repo",
            window_index=0,
            pane_index=2,
            worker_no=2,
            worktree_path="/tmp/repo",
            enable_worktree=False,
            worker_index=1,
        )

        assert first_error is None
        assert second_error is None
        assert first_agent is not None
        assert second_agent is not None
        mock_tmux.create_main_session.assert_awaited_once_with("/tmp/repo")

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
        assert agent.ai_cli_pinned is False
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
        assert worker.ai_cli == AICli.CURSOR
        assert worker.ai_cli_pinned is True

    @pytest.mark.asyncio
    @patch("src.tools.agent_batch_tools.save_agent_to_file")
    @patch("src.tools.agent_batch_tools._assign_and_dispatch_task")
    @patch("src.tools.agent_batch_tools.resolve_worker_number_from_slot")
    async def test_reuse_preserves_pinned_cli_without_preferred(
        self,
        mock_resolve,
        mock_dispatch,
        mock_save,
    ):
        """pin 済み Worker は preferred_cli 未指定でも slot CLI で上書きしない。"""
        worker = _make_worker_agent("w-1", status=AgentStatus.IDLE, ai_cli=AICli.CURSOR)
        worker.ai_cli_pinned = True
        config = {}

        mock_resolve.return_value = 13
        mock_dispatch.return_value = (False, None, False, "none", None)

        mock_ctx = MagicMock()
        mock_settings = MagicMock()
        mock_settings.get_worker_cli.return_value = AICli.CODEX

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
        assert worker.ai_cli == AICli.CURSOR
        assert worker.ai_cli_pinned is True


class TestImageTaskParallelLimit:
    """画像生成タスク（Cursor CLI）の並列実行数上限チェック。

    フラグON時のみ制約を適用し、フラグOFF時は無効化されることを検証する。
    """

    def test_busy_2_plus_request_1_exceeds_limit_when_enabled(self):
        """BUSY Cursor Worker 2 台 + 新規 cursor 1 台 → ON時は上限超過エラー。"""
        settings = MagicMock()
        settings.enable_cursor_image_routing = True
        agents = {
            "w-1": _make_worker_agent(
                "w-1", status=AgentStatus.BUSY, ai_cli=AICli.CURSOR, pane_index=1
            ),
            "w-2": _make_worker_agent(
                "w-2", status=AgentStatus.BUSY, ai_cli=AICli.CURSOR, pane_index=2
            ),
        }
        configs = [{"preferred_cli": "cursor"}]

        error = _validate_cursor_image_task_parallel_limit(settings, agents, configs)
        assert error is not None
        assert "上限を超えます" in error["error"]

    def test_busy_1_plus_request_1_within_limit_when_enabled(self):
        """BUSY Cursor Worker 1 台 + 新規 cursor 1 台 → ON時も上限以内で成功。"""
        settings = MagicMock()
        settings.enable_cursor_image_routing = True
        agents = {
            "w-1": _make_worker_agent(
                "w-1", status=AgentStatus.BUSY, ai_cli=AICli.CURSOR, pane_index=1
            ),
        }
        configs = [{"preferred_cli": "cursor"}]

        error = _validate_cursor_image_task_parallel_limit(settings, agents, configs)
        assert error is None

    def test_idle_cursor_not_counted_as_busy_when_enabled(self):
        """IDLE Cursor Worker 2 台 + 新規 cursor 1 台 → ON時も成功（idle はカウント外）。"""
        settings = MagicMock()
        settings.enable_cursor_image_routing = True
        agents = {
            "w-1": _make_worker_agent(
                "w-1", status=AgentStatus.IDLE, ai_cli=AICli.CURSOR, pane_index=1
            ),
            "w-2": _make_worker_agent(
                "w-2", status=AgentStatus.IDLE, ai_cli=AICli.CURSOR, pane_index=2
            ),
        }
        configs = [{"preferred_cli": "cursor"}]

        error = _validate_cursor_image_task_parallel_limit(settings, agents, configs)
        assert error is None

    def test_limit_is_disabled_when_routing_flag_is_off(self):
        """フラグOFF時は上限超過条件でもエラーにしない。"""
        settings = MagicMock()
        settings.enable_cursor_image_routing = False
        agents = {
            "w-1": _make_worker_agent(
                "w-1", status=AgentStatus.BUSY, ai_cli=AICli.CURSOR, pane_index=1
            ),
            "w-2": _make_worker_agent(
                "w-2", status=AgentStatus.BUSY, ai_cli=AICli.CURSOR, pane_index=2
            ),
        }
        configs = [{"preferred_cli": "cursor"}]

        error = _validate_cursor_image_task_parallel_limit(settings, agents, configs)
        assert error is None
