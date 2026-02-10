"""ターミナル実装の回帰テスト。"""

from unittest.mock import AsyncMock

import pytest

from src.managers.terminal.base import TerminalExecutor
from src.managers.terminal.ghostty import GhosttyExecutor
from src.managers.terminal.iterm2 import ITerm2Executor
from src.managers.terminal.terminal_app import TerminalAppExecutor


class DummyExecutor(TerminalExecutor):
    """TerminalExecutor の抽象実装。"""

    @property
    def name(self) -> str:
        return "dummy"

    async def is_available(self) -> bool:
        return True

    async def execute_script(
        self, working_dir: str, script: str, script_path: str
    ) -> tuple[bool, str]:
        return True, "ok"


class TestTerminalExecutorBase:
    """基底クラスの補助メソッドテスト。"""

    @pytest.mark.asyncio
    async def test_run_osascript_uses_exec_args(self):
        """_run_osascript は引数分離実行を使う。"""
        executor = DummyExecutor()
        executor._run_exec = AsyncMock(return_value=(0, "ok", ""))

        code, stdout, stderr = await executor._run_osascript("return \"ok\"")

        assert (code, stdout, stderr) == (0, "ok", "")
        executor._run_exec.assert_awaited_once_with("osascript", "-e", "return \"ok\"")


class TestGhosttyExecutor:
    """Ghostty 実装のテスト。"""

    @pytest.mark.asyncio
    async def test_open_in_tab_with_single_quote_command(self):
        """シングルクォートを含むコマンドでもタブ実行できる。"""
        error_message = "_run_shell should not be called"
        executor = GhosttyExecutor()
        executor._run_osascript = AsyncMock(return_value=(0, "", ""))
        executor._run_shell = AsyncMock(side_effect=AssertionError(error_message))

        success = await executor._open_in_tab("exec bash '/tmp/it\\'s-script.sh'")

        assert success is True
        executor._run_osascript.assert_awaited_once()
        executor._run_shell.assert_not_called()

    @pytest.mark.asyncio
    async def test_is_running_uses_pgrep_fallback(self):
        """AppleScript 判定失敗時は pgrep 判定で既起動を検出する。"""
        executor = GhosttyExecutor()
        executor._run_osascript = AsyncMock(return_value=(1, "", "osascript error"))
        executor._run_exec = AsyncMock(
            side_effect=[
                (1, "", ""),  # pgrep Ghostty
                (0, "1234\n", ""),  # pgrep ghostty
            ]
        )

        running = await executor._is_running()

        assert running is True
        assert executor._run_exec.await_args_list[0].args == ("pgrep", "-x", "Ghostty")
        assert executor._run_exec.await_args_list[1].args == ("pgrep", "-x", "ghostty")


class TestITerm2Executor:
    """iTerm2 実装のテスト。"""

    @pytest.mark.asyncio
    async def test_execute_script_uses_osascript_exec(self):
        """iTerm2 実装は shell 文字列経由ではなく osascript 実行を使う。"""
        error_message = "_run_shell should not be called"
        executor = ITerm2Executor()
        executor.is_available = AsyncMock(return_value=True)
        executor._run_osascript = AsyncMock(return_value=(0, "tab", ""))
        executor._run_shell = AsyncMock(side_effect=AssertionError(error_message))

        success, message = await executor.execute_script(
            "/tmp",
            "dummy",
            "/tmp/it's-script.sh",
        )

        assert success is True
        assert "タブ" in message
        executor._run_osascript.assert_awaited_once()
        executor._run_shell.assert_not_called()


class TestTerminalAppExecutor:
    """Terminal.app 実装のテスト。"""

    @pytest.mark.asyncio
    async def test_execute_script_uses_osascript_exec(self):
        """Terminal.app 実装は shell 文字列経由ではなく osascript 実行を使う。"""
        error_message = "_run_shell should not be called"
        executor = TerminalAppExecutor()
        executor._run_osascript = AsyncMock(return_value=(0, "tab", ""))
        executor._run_shell = AsyncMock(side_effect=AssertionError(error_message))

        success, message = await executor.execute_script(
            "/tmp",
            "dummy",
            "/tmp/it's-script.sh",
        )

        assert success is True
        assert "タブ" in message
        executor._run_osascript.assert_awaited_once()
        executor._run_shell.assert_not_called()
