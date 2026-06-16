"""TmuxManager の tmux コマンド組み立て検証。"""

from unittest.mock import AsyncMock

import pytest

from src.config.settings import Settings, TerminalApp
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


@pytest.mark.asyncio
async def test_cleanup_sessions_kills_unique_nonempty_and_counts():
    """空文字を除外し重複排除した数だけ kill する。"""
    manager = TmuxManager(Settings())
    manager.kill_session = AsyncMock(return_value=True)
    count = await manager.cleanup_sessions(["a", "b", "b", ""])
    assert count == 2
    assert manager.kill_session.await_count == 2


@pytest.mark.asyncio
async def test_cleanup_all_sessions_uses_list_sessions():
    """list_sessions の結果を cleanup する。"""
    manager = TmuxManager(Settings())
    manager.list_sessions = AsyncMock(return_value=["a", "b"])
    manager.kill_session = AsyncMock(return_value=True)
    assert await manager.cleanup_all_sessions() == 2


@pytest.mark.asyncio
async def test_cleanup_project_session_delegates_to_cleanup_sessions():
    """単一セッション名を cleanup に委譲する。"""
    manager = TmuxManager(Settings())
    manager.kill_session = AsyncMock(return_value=True)
    assert await manager.cleanup_project_session("proj") == 1
    manager.kill_session.assert_awaited_once_with("proj")


@pytest.mark.asyncio
async def test_open_session_in_terminal_rejects_invalid_name():
    """無効なセッション名は opener を呼ばず False を返す。"""
    manager = TmuxManager(Settings())
    manager._open_in_cmux = AsyncMock(return_value=True)
    ok = await manager.open_session_in_terminal("bad name!")
    assert ok is False
    manager._open_in_cmux.assert_not_awaited()


@pytest.mark.asyncio
async def test_open_session_in_terminal_dispatches_to_selected_opener():
    """指定 terminal に対応する opener を呼ぶ。"""
    manager = TmuxManager(Settings())
    manager._open_in_iterm2 = AsyncMock(return_value=True)
    ok = await manager.open_session_in_terminal("mysess", terminal=TerminalApp.ITERM2)
    assert ok is True
    manager._open_in_iterm2.assert_awaited_once()
    attach_cmd = manager._open_in_iterm2.await_args.args[0]
    assert attach_cmd == "tmux attach -t mysess"


@pytest.mark.asyncio
async def test_open_session_in_terminal_auto_falls_back_through_openers():
    """AUTO は成功するまで opener を順に試す。"""
    manager = TmuxManager(Settings())
    manager._open_in_cmux = AsyncMock(return_value=False)
    manager._open_in_ghostty = AsyncMock(return_value=True)
    manager._open_in_iterm2 = AsyncMock(return_value=False)
    manager._open_in_terminal_app = AsyncMock(return_value=False)
    ok = await manager.open_session_in_terminal("mysess", terminal=TerminalApp.AUTO)
    assert ok is True
    manager._open_in_cmux.assert_awaited_once()
    manager._open_in_ghostty.assert_awaited_once()
    manager._open_in_iterm2.assert_not_awaited()
    manager._open_in_terminal_app.assert_not_awaited()


@pytest.mark.asyncio
async def test_open_session_in_terminal_auto_returns_false_when_all_fail():
    """AUTO で全 opener が失敗したら False を返す。"""
    manager = TmuxManager(Settings())
    manager._open_in_cmux = AsyncMock(return_value=False)
    manager._open_in_ghostty = AsyncMock(return_value=False)
    manager._open_in_iterm2 = AsyncMock(return_value=False)
    manager._open_in_terminal_app = AsyncMock(return_value=False)
    ok = await manager.open_session_in_terminal("mysess", terminal=TerminalApp.AUTO)
    assert ok is False
