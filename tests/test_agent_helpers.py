"""agent_helpers のユニットテスト。"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import AICli
from src.models.agent import Agent, AgentRole, AgentStatus
from src.tools.agent_helpers import (
    _get_next_worker_slot,
    _post_create_agent,
    _resolve_agent_cli_name,
    _resolve_tmux_session_name,
    _sanitize_branch_part,
    _send_task_to_worker,
    _short_task_id,
    _validate_agent_creation,
    build_worker_task_branch,
    resolve_worker_number_from_slot,
)


def _make_owner_agent() -> Agent:
    now = datetime.now()
    return Agent(
        id="owner-001",
        role=AgentRole.OWNER,
        status=AgentStatus.IDLE,
        tmux_session=None,
        working_dir="/tmp",
        created_at=now,
        last_activity=now,
    )


def _make_worker_agent(
    agent_id="worker-001",
    session_name="test",
    window_index=0,
    pane_index=1,
) -> Agent:
    now = datetime.now()
    return Agent(
        id=agent_id,
        role=AgentRole.WORKER,
        status=AgentStatus.IDLE,
        tmux_session=f"{session_name}:{window_index}.{pane_index}",
        session_name=session_name,
        window_index=window_index,
        pane_index=pane_index,
        working_dir="/tmp",
        created_at=now,
        last_activity=now,
    )


class TestResolveHelpers:
    """ヘルパー関数群のテスト。"""

    def test_resolve_tmux_session_name_from_session_name(self):
        """session_name が設定されている場合はそれを返す。"""
        agent = _make_worker_agent()
        assert _resolve_tmux_session_name(agent) == "test"

    def test_resolve_tmux_session_name_from_tmux_session(self):
        """session_name がなく tmux_session がある場合はコロン前を返す。"""
        agent = _make_worker_agent()
        agent.session_name = None
        agent.tmux_session = "project:0.1"
        assert _resolve_tmux_session_name(agent) == "project"

    def test_resolve_tmux_session_name_none(self):
        """どちらも未設定の場合は None を返す。"""
        agent = _make_owner_agent()
        agent.session_name = None
        agent.tmux_session = None
        assert _resolve_tmux_session_name(agent) is None

    def test_resolve_agent_cli_name_from_agent(self):
        """agent.ai_cli が設定されていればその value を返す。"""
        agent = _make_worker_agent()
        agent.ai_cli = AICli.CLAUDE
        app_ctx = MagicMock()
        assert _resolve_agent_cli_name(agent, app_ctx) == "claude"

    def test_resolve_agent_cli_name_fallback(self):
        """agent.ai_cli が未設定ならデフォルトを返す。"""
        agent = _make_worker_agent()
        agent.ai_cli = None
        app_ctx = MagicMock()
        app_ctx.ai_cli.get_default_cli.return_value = AICli.CLAUDE
        assert _resolve_agent_cli_name(agent, app_ctx) == "claude"


class TestSanitizeBranchPart:
    """_sanitize_branch_part のテスト。"""

    def test_normal_string(self):
        """通常の文字列はそのまま。"""
        assert _sanitize_branch_part("feature-branch") == "feature-branch"

    def test_special_characters(self):
        """特殊文字はハイフンに置換される。"""
        result = _sanitize_branch_part("feat/some branch!")
        assert "/" not in result
        assert " " not in result
        assert "!" not in result

    def test_empty_string(self):
        """空文字列は 'main' を返す。"""
        assert _sanitize_branch_part("") == "main"

    def test_none_value(self):
        """None は 'main' を返す。"""
        assert _sanitize_branch_part(None) == "main"


class TestShortTaskId:
    """_short_task_id のテスト。"""

    def test_normal_task_id(self):
        """通常のタスクIDを8桁に短縮する。"""
        result = _short_task_id("task-12345678-abcdef")
        assert len(result) <= 8

    def test_empty_task_id(self):
        """空の場合は 'task0000' を返す。"""
        assert _short_task_id("") == "task0000"

    def test_none_task_id(self):
        """None の場合は 'task0000' を返す。"""
        assert _short_task_id(None) == "task0000"


class TestBuildWorkerTaskBranch:
    """build_worker_task_branch のテスト。"""

    def test_generates_branch_name(self):
        """正しいブランチ名を生成する。"""
        result = build_worker_task_branch("main", 1, "task-001")
        assert result.startswith("feature/main-worker-1-")

    def test_strips_feature_prefix_from_base_branch(self):
        """base が feature/ の場合も feature/feature- にならないことをテスト。"""
        result = build_worker_task_branch("feature/add-skill", 2, "task-001")
        assert result.startswith("feature/add-skill-worker-2-")
        assert not result.startswith("feature/feature-")


class TestResolveWorkerNumberFromSlot:
    """resolve_worker_number_from_slot のテスト。"""

    def test_main_window_slot(self, settings):
        """メインウィンドウのスロットは pane_index を返す。"""
        assert resolve_worker_number_from_slot(settings, 0, 1) == 1
        assert resolve_worker_number_from_slot(settings, 0, 6) == 6

    def test_extra_window_slot(self, settings):
        """追加ウィンドウのスロットは 7 以降を返す。"""
        result = resolve_worker_number_from_slot(settings, 1, 0)
        assert result == 7


class TestValidateAgentCreation:
    """_validate_agent_creation のテスト。"""

    def test_invalid_role(self):
        """無効なロールでエラーを返す。"""
        _, _, error = _validate_agent_creation({}, "invalid_role", None, 6)
        assert error is not None
        assert "無効な役割" in error["error"]

    def test_invalid_ai_cli(self):
        """無効な AI CLI でエラーを返す。"""
        _, _, error = _validate_agent_creation({}, "worker", "invalid_cli", 6)
        assert error is not None
        assert "無効なAI CLI" in error["error"]

    def test_worker_limit_reached(self):
        """Worker 上限に達している場合にエラーを返す。"""
        agents = {f"w-{i}": _make_worker_agent(f"w-{i}", pane_index=i) for i in range(6)}
        _, _, error = _validate_agent_creation(agents, "worker", None, 6)
        assert error is not None
        assert "上限" in error["error"]

    def test_duplicate_owner(self):
        """Owner が既に存在する場合にエラーを返す。"""
        agents = {"owner-001": _make_owner_agent()}
        _, _, error = _validate_agent_creation(agents, "owner", None, 6)
        assert error is not None
        assert "既に存在" in error["error"]

    def test_valid_worker_creation(self):
        """正常な Worker 作成は error=None を返す。"""
        role, cli, error = _validate_agent_creation({}, "worker", "claude", 6)
        assert error is None
        assert role == AgentRole.WORKER
        assert cli == AICli.CLAUDE


class TestGetNextWorkerSlot:
    """_get_next_worker_slot のテスト。"""

    def test_first_slot_is_pane_1(self, settings):
        """最初のスロットはメインウィンドウの pane 1。"""
        slot = _get_next_worker_slot({}, settings, "project")
        assert slot == (0, 1)

    def test_returns_none_when_full(self, settings):
        """スロットが全て使用済みの場合は None を返す。"""
        agents = {}
        for i in range(1, 4):  # settings.max_workers=3
            agents[f"w-{i}"] = _make_worker_agent(f"w-{i}", session_name="project", pane_index=i)
        slot = _get_next_worker_slot(agents, settings, "project")
        assert slot is None

    def test_skips_terminated_workers_in_slot_allocation(self, settings):
        """T17: TERMINATED Worker のスロットが空きとして扱われる。"""
        agents = {}
        # Worker 1: TERMINATED（pane 1 は再利用可能）
        agents["w-1"] = _make_worker_agent("w-1", session_name="project", pane_index=1)
        agents["w-1"].status = AgentStatus.TERMINATED
        # Worker 2: IDLE（pane 2 は使用中）
        agents["w-2"] = _make_worker_agent("w-2", session_name="project", pane_index=2)
        agents["w-2"].status = AgentStatus.IDLE

        slot = _get_next_worker_slot(agents, settings, "project")
        # pane 1 が TERMINATED なので再利用可能
        assert slot == (0, 1)

    def test_counts_active_workers_only(self, settings):
        """T18: TERMINATED Worker が上限カウントに含まれない。"""
        agents = {}
        # 2 IDLE Workers
        agents["w-1"] = _make_worker_agent("w-1", session_name="project", pane_index=1)
        agents["w-2"] = _make_worker_agent("w-2", session_name="project", pane_index=2)
        # 1 TERMINATED Worker（カウント対象外）
        agents["w-3"] = _make_worker_agent("w-3", session_name="project", pane_index=3)
        agents["w-3"].status = AgentStatus.TERMINATED

        # settings.max_workers=3 だが、実質 IDLE は 2 なので新規作成可能
        # TERMINATED の pane 3 が空きとして再利用される
        slot = _get_next_worker_slot(agents, settings, "project", max_workers=3)
        assert slot == (0, 3)


class TestPostCreateAgent:
    """_post_create_agent のテスト。"""

    def test_owner_gets_provisional_session_id(self, app_ctx):
        """Owner 作成時に session_id 未設定でも仮 session_id が設定される。"""
        app_ctx.session_id = None
        agent = _make_owner_agent()

        with patch("src.tools.agent_helpers.save_agent_to_file", return_value=True) as mock_save:
            result = _post_create_agent(app_ctx, agent, {agent.id: agent})

        # Owner は仮 session_id が設定されるため保存される
        assert result["file_persisted"] is True
        mock_save.assert_called_once()
        assert app_ctx.session_id is not None
        assert app_ctx.session_id.startswith("provisional-")

    def test_skips_file_persist_without_session_id_worker(self, app_ctx):
        """Worker の session_id 未設定時は save_agent_to_file を呼ばない。"""
        app_ctx.session_id = None
        agent = _make_worker_agent()

        with patch("src.tools.agent_helpers.save_agent_to_file", return_value=True) as mock_save:
            result = _post_create_agent(app_ctx, agent, {agent.id: agent})

        assert result["file_persisted"] is False
        mock_save.assert_not_called()

    def test_persists_file_with_session_id(self, app_ctx):
        """session_id 設定時は save_agent_to_file を呼ぶ。"""
        app_ctx.session_id = "test-session"
        agent = _make_owner_agent()

        with patch("src.tools.agent_helpers.save_agent_to_file", return_value=True) as mock_save:
            result = _post_create_agent(app_ctx, agent, {agent.id: agent})

        assert result["file_persisted"] is True
        mock_save.assert_called_once()

    def test_registers_ipc(self, app_ctx):
        """session_id 設定時に IPC 登録を行う。"""
        app_ctx.session_id = "test-session"
        agent = _make_owner_agent()

        with patch("src.tools.agent_helpers.save_agent_to_file", return_value=True):
            result = _post_create_agent(app_ctx, agent, {agent.id: agent})

        assert result["ipc_registered"] is True

    def test_skips_ipc_without_session_id_worker(self, app_ctx):
        """Worker の session_id 未設定時は IPC 登録をスキップする。"""
        app_ctx.session_id = None
        agent = _make_worker_agent()

        with patch("src.tools.agent_helpers.save_agent_to_file", return_value=True):
            result = _post_create_agent(app_ctx, agent, {agent.id: agent})

        assert result["ipc_registered"] is False


class TestSendTaskToWorker:
    """_send_task_to_worker のテスト。"""

    @pytest.mark.asyncio
    async def test_missing_task_id_returns_failure(self, app_ctx, temp_dir):
        """task_id が未指定の場合は失敗を返す。"""
        agent = _make_worker_agent()
        result = await _send_task_to_worker(
            app_ctx=app_ctx,
            agent=agent,
            task_content="do task",
            task_id=None,
            branch="feature/test",
            worktree_path=str(temp_dir),
            session_id="session-001",
            worker_index=0,
            enable_worktree=False,
            profile_settings={"worker_model": "opus", "worker_thinking_tokens": 4000},
            caller_agent_id="admin-001",
        )
        assert result["task_sent"] is False

    @pytest.mark.asyncio
    async def test_followup_failure_retries_bootstrap_once(self, app_ctx, temp_dir):
        """followup 失敗時に shell 判定なら bootstrap を 1 回再試行する。"""
        now = datetime.now()
        agent = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir=str(temp_dir),
            worktree_path=str(temp_dir),
            created_at=now,
            last_activity=now,
            ai_bootstrapped=True,
        )
        app_ctx.agents[agent.id] = agent
        app_ctx.project_root = str(temp_dir)
        app_ctx.session_id = "session-001"

        app_ctx.tmux.send_keys_to_pane = AsyncMock(side_effect=[False, True])
        app_ctx.tmux.get_pane_current_command = AsyncMock(return_value="zsh")
        app_ctx.ai_cli.build_stdin_command = MagicMock(return_value="bootstrap-command")

        mock_dashboard = MagicMock()
        mock_dashboard.write_task_file.return_value = Path(temp_dir) / "task.md"
        mock_dashboard.save_markdown_dashboard.return_value = None
        mock_dashboard.record_api_call.return_value = None

        mock_persona_manager = MagicMock()
        mock_persona_manager.get_optimal_persona.return_value = MagicMock(
            name="coder",
            system_prompt_addition="focus on fixes",
        )

        with (
            patch("src.tools.agent_helpers.search_memory_context", return_value=[]),
            patch(
                "src.tools.agent_helpers.ensure_persona_manager",
                return_value=mock_persona_manager,
            ),
            patch(
                "src.tools.agent_helpers.get_mcp_tool_prefix_from_config",
                return_value="mcp__x__",
            ),
            patch("src.tools.agent_helpers.generate_7section_task", return_value="task body"),
            patch("src.tools.agent_helpers.ensure_dashboard_manager", return_value=mock_dashboard),
            patch("src.tools.agent_helpers.resolve_main_repo_root", return_value=str(temp_dir)),
            patch("src.tools.agent_helpers.save_agent_to_file", return_value=True),
        ):
            result = await _send_task_to_worker(
                app_ctx=app_ctx,
                agent=agent,
                task_content="do task",
                task_id="task-001",
                branch="feature/task-001",
                worktree_path=str(temp_dir),
                session_id="session-001",
                worker_index=0,
                enable_worktree=False,
                profile_settings={
                    "worker_model": "opus",
                    "worker_thinking_tokens": 4000,
                    "worker_reasoning_effort": "none",
                },
                caller_agent_id="admin-001",
            )

        assert result["task_sent"] is True
        assert result["dispatch_mode"] == "bootstrap"
        assert result["command_sent"] == "bootstrap-command"
        assert agent.ai_bootstrapped is True
        assert app_ctx.tmux.send_keys_to_pane.await_count == 2
