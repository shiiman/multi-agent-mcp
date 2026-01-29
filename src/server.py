"""Multi-Agent MCP Server エントリーポイント。"""

import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.settings import AICli, Settings
from src.config.templates import get_template, get_template_names, list_templates
from src.managers.ai_cli_manager import AiCliManager
from src.managers.cost_manager import CostManager
from src.managers.dashboard_manager import DashboardManager
from src.managers.gtrconfig_manager import GtrconfigManager
from src.managers.healthcheck_manager import HealthcheckManager
from src.managers.ipc_manager import IPCManager
from src.managers.metrics_manager import MetricsManager
from src.managers.scheduler_manager import SchedulerManager, TaskPriority
from src.managers.tmux_manager import TmuxManager
from src.managers.worktree_manager import WorktreeManager
from src.models.agent import Agent, AgentRole, AgentStatus
from src.models.dashboard import TaskStatus
from src.models.message import MessagePriority, MessageType

# ログ設定（stderrに出力）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """アプリケーションコンテキスト。"""

    settings: Settings
    tmux: TmuxManager
    ai_cli: AiCliManager
    agents: dict[str, Agent] = field(default_factory=dict)
    worktree_managers: dict[str, WorktreeManager] = field(default_factory=dict)
    gtrconfig_managers: dict[str, GtrconfigManager] = field(default_factory=dict)
    ipc_manager: IPCManager | None = None
    dashboard_manager: DashboardManager | None = None
    scheduler_manager: SchedulerManager | None = None
    healthcheck_manager: HealthcheckManager | None = None
    metrics_manager: MetricsManager | None = None
    cost_manager: CostManager | None = None
    workspace_id: str | None = None


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """サーバーライフサイクルを管理する。

    Args:
        server: FastMCPサーバーインスタンス

    Yields:
        アプリケーションコンテキスト
    """
    logger.info("Multi-Agent MCP Server を起動しています...")

    # リソースを初期化
    settings = Settings()
    tmux = TmuxManager(settings)
    ai_cli = AiCliManager(settings)

    # ワークスペースディレクトリを作成
    os.makedirs(settings.workspace_base_dir, exist_ok=True)

    try:
        yield AppContext(settings=settings, tmux=tmux, ai_cli=ai_cli)
    finally:
        # クリーンアップ
        logger.info("サーバーをシャットダウンしています...")
        count = await tmux.cleanup_all_sessions()
        logger.info(f"{count} セッションをクリーンアップしました")


# FastMCPサーバーを作成
mcp = FastMCP("Multi-Agent MCP", lifespan=app_lifespan)


# ========== セッション管理 Tools ==========


@mcp.tool()
async def init_workspace(workspace_path: str, ctx: Context) -> dict[str, Any]:
    """ワークスペースを初期化する。

    ディレクトリの作成と基本的な設定を行う。

    Args:
        workspace_path: ワークスペースのパス（ベースディレクトリからの相対パス）

    Returns:
        初期化結果（success, workspace_path, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    settings = app_ctx.settings

    full_path = os.path.join(settings.workspace_base_dir, workspace_path)

    try:
        os.makedirs(full_path, exist_ok=True)
        return {
            "success": True,
            "workspace_path": full_path,
            "message": f"ワークスペースを初期化しました: {full_path}",
        }
    except OSError as e:
        return {
            "success": False,
            "error": f"ワークスペースの初期化に失敗しました: {e}",
        }


@mcp.tool()
async def cleanup_workspace(ctx: Context) -> dict[str, Any]:
    """ワークスペースをクリーンアップする。

    全エージェントを終了し、リソースを解放する。

    Returns:
        クリーンアップ結果（success, terminated_sessions, cleared_agents, message）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    tmux = app_ctx.tmux
    agents = app_ctx.agents

    terminated_count = await tmux.cleanup_all_sessions()
    agent_count = len(agents)
    agents.clear()

    return {
        "success": True,
        "terminated_sessions": terminated_count,
        "cleared_agents": agent_count,
        "message": (
            f"{terminated_count} セッションを終了、"
            f"{agent_count} エージェント情報をクリアしました"
        ),
    }


# ========== エージェント管理 Tools ==========


@mcp.tool()
async def create_agent(role: str, working_dir: str, ctx: Context) -> dict[str, Any]:
    """新しいエージェントを作成し、tmuxセッションを起動する。

    Args:
        role: エージェントの役割（owner/admin/worker）
        working_dir: 作業ディレクトリのパス

    Returns:
        作成結果（success, agent, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    settings = app_ctx.settings
    tmux = app_ctx.tmux
    agents = app_ctx.agents

    # 役割の検証
    try:
        agent_role = AgentRole(role)
    except ValueError:
        return {
            "success": False,
            "error": f"無効な役割です: {role}（有効: owner, admin, worker）",
        }

    # Worker数の上限チェック
    if agent_role == AgentRole.WORKER:
        worker_count = sum(1 for a in agents.values() if a.role == AgentRole.WORKER)
        if worker_count >= settings.max_workers:
            return {
                "success": False,
                "error": f"Worker数が上限（{settings.max_workers}）に達しています",
            }

    # Owner/Adminの重複チェック
    if agent_role in (AgentRole.OWNER, AgentRole.ADMIN):
        existing = [a for a in agents.values() if a.role == agent_role]
        if existing:
            return {
                "success": False,
                "error": f"{agent_role.value}は既に存在します（ID: {existing[0].id}）",
            }

    # エージェントIDを生成
    agent_id = str(uuid.uuid4())[:8]

    # tmuxセッションを作成
    success = await tmux.create_session(agent_id, working_dir)
    if not success:
        return {
            "success": False,
            "error": "tmuxセッションの作成に失敗しました",
        }

    # エージェント情報を登録
    now = datetime.now()
    agent = Agent(
        id=agent_id,
        role=agent_role,
        status=AgentStatus.IDLE,
        tmux_session=agent_id,
        created_at=now,
        last_activity=now,
    )
    agents[agent_id] = agent

    logger.info(f"エージェント {agent_id}（{role}）を作成しました")

    return {
        "success": True,
        "agent": agent.model_dump(mode="json"),
        "message": f"エージェント {agent_id}（{role}）を作成しました",
    }


@mcp.tool()
async def list_agents(ctx: Context) -> dict[str, Any]:
    """全エージェントの一覧を取得する。

    Returns:
        エージェント一覧（success, agents, count）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    agents = app_ctx.agents

    agent_list = [a.model_dump(mode="json") for a in agents.values()]

    return {
        "success": True,
        "agents": agent_list,
        "count": len(agent_list),
    }


