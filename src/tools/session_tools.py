"""セッション管理ツール実装。"""

import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.managers.tmux_manager import get_project_name
from src.tools.helpers import (
    get_gtrconfig_manager,
    get_worktree_manager,
    refresh_app_settings,
    require_permission,
    resolve_main_repo_root,
)
from src.tools.session_env import _setup_mcp_directories
from src.tools.session_state import (
    _check_completion_status,
    cleanup_session_resources,
)

logger = logging.getLogger(__name__)

def register_tools(mcp: FastMCP) -> None:
    """セッション管理ツールを登録する。"""

    @mcp.tool()
    async def cleanup_workspace(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """ワークスペースをクリーンアップする。

        全エージェントを終了し、リソースを解放する。

        ※ Owner のみ使用可能。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            クリーンアップ結果（success, terminated_sessions, cleared_agents, message）
        """
        app_ctx, role_error = require_permission(ctx, "cleanup_workspace", caller_agent_id)
        if role_error:
            return role_error

        results = await cleanup_session_resources(
            app_ctx, remove_worktrees=False
        )

        return {
            "success": True,
            **results,
            "message": (
                f"{results['terminated_sessions']} セッションを終了、"
                f"{results['cleared_agents']} エージェント情報をクリアしました"
            ),
        }

    @mcp.tool()
    async def check_all_tasks_completed(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """全タスクが完了したかチェックする。

        完了条件: pending=0, in_progress=0, failed=0
        failedタスクがある場合は完了と見なさない。

        ※ Owner のみ使用可能。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            is_all_completed: 全タスク完了か
            total_tasks: 総タスク数
            pending_tasks: 未着手タスク数
            in_progress_tasks: 進行中タスク数
            completed_tasks: 完了タスク数
            failed_tasks: 失敗タスク数
        """
        app_ctx, role_error = require_permission(ctx, "check_all_tasks_completed", caller_agent_id)
        if role_error:
            return role_error

        status = _check_completion_status(app_ctx)

        return {
            "success": "error" not in status,
            **status,
        }

    @mcp.tool()
    async def cleanup_on_completion(
        force: bool = False,
        repo_path: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """全タスク完了時にワークスペースをクリーンアップする。

        タスクが完了していない場合はエラーを返す。
        force=True で未完了でも強制クリーンアップ。

        ※ Owner のみ使用可能。

        Args:
            force: 未完了でも強制的にクリーンアップするか
            repo_path: メインリポジトリのパス（worktree 削除に使用）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            クリーンアップ結果
        """
        app_ctx, role_error = require_permission(ctx, "cleanup_on_completion", caller_agent_id)
        if role_error:
            return role_error

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

        # 統一クリーンアップ実行
        results = await cleanup_session_resources(
            app_ctx, remove_worktrees=True, repo_path=repo_path
        )

        result = {
            "success": True,
            **results,
            "was_forced": force and not status["is_all_completed"],
            **status,
            "message": (
                f"クリーンアップ完了: {results['terminated_sessions']}セッション終了, "
                f"{results['cleared_agents']}エージェントクリア, "
                f"{results['removed_worktrees']}worktree削除, "
                f"{results['registry_removed']}レジストリ削除"
            ),
        }

        return result

    @mcp.tool()
    async def init_tmux_workspace(
        working_dir: str,
        open_terminal: bool = True,
        auto_setup_gtr: bool = True,
        session_id: str | None = None,
        caller_agent_id: str | None = None,
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

        ※ Owner のみ使用可能。

        Args:
            working_dir: 作業ディレクトリのパス
            open_terminal: Trueでターミナルを開いて表示（デフォルト）、
                           Falseでバックグラウンド作成
            auto_setup_gtr: gtr利用可能時に自動でgtrconfig設定（デフォルト: True）
            session_id: セッションID（省略時は None、指定時はディレクトリ構造に使用）
            caller_agent_id: 呼び出し元エージェントID（指定時はロールチェック）

        Returns:
            初期化結果（success, session_name, gtr_status, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "init_tmux_workspace", caller_agent_id)
        if role_error:
            return role_error

        tmux = app_ctx.tmux

        # 既存の tmux セッションが存在するかチェック（重複起動防止）
        project_name = get_project_name(working_dir)
        session_exists = await tmux.session_exists(project_name)
        if session_exists:
            # 既存セッションのリカバリ: 古いリソースをクリーンアップして再初期化
            logger.warning(
                f"既存の tmux セッション '{project_name}' を検出。"
                "古いリソースをクリーンアップして再初期化します。"
            )
            await cleanup_session_resources(app_ctx, remove_worktrees=False)
            # tmux セッションを明示的に kill
            await tmux.kill_session(project_name)
            # 再チェック: kill できなかった場合はエラー
            if await tmux.session_exists(project_name):
                return {
                    "success": False,
                    "error": (
                        f"既存の tmux セッション '{project_name}' の削除に失敗しました。"
                        "手動で `tmux kill-session` を実行してください。"
                    ),
                }

        # session_id を設定（後続の create_agent 等で使用）
        if session_id:
            app_ctx.session_id = session_id

            # session_id 設定後、既存エージェント（Owner 等）をファイルに再保存
            # Owner は init_tmux_workspace の前に作成されるため、
            # session_id 未設定で agents.json への保存に失敗している
            from src.tools.helpers_persistence import save_agent_to_file as _save_agent

            for agent in app_ctx.agents.values():
                _save_agent(app_ctx, agent)

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

                    # gtrconfig が存在しない場合は自動生成してコミット
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
        mcp_setup = _setup_mcp_directories(working_dir, session_id=session_id)
        logger.info(
            f"MCP ディレクトリをセットアップしました: "
            f"作成={mcp_setup['created_dirs']}, env_created={mcp_setup['env_created']}"
        )

        # project_root を設定（screenshot 等で使用）
        app_ctx.project_root = resolve_main_repo_root(working_dir)
        refresh_app_settings(app_ctx, app_ctx.project_root)
        logger.info(f"project_root を設定しました: {app_ctx.project_root}")

        # Dashboard マネージャーを初期化（Owner のみが行う）
        # Worker の MCP プロセスでは initialize() を呼ばないため、
        # ここで明示的にディレクトリとファイルを作成する
        from src.tools.helpers_managers import ensure_dashboard_manager

        dashboard = ensure_dashboard_manager(app_ctx)
        dashboard.initialize()

        # セッション名を計算（プロジェクト名をそのまま使用）
        project_name = get_project_name(working_dir)
        session_name = project_name

        if open_terminal:
            # ターミナルを開いてセッション作成
            success, message = await tmux.launch_workspace_in_terminal(working_dir)
            if success:
                return {
                    "success": True,
                    "session_name": session_name,
                    "session_id": session_id,
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
                    "session_name": session_name,
                    "session_id": session_id,
                    "gtr_status": gtr_status,
                    "message": "メインセッションをバックグラウンドで作成しました",
                }
            else:
                return {
                    "success": False,
                    "gtr_status": gtr_status,
                    "error": "メインセッションの作成に失敗しました",
                }
