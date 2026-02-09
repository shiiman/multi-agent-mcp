"""TmuxManager のターミナル起動分岐テスト。"""

from unittest.mock import AsyncMock, patch

import pytest

from src.config.settings import Settings
from src.managers.tmux_manager import TmuxManager


class TestTmuxManagerTerminalOpen:
    """open_session_in_terminal 系のテスト。"""

    @pytest.mark.asyncio
    async def test_open_in_ghostty_prefers_tab_when_running(self):
        """Ghostty 起動中は新規ウィンドウではなくタブ追加を優先する。"""
        manager = TmuxManager(Settings())
        manager._run_exec = AsyncMock(side_effect=[(0, "true", ""), (0, "", "")])

        with patch("shutil.which", return_value="/usr/local/bin/ghostty"):
            success = await manager._open_in_ghostty("tmux attach -t test")

        assert success is True
        assert manager._run_exec.await_count == 2
        assert manager._run_exec.await_args_list[0].args[:2] == ("osascript", "-e")
        assert manager._run_exec.await_args_list[1].args[:2] == ("osascript", "-e")

    @pytest.mark.asyncio
    async def test_open_in_ghostty_falls_back_to_window_when_tab_fails(self):
        """タブ追加失敗時は新規ウィンドウ起動へフォールバックする。"""
        manager = TmuxManager(Settings())
        manager._run_exec = AsyncMock(side_effect=[(0, "true", ""), (1, "", "err"), (0, "", "")])

        with (
            patch("shutil.which", return_value="/usr/local/bin/ghostty"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            success = await manager._open_in_ghostty("tmux attach -t test")

        assert success is True
        fallback_call = manager._run_exec.await_args_list[-1].args
        assert fallback_call[:4] == ("open", "-a", "Ghostty.app", "--args")
        assert fallback_call[4] == "-e"

    @pytest.mark.asyncio
    async def test_open_in_iterm2_contains_tab_branch(self):
        """iTerm2 は既存ウィンドウ時のタブ分岐を持つ。"""
        manager = TmuxManager(Settings())
        manager._run_exec = AsyncMock(return_value=(0, "", ""))

        success = await manager._open_in_iterm2("tmux attach -t test")

        assert success is True
        script = manager._run_exec.await_args.args[2]
        assert "if (count of windows) > 0 then" in script
        assert "create tab with default profile" in script

    @pytest.mark.asyncio
    async def test_open_in_terminal_app_contains_tab_branch(self):
        """Terminal.app は既存ウィンドウ時のタブ分岐を持つ。"""
        manager = TmuxManager(Settings())
        manager._run_exec = AsyncMock(return_value=(0, "", ""))

        success = await manager._open_in_terminal_app("tmux attach -t test")

        assert success is True
        script = manager._run_exec.await_args.args[2]
        assert "if (count of windows) > 0 then" in script
        assert "tell front window" in script
