"""セッション管理ツール。"""

import logging
import os
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.tools.helpers import get_gtrconfig_manager, get_worktree_manager

logger = logging.getLogger(__name__)


def register_tools(mcp: FastMCP) -> None:
    """セッション管理ツールを登録する。"""

    def _check_completion_status(app_ctx: AppContext) -> dict[str, Any]:
        """タスク完了状態を計算する。

        Args:
            app_ctx: アプリケーションコンテキスト

        Returns:
            完了状態の辞書
        """
        if app_ctx.dashboard_manager is None:
            return {
                "is_all_completed": False,
                "total_tasks": 0,
                "pending_tasks": 0,
                "in_progress_tasks": 0,
                "completed_tasks": 0,
                "failed_tasks": 0,
                "error": "ワークスペースが初期化されていません",
            }

        summary = app_ctx.dashboard_manager.get_summary()

        total = summary["total_tasks"]
        pending = summary["pending_tasks"]
        in_progress = summary["in_progress_tasks"]
        completed = summary["completed_tasks"]
        failed = summary["failed_tasks"]

        # 完了条件: タスクがあり、pending/in_progress/failedが全て0
        is_completed = (total > 0) and (pending == 0) and (in_progress == 0) and (failed == 0)

        return {
            "is_all_completed": is_completed,
            "total_tasks": total,
            "pending_tasks": pending,
            "in_progress_tasks": in_progress,
            "completed_tasks": completed,
            "failed_tasks": failed,
        }

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

    @mcp.tool()
    async def check_all_tasks_completed(ctx: Context) -> dict[str, Any]:
        """全タスクが完了したかチェックする。

        完了条件: pending=0, in_progress=0, failed=0
        failedタスクがある場合は完了と見なさない。

        Returns:
            is_all_completed: 全タスク完了か
            total_tasks: 総タスク数
            pending_tasks: 未着手タスク数
            in_progress_tasks: 進行中タスク数
            completed_tasks: 完了タスク数
            failed_tasks: 失敗タスク数
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        status = _check_completion_status(app_ctx)

        return {
            "success": "error" not in status,
            **status,
        }

    @mcp.tool()
    async def cleanup_on_completion(
        force: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """全タスク完了時にワークスペースをクリーンアップする。

        タスクが完了していない場合はエラーを返す。
        force=True で未完了でも強制クリーンアップ。

        Args:
            force: 未完了でも強制的にクリーンアップするか

        Returns:
            クリーンアップ結果
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        status = _check_completion_status(app_ctx)

        # エラーチェック
        if "error" in status:
            return {
                "success": False,
                "error": status["error"],
            }

        # 完了チェック
        if not status["is_all_completed"] and not force:
            incomplete_reason = []
            if status["pending_tasks"] > 0:
                incomplete_reason.append(f"未着手: {status['pending_tasks']}件")
            if status["in_progress_tasks"] > 0:
                incomplete_reason.append(f"進行中: {status['in_progress_tasks']}件")
            if status["failed_tasks"] > 0:
                incomplete_reason.append(f"失敗: {status['failed_tasks']}件")

            return {
                "success": False,
                "error": f"まだ完了していないタスクがあります（{', '.join(incomplete_reason)}）",
                **status,
            }

        # クリーンアップ実行
        tmux = app_ctx.tmux
        agents = app_ctx.agents

        terminated_count = await tmux.cleanup_all_sessions()
        agent_count = len(agents)
        agents.clear()

        return {
            "success": True,
            "terminated_sessions": terminated_count,
            "cleared_agents": agent_count,
            "was_forced": force and not status["is_all_completed"],
            **status,
            "message": (
                f"クリーンアップ完了: {terminated_count}セッション終了, "
                f"{agent_count}エージェントクリア"
            ),
        }

    @mcp.tool()
    async def init_tmux_workspace(
        working_dir: str,
        open_terminal: bool = True,
        auto_setup_gtr: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """ターミナルを開いてtmuxワークスペース（グリッドレイアウト）を構築する。

        ターミナルを先に起動し、その中でtmuxセッション作成・ペイン分割を行う。
        セッションが既に存在する場合はattachのみ行う。
        gtr が利用可能な場合、gtrconfig を自動確認・生成する。

        レイアウト:
        ┌─────────────┬────────┬────────┬────────┐
        │   pane 0    │ pane 1 │ pane 3 │ pane 5 │
        │   (Admin)   ├────────┼────────┼────────┤
        │    (40%)    │ pane 2 │ pane 4 │ pane 6 │
        └─────────────┴────────┴────────┴────────┘
          左40%          右60% (Workers 1-6)

        Args:
            working_dir: 作業ディレクトリのパス
            open_terminal: Trueでターミナルを開いて表示（デフォルト）、
                           Falseでバックグラウンド作成
            auto_setup_gtr: gtr利用可能時に自動でgtrconfig設定（デフォルト: True）

        Returns:
            初期化結果（success, session_name, gtr_status, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        tmux = app_ctx.tmux

        # gtr 自動確認・設定
        gtr_status = {
            "gtr_available": False,
            "gtrconfig_exists": False,
            "gtrconfig_generated": False,
        }

        if auto_setup_gtr:
            try:
                worktree = get_worktree_manager(app_ctx, working_dir)
                gtr_available = await worktree.is_gtr_available()
                gtr_status["gtr_available"] = gtr_available

                if gtr_available:
                    gtrconfig = get_gtrconfig_manager(app_ctx, working_dir)
                    gtr_status["gtrconfig_exists"] = gtrconfig.exists()

                    # gtrconfig が存在しない場合は自動生成
                    if not gtrconfig.exists():
                        success, result = gtrconfig.generate()
                        if success:
                            gtr_status["gtrconfig_generated"] = True
                            logger.info(f".gtrconfig を自動生成しました: {working_dir}")
                        else:
                            logger.warning(f".gtrconfig 自動生成に失敗: {result}")
            except Exception as e:
                logger.warning(f"gtr 設定確認に失敗: {e}")

        if open_terminal:
            # ターミナルを開いてセッション作成
            success, message = await tmux.launch_workspace_in_terminal(working_dir)
            if success:
                return {
                    "success": True,
                    "session_name": "main",
                    "gtr_status": gtr_status,
                    "message": message,
                }
            else:
                return {
                    "success": False,
                    "gtr_status": gtr_status,
                    "error": message,
                }
        else:
            # バックグラウンドで作成（従来の動作）
            success = await tmux.create_main_session(working_dir)
            if success:
                return {
                    "success": True,
                    "session_name": "main",
                    "gtr_status": gtr_status,
                    "message": "メインセッションをバックグラウンドで作成しました",
                }
            else:
                return {
                    "success": False,
                    "gtr_status": gtr_status,
                    "error": "メインセッションの作成に失敗しました",
                }
