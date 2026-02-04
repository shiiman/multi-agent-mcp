"""MCPツール用共通ヘルパー関数。"""

import json
import logging
import os
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config.settings import get_mcp_dir
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
        else:
            # worktree: /path/to/main-repo/.git/worktrees/xxx → /path/to/main-repo
            git_dir_index = git_common_dir.find("/.git")
            return git_common_dir[:git_dir_index]

    except subprocess.CalledProcessError as e:
        raise ValueError(f"{path} は git リポジトリではありません: {e}") from e


# ========== プロジェクトルート解決ヘルパー ==========


def resolve_project_root(
    app_ctx: AppContext,
    allow_env_fallback: bool = False,
    allow_agent_fallback: bool = False,
    require_worktree_resolution: bool = True,
    caller_agent_id: str | None = None,
) -> str:
    """project_root を解決する共通ロジック。

    複数のソースから project_root を探索し、解決する。
    ensure_*_manager() 関数で共通して使用される。

    Args:
        app_ctx: アプリケーションコンテキスト
        allow_env_fallback: MCP_PROJECT_ROOT 環境変数からの取得を許可
        allow_agent_fallback: エージェントの working_dir からの取得を許可
        require_worktree_resolution: worktree の場合にメインリポジトリを返す
        caller_agent_id: 呼び出し元エージェントID（レジストリ検索用）

    Returns:
        project_root のパス

    Raises:
        ValueError: project_root が解決できない場合
    """
    # app_ctx.project_root から取得
    project_root = app_ctx.project_root

    # グローバルレジストリ / config.json から取得
    if not project_root:
        project_root = get_project_root_from_config(caller_agent_id=caller_agent_id)

    # エージェントの working_dir または worktree_path から取得（オプション）
    if not project_root and allow_agent_fallback:
        sync_agents_from_file(app_ctx)
        for agent in app_ctx.agents.values():
            if agent.working_dir:
                project_root = resolve_main_repo_root(agent.working_dir)
                break
            elif agent.worktree_path:
                project_root = resolve_main_repo_root(agent.worktree_path)
                break

    # 環境変数 MCP_PROJECT_ROOT からのフォールバック（オプション）
    if not project_root and allow_env_fallback:
        import os
        env_project_root = os.environ.get("MCP_PROJECT_ROOT")
        if env_project_root:
            project_root = env_project_root

    if not project_root:
        raise ValueError(
            "project_root が設定されていません。init_tmux_workspace を先に実行してください。"
        )

    # worktree の場合はメインリポジトリのパスを使用
    if require_worktree_resolution:
        project_root = resolve_main_repo_root(project_root)

    return project_root


# ========== ロールチェック ヘルパー ==========


def ensure_project_root_from_caller(
    app_ctx: AppContext, caller_agent_id: str | None
) -> None:
    """caller_agent_id からレジストリを検索し、app_ctx.project_root と session_id を設定する。

    各ツールの最初で呼び出すことで、Admin/Worker の MCP インスタンスでも
    正しい project_root と session_id を使用できるようにする。

    Args:
        app_ctx: アプリケーションコンテキスト
        caller_agent_id: 呼び出し元エージェントID
    """
    if caller_agent_id:
        # project_root が未設定の場合、レジストリから取得
        if not app_ctx.project_root:
            project_root = get_project_root_from_registry(caller_agent_id)
            if project_root:
                app_ctx.project_root = project_root
                logger.debug(
                    f"caller_agent_id {caller_agent_id} から project_root を設定: {project_root}"
                )

        # session_id が未設定の場合、レジストリから取得
        if not app_ctx.session_id:
            session_id = get_session_id_from_registry(caller_agent_id)
            if session_id:
                app_ctx.session_id = session_id
                logger.debug(
                    f"caller_agent_id {caller_agent_id} から session_id を設定: {session_id}"
                )


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

    # ファイルからエージェント情報を同期（他の MCP インスタンスで作成されたエージェントを取得）
    sync_agents_from_file(app_ctx)

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


