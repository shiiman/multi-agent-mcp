"""セッション管理ツール実装。"""

import logging
import shutil
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.settings import load_effective_settings_for_project
from src.managers import tmux_shared
from src.managers.tmux_manager import get_project_name
from src.tools.helpers import (
    InvalidConfigError,
    get_enable_git_from_config,
    get_gtrconfig_manager,
    get_worktree_manager,
    refresh_app_settings,
    require_permission,
    resolve_main_repo_root,
)
from src.tools.session_env import _setup_mcp_directories
from src.tools.session_state import (
    _check_completion_status,
    cleanup_orphan_provisional_sessions,
    cleanup_session_resources,
)

logger = logging.getLogger(__name__)


def _migrate_provisional_session_dir(
    project_root: str,
    mcp_dir_name: str,
    previous_session_id: str | None,
    new_session_id: str,
) -> dict[str, Any]:
    """provisional セッションディレクトリを正式 session_id 配下へ移行する。"""
    result: dict[str, Any] = {
        "executed": False,
        "source_session_id": previous_session_id,
        "target_session_id": new_session_id,
        "source_removed": False,
    }
    if (
        not previous_session_id
        or previous_session_id == new_session_id
        or not previous_session_id.startswith("provisional-")
    ):
        return result

    base_dir = Path(project_root) / mcp_dir_name
    source_dir = base_dir / previous_session_id
    target_dir = base_dir / new_session_id
    if not source_dir.exists() or not source_dir.is_dir():
        return result

    target_dir.mkdir(parents=True, exist_ok=True)
    for child in source_dir.iterdir():
        target_child = target_dir / child.name
        if child.is_dir() and target_child.exists() and target_child.is_dir():
            shutil.copytree(child, target_child, dirs_exist_ok=True)
            shutil.rmtree(child, ignore_errors=True)
            continue
        if child.is_file() and target_child.exists():
            shutil.copy2(child, target_child)
            child.unlink(missing_ok=True)
            continue
        shutil.move(str(child), str(target_child))

    shutil.rmtree(source_dir, ignore_errors=True)
    result["executed"] = True
    result["source_removed"] = not source_dir.exists()
    return result


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
        enable_git: bool | None = None,
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
            enable_git: git 機能を有効化するか（省略時は config/.env を使用）
            caller_agent_id: 呼び出し元エージェントID（指定時はロールチェック）

        Returns:
            初期化結果（success, session_name, gtr_status, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "init_tmux_workspace", caller_agent_id)
        if role_error:
            return role_error

        tmux = app_ctx.tmux
        working_dir_path = str(Path(working_dir).expanduser())
        try:
            detected_project_root = resolve_main_repo_root(working_dir_path)
            is_git_repo = True
        except ValueError:
            detected_project_root = working_dir_path
            is_git_repo = False

        try:
            config_enable_git = get_enable_git_from_config(working_dir_path, strict=True)
            project_settings = load_effective_settings_for_project(
                detected_project_root, strict_config=True
            )
        except (InvalidConfigError, ValueError) as e:
            return {
                "success": False,
                "error": str(e),
            }
        effective_enable_git = (
            enable_git
            if enable_git is not None
            else config_enable_git
            if config_enable_git is not None
            else project_settings.enable_git
        )

        if effective_enable_git and not is_git_repo:
            return {
                "success": False,
                "error": (
                    f"git が有効ですが `{working_dir}` は git リポジトリではありません。"
                    " 非gitディレクトリで実行する場合は enable_git=false を指定してください。"
                ),
            }

        resolved_project_root = (
            detected_project_root if effective_enable_git else working_dir_path
        )
        app_ctx.settings.enable_git = effective_enable_git
        app_ctx.tmux.settings.enable_git = effective_enable_git
        app_ctx.ai_cli.settings.enable_git = effective_enable_git

        # 旧命名（suffix なし）セッションを新命名（suffix 付き）へ自動移行
        project_name = get_project_name(working_dir, enable_git=effective_enable_git)
        legacy_project_name = tmux_shared.get_legacy_project_name(
            working_dir,
            enable_git=effective_enable_git,
        )
        if legacy_project_name and legacy_project_name != project_name:
            legacy_exists = await tmux.session_exists(legacy_project_name)
            new_exists = await tmux.session_exists(project_name)
            if legacy_exists and not new_exists:
                logger.info(
                    "旧 tmux セッション名を移行します: %s -> %s",
                    legacy_project_name,
                    project_name,
                )
                renamed = await tmux.rename_session(legacy_project_name, project_name)
                if not renamed:
                    return {
                        "success": False,
                        "error": (
                            "旧 tmux セッション名から新命名への移行に失敗しました: "
                            f"{legacy_project_name} -> {project_name}"
                        ),
                    }
            elif legacy_exists and new_exists:
                logger.warning(
                    "旧/新 tmux セッションが両方存在するため新命名を優先します: old=%s new=%s",
                    legacy_project_name,
                    project_name,
                )

        # 既存の tmux セッションが存在するかチェック（重複起動防止）
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
        migration_result = {
            "executed": False,
            "source_session_id": app_ctx.session_id,
            "target_session_id": session_id,
            "source_removed": False,
        }
        provisional_cleanup_result = {
            "removed_count": 0,
            "removed_dirs": [],
            "errors": [],
        }
        if session_id:
            migration_result = _migrate_provisional_session_dir(
                project_root=resolved_project_root,
                mcp_dir_name=app_ctx.settings.mcp_dir,
                previous_session_id=app_ctx.session_id,
                new_session_id=session_id,
            )
            app_ctx.session_id = session_id

            # session_id 設定後、既存エージェント（Owner 等）をファイルに再保存
            # Owner は init_tmux_workspace の前に作成されるため、
            # session_id 未設定で agents.json への保存に失敗している
            from src.models.agent import AgentRole
            from src.tools.helpers_persistence import save_agent_to_file as _save_agent
            from src.tools.helpers_registry import save_agent_to_registry

            for agent in app_ctx.agents.values():
                _save_agent(app_ctx, agent)
                owner_agent = next(
                    (a for a in app_ctx.agents.values() if a.role == AgentRole.OWNER),
                    None,
                )
                owner_id = owner_agent.id if owner_agent else agent.id
                if agent.role == AgentRole.OWNER:
                    owner_id = agent.id
                save_agent_to_registry(
                    agent_id=agent.id,
                    owner_id=owner_id,
                    project_root=resolved_project_root,
                    session_id=session_id,
                )
            provisional_cleanup_result = cleanup_orphan_provisional_sessions(
                resolved_project_root,
                app_ctx.settings.mcp_dir,
                target_session_ids=[migration_result.get("source_session_id")],
            )

        # gtr 自動確認・設定
        gtr_status = {
            "gtr_available": False,
            "gtrconfig_exists": False,
            "gtrconfig_generated": False,
        }

        if auto_setup_gtr and effective_enable_git:
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
        try:
            mcp_setup = _setup_mcp_directories(
                working_dir,
                settings=project_settings,
                session_id=session_id,
                enable_git_override=effective_enable_git,
            )
        except ValueError as e:
            return {
                "success": False,
                "error": str(e),
            }
        logger.info(
            f"MCP ディレクトリをセットアップしました: "
            f"作成={mcp_setup['created_dirs']}, env_created={mcp_setup['env_created']}"
        )

        # project_root を設定（screenshot 等で使用）
        app_ctx.project_root = resolved_project_root
        refresh_app_settings(app_ctx, app_ctx.project_root)
        logger.info(f"project_root を設定しました: {app_ctx.project_root}")

        # Dashboard マネージャーを初期化（Owner のみが行う）
        # Worker の MCP プロセスでは initialize() を呼ばないため、
        # ここで明示的にディレクトリとファイルを作成する
        from src.tools.helpers_managers import ensure_dashboard_manager

        dashboard = ensure_dashboard_manager(app_ctx)
        dashboard.initialize()

        # セッション名を計算（プロジェクト名をそのまま使用）
        project_name = get_project_name(working_dir, enable_git=effective_enable_git)
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
                    "mode": {
                        "enable_git": app_ctx.settings.enable_git,
                        "enable_worktree": app_ctx.settings.is_worktree_enabled(),
                    },
                    "provisional_migration": migration_result,
                    "provisional_cleanup": provisional_cleanup_result,
                    "message": message,
                }
            else:
                return {
                    "success": False,
                    "gtr_status": gtr_status,
                    "mode": {
                        "enable_git": app_ctx.settings.enable_git,
                        "enable_worktree": app_ctx.settings.is_worktree_enabled(),
                    },
                    "provisional_migration": migration_result,
                    "provisional_cleanup": provisional_cleanup_result,
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
                    "mode": {
                        "enable_git": app_ctx.settings.enable_git,
                        "enable_worktree": app_ctx.settings.is_worktree_enabled(),
                    },
                    "provisional_migration": migration_result,
                    "provisional_cleanup": provisional_cleanup_result,
                    "message": "メインセッションをバックグラウンドで作成しました",
                }
            else:
                return {
                    "success": False,
                    "gtr_status": gtr_status,
                    "mode": {
                        "enable_git": app_ctx.settings.enable_git,
                        "enable_worktree": app_ctx.settings.is_worktree_enabled(),
                    },
                    "provisional_migration": migration_result,
                    "provisional_cleanup": provisional_cleanup_result,
                    "error": "メインセッションの作成に失敗しました",
                }
