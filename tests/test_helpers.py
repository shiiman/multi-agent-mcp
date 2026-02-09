"""tools/helpers.py のテスト。"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.tmux_manager import TmuxManager
from src.models.agent import Agent, AgentRole, AgentStatus
from src.tools.helpers import (
    check_tool_permission,
    get_mcp_tool_prefix_from_config,
    get_project_root_from_config,
    load_agents_from_file,
    remove_agent_from_file,
    resolve_main_repo_root,
    resolve_project_root,
    save_agent_to_file,
    sync_agents_from_file,
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

    def test_does_not_use_env_fallback_when_disabled(
        self, app_ctx, git_repo, temp_dir, monkeypatch
    ):
        """allow_env_fallback=False で環境変数を使用しないことをテスト。"""
        monkeypatch.chdir(temp_dir)
        monkeypatch.setenv("MCP_PROJECT_ROOT", str(git_repo))

        with pytest.raises(ValueError):
            resolve_project_root(app_ctx, allow_env_fallback=False)


class TestGetProjectRootFromConfig:
    """get_project_root_from_config 関数のテスト。"""

    def test_returns_none_when_no_caller_agent_id(self):
        """caller_agent_id がない場合に None を返すことをテスト。"""
        result = get_project_root_from_config()
        assert result is None

    def test_returns_none_when_agent_not_in_registry(self):
        """レジストリにエージェントがない場合に None を返すことをテスト。"""
        result = get_project_root_from_config(caller_agent_id="nonexistent-agent")
        assert result is None


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


class TestCheckToolPermission:
    """check_tool_permission 関数のテスト。"""

    def test_bootstrap_tool_allows_none_caller(self, app_ctx):
        """BOOTSTRAP_TOOLS は caller_agent_id=None でも許可される。"""
        result = check_tool_permission(app_ctx, "init_tmux_workspace", None)
        assert result is None

    def test_bootstrap_tool_create_agent_allows_none(self, app_ctx):
        """create_agent は BOOTSTRAP_TOOLS なので None でも許可。"""
        result = check_tool_permission(app_ctx, "create_agent", None)
        assert result is None

    def test_non_bootstrap_tool_requires_caller(self, app_ctx):
        """非 BOOTSTRAP ツールで caller_agent_id=None の場合エラー。"""
        result = check_tool_permission(app_ctx, "list_agents", None)
        assert result is not None
        assert result["success"] is False
        assert "caller_agent_id" in result["error"]

    def test_unknown_agent_returns_error(self, app_ctx):
        """存在しないエージェントID でエラーを返す。"""
        result = check_tool_permission(app_ctx, "list_agents", "nonexistent-agent")
        assert result is not None
        assert result["success"] is False
        assert "見つかりません" in result["error"]

    def test_allowed_role_returns_none(self, app_ctx):
        """許可ロールに含まれるエージェントは None を返す（許可）。"""
        # app_ctx.agents には agent-001 (owner) が含まれている
        now = datetime.now()
        app_ctx.agents["test-owner"] = Agent(
            id="test-owner",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            created_at=now,
            last_activity=now,
        )
        result = check_tool_permission(app_ctx, "list_agents", "test-owner")
        assert result is None

    def test_owner_wait_lock_blocks_non_allowed_tool(self, app_ctx):
        """Owner が待機ロック中は許可外ツールを拒否する。"""
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            created_at=now,
            last_activity=now,
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": now,
            "unlocked_at": None,
            "unlock_reason": None,
        }

        result = check_tool_permission(app_ctx, "send_task", "owner-001")
        assert result is not None
        assert result["success"] is False
        assert "owner_wait_locked" in result["error"]
        assert result["waiting_for_admin_id"] == "admin-001"

    def test_owner_wait_lock_allows_read_messages(self, app_ctx):
        """Owner 待機ロック中でも read_messages は許可される。"""
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            created_at=now,
            last_activity=now,
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": now,
            "unlocked_at": None,
            "unlock_reason": None,
        }

        result = check_tool_permission(app_ctx, "read_messages", "owner-001")
        assert result is None

    def test_owner_wait_lock_allows_get_unread_count(self, app_ctx):
        """Owner 待機ロック中でも get_unread_count は許可される。"""
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            created_at=now,
            last_activity=now,
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": now,
            "unlocked_at": None,
            "unlock_reason": None,
        }

        result = check_tool_permission(app_ctx, "get_unread_count", "owner-001")
        assert result is None

    def test_owner_wait_lock_allows_unlock_tool(self, app_ctx):
        """Owner 待機ロック中でも unlock_owner_wait は許可される。"""
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            created_at=now,
            last_activity=now,
        )
        app_ctx._owner_wait_state["owner-001"] = {
            "waiting_for_admin": True,
            "admin_id": "admin-001",
            "session_id": "issue-001",
            "locked_at": now,
            "unlocked_at": None,
            "unlock_reason": None,
        }

        result = check_tool_permission(app_ctx, "unlock_owner_wait", "owner-001")
        assert result is None

    def test_disallowed_role_returns_error(self, app_ctx):
        """許可ロールに含まれないエージェントはエラーを返す。"""
        now = datetime.now()
        app_ctx.agents["test-worker"] = Agent(
            id="test-worker",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            created_at=now,
            last_activity=now,
        )
        # reset_cost_counter は owner のみ許可
        result = check_tool_permission(app_ctx, "reset_cost_counter", "test-worker")
        assert result is not None
        assert result["success"] is False

    def test_undefined_tool_allows_all_roles(self, app_ctx):
        """権限が未定義のツールは全ロール許可。"""
        now = datetime.now()
        app_ctx.agents["test-worker"] = Agent(
            id="test-worker",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            created_at=now,
            last_activity=now,
        )
        result = check_tool_permission(app_ctx, "undefined_tool_xyz", "test-worker")
        assert result is None


class TestAgentFilePersistence:
    """エージェント永続化関数のテスト。"""

    @pytest.fixture
    def persistence_ctx(self, settings, git_repo):
        """永続化テスト用の AppContext を作成する。"""
        from src.tools.helpers_persistence import reset_sync_cache

        # テスト間のキャッシュ副作用を防止
        reset_sync_cache()
        tmux = TmuxManager(settings)
        ai_cli = AiCliManager(settings)
        ctx = AppContext(
            settings=settings,
            tmux=tmux,
            ai_cli=ai_cli,
            project_root=str(git_repo),
            session_id="test-session",
        )
        return ctx

    @pytest.fixture
    def sample_agent(self):
        """テスト用のエージェントを作成する。"""
        now = datetime.now()
        return Agent(
            id="persist-agent-001",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            created_at=now,
            last_activity=now,
            working_dir="/tmp/test",
        )

    def test_save_agent_to_file(self, persistence_ctx, sample_agent):
        """エージェントをファイルに保存できることをテスト。"""
        result = save_agent_to_file(persistence_ctx, sample_agent)
        assert result is True

    def test_load_agents_from_file(self, persistence_ctx, sample_agent):
        """保存済みファイルから Agent を正しく復元できることをテスト。"""
        save_agent_to_file(persistence_ctx, sample_agent)
        agents = load_agents_from_file(persistence_ctx)
        assert "persist-agent-001" in agents
        agent = agents["persist-agent-001"]
        assert agent.role == AgentRole.WORKER.value
        assert agent.status == AgentStatus.IDLE.value

    def test_load_agents_returns_empty_when_no_file(self, persistence_ctx):
        """ファイルが存在しない場合に空 dict を返すことをテスト。"""
        agents = load_agents_from_file(persistence_ctx)
        assert agents == {}

    def test_load_agents_datetime_conversion(self, persistence_ctx, sample_agent):
        """datetime 文字列が正しく変換されることをテスト。"""
        save_agent_to_file(persistence_ctx, sample_agent)
        agents = load_agents_from_file(persistence_ctx)
        agent = agents["persist-agent-001"]
        assert isinstance(agent.created_at, datetime)
        assert isinstance(agent.last_activity, datetime)

    def test_load_agents_defaults_ai_bootstrapped_when_missing(self, persistence_ctx, sample_agent):
        """ai_bootstrapped 欠落時でも False で読み込めることをテスト。"""
        save_agent_to_file(persistence_ctx, sample_agent)
        agents_file = (
            Path(persistence_ctx.project_root)
            / ".multi-agent-mcp"
            / persistence_ctx.session_id
            / "agents.json"
        )
        raw = json.loads(agents_file.read_text(encoding="utf-8"))
        raw["persist-agent-001"].pop("ai_bootstrapped", None)
        agents_file.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

        agents = load_agents_from_file(persistence_ctx)
        assert agents["persist-agent-001"].ai_bootstrapped is False

    def test_sync_agents_from_file(self, persistence_ctx, sample_agent):
        """ファイルの内容が AppContext に同期されることをテスト。"""
        save_agent_to_file(persistence_ctx, sample_agent)
        added = sync_agents_from_file(persistence_ctx)
        assert added == 1
        assert "persist-agent-001" in persistence_ctx.agents

    def test_sync_agents_does_not_overwrite_existing(self, persistence_ctx, sample_agent):
        """既存のエージェントを上書きしないことをテスト。"""
        # メモリにエージェントを追加
        persistence_ctx.agents["persist-agent-001"] = sample_agent
        # ファイルにも保存
        save_agent_to_file(persistence_ctx, sample_agent)
        # sync しても追加数は 0
        added = sync_agents_from_file(persistence_ctx)
        assert added == 0

    def test_remove_agent_from_file(self, persistence_ctx, sample_agent):
        """エージェントをファイルから削除できることをテスト。"""
        save_agent_to_file(persistence_ctx, sample_agent)
        result = remove_agent_from_file(persistence_ctx, "persist-agent-001")
        assert result is True
        # 削除後は空
        agents = load_agents_from_file(persistence_ctx)
        assert "persist-agent-001" not in agents

    def test_remove_nonexistent_agent(self, persistence_ctx, sample_agent):
        """存在しないエージェントID で例外が出ないことをテスト。"""
        save_agent_to_file(persistence_ctx, sample_agent)
        result = remove_agent_from_file(persistence_ctx, "nonexistent-id")
        assert result is False


class TestHelpersImportCompat:
    """helpers.py 分割後の import 互換性テスト。

    全シンボルが from src.tools.helpers import ... で引き続き利用可能であることを確認する。
    """

    def test_git_helpers_reexport(self):
        """helpers_git のシンボルが helpers から import 可能。"""
        from src.tools.helpers import resolve_main_repo_root
        assert callable(resolve_main_repo_root)

    def test_registry_helpers_reexport(self):
        """helpers_registry のシンボルが helpers から import 可能。"""
        from src.tools.helpers import (
            _get_from_config,
            ensure_session_id,
            get_mcp_tool_prefix_from_config,
            get_project_root_from_config,
            get_project_root_from_registry,
            get_session_id_from_config,
            get_session_id_from_registry,
            remove_agent_from_registry,
            remove_agents_by_owner,
            save_agent_to_registry,
        )
        assert callable(save_agent_to_registry)
        assert callable(get_project_root_from_registry)
        assert callable(get_session_id_from_registry)
        assert callable(remove_agent_from_registry)
        assert callable(remove_agents_by_owner)
        assert callable(get_project_root_from_config)
        assert callable(get_mcp_tool_prefix_from_config)
        assert callable(get_session_id_from_config)
        assert callable(ensure_session_id)
        assert callable(_get_from_config)

    def test_persistence_helpers_reexport(self):
        """helpers_persistence のシンボルが helpers から import 可能。"""
        from src.tools.helpers import (
            load_agents_from_file,
            remove_agent_from_file,
            save_agent_to_file,
            sync_agents_from_file,
        )
        assert callable(save_agent_to_file)
        assert callable(load_agents_from_file)
        assert callable(sync_agents_from_file)
        assert callable(remove_agent_from_file)

    def test_managers_helpers_reexport(self):
        """helpers_managers のシンボルが helpers から import 可能。"""
        from src.tools.helpers import (
            ensure_dashboard_manager,
            ensure_global_memory_manager,
            ensure_healthcheck_manager,
            ensure_ipc_manager,
            ensure_memory_manager,
            ensure_persona_manager,
            ensure_scheduler_manager,
            get_gtrconfig_manager,
            get_worktree_manager,
            search_memory_context,
        )
        assert callable(get_worktree_manager)
        assert callable(get_gtrconfig_manager)
        assert callable(ensure_ipc_manager)
        assert callable(ensure_dashboard_manager)
        assert callable(ensure_scheduler_manager)
        assert callable(ensure_healthcheck_manager)
        assert callable(ensure_persona_manager)
        assert callable(ensure_memory_manager)
        assert callable(ensure_global_memory_manager)
        assert callable(search_memory_context)

    def test_direct_submodule_imports(self):
        """各サブモジュールから直接 import も可能。"""
        from src.tools.helpers_git import resolve_main_repo_root
        from src.tools.helpers_managers import ensure_ipc_manager
        from src.tools.helpers_persistence import save_agent_to_file
        from src.tools.helpers_registry import save_agent_to_registry
        assert callable(resolve_main_repo_root)
        assert callable(save_agent_to_registry)
        assert callable(save_agent_to_file)
        assert callable(ensure_ipc_manager)

    def test_core_functions_remain_in_helpers(self):
        """コア関数が helpers.py に直接定義されていることを確認。"""
        from src.tools.helpers import (
            BOOTSTRAP_TOOLS,
            check_tool_permission,
            ensure_project_root_from_caller,
            find_agents_by_role,
            get_agent_role,
            resolve_project_root,
        )
        assert callable(check_tool_permission)
        assert callable(resolve_project_root)
        assert callable(ensure_project_root_from_caller)
        assert callable(get_agent_role)
        assert callable(find_agents_by_role)
        assert isinstance(BOOTSTRAP_TOOLS, set)


class TestRequirePermission:
    """get_app_ctx / require_permission ヘルパーのテスト。"""

    def _make_mock_ctx(self, app_ctx):
        """テスト用の mock Context を作成する。"""
        ctx = MagicMock()
        ctx.request_context.lifespan_context = app_ctx
        return ctx

    def test_get_app_ctx(self, app_ctx):
        """get_app_ctx が AppContext を正しく取得する。"""
        from src.tools.helpers import get_app_ctx

        ctx = self._make_mock_ctx(app_ctx)
        result = get_app_ctx(ctx)
        assert result is app_ctx

    @patch("src.tools.helpers.sync_agents_from_file")
    def test_require_permission_allowed(self, mock_sync, app_ctx):
        """権限OK時に (app_ctx, None) を返す。"""
        from src.tools.helpers import require_permission

        # Owner エージェントを登録
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir="/tmp",
            created_at=now,
            last_activity=now,
        )

        ctx = self._make_mock_ctx(app_ctx)
        result_ctx, error = require_permission(ctx, "create_task", "owner-001")
        assert result_ctx is app_ctx
        assert error is None

    @patch("src.tools.helpers.sync_agents_from_file")
    def test_require_permission_denied(self, mock_sync, app_ctx):
        """権限エラー時に (app_ctx, error_dict) を返す。"""
        from src.tools.helpers import require_permission

        ctx = self._make_mock_ctx(app_ctx)
        # caller_agent_id=None は非 BOOTSTRAP ツールではエラー
        result_ctx, error = require_permission(ctx, "get_dashboard", None)
        assert result_ctx is app_ctx
        assert error is not None
        assert error["success"] is False


class TestEnsureDashboardManager:
    """ensure_dashboard_manager のセッション切替挙動テスト。"""

    def test_recreate_dashboard_manager_on_session_switch(self, app_ctx, git_repo):
        from src.managers.dashboard_manager import DashboardManager
        from src.tools.helpers_managers import ensure_dashboard_manager

        # 旧セッションの manager をセット
        app_ctx.project_root = str(git_repo)
        app_ctx.session_id = "old-session"
        old_dir = git_repo / ".multi-agent-mcp" / "old-session" / "dashboard"
        app_ctx.workspace_id = "old-session"
        app_ctx.dashboard_manager = DashboardManager(
            workspace_id="old-session",
            workspace_path=str(git_repo),
            dashboard_dir=str(old_dir),
        )

        # 新セッションへ切替
        app_ctx.session_id = "new-session"
        manager = ensure_dashboard_manager(app_ctx)

        assert manager.workspace_id == "new-session"
        assert str(manager.dashboard_dir).endswith(
            ".multi-agent-mcp/new-session/dashboard"
        )
        assert app_ctx.workspace_id == "new-session"


class TestCodexPromptDetection:
    """Codex 入力残留判定のテスト。"""

    def test_pending_codex_prompt_detects_prefix_match(self):
        from src.managers.tmux_workspace_mixin import TmuxWorkspaceMixin

        output = "\n".join([
            "some logs...",
            "› [IPC] 新しいメッセージ: task_progress from worker-001",
        ])
        command = "[IPC] 新しいメッセージ: task_progress from worker-001"

        assert TmuxWorkspaceMixin._is_pending_codex_prompt(output, command) is True

    def test_pending_codex_prompt_returns_true_with_tab_hint(self):
        """'tab to queue message' ヒントが表示中は未確定と判定する。"""
        from src.managers.tmux_workspace_mixin import TmuxWorkspaceMixin

        output = "\n".join([
            "processed",
            "›",
            "tab to queue message",
        ])
        command = "[IPC] 新しいメッセージ: task_progress from worker-001"

        # "tab to queue message" はCodexが入力バッファにテキストがある状態を示す
        assert TmuxWorkspaceMixin._is_pending_codex_prompt(output, command) is True

    def test_pending_codex_prompt_returns_false_after_confirmed(self):
        """入力確定後（プロンプト復帰・ヒントなし）は False を返す。"""
        from src.managers.tmux_workspace_mixin import TmuxWorkspaceMixin

        output = "\n".join([
            "processed",
            "›",
        ])
        command = "[IPC] 新しいメッセージ: task_progress from worker-001"

        assert TmuxWorkspaceMixin._is_pending_codex_prompt(output, command) is False
