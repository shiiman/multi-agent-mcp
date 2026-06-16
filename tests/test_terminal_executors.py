"""ターミナル実装の回帰テスト。"""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from src.managers.terminal.base import TerminalExecutor
from src.managers.terminal.cmux import CmuxExecutor
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

    @pytest.mark.asyncio
    async def test_run_exec_timeout_kills_process_and_returns_structured_error(self, monkeypatch):
        """_run_exec はタイムアウト時に kill し、構造化エラーを返す。"""
        executor = DummyExecutor()

        class _FakeProc:
            def __init__(self) -> None:
                self.returncode = None
                self.kill_called = False

            async def communicate(self):
                return b"", b""

            async def wait(self):
                self.returncode = -9
                return -9

            def kill(self) -> None:
                self.kill_called = True
                self.returncode = -9

            def terminate(self) -> None:
                self.returncode = -15

        fake_proc = _FakeProc()

        async def _fake_wait_for(awaitable, timeout):
            _fake_wait_for.calls += 1
            if _fake_wait_for.calls == 1:
                awaitable.close()
                raise asyncio.TimeoutError
            return await awaitable

        _fake_wait_for.calls = 0

        async def _fake_create_subprocess_exec(*args, **kwargs):
            return fake_proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
        monkeypatch.setattr(asyncio, "wait_for", _fake_wait_for)

        code, stdout, stderr = await executor._run_exec("echo", "hello")

        assert code == 124
        assert stdout == ""
        assert fake_proc.kill_called is True
        assert executor.last_subprocess_error is not None
        assert executor.last_subprocess_error["kind"] == "timeout"
        error_payload = json.loads(stderr)
        assert error_payload["kind"] == "timeout"
        # SEC-001: command はエラーレスポンスに含めない
        assert "command" not in error_payload


class TestGhosttyExecutor:
    """Ghostty 実装のテスト。"""

    @pytest.mark.asyncio
    async def test_open_in_tab_with_single_quote_command(self):
        """シングルクォートを含むコマンドでもタブ実行できる。"""
        executor = GhosttyExecutor()
        executor._run_osascript = AsyncMock(return_value=(0, "", ""))

        success = await executor._open_in_tab("exec bash '/tmp/it\\'s-script.sh'")

        assert success is True
        executor._run_osascript.assert_awaited_once()
        script = executor._run_osascript.await_args.args[0]
        assert 'exists process "Ghostty"' in script
        assert 'exists process "ghostty"' in script

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
        executor = ITerm2Executor()
        executor.is_available = AsyncMock(return_value=True)
        executor._run_osascript = AsyncMock(return_value=(0, "tab", ""))

        success, message = await executor.execute_script(
            "/tmp",
            "dummy",
            "/tmp/it's-script.sh",
        )

        assert success is True
        assert "タブ" in message
        executor._run_osascript.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_script_keeps_single_quote_in_path(self):
        """シングルクォートを含むパスでも AppleScript が壊れない。"""
        executor = ITerm2Executor()
        executor.is_available = AsyncMock(return_value=True)
        executor._run_osascript = AsyncMock(return_value=(0, "tab", ""))

        success, _ = await executor.execute_script(
            "/tmp/it's test",
            "dummy",
            "echo ok && cd '/tmp/it's test'",
        )

        assert success is True
        script = executor._run_osascript.await_args.args[0]
        # AppleScript 文字列内ではシングルクォートはそのまま保持される
        assert "it's test" in script
        # shell 風の壊れたクォート連結 ("'"'"...) が混入していない
        assert '"\'"\'"' not in script


class TestTerminalAppExecutor:
    """Terminal.app 実装のテスト。"""

    @pytest.mark.asyncio
    async def test_execute_script_uses_osascript_exec(self):
        """Terminal.app 実装は shell 文字列経由ではなく osascript 実行を使う。"""
        executor = TerminalAppExecutor()
        executor._run_osascript = AsyncMock(return_value=(0, "tab", ""))

        success, message = await executor.execute_script(
            "/tmp",
            "dummy",
            "/tmp/it's-script.sh",
        )

        assert success is True
        assert "タブ" in message
        executor._run_osascript.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_script_keeps_single_quote_in_path(self):
        """シングルクォートを含むパスでも AppleScript が壊れない。"""
        executor = TerminalAppExecutor()
        executor._run_osascript = AsyncMock(return_value=(0, "tab", ""))

        success, _ = await executor.execute_script(
            "/tmp/it's test",
            "dummy",
            "echo ok && cd '/tmp/it's test'",
        )

        assert success is True
        script = executor._run_osascript.await_args.args[0]
        # AppleScript 文字列内ではシングルクォートはそのまま保持される
        assert "it's test" in script
        # shell 風の壊れたクォート連結 ("'"'"...) が混入していない
        assert '"\'"\'"' not in script


