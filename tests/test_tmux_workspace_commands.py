"""TmuxWorkspaceMixin のペイン/セッションコマンド組み立て検証。"""

from unittest.mock import AsyncMock, call

import pytest

from src.config.settings import Settings
from src.managers.tmux_manager import TmuxManager


def _manager(run_return=(0, "", "")):
    manager = TmuxManager(Settings())
    manager._run = AsyncMock(return_value=run_return)
    return manager


@pytest.mark.asyncio
async def test_capture_pane_by_index_builds_args_and_returns_stdout():
    manager = _manager((0, "captured\n", ""))
    target = manager._pane_target("sess", 1, 2)
    out = await manager.capture_pane_by_index("sess", 1, 2, lines=80)
    assert out == "captured\n"
    manager._run.assert_called_with("capture-pane", "-t", target, "-p", "-S", "-80")


@pytest.mark.asyncio
async def test_capture_pane_by_index_returns_empty_on_error():
    manager = _manager((1, "", "err"))
    assert await manager.capture_pane_by_index("sess", 0, 0) == ""


@pytest.mark.asyncio
async def test_get_pane_current_command_builds_display_message_args():
    manager = _manager((0, "codex\n", ""))
    target = manager._pane_target("sess", 0, 1)
    cmd = await manager.get_pane_current_command("sess", 0, 1)
    assert cmd == "codex"
    manager._run.assert_called_with(
        "display-message", "-p", "-t", target, "#{pane_current_command}"
    )


@pytest.mark.asyncio
async def test_get_pane_current_command_none_on_empty_or_error():
    assert await _manager((0, "  \n", "")).get_pane_current_command("s", 0, 0) is None
    assert await _manager((1, "", "x")).get_pane_current_command("s", 0, 0) is None


@pytest.mark.asyncio
async def test_set_pane_title_builds_select_pane_args():
    manager = _manager()
    target = manager._pane_target("sess", 0, 3)
    ok = await manager.set_pane_title("sess", 0, 3, "Worker 3")
    assert ok is True
    manager._run.assert_called_with("select-pane", "-t", target, "-T", "Worker 3")


@pytest.mark.asyncio
async def test_list_windows_parses_format_output():
    manager = _manager((0, "0:main:7\n1:workers-1:10\n\n", ""))
    windows = await manager.list_windows("sess")
    assert windows == [
        {"index": 0, "name": "main", "panes": 7},
        {"index": 1, "name": "workers-1", "panes": 10},
    ]
    manager._run.assert_called_with(
        "list-windows", "-t", "sess", "-F", "#{window_index}:#{window_name}:#{window_panes}"
    )


@pytest.mark.asyncio
async def test_get_pane_count_returns_matching_window_panes():
    manager = _manager((0, "0:main:7\n1:workers-1:10\n", ""))
    assert await manager.get_pane_count("sess", 1) == 10
    assert await manager.get_pane_count("sess", 9) == 0


@pytest.mark.asyncio
async def test_create_main_session_window_builds_new_session_with_name():
    manager = _manager()
    ok = await manager._create_main_session_window("sess", "/wd")
    assert ok is True
    manager._run.assert_called_with(
        "new-session", "-d", "-s", "sess", "-c", "/wd",
        "-n", manager.settings.window_name_main,
    )


@pytest.mark.asyncio
async def test_create_main_session_window_returns_false_on_error():
    manager = _manager((1, "", "boom"))
    assert await manager._create_main_session_window("sess", "/wd") is False


@pytest.mark.asyncio
async def test_configure_session_options_sets_base_index_options():
    manager = _manager()
    ok = await manager._configure_session_options("sess")
    assert ok is True
    main = manager.settings.window_name_main
    manager._run.assert_has_awaits([
        call("set-option", "-t", "sess", "base-index", "0"),
        call("set-option", "-t", "sess", "pane-base-index", "0"),
        call("set-window-option", "-t", f"sess:{main}", "pane-base-index", "0"),
    ])


@pytest.mark.asyncio
async def test_normalize_window_indices_builds_move_window_args():
    manager = _manager()
    ok = await manager._normalize_window_indices("sess")
    assert ok is True
    manager._run.assert_called_with("move-window", "-r", "-t", "sess")