@mcp.tool()
async def get_agent_status(agent_id: str, ctx: Context) -> dict[str, Any]:
    """指定エージェントの詳細ステータスを取得する。

    Args:
        agent_id: エージェントID

    Returns:
        エージェント詳細（success, agent, session_active または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    tmux = app_ctx.tmux
    agents = app_ctx.agents

    agent = agents.get(agent_id)
    if not agent:
        return {
            "success": False,
            "error": f"エージェント {agent_id} が見つかりません",
        }

    session_exists = await tmux.session_exists(agent.tmux_session)

    return {
        "success": True,
        "agent": agent.model_dump(mode="json"),
        "session_active": session_exists,
    }


@mcp.tool()
async def terminate_agent(agent_id: str, ctx: Context) -> dict[str, Any]:
    """エージェントを終了し、tmuxセッションを削除する。

    Args:
        agent_id: 終了するエージェントID

    Returns:
        終了結果（success, agent_id, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    tmux = app_ctx.tmux
    agents = app_ctx.agents

    agent = agents.get(agent_id)
    if not agent:
        return {
            "success": False,
            "error": f"エージェント {agent_id} が見つかりません",
        }

    await tmux.kill_session(agent.tmux_session)
    del agents[agent_id]

    logger.info(f"エージェント {agent_id} を終了しました")

    return {
        "success": True,
        "agent_id": agent_id,
        "message": f"エージェント {agent_id} を終了しました",
    }


# ========== コマンド実行 Tools ==========


@mcp.tool()
async def send_command(agent_id: str, command: str, ctx: Context) -> dict[str, Any]:
    """指定エージェントにコマンドを送信する。

    Args:
        agent_id: 対象エージェントID
        command: 実行するコマンド

    Returns:
        送信結果（success, agent_id, command, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    tmux = app_ctx.tmux
    agents = app_ctx.agents

    agent = agents.get(agent_id)
    if not agent:
        return {
            "success": False,
            "error": f"エージェント {agent_id} が見つかりません",
        }

    success = await tmux.send_keys(agent.tmux_session, command)

    if success:
        agent.status = AgentStatus.BUSY
        agent.last_activity = datetime.now()

    return {
        "success": success,
        "agent_id": agent_id,
        "command": command,
        "message": "コマンドを送信しました" if success else "コマンド送信に失敗しました",
    }


@mcp.tool()
async def get_output(agent_id: str, lines: int = 50, ctx: Context = None) -> dict[str, Any]:
    """エージェントのtmux出力を取得する。

    Args:
        agent_id: 対象エージェントID
        lines: 取得する行数（デフォルト: 50）

    Returns:
        出力内容（success, agent_id, lines, output または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    tmux = app_ctx.tmux
    agents = app_ctx.agents

    agent = agents.get(agent_id)
    if not agent:
        return {
            "success": False,
            "error": f"エージェント {agent_id} が見つかりません",
        }

    output = await tmux.capture_pane(agent.tmux_session, lines)

    return {
        "success": True,
        "agent_id": agent_id,
        "lines": lines,
        "output": output,
    }


