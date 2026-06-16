"""TmuxManager の tmux コマンド組み立て検証。"""

from unittest.mock import AsyncMock

import pytest

from src.config.settings import Settings
from src.managers.tmux_manager import TmuxManager


def _manager_with_run(return_value=(0, "", "")):
    manager = TmuxManager(Settings())
    manager._run = AsyncMock(return_value=return_value)
    return manager


@pytest.mark.asyncio
async def test_create_session_builds_new_session_args():
    manager = _manager_with_run()
    ok = await manager.create_session("proj", "/work/dir")
    assert ok is True
    manager._run.assert_called_with("new-session", "-d", "-s", "proj", "-c", "/work/dir")


@pytest.mark.asyncio
async def test_create_session_returns_false_on_error():
    manager = _manager_with_run((1, "", "boom"))
    ok = await manager.create_session("proj", "/work/dir")
    assert ok is False


@pytest.mark.asyncio
async def test_send_keys_literal_sends_text_then_enter():
    manager = _manager_with_run()
    ok = await manager.send_keys("proj", "echo hi", literal=True)
    assert ok is True
    assert manager._run.await_args_list[0].args == ("send-keys", "-t", "proj", "-l", "echo hi")
    assert manager._run.await_args_list[1].args == ("send-keys", "-t", "proj", "Enter")


@pytest.mark.asyncio
async def test_send_keys_non_literal_omits_l_flag():
    manager = _manager_with_run()
    await manager.send_keys("proj", "C-c", literal=False)
    assert manager._run.await_args_list[0].args == ("send-keys", "-t", "proj", "C-c")


@pytest.mark.asyncio
async def test_send_keys_returns_false_when_text_send_fails():
    manager = _manager_with_run((1, "", "err"))
    ok = await manager.send_keys("proj", "echo hi")
    assert ok is False


@pytest.mark.asyncio
async def test_capture_pane_builds_capture_args_and_returns_stdout():
    manager = _manager_with_run((0, "captured-output\n", ""))
    out = await manager.capture_pane("proj", lines=50)
    assert out == "captured-output\n"
    manager._run.assert_called_with("capture-pane", "-t", "proj", "-p", "-S", "-50")


@pytest.mark.asyncio
async def test_kill_session_builds_kill_args():
    manager = _manager_with_run()
    await manager.kill_session("proj")
    manager._run.assert_called_with("kill-session", "-t", "proj")


@pytest.mark.asyncio
async def test_session_exists_uses_has_session():
    manager = _manager_with_run((0, "", ""))
    assert await manager.session_exists("proj") is True
    manager._run.assert_called_with("has-session", "-t", "proj")


@pytest.mark.asyncio
async def test_list_sessions_parses_lines():
    manager = _manager_with_run((0, "a\nb\n\n", ""))
    assert await manager.list_sessions() == ["a", "b"]
    manager._run.assert_called_with("list-sessions", "-F", "#{session_name}")


@pytest.mark.asyncio
async def test_rename_session_builds_rename_args():
    manager = _manager_with_run()
    await manager.rename_session("old", "new")
    manager._run.assert_called_with("rename-session", "-t", "old", "new")
