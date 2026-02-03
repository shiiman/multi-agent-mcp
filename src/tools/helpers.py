"""MCPツール用共通ヘルパー関数。"""

import json
import logging
import os
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from src.context import AppContext

logger = logging.getLogger(__name__)
from src.managers.cost_manager import CostManager
from src.managers.dashboard_manager import DashboardManager
from src.managers.gtrconfig_manager import GtrconfigManager
from src.managers.healthcheck_manager import HealthcheckManager
from src.managers.ipc_manager import IPCManager
from src.managers.memory_manager import MemoryManager
from src.managers.metrics_manager import MetricsManager
from src.managers.persona_manager import PersonaManager
from src.managers.scheduler_manager import SchedulerManager
from src.managers.worktree_manager import WorktreeManager
from src.models.agent import Agent, AgentRole


# ========== Git ヘルパー ==========


def resolve_main_repo_root(path: str | Path) -> str:
    """パスからメインリポジトリのルートを解決する。

    git worktree の場合はメインリポジトリのルートを返す。
    通常のリポジトリの場合はそのままルートを返す。

    Args:
        path: 解決するパス（worktree またはリポジトリ内のパス）

    Returns:
        メインリポジトリのルートパス
    """
    path = Path(path)

    try:
        # git rev-parse --show-toplevel でリポジトリのルートを取得
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path),
            capture_output=True,
            text=True,
            check=True,
        )
        repo_root = result.stdout.strip()

        # git rev-parse --git-common-dir でメインリポジトリの .git を取得
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(path),
            capture_output=True,
            text=True,
            check=True,
        )
        git_common_dir = result.stdout.strip()

        # .git が絶対パスでない場合は repo_root からの相対パス
        if not os.path.isabs(git_common_dir):
            git_common_dir = os.path.join(repo_root, git_common_dir)

        # .git/worktrees/xxx の形式なら、メインリポジトリは .git の親
        git_common_dir = os.path.normpath(git_common_dir)
        if git_common_dir.endswith(".git"):
            # 通常のリポジトリ（worktree ではない）
            return os.path.dirname(git_common_dir)
        elif "/.git/" in git_common_dir or git_common_dir.endswith("/.git"):
            # worktree: /path/to/main-repo/.git/worktrees/xxx → /path/to/main-repo
            git_dir_index = git_common_dir.find("/.git")
            return git_common_dir[:git_dir_index]
        else:
            # フォールバック
            return repo_root

    except subprocess.CalledProcessError:
        # git コマンドが失敗した場合はそのまま返す
        return str(path)


# ========== ロールチェック ヘルパー ==========


def get_agent_role(app_ctx: AppContext, agent_id: str) -> AgentRole | None:
    """エージェントIDからロールを取得する。

    Args:
        app_ctx: アプリケーションコンテキスト
        agent_id: エージェントID

    Returns:
        エージェントのロール、見つからない場合はNone
    """
    agent = app_ctx.agents.get(agent_id)
    if agent:
        return AgentRole(agent.role)
    return None


def check_role_permission(
    app_ctx: AppContext,
    caller_agent_id: str | None,
    allowed_roles: list[str],
) -> dict[str, Any] | None:
    """ロール権限をチェックする。

    Args:
        app_ctx: アプリケーションコンテキスト
        caller_agent_id: 呼び出し元エージェントID
        allowed_roles: 許可されたロールのリスト

    Returns:
        権限エラーの場合はエラー dict、許可されている場合は None
    """
    if caller_agent_id is None:
        return {
            "success": False,
            "error": "caller_agent_id が必要です（このツールはロール制限があります）",
        }

    role = get_agent_role(app_ctx, caller_agent_id)
    if role is None:
        return {
            "success": False,
            "error": f"エージェント {caller_agent_id} が見つかりません",
        }

    if role.value not in allowed_roles:
        return {
            "success": False,
            "error": f"このツールは {allowed_roles} のみ使用可能です（現在: {role.value}）",
        }

    return None


