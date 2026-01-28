"""pytest設定とフィクスチャ。"""

import os
import tempfile
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.managers.dashboard_manager import DashboardManager
from src.managers.ipc_manager import IPCManager
from src.managers.tmux_manager import TmuxManager


@pytest.fixture
def temp_dir():
    """一時ディレクトリを作成する。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def settings(temp_dir):
    """テスト用の設定を作成する。"""
    return Settings(
        workspace_base_dir=str(temp_dir / "workspaces"),
        max_workers=3,
        tmux_prefix="test-mcp-agent",
    )


@pytest.fixture
def tmux_manager(settings):
    """TmuxManagerインスタンスを作成する。"""
    return TmuxManager(settings)


@pytest.fixture
def ipc_manager(temp_dir):
    """IPCManagerインスタンスを作成する。"""
    ipc_dir = temp_dir / ".ipc"
    manager = IPCManager(str(ipc_dir))
    manager.initialize()
    yield manager
    manager.cleanup()


@pytest.fixture
def dashboard_manager(temp_dir):
    """DashboardManagerインスタンスを作成する。"""
    dashboard_dir = temp_dir / ".dashboard"
    manager = DashboardManager(
        workspace_id="test-workspace",
        workspace_path=str(temp_dir),
        dashboard_dir=str(dashboard_dir),
    )
    manager.initialize()
    yield manager
    manager.cleanup()


@pytest.fixture
def git_repo(temp_dir):
    """テスト用のgitリポジトリを作成する。"""
    repo_path = temp_dir / "repo"
    repo_path.mkdir()
    os.system(f"cd {repo_path} && git init && git commit --allow-empty -m 'init'")
    return repo_path
