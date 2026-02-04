"""tools/helpers.py のテスト。"""

import json
import os
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.tmux_manager import TmuxManager
from src.tools.helpers import (
    get_mcp_tool_prefix_from_config,
    get_project_root_from_config,
    resolve_main_repo_root,
    resolve_project_root,
)


@pytest.fixture
def app_ctx(settings):
    """テスト用の AppContext を作成する。"""
    tmux = TmuxManager(settings)
    ai_cli = AiCliManager(settings)
    return AppContext(settings=settings, tmux=tmux, ai_cli=ai_cli)


class TestResolveMainRepoRoot:
    """resolve_main_repo_root 関数のテスト。"""

    def test_raises_value_error_for_non_git_directory(self, temp_dir):
        """git リポジトリでないディレクトリで ValueError を発生させることをテスト。"""
        with pytest.raises(ValueError) as exc_info:
            resolve_main_repo_root(str(temp_dir))

        assert "git リポジトリではありません" in str(exc_info.value)

    def test_returns_same_path_for_main_repo(self, git_repo):
        """メインリポジトリのパスをそのまま返すことをテスト。"""
        result = resolve_main_repo_root(str(git_repo))
        # macOS では /var → /private/var のシンボリックリンク解決が発生するため
        # Path.resolve() で正規化して比較
        assert Path(result).resolve() == git_repo.resolve()


class TestResolveProjectRoot:
    """resolve_project_root 関数のテスト。"""

    def test_returns_project_root_from_context(self, app_ctx, git_repo):
        """AppContext の project_root を返すことをテスト。"""
        app_ctx.project_root = str(git_repo)

        result = resolve_project_root(app_ctx)
        assert Path(result).resolve() == git_repo.resolve()

    def test_raises_value_error_when_no_project_root(self, app_ctx, temp_dir, monkeypatch):
        """project_root が設定されていない場合に ValueError を発生させることをテスト。"""
        # config.json も存在しない状態
        monkeypatch.chdir(temp_dir)

        with pytest.raises(ValueError) as exc_info:
            resolve_project_root(app_ctx)

        assert "project_root が設定されていません" in str(exc_info.value)

    def test_uses_env_fallback_when_enabled(self, app_ctx, git_repo, temp_dir, monkeypatch):
        """allow_env_fallback=True で環境変数から取得できることをテスト。"""
        monkeypatch.chdir(temp_dir)
        monkeypatch.setenv("MCP_PROJECT_ROOT", str(git_repo))

        result = resolve_project_root(app_ctx, allow_env_fallback=True)
        assert Path(result).resolve() == git_repo.resolve()

    def test_does_not_use_env_fallback_when_disabled(self, app_ctx, git_repo, temp_dir, monkeypatch):
        """allow_env_fallback=False で環境変数を使用しないことをテスト。"""
        monkeypatch.chdir(temp_dir)
        monkeypatch.setenv("MCP_PROJECT_ROOT", str(git_repo))

        with pytest.raises(ValueError):
            resolve_project_root(app_ctx, allow_env_fallback=False)


class TestGetProjectRootFromConfig:
    """get_project_root_from_config 関数のテスト。"""

    def test_returns_none_when_no_config(self, temp_dir, monkeypatch):
        """config.json が存在しない場合に None を返すことをテスト。"""
        monkeypatch.chdir(temp_dir)
        result = get_project_root_from_config()
        assert result is None

    def test_returns_project_root_from_config(self, temp_dir, monkeypatch):
        """config.json から project_root を取得できることをテスト。"""
        monkeypatch.chdir(temp_dir)

        # config.json を作成
        mcp_dir = temp_dir / ".multi-agent-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)
        config_file = mcp_dir / "config.json"
        config_file.write_text(json.dumps({"project_root": "/some/path"}))

        result = get_project_root_from_config()
        assert result == "/some/path"

    def test_returns_none_when_project_root_missing_in_config(self, temp_dir, monkeypatch):
        """config.json に project_root がない場合に None を返すことをテスト。"""
        monkeypatch.chdir(temp_dir)

        # project_root なしの config.json を作成
        mcp_dir = temp_dir / ".multi-agent-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)
        config_file = mcp_dir / "config.json"
        config_file.write_text(json.dumps({"other_key": "value"}))

        result = get_project_root_from_config()
        assert result is None

    def test_uses_working_dir_parameter(self, git_repo):
        """working_dir パラメータを使用できることをテスト。"""
        # working_dir 内に config.json を作成
        mcp_dir = git_repo / ".multi-agent-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)
        config_file = mcp_dir / "config.json"
        # シンボリックリンク解決後のパスを使用
        resolved_path = str(git_repo.resolve())
        config_file.write_text(json.dumps({"project_root": resolved_path}))

        result = get_project_root_from_config(working_dir=str(git_repo))
        assert result == resolved_path


class TestGetMcpToolPrefixFromConfig:
    """get_mcp_tool_prefix_from_config 関数のテスト。"""

    def test_returns_default_when_no_config(self, temp_dir, monkeypatch):
        """config.json が存在しない場合にデフォルト値を返すことをテスト。"""
        monkeypatch.chdir(temp_dir)
        result = get_mcp_tool_prefix_from_config()
        assert result == "mcp__multi-agent-mcp__"

    def test_returns_prefix_from_config(self, temp_dir, monkeypatch):
        """config.json から mcp_tool_prefix を取得できることをテスト。"""
        monkeypatch.chdir(temp_dir)

        # config.json を作成
        mcp_dir = temp_dir / ".multi-agent-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)
        config_file = mcp_dir / "config.json"
        config_file.write_text(json.dumps({"mcp_tool_prefix": "mcp__custom-server__"}))

        result = get_mcp_tool_prefix_from_config()
        assert result == "mcp__custom-server__"

    def test_returns_default_when_prefix_missing_in_config(self, temp_dir, monkeypatch):
        """config.json に mcp_tool_prefix がない場合にデフォルト値を返すことをテスト。"""
        monkeypatch.chdir(temp_dir)

        # mcp_tool_prefix なしの config.json を作成
        mcp_dir = temp_dir / ".multi-agent-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)
        config_file = mcp_dir / "config.json"
        config_file.write_text(json.dumps({"project_root": "/some/path"}))

        result = get_mcp_tool_prefix_from_config()
        assert result == "mcp__multi-agent-mcp__"

    def test_uses_working_dir_parameter(self, git_repo):
        """working_dir パラメータを使用できることをテスト。"""
        # working_dir 内に config.json を作成
        mcp_dir = git_repo / ".multi-agent-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)
        config_file = mcp_dir / "config.json"
        config_file.write_text(json.dumps({"mcp_tool_prefix": "mcp__test-server__"}))

        result = get_mcp_tool_prefix_from_config(working_dir=str(git_repo))
        assert result == "mcp__test-server__"