def find_agents_by_role(app_ctx: AppContext, role: str) -> list[str]:
    """指定されたロールのエージェントIDを取得する。

    Args:
        app_ctx: アプリケーションコンテキスト
        role: 検索するロール（"owner", "admin", "worker"）

    Returns:
        該当するエージェントIDのリスト
    """
    return [
        agent_id
        for agent_id, agent in app_ctx.agents.items()
        if agent.role == role
    ]


# ========== Manager初期化ヘルパー ==========


def get_worktree_manager(app_ctx: AppContext, repo_path: str) -> WorktreeManager:
    """指定リポジトリのWorktreeManagerを取得または作成する。"""
    if repo_path not in app_ctx.worktree_managers:
        app_ctx.worktree_managers[repo_path] = WorktreeManager(repo_path)
    return app_ctx.worktree_managers[repo_path]


def get_gtrconfig_manager(app_ctx: AppContext, project_path: str) -> GtrconfigManager:
    """指定プロジェクトのGtrconfigManagerを取得または作成する。"""
    if project_path not in app_ctx.gtrconfig_managers:
        app_ctx.gtrconfig_managers[project_path] = GtrconfigManager(project_path)
    return app_ctx.gtrconfig_managers[project_path]


def ensure_ipc_manager(app_ctx: AppContext) -> IPCManager:
    """IPCManagerが初期化されていることを確認する。

    worktree 内で実行されている場合でも、メインリポジトリの IPC ディレクトリを使用する。
    これにより、Admin/Worker（worktree内）と Owner（メインリポジトリ）間の
    メッセージ配信が正しく機能する。
    """
    if app_ctx.ipc_manager is None:
        # project_root を決定（複数のソースから取得を試みる）
        base_dir = app_ctx.project_root

        # config.json から取得（init_tmux_workspace で設定される）
        if not base_dir:
            base_dir = get_project_root_from_config()

        # フォールバック: workspace_base_dir
        if not base_dir:
            base_dir = app_ctx.settings.workspace_base_dir

        # worktree の場合はメインリポジトリのパスを使用
        if base_dir:
            base_dir = resolve_main_repo_root(base_dir)

        ipc_dir = os.path.join(base_dir, ".multi-agent-mcp", ".ipc")
        app_ctx.ipc_manager = IPCManager(ipc_dir)
        app_ctx.ipc_manager.initialize()
    return app_ctx.ipc_manager


def ensure_dashboard_manager(app_ctx: AppContext) -> DashboardManager:
    """DashboardManagerが初期化されていることを確認する。

    worktree 内で実行されている場合でも、メインリポジトリの Dashboard ディレクトリを使用する。
    これにより、全エージェント間で Dashboard state が正しく同期される。
    """
    if app_ctx.dashboard_manager is None:
        if app_ctx.workspace_id is None:
            app_ctx.workspace_id = str(uuid.uuid4())[:8]

        # project_root を決定（複数のソースから取得を試みる）
        base_dir = app_ctx.project_root

        # config.json から取得（init_tmux_workspace で設定される）
        if not base_dir:
            base_dir = get_project_root_from_config()

        # フォールバック: workspace_base_dir
        if not base_dir:
            base_dir = app_ctx.settings.workspace_base_dir

        # worktree の場合はメインリポジトリのパスを使用
        if base_dir:
            base_dir = resolve_main_repo_root(base_dir)

        dashboard_dir = os.path.join(base_dir, ".multi-agent-mcp", ".dashboard")
        app_ctx.dashboard_manager = DashboardManager(
            workspace_id=app_ctx.workspace_id,
            workspace_path=base_dir,
            dashboard_dir=dashboard_dir,
        )
        app_ctx.dashboard_manager.initialize()
    return app_ctx.dashboard_manager


