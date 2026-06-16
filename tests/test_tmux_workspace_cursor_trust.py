"""TmuxWorkspaceMixin の Cursor 信頼検知・Codex トークン分岐検証。"""

from unittest.mock import AsyncMock, patch

import pytest

from src.config.settings import Settings
from src.managers.tmux_manager import TmuxManager

_MIXIN = "src.managers.tmux_workspace_mixin"


@pytest.mark.parametrize(
    "command,expected",
    [
        ("cursor-agent", True),
        ("agent", True),
        ("/usr/local/bin/cursor-agent --flag", True),
        ("echo hi && agent", True),
        ("echo hi; cursor-agent", True),
        ("vim agent.py", False),        # 引数の agent は起動でない
        ("agent_helpers", False),  # 語境界(\b)不一致: agent_helpers は agent に続く _ で境界なし
        ("codex run", False),
        ("", False),
    ],
)
def test_command_may_launch_cursor_agent(command, expected):
    assert TmuxManager(Settings())._command_may_launch_cursor_agent(command) is expected


@pytest.mark.parametrize(
    "output,expected",
    [
        ("Workspace Trust Required\nTrust this workspace? (y/n)", True),
        ("workspace trust required", False),   # 片方のみ
        ("trust this workspace", False),       # 片方のみ
        ("just normal output", False),
    ],
)
def test_is_cursor_workspace_trust_prompt(output, expected):
    assert TmuxManager(Settings())._is_cursor_workspace_trust_prompt(output) is expected


@pytest.mark.asyncio
async def test_confirm_cursor_trust_returns_true_when_no_prompt():
    manager = TmuxManager(Settings())
    manager.capture_pane_by_index = AsyncMock(return_value="all good")
    manager._run = AsyncMock(return_value=(0, "", ""))
    ok = await manager._confirm_cursor_workspace_trust("sess", 0, 1)
    assert ok is True
    manager._run.assert_not_awaited()  # プロンプトなし→承認キー送らず


@pytest.mark.asyncio
async def test_confirm_cursor_trust_sends_accept_key_then_confirms():
    manager = TmuxManager(Settings())
    prompt = "Workspace Trust Required\nTrust this workspace"
    manager.capture_pane_by_index = AsyncMock(side_effect=[prompt, "cleared"])
    manager._run = AsyncMock(return_value=(0, "", ""))
    target = manager._pane_target("sess", 0, 1)
    with patch(f"{_MIXIN}.asyncio.sleep", new=AsyncMock()):
        ok = await manager._confirm_cursor_workspace_trust("sess", 0, 1)
    assert ok is True
    manager._run.assert_awaited_with("send-keys", "-t", target, "a")


@pytest.mark.asyncio
async def test_confirm_cursor_trust_returns_false_when_key_send_fails():
    manager = TmuxManager(Settings())
    prompt = "Workspace Trust Required\nTrust this workspace"
    manager.capture_pane_by_index = AsyncMock(return_value=prompt)
    manager._run = AsyncMock(return_value=(1, "", "err"))
    with patch(f"{_MIXIN}.asyncio.sleep", new=AsyncMock()):
        ok = await manager._confirm_cursor_workspace_trust("sess", 0, 1)
    assert ok is False


@pytest.mark.parametrize(
    "output,command,expected",
    [
        # トークン重複 >=0.4 で未確定（prefix では一致しないケース）
        ("› gamma alpha zeta", "alpha beta gamma delta", True),
        # トークン重複 <0.4 は確定扱い
        ("› zzz qqq", "alpha beta gamma delta", False),
    ],
)
def test_is_pending_codex_prompt_token_overlap_branch(output, command, expected):
    assert TmuxManager(Settings())._is_pending_codex_prompt(output, command) is expected