def check_tool_permission(
    app_ctx: AppContext,
    tool_name: str,
    caller_agent_id: str | None,
) -> dict[str, Any] | None:
    """ツールのロール権限をチェックする。

    全ての MCP ツールで使用する統一的な権限チェック関数。
    role_permissions.py で定義された許可ロールに基づいてチェックする。

    Args:
        app_ctx: アプリケーションコンテキスト
        tool_name: ツール名
        caller_agent_id: 呼び出し元エージェントID（必須）

    Returns:
        権限エラーの場合はエラー dict、許可されている場合は None
    """
    from src.config.role_permissions import get_allowed_roles, get_role_error_message

    # caller_agent_id は必須
    if caller_agent_id is None:
        return {
            "success": False,
            "error": (
                f"`{tool_name}` の呼び出しには `caller_agent_id` が必須です。"
                "自身のエージェント ID を指定してください。"
            ),
        }

    # caller_agent_id からレジストリを検索し project_root を設定
    # （Admin/Worker の MCP インスタンスでも正しい project_root を使用可能にする）
    ensure_project_root_from_caller(app_ctx, caller_agent_id)

    # ファイルからエージェント情報を同期（他の MCP インスタンスで作成されたエージェントを取得）
    sync_agents_from_file(app_ctx)

    # ロールを取得
    role = get_agent_role(app_ctx, caller_agent_id)
    if role is None:
        return {
            "success": False,
            "error": f"エージェント {caller_agent_id} が見つかりません",
        }

    # 許可ロールを取得
    allowed_roles = get_allowed_roles(tool_name)

    # ツールが未定義の場合は全ロール許可（後方互換性）
    if not allowed_roles:
        logger.warning(f"ツール '{tool_name}' の権限が未定義です。全ロールに許可します。")
        return None

    # ロールチェック
    if role.value not in allowed_roles:
        return {
            "success": False,
            "error": get_role_error_message(tool_name, role.value),
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

    Raises:
        ValueError: project_root が設定されていない場合
    """
    if app_ctx.ipc_manager is None:
        base_dir = resolve_project_root(app_ctx)
        # session_id を確保（必須）
        session_id = ensure_session_id(app_ctx)
        if not session_id:
            raise ValueError(
                "session_id が設定されていません。init_tmux_workspace で session_id を指定してください。"
            )
        ipc_dir = os.path.join(base_dir, get_mcp_dir(), session_id, ".ipc")
        app_ctx.ipc_manager = IPCManager(ipc_dir)
        app_ctx.ipc_manager.initialize()
    return app_ctx.ipc_manager


def ensure_dashboard_manager(app_ctx: AppContext) -> DashboardManager:
    """DashboardManagerが初期化されていることを確認する。

    worktree 内で実行されている場合でも、メインリポジトリの Dashboard ディレクトリを使用する。

    Raises:
        ValueError: project_root または session_id が設定されていない場合
    """
    if app_ctx.dashboard_manager is None:
        base_dir = resolve_project_root(app_ctx)
        # session_id を確保（必須）
        session_id = ensure_session_id(app_ctx)
        if not session_id:
            raise ValueError(
                "session_id が設定されていません。init_tmux_workspace で session_id を指定してください。"
            )
        # workspace_id は session_id を使用（同一タスク = 同一ダッシュボード）
        if app_ctx.workspace_id is None:
            app_ctx.workspace_id = session_id
        dashboard_dir = os.path.join(base_dir, get_mcp_dir(), session_id, ".dashboard")
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
            app_ctx.settings.healthcheck_interval_seconds,
        )
    return app_ctx.healthcheck_manager


def ensure_metrics_manager(app_ctx: AppContext) -> MetricsManager:
    """MetricsManagerが初期化されていることを確認する。

    Raises:
        ValueError: project_root が設定されていない場合
    """
    if app_ctx.metrics_manager is None:
        base_dir = resolve_project_root(app_ctx, require_worktree_resolution=False)
        metrics_dir = os.path.join(base_dir, get_mcp_dir(), ".metrics")
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
    """
    if app_ctx.memory_manager is None:
        project_root = resolve_project_root(
            app_ctx,
            allow_env_fallback=True,
            allow_agent_fallback=True,
        )
        # project_root を設定（次回以降のために）
        if not app_ctx.project_root:
            app_ctx.project_root = project_root
            logger.info(f"project_root を自動設定: {project_root}")
        # session_id を確保（config.json から読み取り）
        session_id = ensure_session_id(app_ctx)
        if session_id:
            memory_path = os.path.join(project_root, get_mcp_dir(), session_id, ".memory", "memory.json")
        else:
            memory_path = os.path.join(project_root, get_mcp_dir(), "memory", "memory.json")
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


def _get_global_mcp_dir() -> Path:
    """グローバルな MCP ディレクトリを取得する。"""
    return Path.home() / ".multi-agent-mcp"


def _get_agent_registry_dir() -> Path:
    """エージェントレジストリディレクトリを取得する。"""
    return _get_global_mcp_dir() / "agents"


def save_agent_to_registry(
    agent_id: str,
    owner_id: str,
    project_root: str,
    session_id: str | None = None,
) -> None:
    """エージェント情報をグローバルレジストリに保存する。

    Args:
        agent_id: エージェントID
        owner_id: オーナーエージェントID（自分自身の場合は同じID）
        project_root: プロジェクトルートパス
        session_id: セッションID（タスクディレクトリ名）
    """
    registry_dir = _get_agent_registry_dir()
    registry_dir.mkdir(parents=True, exist_ok=True)
    agent_file = registry_dir / f"{agent_id}.json"
    data = {
        "agent_id": agent_id,
        "owner_id": owner_id,
        "project_root": project_root,
    }
    if session_id:
        data["session_id"] = session_id
    with open(agent_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.debug(f"エージェントをレジストリに保存: {agent_id} -> {project_root} (session: {session_id})")


def get_project_root_from_registry(agent_id: str) -> str | None:
    """レジストリからエージェントの project_root を取得する。

    Args:
        agent_id: エージェントID

    Returns:
        project_root のパス、見つからない場合は None
    """
    agent_file = _get_agent_registry_dir() / f"{agent_id}.json"
    if not agent_file.exists():
        return None
    try:
        with open(agent_file, encoding="utf-8") as f:
            data = json.load(f)
        project_root = data.get("project_root")
        if project_root:
            logger.debug(f"レジストリから project_root を取得: {agent_id} -> {project_root}")
        return project_root
    except Exception as e:
        logger.warning(f"レジストリファイルの読み込みに失敗: {agent_file}: {e}")
        return None


def get_session_id_from_registry(agent_id: str) -> str | None:
    """レジストリからエージェントの session_id を取得する。

    Args:
        agent_id: エージェントID

    Returns:
        session_id、見つからない場合は None
    """
    agent_file = _get_agent_registry_dir() / f"{agent_id}.json"
    if not agent_file.exists():
        return None
    try:
        with open(agent_file, encoding="utf-8") as f:
            data = json.load(f)
        session_id = data.get("session_id")
        if session_id:
            logger.debug(f"レジストリから session_id を取得: {agent_id} -> {session_id}")
        return session_id
    except Exception as e:
        logger.warning(f"レジストリファイルの読み込みに失敗: {agent_file}: {e}")
        return None


def remove_agent_from_registry(agent_id: str) -> bool:
    """レジストリからエージェント情報を削除する。

    Args:
        agent_id: エージェントID

    Returns:
        削除成功時 True
    """
    agent_file = _get_agent_registry_dir() / f"{agent_id}.json"
    if agent_file.exists():
        agent_file.unlink()
        logger.debug(f"エージェントをレジストリから削除: {agent_id}")
        return True
    return False


def remove_agents_by_owner(owner_id: str) -> int:
    """オーナーに紐づく全エージェントをレジストリから削除する。

    Args:
        owner_id: オーナーエージェントID

    Returns:
        削除したエージェント数
    """
    registry_dir = _get_agent_registry_dir()
    if not registry_dir.exists():
        return 0

    removed_count = 0
    for agent_file in registry_dir.glob("*.json"):
        try:
            with open(agent_file, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("owner_id") == owner_id:
                agent_file.unlink()
                logger.debug(f"エージェントをレジストリから削除: {agent_file.stem}")
                removed_count += 1
        except Exception as e:
            logger.warning(f"レジストリファイルの処理に失敗: {agent_file}: {e}")

    return removed_count


def get_project_root_from_config(
    caller_agent_id: str | None = None,
) -> str | None:
    """project_root をグローバルレジストリから取得する。

    Args:
        caller_agent_id: 呼び出し元エージェントID（オプション）

    Returns:
        project_root のパス、見つからない場合は None
    """
    if caller_agent_id:
        return get_project_root_from_registry(caller_agent_id)
    return None


def get_mcp_tool_prefix_from_config(working_dir: str | None = None) -> str:
    """config.json から mcp_tool_prefix を取得する。

    init_tmux_workspace で作成された config.json を読み取る。
    見つからない場合はデフォルト値を返す。

    Args:
        working_dir: 探索開始ディレクトリ（オプション）

    Returns:
        MCP ツールの完全名プレフィックス
    """
    default_prefix = "mcp__multi-agent-mcp__"
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
        config_file = base_dir / get_mcp_dir() / "config.json"
        if config_file.exists():
            try:
                with open(config_file, encoding="utf-8") as f:
                    config = json.load(f)
                prefix = config.get("mcp_tool_prefix")
                if prefix:
                    logger.debug(f"config.json から mcp_tool_prefix を取得: {prefix}")
                    return prefix
            except Exception as e:
                logger.warning(f"config.json の読み込みに失敗: {e}")

    return default_prefix


def get_session_id_from_config(working_dir: str | None = None) -> str | None:
    """config.json から session_id を取得する。

    init_tmux_workspace で作成された config.json を読み取る。
    見つからない場合は None を返す。

    Args:
        working_dir: 探索開始ディレクトリ（オプション）

    Returns:
        セッションID、見つからない場合は None
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
        config_file = base_dir / get_mcp_dir() / "config.json"
        if config_file.exists():
            try:
                with open(config_file, encoding="utf-8") as f:
                    config = json.load(f)
                session_id = config.get("session_id")
                if session_id:
                    logger.debug(f"config.json から session_id を取得: {session_id}")
                    return session_id
            except Exception as e:
                logger.warning(f"config.json の読み込みに失敗: {e}")

    return None


def ensure_session_id(app_ctx: "AppContext") -> str | None:
    """セッションID を確保する。

    app_ctx.session_id が設定されていなければ config.json から読み取る。

    Args:
        app_ctx: アプリケーションコンテキスト

    Returns:
        セッションID、見つからない場合は None
    """
    if app_ctx.session_id:
        return app_ctx.session_id

    # config.json から取得
    working_dir = app_ctx.project_root or get_project_root_from_config()
    session_id = get_session_id_from_config(working_dir)

    if session_id:
        app_ctx.session_id = session_id
        logger.debug(f"config.json から session_id を設定: {session_id}")

    return session_id


# ========== エージェント永続化ヘルパー ==========


def _get_agents_file_path(
    project_root: str | None, session_id: str | None = None
) -> Path | None:
    """エージェント情報ファイルのパスを取得する。

    Args:
        project_root: プロジェクトルートパス
        session_id: セッションID（タスクディレクトリ名、必須）

    Returns:
        agents.json のパス、project_root または session_id が None の場合は None
    """
    if not project_root:
        return None
    if not session_id:
        logger.warning("session_id が指定されていません。agents.json のパスを取得できません。")
        return None
    # タスクディレクトリ配下に配置（session_id 必須）
    return Path(project_root) / get_mcp_dir() / session_id / "agents.json"


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

    # session_id を確保（config.json から読み取り）
    session_id = ensure_session_id(app_ctx)
    agents_file = _get_agents_file_path(project_root, session_id)

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

    # project_root を決定（app_ctx → config.json の順）
    project_root = app_ctx.project_root
    if not project_root:
        project_root = get_project_root_from_config()

    # worktree の場合はメインリポジトリのパスを使用
    if project_root:
        project_root = resolve_main_repo_root(project_root)

    # session_id を確保（config.json から読み取り）
    session_id = ensure_session_id(app_ctx)
    agents_file = _get_agents_file_path(project_root, session_id)

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

    # worktree の場合はメインリポジトリのパスを使用
    if project_root:
        project_root = resolve_main_repo_root(project_root)

    # session_id を確保（config.json から読み取り）
    session_id = ensure_session_id(app_ctx)
    agents_file = _get_agents_file_path(project_root, session_id)

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
