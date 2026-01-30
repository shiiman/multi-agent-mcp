"""Git worktree管理ツール。"""

import logging
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.tools.helpers import get_worktree_manager

logger = logging.getLogger(__name__)


def register_tools(mcp: FastMCP) -> None:
    """Git worktree管理ツールを登録する。"""

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
        worktree = get_worktree_manager(app_ctx, repo_path)

        # リポジトリの確認
        if not await worktree.is_git_repo():
            return {
                "success": False,
                "error": f"有効なgitリポジトリではありません: {repo_path}",
            }

        success, message, actual_path = await worktree.create_worktree(
            worktree_path, branch, create_branch, base_branch
        )

        if success:
            logger.info(f"worktreeを作成しました: {actual_path} ({branch})")

        return {
            "success": success,
            "worktree_path": actual_path if success else None,
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
        worktree = get_worktree_manager(app_ctx, repo_path)

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
        worktree = get_worktree_manager(app_ctx, repo_path)

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
        worktree = get_worktree_manager(app_ctx, repo_path)

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
        worktree = get_worktree_manager(app_ctx, repo_path)

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
        worktree = get_worktree_manager(app_ctx, repo_path)

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
        worktree = get_worktree_manager(app_ctx, repo_path)

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