def ensure_scheduler_manager(app_ctx: AppContext) -> SchedulerManager:
    """SchedulerManagerが初期化されていることを確認する。"""
    if app_ctx.scheduler_manager is None:
        dashboard = ensure_dashboard_manager(app_ctx)
        app_ctx.scheduler_manager = SchedulerManager(dashboard, app_ctx.agents)
    return app_ctx.scheduler_manager


def ensure_healthcheck_manager(app_ctx: AppContext) -> HealthcheckManager:
    """HealthcheckManagerが初期化されていることを確認する。"""
    if app_ctx.healthcheck_manager is None:
        app_ctx.healthcheck_manager = HealthcheckManager(
            app_ctx.tmux,
            app_ctx.agents,
            app_ctx.settings.heartbeat_timeout_seconds,
        )
    return app_ctx.healthcheck_manager


def ensure_metrics_manager(app_ctx: AppContext) -> MetricsManager:
    """MetricsManagerが初期化されていることを確認する。"""
    if app_ctx.metrics_manager is None:
        metrics_dir = os.path.join(app_ctx.settings.workspace_base_dir, ".metrics")
        app_ctx.metrics_manager = MetricsManager(metrics_dir)
    return app_ctx.metrics_manager


def ensure_cost_manager(app_ctx: AppContext) -> CostManager:
    """CostManagerが初期化されていることを確認する。"""
    if app_ctx.cost_manager is None:
        app_ctx.cost_manager = CostManager(
            app_ctx.settings.cost_warning_threshold_usd
        )
    return app_ctx.cost_manager


def ensure_persona_manager(app_ctx: AppContext) -> PersonaManager:
    """PersonaManagerが初期化されていることを確認する。"""
    if app_ctx.persona_manager is None:
        app_ctx.persona_manager = PersonaManager()
    return app_ctx.persona_manager


def ensure_memory_manager(app_ctx: AppContext) -> MemoryManager:
    """MemoryManagerが初期化されていることを確認する。

    worktree 内で実行されている場合でも、メインリポジトリの memory ディレクトリを使用する。
    これにより、全エージェントの完了報告が同じ memory.json に保存される。
    """
    if app_ctx.memory_manager is None:
        # プロジェクトルートを決定
        project_root = app_ctx.project_root

        # config.json から取得（init_tmux_workspace で設定される）
        if not project_root:
            project_root = get_project_root_from_config()
            if project_root:
                logger.info(f"config.json から project_root を取得: {project_root}")

        # MCP_PROJECT_ROOT 環境変数をチェック（フォールバック）
        if not project_root:
            env_project_root = os.getenv("MCP_PROJECT_ROOT")
            if env_project_root:
                project_root = env_project_root
                logger.info(f"MCP_PROJECT_ROOT 環境変数から取得: {project_root}")

        # エージェントの working_dir または worktree_path から取得
        if not project_root:
            sync_agents_from_file(app_ctx)
            for agent in app_ctx.agents.values():
                if agent.working_dir:
                    project_root = resolve_main_repo_root(agent.working_dir)
                    break
                elif agent.worktree_path:
                    project_root = resolve_main_repo_root(agent.worktree_path)
                    break

        # それでも未設定の場合は workspace_base_dir を使用
        if not project_root:
            project_root = app_ctx.settings.workspace_base_dir

        # worktree の場合はメインリポジトリのパスを使用
        if project_root:
            project_root = resolve_main_repo_root(project_root)

        # project_root を設定（次回以降のために）
        if project_root and not app_ctx.project_root:
            app_ctx.project_root = project_root
            logger.info(f"project_root を自動設定: {project_root}")

        # .multi-agent-mcp/memory/memory.json に保存
        memory_path = os.path.join(project_root, ".multi-agent-mcp", "memory", "memory.json")
        app_ctx.memory_manager = MemoryManager(storage_path=memory_path)
    return app_ctx.memory_manager