@mcp.tool()
async def send_task(
    agent_id: str,
    task_content: str,
    session_id: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """タスク指示をファイル経由でWorkerに送信する。

    長いマルチライン指示に対応。Workerは claude < TASK.md でタスクを実行。

    Args:
        agent_id: エージェントID
        task_content: タスク内容（Markdown形式）
        session_id: Issue番号または一意なタスクID（例: "94", "a1b2c3d4"）

    Returns:
        送信結果（success, task_file, command_sent, message または error）
    """
    from pathlib import Path

    app_ctx: AppContext = ctx.request_context.lifespan_context
    tmux = app_ctx.tmux
    agents = app_ctx.agents

    agent = agents.get(agent_id)
    if not agent:
        return {
            "success": False,
            "error": f"エージェント {agent_id} が見つかりません",
        }

    # プロジェクトルートを取得（Workerの working_dir から）
    # worktree_path が設定されていればそれを使用、なければ workspace_base_dir を使用
    if agent.worktree_path:
        project_root = Path(agent.worktree_path)
    else:
        project_root = Path(app_ctx.settings.workspace_base_dir)

    # タスクファイル作成
    dashboard = _ensure_dashboard_manager(app_ctx)
    task_file = dashboard.write_task_file(
        project_root, session_id, agent_id, task_content
    )

    # Workerに claude < TASK.md コマンドを送信
    read_command = f"claude < {task_file}"
    success = await tmux.send_keys(agent.tmux_session, read_command)

    if success:
        agent.status = AgentStatus.BUSY
        agent.last_activity = datetime.now()
        # ダッシュボード更新
        dashboard.save_markdown_dashboard(project_root, session_id)

    return {
        "success": success,
        "agent_id": agent_id,
        "session_id": session_id,
        "task_file": str(task_file),
        "command_sent": read_command,
        "message": "タスクを送信しました" if success else "タスク送信に失敗しました",
    }


@mcp.tool()
async def open_session(agent_id: str, ctx: Context = None) -> dict[str, Any]:
    """エージェントのtmuxセッションをターミナルアプリで開く。

    優先順位: ghostty → iTerm2 → Terminal.app

    Args:
        agent_id: エージェントID

    Returns:
        開く結果（success, agent_id, session, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    tmux = app_ctx.tmux
    agents = app_ctx.agents

    agent = agents.get(agent_id)
    if not agent:
        return {
            "success": False,
            "error": f"エージェント {agent_id} が見つかりません",
        }

    success = await tmux.open_session_in_terminal(agent.tmux_session)

    return {
        "success": success,
        "agent_id": agent_id,
        "session": agent.tmux_session,
        "message": (
            "ターミナルでセッションを開きました"
            if success
            else "セッションを開けませんでした"
        ),
    }


@mcp.tool()
async def broadcast_command(
    command: str, role: str | None = None, ctx: Context = None
) -> dict[str, Any]:
    """全エージェント（または特定役割）にコマンドをブロードキャストする。

    Args:
        command: 実行するコマンド
        role: 対象の役割（省略時は全員、有効: owner/admin/worker）

    Returns:
        送信結果（success, command, role_filter, results, summary または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    tmux = app_ctx.tmux
    agents = app_ctx.agents

    target_role = None
    if role:
        try:
            target_role = AgentRole(role)
        except ValueError:
            return {
                "success": False,
                "error": f"無効な役割です: {role}（有効: owner, admin, worker）",
            }

    results: dict[str, bool] = {}
    now = datetime.now()

    for aid, agent in agents.items():
        if target_role and agent.role != target_role:
            continue

        success = await tmux.send_keys(agent.tmux_session, command)
        results[aid] = success

        if success:
            agent.last_activity = now

    success_count = sum(1 for v in results.values() if v)
    total_count = len(results)

    return {
        "success": True,
        "command": command,
        "role_filter": role,
        "results": results,
        "summary": f"{success_count}/{total_count} エージェントに送信成功",
    }


# ========== git worktree 管理 Tools ==========


def _get_worktree_manager(app_ctx: AppContext, repo_path: str) -> WorktreeManager:
    """指定リポジトリのWorktreeManagerを取得または作成する。"""
    if repo_path not in app_ctx.worktree_managers:
        app_ctx.worktree_managers[repo_path] = WorktreeManager(repo_path)
    return app_ctx.worktree_managers[repo_path]


@mcp.tool()
async def create_worktree(
    repo_path: str,
    worktree_path: str,
    branch: str,
    create_branch: bool = True,
    base_branch: str | None = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """新しいgit worktreeを作成する。

    Args:
        repo_path: メインリポジトリのパス
        worktree_path: 作成するworktreeのパス
        branch: ブランチ名
        create_branch: 新しいブランチを作成するか（デフォルト: True）
        base_branch: 基点ブランチ（create_branch=Trueの場合のみ有効）

    Returns:
        作成結果（success, worktree_path, branch, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    worktree = _get_worktree_manager(app_ctx, repo_path)

    # リポジトリの確認
    if not await worktree.is_git_repo():
        return {
            "success": False,
            "error": f"有効なgitリポジトリではありません: {repo_path}",
        }

    success, message = await worktree.create_worktree(
        worktree_path, branch, create_branch, base_branch
    )

    if success:
        logger.info(f"worktreeを作成しました: {worktree_path} ({branch})")

    return {
        "success": success,
        "worktree_path": worktree_path if success else None,
        "branch": branch if success else None,
        "message": message,
    }


@mcp.tool()
async def list_worktrees(repo_path: str, ctx: Context = None) -> dict[str, Any]:
    """リポジトリのworktree一覧を取得する。

    Args:
        repo_path: メインリポジトリのパス

    Returns:
        worktree一覧（success, worktrees, count または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    worktree = _get_worktree_manager(app_ctx, repo_path)

    if not await worktree.is_git_repo():
        return {
            "success": False,
            "error": f"有効なgitリポジトリではありません: {repo_path}",
        }

    worktrees = await worktree.list_worktrees()
    worktree_list = [w.model_dump() for w in worktrees]

    return {
        "success": True,
        "worktrees": worktree_list,
        "count": len(worktree_list),
    }


@mcp.tool()
async def remove_worktree(
    repo_path: str,
    worktree_path: str,
    force: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """git worktreeを削除する。

    Args:
        repo_path: メインリポジトリのパス
        worktree_path: 削除するworktreeのパス
        force: 強制削除するか（デフォルト: False）

    Returns:
        削除結果（success, worktree_path, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    worktree = _get_worktree_manager(app_ctx, repo_path)

    if not await worktree.is_git_repo():
        return {
            "success": False,
            "error": f"有効なgitリポジトリではありません: {repo_path}",
        }

    success, message = await worktree.remove_worktree(worktree_path, force)

    if success:
        logger.info(f"worktreeを削除しました: {worktree_path}")

    return {
        "success": success,
        "worktree_path": worktree_path,
        "message": message,
    }


@mcp.tool()
async def assign_worktree(
    agent_id: str,
    worktree_path: str,
    branch: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """エージェントにworktreeを割り当てる。

    Args:
        agent_id: エージェントID
        worktree_path: worktreeのパス
        branch: ブランチ名

    Returns:
        割り当て結果（success, agent_id, worktree_path, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    agents = app_ctx.agents

    agent = agents.get(agent_id)
    if not agent:
        return {
            "success": False,
            "error": f"エージェント {agent_id} が見つかりません",
        }

    # エージェント情報を更新
    agent.worktree_path = worktree_path
    agent.last_activity = datetime.now()

    logger.info(f"エージェント {agent_id} に worktree を割り当てました: {worktree_path}")

    return {
        "success": True,
        "agent_id": agent_id,
        "worktree_path": worktree_path,
        "branch": branch,
        "message": f"worktreeを割り当てました: {worktree_path}",
    }


@mcp.tool()
async def get_worktree_status(
    repo_path: str,
    worktree_path: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """指定worktreeのgitステータスを取得する。

    Args:
        repo_path: メインリポジトリのパス
        worktree_path: worktreeのパス

    Returns:
        ステータス情報（success, status または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    worktree = _get_worktree_manager(app_ctx, repo_path)

    if not await worktree.is_git_repo():
        return {
            "success": False,
            "error": f"有効なgitリポジトリではありません: {repo_path}",
        }

    status = await worktree.get_worktree_status(worktree_path)

    return {
        "success": True,
        "status": status,
    }


@mcp.tool()
async def check_gtr_available(repo_path: str, ctx: Context = None) -> dict[str, Any]:
    """gtr (git-worktree-runner) が利用可能か確認する。

    Args:
        repo_path: リポジトリのパス

    Returns:
        gtrの利用可否（success, gtr_available, message）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    worktree = _get_worktree_manager(app_ctx, repo_path)

    available = await worktree.is_gtr_available()

    return {
        "success": True,
        "gtr_available": available,
        "message": (
            "gtr (git-worktree-runner) が利用可能です"
            if available
            else "gtr が見つかりません。通常の git worktree を使用します"
        ),
    }


@mcp.tool()
async def open_worktree_with_ai(
    repo_path: str,
    branch: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """gtr ai コマンドでworktreeをAIツール（Claude Code）で開く。

    gtr がインストールされている場合のみ使用可能。

    Args:
        repo_path: リポジトリのパス
        branch: ブランチ名

    Returns:
        実行結果（success, branch, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    worktree = _get_worktree_manager(app_ctx, repo_path)

    if not await worktree.is_git_repo():
        return {
            "success": False,
            "error": f"有効なgitリポジトリではありません: {repo_path}",
        }

    success, message = await worktree.open_with_ai(branch)

    if success:
        logger.info(f"AIツールでworktreeを開きました: {branch}")

    return {
        "success": success,
        "branch": branch if success else None,
        "message": message,
    }


@mcp.tool()
async def open_worktree_with_editor(
    repo_path: str,
    branch: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """gtr editor コマンドでworktreeをエディタで開く。

    gtr がインストールされている場合のみ使用可能。

    Args:
        repo_path: リポジトリのパス
        branch: ブランチ名

    Returns:
        実行結果（success, branch, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    worktree = _get_worktree_manager(app_ctx, repo_path)

    if not await worktree.is_git_repo():
        return {
            "success": False,
            "error": f"有効なgitリポジトリではありません: {repo_path}",
        }

    success, message = await worktree.open_with_editor(branch)

    if success:
        logger.info(f"エディタでworktreeを開きました: {branch}")

    return {
        "success": success,
        "branch": branch if success else None,
        "message": message,
    }


# ========== IPC/メッセージング Tools ==========


def _ensure_ipc_manager(app_ctx: AppContext) -> IPCManager:
    """IPCManagerが初期化されていることを確認する。"""
    if app_ctx.ipc_manager is None:
        ipc_dir = os.path.join(app_ctx.settings.workspace_base_dir, ".ipc")
        app_ctx.ipc_manager = IPCManager(ipc_dir)
        app_ctx.ipc_manager.initialize()
    return app_ctx.ipc_manager


@mcp.tool()
async def send_message(
    sender_id: str,
    receiver_id: str | None,
    message_type: str,
    content: str,
    subject: str = "",
    priority: str = "normal",
    ctx: Context = None,
) -> dict[str, Any]:
    """エージェント間でメッセージを送信する。

    Args:
        sender_id: 送信元エージェントID
        receiver_id: 宛先エージェントID（Noneでブロードキャスト）
        message_type: メッセージタイプ（task_assign, task_complete, etc.）
        content: メッセージ内容
        subject: 件名（オプション）
        priority: 優先度（low/normal/high/urgent）

    Returns:
        送信結果（success, message_id, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    ipc = _ensure_ipc_manager(app_ctx)

    # メッセージタイプの検証
    try:
        msg_type = MessageType(message_type)
    except ValueError:
        valid_types = [t.value for t in MessageType]
        return {
            "success": False,
            "error": f"無効なメッセージタイプです: {message_type}（有効: {valid_types}）",
        }

    # 優先度の検証
    try:
        msg_priority = MessagePriority(priority)
    except ValueError:
        valid_priorities = [p.value for p in MessagePriority]
        return {
            "success": False,
            "error": f"無効な優先度です: {priority}（有効: {valid_priorities}）",
        }

    # 送信者がIPCに登録されているか確認
    if sender_id not in ipc.get_all_agent_ids():
        ipc.register_agent(sender_id)

    # 受信者の確認（ブロードキャスト以外）
    if receiver_id and receiver_id not in ipc.get_all_agent_ids():
        ipc.register_agent(receiver_id)

    message = ipc.send_message(
        sender_id=sender_id,
        receiver_id=receiver_id,
        message_type=msg_type,
        content=content,
        subject=subject,
        priority=msg_priority,
    )

    return {
        "success": True,
        "message_id": message.id,
        "message": (
            "ブロードキャストを送信しました"
            if receiver_id is None
            else f"メッセージを {receiver_id} に送信しました"
        ),
    }


@mcp.tool()
async def read_messages(
    agent_id: str,
    unread_only: bool = False,
    message_type: str | None = None,
    mark_as_read: bool = True,
    ctx: Context = None,
) -> dict[str, Any]:
    """エージェントのメッセージを読み取る。

    Args:
        agent_id: エージェントID
        unread_only: 未読のみ取得するか
        message_type: フィルターするメッセージタイプ
        mark_as_read: 既読としてマークするか

    Returns:
        メッセージ一覧（success, messages, count または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    ipc = _ensure_ipc_manager(app_ctx)

    # メッセージタイプの検証
    msg_type = None
    if message_type:
        try:
            msg_type = MessageType(message_type)
        except ValueError:
            valid_types = [t.value for t in MessageType]
            return {
                "success": False,
                "error": (
                    f"無効なメッセージタイプです: {message_type}"
                    f"（有効: {valid_types}）"
                ),
            }

    # エージェントが登録されていなければ登録
    if agent_id not in ipc.get_all_agent_ids():
        ipc.register_agent(agent_id)

    messages = ipc.read_messages(
        agent_id=agent_id,
        unread_only=unread_only,
        message_type=msg_type,
        mark_as_read=mark_as_read,
    )

    return {
        "success": True,
        "messages": [m.model_dump(mode="json") for m in messages],
        "count": len(messages),
    }


@mcp.tool()
async def get_unread_count(agent_id: str, ctx: Context = None) -> dict[str, Any]:
    """エージェントの未読メッセージ数を取得する。

    Args:
        agent_id: エージェントID

    Returns:
        未読数（success, agent_id, unread_count）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    ipc = _ensure_ipc_manager(app_ctx)

    if agent_id not in ipc.get_all_agent_ids():
        ipc.register_agent(agent_id)

    count = ipc.get_unread_count(agent_id)

    return {
        "success": True,
        "agent_id": agent_id,
        "unread_count": count,
    }


@mcp.tool()
async def clear_messages(agent_id: str, ctx: Context = None) -> dict[str, Any]:
    """エージェントのメッセージをクリアする。

    Args:
        agent_id: エージェントID

    Returns:
        クリア結果（success, agent_id, deleted_count, message）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    ipc = _ensure_ipc_manager(app_ctx)

    if agent_id not in ipc.get_all_agent_ids():
        return {
            "success": False,
            "error": f"エージェント {agent_id} のキューが見つかりません",
        }

    deleted_count = ipc.clear_messages(agent_id)

    return {
        "success": True,
        "agent_id": agent_id,
        "deleted_count": deleted_count,
        "message": f"{deleted_count} 件のメッセージを削除しました",
    }


@mcp.tool()
async def register_agent_to_ipc(agent_id: str, ctx: Context = None) -> dict[str, Any]:
    """エージェントをIPCシステムに登録する。

    Args:
        agent_id: エージェントID

    Returns:
        登録結果（success, agent_id, message）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    ipc = _ensure_ipc_manager(app_ctx)

    ipc.register_agent(agent_id)

    return {
        "success": True,
        "agent_id": agent_id,
        "message": f"エージェント {agent_id} をIPCに登録しました",
    }


# ========== ダッシュボード/タスク管理 Tools ==========


def _ensure_dashboard_manager(app_ctx: AppContext) -> DashboardManager:
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


@mcp.tool()
async def create_task(
    title: str,
    description: str = "",
    assigned_agent_id: str | None = None,
    branch: str | None = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """新しいタスクを作成する。

    Args:
        title: タスクタイトル
        description: タスク説明
        assigned_agent_id: 割り当て先エージェントID（オプション）
        branch: 作業ブランチ（オプション）

    Returns:
        作成結果（success, task, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    dashboard = _ensure_dashboard_manager(app_ctx)

    task = dashboard.create_task(
        title=title,
        description=description,
        assigned_agent_id=assigned_agent_id,
        branch=branch,
    )

    return {
        "success": True,
        "task": task.model_dump(mode="json"),
        "message": f"タスクを作成しました: {task.id}",
    }


@mcp.tool()
async def update_task_status(
    task_id: str,
    status: str,
    progress: int | None = None,
    error_message: str | None = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """タスクのステータスを更新する。

    Args:
        task_id: タスクID
        status: 新しいステータス（pending/in_progress/completed/failed/blocked）
        progress: 進捗率（0-100）
        error_message: エラーメッセージ（failedの場合）

    Returns:
        更新結果（success, task_id, status, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    dashboard = _ensure_dashboard_manager(app_ctx)

    # ステータスの検証
    try:
        task_status = TaskStatus(status)
    except ValueError:
        valid_statuses = [s.value for s in TaskStatus]
        return {
            "success": False,
            "error": f"無効なステータスです: {status}（有効: {valid_statuses}）",
        }

    success, message = dashboard.update_task_status(
        task_id=task_id,
        status=task_status,
        progress=progress,
        error_message=error_message,
    )

    return {
        "success": success,
        "task_id": task_id,
        "status": status if success else None,
        "message": message,
    }


@mcp.tool()
async def assign_task_to_agent(
    task_id: str,
    agent_id: str,
    branch: str | None = None,
    worktree_path: str | None = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """タスクをエージェントに割り当てる。

    Args:
        task_id: タスクID
        agent_id: エージェントID
        branch: 作業ブランチ（オプション）
        worktree_path: worktreeパス（オプション）

    Returns:
        割り当て結果（success, task_id, agent_id, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    dashboard = _ensure_dashboard_manager(app_ctx)

    # エージェントの存在確認
    if agent_id not in app_ctx.agents:
        return {
            "success": False,
            "error": f"エージェント {agent_id} が見つかりません",
        }

    success, message = dashboard.assign_task(
        task_id=task_id,
        agent_id=agent_id,
        branch=branch,
        worktree_path=worktree_path,
    )

    return {
        "success": success,
        "task_id": task_id,
        "agent_id": agent_id if success else None,
        "message": message,
    }


@mcp.tool()
async def list_tasks(
    status: str | None = None,
    agent_id: str | None = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """タスク一覧を取得する。

    Args:
        status: フィルターするステータス（オプション）
        agent_id: フィルターするエージェントID（オプション）

    Returns:
        タスク一覧（success, tasks, count または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    dashboard = _ensure_dashboard_manager(app_ctx)

    # ステータスの検証
    task_status = None
    if status:
        try:
            task_status = TaskStatus(status)
        except ValueError:
            valid_statuses = [s.value for s in TaskStatus]
            return {
                "success": False,
                "error": f"無効なステータスです: {status}（有効: {valid_statuses}）",
            }

    tasks = dashboard.list_tasks(status=task_status, agent_id=agent_id)

    return {
        "success": True,
        "tasks": [t.model_dump(mode="json") for t in tasks],
        "count": len(tasks),
    }


@mcp.tool()
async def get_task(task_id: str, ctx: Context = None) -> dict[str, Any]:
    """タスクの詳細を取得する。

    Args:
        task_id: タスクID

    Returns:
        タスク詳細（success, task または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    dashboard = _ensure_dashboard_manager(app_ctx)

    task = dashboard.get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"タスク {task_id} が見つかりません",
        }

    return {
        "success": True,
        "task": task.model_dump(mode="json"),
    }


@mcp.tool()
async def remove_task(task_id: str, ctx: Context = None) -> dict[str, Any]:
    """タスクを削除する。

    Args:
        task_id: タスクID

    Returns:
        削除結果（success, task_id, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    dashboard = _ensure_dashboard_manager(app_ctx)

    success, message = dashboard.remove_task(task_id)

    return {
        "success": success,
        "task_id": task_id,
        "message": message,
    }


@mcp.tool()
async def get_dashboard(ctx: Context = None) -> dict[str, Any]:
    """ダッシュボード全体を取得する。

    Returns:
        ダッシュボード情報（success, dashboard）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    dashboard = _ensure_dashboard_manager(app_ctx)

    # エージェント情報を同期
    for agent in app_ctx.agents.values():
        dashboard.update_agent_summary(agent)

    dashboard_data = dashboard.get_dashboard()

    return {
        "success": True,
        "dashboard": dashboard_data.model_dump(mode="json"),
    }


@mcp.tool()
async def get_dashboard_summary(ctx: Context = None) -> dict[str, Any]:
    """ダッシュボードのサマリーを取得する。

    Returns:
        サマリー情報（success, summary）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    dashboard = _ensure_dashboard_manager(app_ctx)

    # エージェント情報を同期
    for agent in app_ctx.agents.values():
        dashboard.update_agent_summary(agent)

    summary = dashboard.get_summary()

    return {
        "success": True,
        "summary": summary,
    }


# ========== AI CLI Tools ==========


@mcp.tool()
async def get_available_ai_clis(ctx: Context = None) -> dict[str, Any]:
    """利用可能なAI CLI一覧を取得する。

    Returns:
        AI CLI一覧（success, clis, default）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    ai_cli = app_ctx.ai_cli

    return {
        "success": True,
        "clis": ai_cli.get_all_cli_info(),
        "default": ai_cli.get_default_cli().value,
    }


@mcp.tool()
async def open_worktree_with_ai_cli(
    worktree_path: str,
    cli: str | None = None,
    prompt: str | None = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """指定のAI CLIでworktreeを開く。

    Args:
        worktree_path: worktreeのパス
        cli: 使用するAI CLI（claude/codex/gemini、省略でデフォルト）
        prompt: 初期プロンプト（オプション）

    Returns:
        実行結果（success, cli, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    ai_cli_manager = app_ctx.ai_cli

    # CLI の検証
    selected_cli = None
    if cli:
        try:
            selected_cli = AICli(cli)
        except ValueError:
            valid_clis = [c.value for c in AICli]
            return {
                "success": False,
                "error": f"無効なAI CLIです: {cli}（有効: {valid_clis}）",
            }

    success, message = await ai_cli_manager.open_worktree(
        worktree_path, selected_cli, prompt
    )

    used_cli = selected_cli or ai_cli_manager.get_default_cli()

    # コスト記録
    if success and app_ctx.cost_manager:
        app_ctx.cost_manager.record_call(used_cli.value)

    return {
        "success": success,
        "cli": used_cli.value if success else None,
        "worktree_path": worktree_path if success else None,
        "message": message,
    }


# ========== Gtrconfig Tools ==========


def _get_gtrconfig_manager(app_ctx: AppContext, project_path: str) -> GtrconfigManager:
    """指定プロジェクトのGtrconfigManagerを取得または作成する。"""
    if project_path not in app_ctx.gtrconfig_managers:
        app_ctx.gtrconfig_managers[project_path] = GtrconfigManager(project_path)
    return app_ctx.gtrconfig_managers[project_path]


@mcp.tool()
async def check_gtrconfig(project_path: str, ctx: Context = None) -> dict[str, Any]:
    """Gtrconfigの存在確認と内容取得。

    Args:
        project_path: プロジェクトのルートパス

    Returns:
        Gtrconfig状態（success, status）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    gtrconfig = _get_gtrconfig_manager(app_ctx, project_path)

    status = gtrconfig.get_status()

    return {
        "success": True,
        "status": status,
    }


@mcp.tool()
async def analyze_project_for_gtrconfig(
    project_path: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """プロジェクト構造を解析して推奨設定を提案する。

    Args:
        project_path: プロジェクトのルートパス

    Returns:
        推奨設定（success, recommended_config）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    gtrconfig = _get_gtrconfig_manager(app_ctx, project_path)

    config = gtrconfig.analyze_project()

    return {
        "success": True,
        "recommended_config": config,
    }


@mcp.tool()
async def generate_gtrconfig(
    project_path: str,
    overwrite: bool = False,
    generate_example: bool = True,
    ctx: Context = None,
) -> dict[str, Any]:
    """Gtrconfigを自動生成する。

    Args:
        project_path: プロジェクトのルートパス
        overwrite: 既存ファイルを上書きするか
        generate_example: .gtrconfig.example も生成するか

    Returns:
        生成結果（success, config, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    gtrconfig = _get_gtrconfig_manager(app_ctx, project_path)

    success, result = gtrconfig.generate(overwrite)

    if not success:
        return {
            "success": False,
            "error": result,
        }

    # .gtrconfig.example も生成
    if generate_example:
        gtrconfig.generate_example()

    return {
        "success": True,
        "config": result,
        "message": ".gtrconfig を生成しました",
    }


# ========== Template Tools ==========


@mcp.tool()
async def list_workspace_templates(ctx: Context = None) -> dict[str, Any]:
    """利用可能なテンプレート一覧を取得する。

    Returns:
        テンプレート一覧（success, templates, names）
    """
    templates = list_templates()

    return {
        "success": True,
        "templates": [t.to_dict() for t in templates],
        "names": get_template_names(),
    }


@mcp.tool()
async def get_workspace_template(
    template_name: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """特定テンプレートの詳細を取得する。

    Args:
        template_name: テンプレート名

    Returns:
        テンプレート詳細（success, template または error）
    """
    template = get_template(template_name)

    if not template:
        return {
            "success": False,
            "error": f"テンプレート '{template_name}' が見つかりません。"
            f"有効なテンプレート: {get_template_names()}",
        }

    return {
        "success": True,
        "template": template.to_dict(),
    }


# ========== Scheduler Tools ==========


def _ensure_scheduler_manager(app_ctx: AppContext) -> SchedulerManager:
    """SchedulerManagerが初期化されていることを確認する。"""
    if app_ctx.scheduler_manager is None:
        dashboard = _ensure_dashboard_manager(app_ctx)
        app_ctx.scheduler_manager = SchedulerManager(dashboard, app_ctx.agents)
    return app_ctx.scheduler_manager


@mcp.tool()
async def enqueue_task(
    task_id: str,
    priority: str = "medium",
    dependencies: list[str] | None = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """タスクをスケジューラーキューに追加する。

    Args:
        task_id: タスクID
        priority: 優先度（critical/high/medium/low）
        dependencies: 依存タスクのIDリスト

    Returns:
        追加結果（success, task_id, priority, message または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    scheduler = _ensure_scheduler_manager(app_ctx)

    # 優先度の検証
    try:
        task_priority = TaskPriority[priority.upper()]
    except KeyError:
        valid_priorities = [p.name.lower() for p in TaskPriority]
        return {
            "success": False,
            "error": f"無効な優先度です: {priority}（有効: {valid_priorities}）",
        }

    success = scheduler.enqueue_task(task_id, task_priority, dependencies)

    if not success:
        return {
            "success": False,
            "error": f"タスク {task_id} は既にキューに存在します",
        }

    return {
        "success": True,
        "task_id": task_id,
        "priority": priority,
        "message": f"タスク {task_id} をキューに追加しました",
    }


@mcp.tool()
async def auto_assign_tasks(ctx: Context = None) -> dict[str, Any]:
    """空いているWorkerにタスクを自動割り当てする。

    Returns:
        割り当て結果（success, assignments, count）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    scheduler = _ensure_scheduler_manager(app_ctx)

    assignments = scheduler.run_auto_assign_loop()

    return {
        "success": True,
        "assignments": [
            {"task_id": tid, "worker_id": wid} for tid, wid in assignments
        ],
        "count": len(assignments),
        "message": f"{len(assignments)} 件のタスクを割り当てました",
    }


@mcp.tool()
async def get_task_queue(ctx: Context = None) -> dict[str, Any]:
    """現在のタスクキューを取得する。

    Returns:
        キュー状態（success, queue）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    scheduler = _ensure_scheduler_manager(app_ctx)

    queue_status = scheduler.get_queue_status()

    return {
        "success": True,
        "queue": queue_status,
    }


# ========== Healthcheck Tools ==========


def _ensure_healthcheck_manager(app_ctx: AppContext) -> HealthcheckManager:
    """HealthcheckManagerが初期化されていることを確認する。"""
    if app_ctx.healthcheck_manager is None:
        app_ctx.healthcheck_manager = HealthcheckManager(
            app_ctx.tmux,
            app_ctx.agents,
            app_ctx.settings.heartbeat_timeout_seconds,
        )
    return app_ctx.healthcheck_manager


@mcp.tool()
async def healthcheck_agent(agent_id: str, ctx: Context = None) -> dict[str, Any]:
    """特定エージェントのヘルスチェックを実行する。

    Args:
        agent_id: エージェントID

    Returns:
        ヘルス状態（success, health_status）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    healthcheck = _ensure_healthcheck_manager(app_ctx)

    status = await healthcheck.check_agent(agent_id)

    return {
        "success": True,
        "health_status": status.to_dict(),
    }


@mcp.tool()
async def healthcheck_all(ctx: Context = None) -> dict[str, Any]:
    """全エージェントのヘルスチェックを実行する。

    Returns:
        全ヘルス状態（success, statuses, summary）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    healthcheck = _ensure_healthcheck_manager(app_ctx)

    statuses = await healthcheck.check_all_agents()
    healthy_count = sum(1 for s in statuses if s.is_healthy)
    unhealthy_count = len(statuses) - healthy_count

    return {
        "success": True,
        "statuses": [s.to_dict() for s in statuses],
        "summary": {
            "total": len(statuses),
            "healthy": healthy_count,
            "unhealthy": unhealthy_count,
        },
    }


@mcp.tool()
async def get_unhealthy_agents(ctx: Context = None) -> dict[str, Any]:
    """異常なエージェント一覧を取得する。

    Returns:
        異常エージェント一覧（success, unhealthy_agents, count）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    healthcheck = _ensure_healthcheck_manager(app_ctx)

    unhealthy = await healthcheck.get_unhealthy_agents()

    return {
        "success": True,
        "unhealthy_agents": [s.to_dict() for s in unhealthy],
        "count": len(unhealthy),
    }


@mcp.tool()
async def attempt_recovery(agent_id: str, ctx: Context = None) -> dict[str, Any]:
    """エージェントの復旧を試みる。

    Args:
        agent_id: エージェントID

    Returns:
        復旧結果（success, message）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    healthcheck = _ensure_healthcheck_manager(app_ctx)

    success, message = await healthcheck.attempt_recovery(agent_id)

    return {
        "success": success,
        "agent_id": agent_id,
        "message": message,
    }


@mcp.tool()
async def record_heartbeat(agent_id: str, ctx: Context = None) -> dict[str, Any]:
    """ハートビートを記録する。

    Args:
        agent_id: エージェントID

    Returns:
        記録結果（success, message）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    healthcheck = _ensure_healthcheck_manager(app_ctx)

    success = healthcheck.record_heartbeat(agent_id)

    return {
        "success": success,
        "agent_id": agent_id,
        "message": "ハートビートを記録しました" if success else "エージェントが見つかりません",
    }


# ========== Metrics Tools ==========


def _ensure_metrics_manager(app_ctx: AppContext) -> MetricsManager:
    """MetricsManagerが初期化されていることを確認する。"""
    if app_ctx.metrics_manager is None:
        metrics_dir = os.path.join(app_ctx.settings.workspace_base_dir, ".metrics")
        app_ctx.metrics_manager = MetricsManager(metrics_dir)
    return app_ctx.metrics_manager


@mcp.tool()
async def get_task_metrics(task_id: str, ctx: Context = None) -> dict[str, Any]:
    """タスクのメトリクスを取得する。

    Args:
        task_id: タスクID

    Returns:
        タスクメトリクス（success, metrics または error）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    metrics = _ensure_metrics_manager(app_ctx)

    task_metrics = metrics.get_task_metrics(task_id)

    if not task_metrics:
        return {
            "success": False,
            "error": f"タスク {task_id} のメトリクスが見つかりません",
        }

    return {
        "success": True,
        "metrics": task_metrics.to_dict(),
    }


@mcp.tool()
async def get_agent_metrics(agent_id: str, ctx: Context = None) -> dict[str, Any]:
    """エージェントのメトリクスを取得する。

    Args:
        agent_id: エージェントID

    Returns:
        エージェントメトリクス（success, metrics）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    metrics = _ensure_metrics_manager(app_ctx)

    agent_metrics = metrics.get_agent_metrics(agent_id)

    return {
        "success": True,
        "metrics": agent_metrics.to_dict(),
    }


@mcp.tool()
async def get_workspace_metrics(ctx: Context = None) -> dict[str, Any]:
    """ワークスペース全体のメトリクスを取得する。

    Returns:
        ワークスペースメトリクス（success, metrics）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    metrics = _ensure_metrics_manager(app_ctx)

    workspace_metrics = metrics.get_workspace_metrics(app_ctx.agents)

    return {
        "success": True,
        "metrics": workspace_metrics.to_dict(),
    }


@mcp.tool()
async def get_metrics_summary(ctx: Context = None) -> dict[str, Any]:
    """メトリクスのサマリーを取得する。

    Returns:
        サマリー（success, summary）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    metrics = _ensure_metrics_manager(app_ctx)

    summary = metrics.get_summary()

    return {
        "success": True,
        "summary": summary,
    }


# ========== Cost Tools ==========


def _ensure_cost_manager(app_ctx: AppContext) -> CostManager:
    """CostManagerが初期化されていることを確認する。"""
    if app_ctx.cost_manager is None:
        app_ctx.cost_manager = CostManager(
            app_ctx.settings.cost_warning_threshold_usd
        )
    return app_ctx.cost_manager


@mcp.tool()
async def get_cost_estimate(ctx: Context = None) -> dict[str, Any]:
    """現在のコスト推定を取得する。

    Returns:
        コスト推定（success, estimate, warning）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    cost = _ensure_cost_manager(app_ctx)

    estimate = cost.get_estimate()
    warning = cost.check_warning()

    return {
        "success": True,
        "estimate": estimate.to_dict(),
        "warning": warning,
    }


@mcp.tool()
async def set_cost_warning_threshold(
    threshold_usd: float,
    ctx: Context = None,
) -> dict[str, Any]:
    """コスト警告の閾値を設定する。

    Args:
        threshold_usd: 新しい閾値（USD）

    Returns:
        設定結果（success, threshold, message）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    cost = _ensure_cost_manager(app_ctx)

    cost.set_warning_threshold(threshold_usd)

    return {
        "success": True,
        "threshold": threshold_usd,
        "message": f"コスト警告閾値を ${threshold_usd:.2f} に設定しました",
    }


@mcp.tool()
async def reset_cost_counter(ctx: Context = None) -> dict[str, Any]:
    """コストカウンターをリセットする。

    Returns:
        リセット結果（success, deleted_count, message）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    cost = _ensure_cost_manager(app_ctx)

    deleted = cost.reset()

    return {
        "success": True,
        "deleted_count": deleted,
        "message": f"{deleted} 件の記録をリセットしました",
    }


@mcp.tool()
async def get_cost_summary(ctx: Context = None) -> dict[str, Any]:
    """コストサマリーを取得する。

    Returns:
        コストサマリー（success, summary）
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    cost = _ensure_cost_manager(app_ctx)

    summary = cost.get_summary()

    return {
        "success": True,
        "summary": summary,
    }


def main() -> None:
    """MCPサーバーを起動する。"""
    mcp.run()


if __name__ == "__main__":
    main()
