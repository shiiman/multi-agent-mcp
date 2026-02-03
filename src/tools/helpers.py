"""MCPツール用共通ヘルパー関数。"""

import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

from src.context import AppContext
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
    """IPCManagerが初期化されていることを確認する。"""
    if app_ctx.ipc_manager is None:
        ipc_dir = os.path.join(app_ctx.settings.workspace_base_dir, ".ipc")
        app_ctx.ipc_manager = IPCManager(ipc_dir)
        app_ctx.ipc_manager.initialize()
    return app_ctx.ipc_manager


def ensure_dashboard_manager(app_ctx: AppContext) -> DashboardManager:
    """DashboardManagerが初期化されていることを確認する。"""
    if app_ctx.dashboard_manager is None:
        if app_ctx.workspace_id is None:
            app_ctx.workspace_id = str(uuid.uuid4())[:8]
        dashboard_dir = os.path.join(
            app_ctx.settings.workspace_base_dir, ".dashboard"
        )
        app_ctx.dashboard_manager = DashboardManager(
            workspace_id=app_ctx.workspace_id,
            workspace_path=app_ctx.settings.workspace_base_dir,
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
    """MemoryManagerが初期化されていることを確認する。"""
    if app_ctx.memory_manager is None:
        # プロジェクトルートを決定
        project_root = app_ctx.project_root

        # プロジェクトルートが未設定の場合、エージェントの worktree_path から取得
        if not project_root:
            for agent in app_ctx.agents.values():
                if agent.worktree_path:
                    # worktree の場合はメインリポジトリのルートを使用
                    project_root = resolve_main_repo_root(agent.worktree_path)
                    break

        # それでも未設定の場合は workspace_base_dir を使用
        if not project_root:
            project_root = app_ctx.settings.workspace_base_dir

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