# グローバルメモリマネージャーのキャッシュ（アプリケーション全体で共有）
_global_memory_manager: MemoryManager | None = None


def ensure_global_memory_manager() -> MemoryManager:
    """グローバルMemoryManagerが初期化されていることを確認する。"""
    global _global_memory_manager
    if _global_memory_manager is None:
        _global_memory_manager = MemoryManager.from_global()
    return _global_memory_manager


# ========== プロジェクト設定ヘルパー ==========


def get_project_root_from_config(working_dir: str | None = None) -> str | None:
    """config.json から project_root を取得する。

    init_tmux_workspace で作成された config.json を読み取る。
    working_dir が指定された場合、そのディレクトリの config.json を探す。
    指定されない場合、カレントディレクトリから親方向に探索する。

    Args:
        working_dir: 探索開始ディレクトリ（オプション）

    Returns:
        project_root のパス、見つからない場合は None
    """
    search_dirs = []

    if working_dir:
        search_dirs.append(Path(working_dir))
        # worktree の場合、メインリポジトリを探す
        main_repo = resolve_main_repo_root(working_dir)
        if main_repo != working_dir:
            search_dirs.append(Path(main_repo))

    # カレントディレクトリからも探索
    cwd = Path.cwd()
    search_dirs.append(cwd)

    for base_dir in search_dirs:
        config_file = base_dir / ".multi-agent-mcp" / "config.json"
        if config_file.exists():
            try:
                with open(config_file, encoding="utf-8") as f:
                    config = json.load(f)
                project_root = config.get("project_root")
                if project_root:
                    logger.debug(f"config.json から project_root を取得: {project_root}")
                    return project_root
            except Exception as e:
                logger.warning(f"config.json の読み込みに失敗: {e}")

    return None


# ========== エージェント永続化ヘルパー ==========


def _get_agents_file_path(project_root: str | None) -> Path | None:
    """エージェント情報ファイルのパスを取得する。

    Args:
        project_root: プロジェクトルートパス

    Returns:
        agents.json のパス、project_root が None の場合は None
    """
    if not project_root:
        return None
    return Path(project_root) / ".multi-agent-mcp" / "agents.json"


def save_agent_to_file(app_ctx: AppContext, agent: "Agent") -> bool:
    """エージェント情報をファイルに保存する。

    worktree 内で実行されている場合でも、メインリポジトリの agents.json に保存する。
    これにより、全エージェント（Owner/Admin/Workers）が同じファイルに記録される。

    Args:
        app_ctx: アプリケーションコンテキスト
        agent: 保存するエージェント

    Returns:
        成功した場合 True
    """
    from src.models.agent import Agent  # 循環インポート回避

    # project_root を決定（複数のソースから取得を試みる）
    project_root = app_ctx.project_root

    # config.json から取得（init_tmux_workspace で設定される）
    if not project_root:
        project_root = get_project_root_from_config()

    # エージェントの working_dir から取得
    if not project_root and agent.working_dir:
        project_root = agent.working_dir

    # worktree の場合はメインリポジトリのパスを使用
    if project_root:
        project_root = resolve_main_repo_root(project_root)

    agents_file = _get_agents_file_path(project_root)

    if not agents_file:
        logger.debug("project_root が設定されていないため、エージェント情報を保存できません")
        return False

    try:
        # 既存のエージェント情報を読み込み
        agents_data: dict[str, Any] = {}
        if agents_file.exists():
            with open(agents_file, encoding="utf-8") as f:
                agents_data = json.load(f)

        # エージェント情報を追加/更新
        agents_data[agent.id] = agent.model_dump(mode="json")

        # ディレクトリ作成
        agents_file.parent.mkdir(parents=True, exist_ok=True)

        # ファイルに保存
        with open(agents_file, "w", encoding="utf-8") as f:
            json.dump(agents_data, f, ensure_ascii=False, indent=2, default=str)

        logger.debug(f"エージェント {agent.id} を {agents_file} に保存しました")
        return True

    except Exception as e:
        logger.warning(f"エージェント情報の保存に失敗: {e}")
        return False


