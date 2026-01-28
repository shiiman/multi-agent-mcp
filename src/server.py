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

from src.config.settings import Settings
from src.managers.dashboard_manager import DashboardManager
from src.managers.ipc_manager import IPCManager
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
    agents: dict[str, Agent] = field(default_factory=dict)
    worktree_managers: dict[str, WorktreeManager] = field(default_factory=dict)
    ipc_manager: IPCManager | None = None
    dashboard_manager: DashboardManager | None = None
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

    # ワークスペースディレクトリを作成
    os.makedirs(settings.workspace_base_dir, exist_ok=True)

    try:
        yield AppContext(settings=settings, tmux=tmux)
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


def main() -> None:
    """MCPサーバーを起動する。"""
    mcp.run()


if __name__ == "__main__":
    main()
