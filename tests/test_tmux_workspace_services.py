"""tmux workspace service/planner のテスト。"""

import shlex
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.settings import Settings
from src.managers.pane_layout_planner import PaneLayoutPlanner
from src.managers.session_bootstrapper import SessionBootstrapper
from src.managers.tmux_manager import TmuxManager
from src.managers.tmux_workspace_mixin import TmuxWorkspaceMixin


def test_pane_layout_planner_returns_expected_worker_slots():
    """PaneLayoutPlanner が worker slot を既存仕様どおり返す。"""
    planner = PaneLayoutPlanner(Settings())

    assert planner.get_pane_for_role("owner") is None
    assert planner.get_pane_for_role("admin") == ("main", 0, 0)
    assert planner.get_pane_for_role("worker", 0) == ("main", 0, 1)
    assert planner.get_pane_for_role("worker", 5) == ("main", 0, 6)
    assert planner.get_pane_for_role("worker", 6) == ("main", 1, 0)


@pytest.mark.asyncio
async def test_session_bootstrapper_uses_expected_main_session_flow():
    """SessionBootstrapper が main session 構築手順をまとめて実行する。"""
    manager = MagicMock()
    manager.settings = Settings()
    manager._get_project_name.return_value = "project-abc123"
    manager.session_exists = AsyncMock(return_value=False)
    manager._create_main_session_window = AsyncMock(return_value=True)
    manager._configure_session_options = AsyncMock(return_value=True)
    manager._normalize_window_indices = AsyncMock(return_value=True)
    manager._run = AsyncMock(return_value=(0, "", ""))

    bootstrapper = SessionBootstrapper(manager, PaneLayoutPlanner(manager.settings))
    success = await bootstrapper.create_main_session("/tmp/project")

    assert success is True
    manager._create_main_session_window.assert_awaited_once_with(
        "project-abc123", "/tmp/project"
    )
    manager._configure_session_options.assert_awaited_once_with("project-abc123")
    manager._normalize_window_indices.assert_awaited_once_with("project-abc123")
    assert manager._run.await_count == 6


@pytest.mark.asyncio
async def test_session_bootstrapper_reuses_existing_extra_worker_window():
    """既存の追加 Worker ウィンドウがあれば再作成しない。"""
    manager = MagicMock()
    manager.settings = Settings()
    manager.list_windows = AsyncMock(return_value=[{"index": 1}])
    manager._create_named_window = AsyncMock(return_value=True)
    manager._run = AsyncMock(return_value=(0, "", ""))

    bootstrapper = SessionBootstrapper(manager, PaneLayoutPlanner(manager.settings))
    success = await bootstrapper.add_extra_worker_window("project-abc123", 1)

    assert success is True
    manager._create_named_window.assert_not_awaited()


def test_generate_workspace_script_escapes_malicious_working_dir():
    """working_dir に含まれるシェルメタ文字が安全に引用符化されること。"""
    malicious_wd = '/tmp/foo"; touch /tmp/pwned #'
    script = TmuxWorkspaceMixin._generate_workspace_script(
        MagicMock(), "test-session", malicious_wd
    )

    # shlex.quote 済みの値がそのまま WD= 行に現れる（破壊的展開が起きない）
    assert f"WD={shlex.quote(malicious_wd)}" in script
    # 未エスケープの危険な行 `WD="/tmp/foo"; touch ...` が生成されていない
    assert 'WD="/tmp/foo";' not in script


@pytest.mark.asyncio
async def test_send_interrupt_to_pane_sends_ctrl_c():
    """send_interrupt_to_pane が対象ペインに C-c を送ること。"""
    mgr = TmuxManager(Settings())
    mgr._run = AsyncMock(return_value=(0, "", ""))

    ok = await mgr.send_interrupt_to_pane("sess", 0, 1)

    assert ok is True
    args = mgr._run.await_args.args
    assert args[0] == "send-keys"
    assert "-t" in args
    assert args[-1] == "C-c"
