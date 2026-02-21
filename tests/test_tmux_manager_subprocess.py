"""TmuxManager の subprocess 実行エラー処理テスト。"""

import asyncio
import json

import pytest

from src.config.settings import Settings
from src.managers.tmux_manager import TmuxManager


class _FakeProc:
    def __init__(self) -> None:
        self.returncode = None
        self.kill_called = False
        self.terminate_called = False

    async def communicate(self):
        return b"", b""

    async def wait(self):
        self.returncode = -9
        return -9

    def kill(self) -> None:
        self.kill_called = True
        self.returncode = -9

    def terminate(self) -> None:
        self.terminate_called = True
        self.returncode = -15


@pytest.mark.asyncio
async def test_run_timeout_kills_process_and_returns_structured_error(monkeypatch):
    """_run は timeout 時に kill を実行し、構造化エラーを返す。"""
    manager = TmuxManager(Settings())
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

    code, stdout, stderr = await manager._run("list-sessions")

    assert code == 124
    assert stdout == ""
    assert fake_proc.kill_called is True
    assert manager.last_subprocess_error is not None
    assert manager.last_subprocess_error["kind"] == "timeout"
    payload = json.loads(stderr)
    assert payload["kind"] == "timeout"
    # SEC-001: command はエラーレスポンスに含めない
    assert "command" not in payload
    assert "timeout_seconds" in payload


@pytest.mark.asyncio
async def test_run_exec_timeout_kills_process_and_returns_structured_error(monkeypatch):
    """_run_exec は timeout 時に kill を実行し、構造化エラーを返す。"""
    manager = TmuxManager(Settings())
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

    code, stdout, stderr = await manager._run_exec("pgrep", "-x", "tmux")

    assert code == 124
    assert stdout == ""
    assert fake_proc.kill_called is True
    payload = json.loads(stderr)
    assert payload["kind"] == "timeout"
    # SEC-001: command はエラーレスポンスに含めない
    assert "command" not in payload