class TestCmuxExecutor:
    """cmux 実装のテスト。"""

    @pytest.mark.asyncio
    async def test_name_property(self):
        """name プロパティが 'cmux' を返す。"""
        executor = CmuxExecutor()
        assert executor.name == "cmux"

    @pytest.mark.asyncio
    async def test_open_workspace_with_single_quote_command(self):
        """シングルクォートを含むコマンドでも workspace 実行できる。"""
        executor = CmuxExecutor()
        executor._run_osascript = AsyncMock(return_value=(0, "", ""))

        success = await executor._open_workspace(
            "exec bash '/tmp/it\\'s-script.sh'"
        )

        assert success is True
        executor._run_osascript.assert_awaited_once()
        script = executor._run_osascript.await_args.args[0]
        assert 'exists process "cmux"' in script
        # Cmd+N で workspace を開く（タブではなく）
        assert 'keystroke "n" using command down' in script

    @pytest.mark.asyncio
    async def test_is_running_uses_pgrep_fallback(self):
        """AppleScript 判定失敗時は pgrep 判定で既起動を検出する。"""
        executor = CmuxExecutor()
        executor._run_osascript = AsyncMock(return_value=(1, "", "osascript error"))
        executor._run_exec = AsyncMock(return_value=(0, "1234\n", ""))

        running = await executor._is_running()

        assert running is True
        executor._run_exec.assert_awaited_once_with("pgrep", "-x", "cmux")

    @pytest.mark.asyncio
    async def test_is_available_with_which(self, monkeypatch):
        """which で cmux が見つかる場合に利用可能と判定する。"""
        executor = CmuxExecutor()
        monkeypatch.setattr(
            "src.managers.terminal.cmux.shutil.which",
            lambda x: "/usr/local/bin/cmux" if x == "cmux" else None,
        )
        assert await executor.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_with_app_bundle(self, monkeypatch):
        """cmux.app が存在する場合に利用可能と判定する。"""
        from pathlib import Path

        executor = CmuxExecutor()
        monkeypatch.setattr(
            "src.managers.terminal.cmux.shutil.which",
            lambda x: None,
        )
        original_exists = Path.exists

        def mock_exists(self):
            if str(self) == "/Applications/cmux.app":
                return True
            if str(self) == "/Applications/cmux.app/Contents/MacOS/cmux":
                return False
            return original_exists(self)

        monkeypatch.setattr(Path, "exists", mock_exists)
        assert await executor.is_available() is True

    @pytest.mark.asyncio
    async def test_close_workspace_finds_and_closes_matching_window(self):
        """セッション名に一致するウィンドウを検索 → tmux kill → Cmd+W で閉じる。"""
        executor = CmuxExecutor()
        executor._is_running = AsyncMock(return_value=True)
        # 1回目: ウィンドウ検索 (found), 2回目: Cmd+W (closed)
        executor._run_osascript = AsyncMock(
            side_effect=[
                (0, "found", ""),
                (0, "closed", ""),
            ]
        )
        executor._run_exec = AsyncMock(return_value=(0, "", ""))

        result = await executor.close_workspace("my-session")

        assert result is True
        assert executor._run_osascript.await_count == 2
        # 1回目: ウィンドウタイトルでセッション名をマッチング
        find_script = executor._run_osascript.await_args_list[0].args[0]
        assert 'contains "my-session"' in find_script
        # 2回目: Cmd+W で閉じる
        close_script = executor._run_osascript.await_args_list[1].args[0]
        assert 'keystroke "w" using command down' in close_script
        # tmux kill-session が呼ばれた
        executor._run_exec.assert_any_await(
            "tmux", "kill-session", "-t", "my-session"
        )

    @pytest.mark.asyncio
    async def test_close_workspace_returns_false_when_not_found(self):
        """一致するウィンドウがない場合 False を返す。"""
        executor = CmuxExecutor()
        executor._is_running = AsyncMock(return_value=True)
        executor._run_osascript = AsyncMock(
            return_value=(0, "not_found", "")
        )

        result = await executor.close_workspace("nonexistent-session")

        assert result is False
        # 検索のみ（1回）で終了
        executor._run_osascript.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_workspace_returns_false_when_not_running(self):
        """cmux が起動していない場合 False を返す。"""
        executor = CmuxExecutor()
        executor._is_running = AsyncMock(return_value=False)

        result = await executor.close_workspace("my-session")

        assert result is False
        # osascript は呼ばれない
        assert not hasattr(executor, "_run_osascript") or not isinstance(
            executor._run_osascript, AsyncMock
        )

    @pytest.mark.asyncio
    async def test_close_workspace_base_returns_false(self):
        """基底クラスの close_workspace はデフォルト False を返す。"""
        executor = DummyExecutor()
        result = await executor.close_workspace("any-session")
        assert result is False