def load_agents_from_file(app_ctx: AppContext) -> dict[str, "Agent"]:
    """ファイルからエージェント情報を読み込む。

    Args:
        app_ctx: アプリケーションコンテキスト

    Returns:
        エージェント ID -> Agent の辞書
    """
    from src.models.agent import Agent  # 循環インポート回避

    # project_root を決定（config.json → 環境変数 → app_ctx の順）
    project_root = app_ctx.project_root
    if not project_root:
        project_root = get_project_root_from_config()
    if not project_root:
        project_root = os.getenv("MCP_PROJECT_ROOT")

    # worktree の場合はメインリポジトリのパスを使用
    if project_root:
        project_root = resolve_main_repo_root(project_root)
    agents_file = _get_agents_file_path(project_root)

    if not agents_file or not agents_file.exists():
        return {}

    try:
        with open(agents_file, encoding="utf-8") as f:
            agents_data = json.load(f)

        agents: dict[str, Agent] = {}
        for agent_id, data in agents_data.items():
            try:
                # datetime 文字列を datetime オブジェクトに変換
                if isinstance(data.get("created_at"), str):
                    data["created_at"] = datetime.fromisoformat(data["created_at"])
                if isinstance(data.get("last_activity"), str):
                    data["last_activity"] = datetime.fromisoformat(data["last_activity"])
                agents[agent_id] = Agent(**data)
            except Exception as e:
                logger.warning(f"エージェント {agent_id} のパースに失敗: {e}")

        logger.debug(f"{len(agents)} 件のエージェント情報を {agents_file} から読み込みました")
        return agents

    except Exception as e:
        logger.warning(f"エージェント情報の読み込みに失敗: {e}")
        return {}


def sync_agents_from_file(app_ctx: AppContext) -> int:
    """ファイルからエージェント情報をメモリに同期する。

    既存のエージェント情報は保持し、ファイルにのみ存在するエージェントを追加する。

    Args:
        app_ctx: アプリケーションコンテキスト

    Returns:
        追加されたエージェント数
    """
    file_agents = load_agents_from_file(app_ctx)
    added = 0

    for agent_id, agent in file_agents.items():
        if agent_id not in app_ctx.agents:
            app_ctx.agents[agent_id] = agent
            added += 1

    if added > 0:
        logger.info(f"ファイルから {added} 件のエージェント情報を同期しました")

    return added


def remove_agent_from_file(app_ctx: AppContext, agent_id: str) -> bool:
    """ファイルからエージェント情報を削除する。

    Args:
        app_ctx: アプリケーションコンテキスト
        agent_id: 削除するエージェントID

    Returns:
        成功した場合 True
    """
    # project_root を決定（複数のソースから取得を試みる）
    project_root = app_ctx.project_root

    # config.json から取得（init_tmux_workspace で設定される）
    if not project_root:
        project_root = get_project_root_from_config()

    # 環境変数から取得
    if not project_root:
        project_root = os.getenv("MCP_PROJECT_ROOT")

    # worktree の場合はメインリポジトリのパスを使用
    if project_root:
        project_root = resolve_main_repo_root(project_root)
    agents_file = _get_agents_file_path(project_root)

    if not agents_file or not agents_file.exists():
        return False

    try:
        with open(agents_file, encoding="utf-8") as f:
            agents_data = json.load(f)

        if agent_id in agents_data:
            del agents_data[agent_id]

            with open(agents_file, "w", encoding="utf-8") as f:
                json.dump(agents_data, f, ensure_ascii=False, indent=2, default=str)

            logger.debug(f"エージェント {agent_id} を {agents_file} から削除しました")
            return True

        return False

    except Exception as e:
        logger.warning(f"エージェント情報の削除に失敗: {e}")
        return False
