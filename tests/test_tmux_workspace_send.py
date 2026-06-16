"""TmuxWorkspaceMixin の send 系コマンド組み立て検証。"""

from unittest.mock import AsyncMock

import pytest

from src.config.settings import Settings
from src.managers.tmux_manager import TmuxManager


def _manager(run_return=(0, "", "")):
    manager = TmuxManager(Settings())
    manager._run = AsyncMock(return_value=run_return)
    manager._send_enter_key = AsyncMock(return_value=True)
    return manager


@pytest.mark.asyncio
async def test_send_keys_to_pane_clears_input_with_c_u_first():
    manager = _manager()
    ok = await manager.send_keys_to_pane("sess", 0, 1, "echo hi", clear_input=True)
    assert ok is True
    target = manager._pane_target("sess", 0, 1)
    assert manager._run.await_args_list[0].args == ("send-keys", "-t", target, "C-u")
    assert manager._run.await_args_list[1].args == ("send-keys", "-t", target, "-l", "echo hi")
    manager._send_enter_key.assert_awaited_once_with(target)


@pytest.mark.asyncio
async def test_send_keys_to_pane_skips_clear_when_disabled():
    manager = _manager()
    await manager.send_keys_to_pane("sess", 0, 1, "echo hi", clear_input=False)
    target = manager._pane_target("sess", 0, 1)
    assert manager._run.await_args_list[0].args == ("send-keys", "-t", target, "-l", "echo hi")


@pytest.mark.asyncio
async def test_send_keys_to_pane_non_literal_omits_l_flag():
    manager = _manager()
    await manager.send_keys_to_pane("sess", 0, 1, "C-c", literal=False, clear_input=False)
    target = manager._pane_target("sess", 0, 1)
    assert manager._run.await_args_list[0].args == ("send-keys", "-t", target, "C-c")


@pytest.mark.asyncio
async def test_send_keys_to_pane_returns_false_on_send_error():
    manager = _manager((1, "", "err"))
    ok = await manager.send_keys_to_pane("sess", 0, 1, "echo hi", clear_input=False)
    assert ok is False
    manager._send_enter_key.assert_not_awaited()
