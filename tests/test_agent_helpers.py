"""agent_helpers のユニットテスト。"""

from datetime import datetime
from unittest.mock import patch

from src.models.agent import Agent, AgentRole, AgentStatus
from src.tools.agent_helpers import _post_create_agent


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

