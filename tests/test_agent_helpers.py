"""agent_helpers のユニットテスト。"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.agent import Agent, AgentRole, AgentStatus
from src.tools.agent_helpers import _post_create_agent, _send_task_to_worker


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


def test_post_create_agent_skips_file_persist_without_session_id(app_ctx):
    """session_id 未設定時は save_agent_to_file を呼ばない。"""
    app_ctx.session_id = None
    agent = _make_owner_agent()

    with patch("src.tools.agent_helpers.save_agent_to_file", return_value=True) as mock_save:
        result = _post_create_agent(app_ctx, agent, {agent.id: agent})

    assert result["file_persisted"] is False
    mock_save.assert_not_called()


def test_post_create_agent_persists_file_with_session_id(app_ctx):
    """session_id 設定時は save_agent_to_file を呼ぶ。"""
    app_ctx.session_id = "test-session"
    agent = _make_owner_agent()

    with patch("src.tools.agent_helpers.save_agent_to_file", return_value=True) as mock_save:
        result = _post_create_agent(app_ctx, agent, {agent.id: agent})

    assert result["file_persisted"] is True
    mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_send_task_to_worker_followup_failure_retries_bootstrap_once(app_ctx, temp_dir):
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
        patch("src.tools.agent_helpers.ensure_persona_manager", return_value=mock_persona_manager),
        patch("src.tools.agent_helpers.get_mcp_tool_prefix_from_config", return_value="mcp__x__"),
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
