"""セッション管理ツール。"""

import logging
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.tools.helpers import get_gtrconfig_manager, get_worktree_manager

logger = logging.getLogger(__name__)


def generate_env_template() -> str:
    """設定可能な変数とデフォルト値を含む .env テンプレートを生成する。

    Returns:
        .env ファイルの内容
    """
    return '''# Multi-Agent MCP プロジェクト設定
# 環境変数で上書きされます（環境変数 > .env > デフォルト）

# ========== エージェント設定 ==========
# Worker エージェントの最大数
MCP_MAX_WORKERS=6

# ========== モデルプロファイル ==========
# 現在のプロファイル（standard / performance）
MCP_MODEL_PROFILE_ACTIVE=standard

# standard プロファイル設定（Sonnet）
MCP_MODEL_PROFILE_STANDARD_CLI=claude
MCP_MODEL_PROFILE_STANDARD_MODEL=claude-sonnet-4-20250514
MCP_MODEL_PROFILE_STANDARD_MAX_WORKERS=6
MCP_MODEL_PROFILE_STANDARD_THINKING_MULTIPLIER=1.0

# performance プロファイル設定（Opus）
MCP_MODEL_PROFILE_PERFORMANCE_CLI=claude
MCP_MODEL_PROFILE_PERFORMANCE_MODEL=claude-opus-4-20250514
MCP_MODEL_PROFILE_PERFORMANCE_MAX_WORKERS=16
MCP_MODEL_PROFILE_PERFORMANCE_THINKING_MULTIPLIER=2.0

# ========== コスト設定 ==========
# コスト警告の閾値（USD）
MCP_COST_WARNING_THRESHOLD_USD=10.0

# ========== ヘルスチェック設定 ==========
# ヘルスチェックの間隔（秒）
MCP_HEALTHCHECK_INTERVAL_SECONDS=300

# ハートビートタイムアウト（秒）
MCP_HEARTBEAT_TIMEOUT_SECONDS=300

# ========== Extended Thinking 設定 ==========
# Owner の思考トークン数（0 = 即断即決モード）
MCP_OWNER_THINKING_TOKENS=0

# Admin の思考トークン数
MCP_ADMIN_THINKING_TOKENS=1000

# Worker の思考トークン数
MCP_WORKER_THINKING_TOKENS=10000
'''


def _setup_mcp_directories(working_dir: str) -> dict[str, Any]:
    """MCP ディレクトリと .env ファイルをセットアップする。

    Args:
        working_dir: 作業ディレクトリのパス

    Returns:
        セットアップ結果（created_dirs, env_created, env_path）
    """
    mcp_dir = Path(working_dir) / ".multi-agent-mcp"
    created_dirs = []

    # memory ディレクトリ作成
    memory_dir = mcp_dir / "memory"
    if not memory_dir.exists():
        memory_dir.mkdir(parents=True, exist_ok=True)
        created_dirs.append("memory")

    # screenshot ディレクトリ作成
    screenshot_dir = mcp_dir / "screenshot"
    if not screenshot_dir.exists():
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        created_dirs.append("screenshot")

    # .env ファイル作成（存在しない場合のみ）
    env_file = mcp_dir / ".env"
    env_created = False
    if not env_file.exists():
        env_file.write_text(generate_env_template())
        env_created = True
        logger.info(f".env テンプレートを作成しました: {env_file}")

    return {
        "created_dirs": created_dirs,
        "env_created": env_created,
        "env_path": str(env_file),
    }


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

        # worktree のパスを収集（削除前に取得）
        worktree_paths = []
        main_repo_path = None
        for agent in agents.values():
            if agent.worktree_path:
                worktree_paths.append(agent.worktree_path)
                # メインリポジトリのパスを取得（working_dir から）
                if agent.working_dir and not main_repo_path:
                    main_repo_path = agent.working_dir

        terminated_count = await tmux.cleanup_all_sessions()
        agent_count = len(agents)
        agents.clear()

        # worktree を削除
        removed_worktrees = 0
        if worktree_paths and main_repo_path:
            try:
                worktree_manager = get_worktree_manager(app_ctx, main_repo_path)
                for worktree_path in worktree_paths:
                    try:
                        success, _ = await worktree_manager.remove_worktree(
                            worktree_path, force=True
                        )
                        if success:
                            removed_worktrees += 1
                    except Exception as e:
                        logger.warning(f"worktree 削除失敗: {worktree_path} - {e}")
            except Exception as e:
                logger.warning(f"WorktreeManager の初期化に失敗: {e}")

        return {
            "success": True,
            "terminated_sessions": terminated_count,
            "cleared_agents": agent_count,
            "removed_worktrees": removed_worktrees,
            "was_forced": force and not status["is_all_completed"],
            **status,
            "message": (
                f"クリーンアップ完了: {terminated_count}セッション終了, "
                f"{agent_count}エージェントクリア, "
                f"{removed_worktrees}worktree削除"
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

        # MCP ディレクトリと .env ファイルのセットアップ
        mcp_setup = _setup_mcp_directories(working_dir)
        logger.info(
            f"MCP ディレクトリをセットアップしました: "
            f"作成={mcp_setup['created_dirs']}, env_created={mcp_setup['env_created']}"
        )

        # project_root を設定（screenshot 等で使用）
        app_ctx.project_root = working_dir
        logger.info(f"project_root を設定しました: {working_dir}")

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
