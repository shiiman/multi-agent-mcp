"""セッション状態操作ヘルパー。"""

import json
import logging
import os
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from src.config.settings import get_mcp_dir
from src.context import AppContext

logger = logging.getLogger(__name__)


def _check_completion_status(app_ctx: AppContext) -> dict[str, Any]:
    """タスク完了状態を計算する。"""
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

    is_completed = (total > 0) and (pending == 0) and (in_progress == 0) and (failed == 0)

    return {
        "is_all_completed": is_completed,
        "total_tasks": total,
        "pending_tasks": pending,
        "in_progress_tasks": in_progress,
        "completed_tasks": completed,
        "failed_tasks": failed,
    }

def _reset_app_context(app_ctx: AppContext) -> None:
    """アプリケーションコンテキストのインメモリ状態をリセットする。

    cleanup_workspace / cleanup_on_completion から呼び出される。
    session_id, project_root, 各種 manager をリセットすることで、
    次のセッションで古い値が使われることを防ぐ。
    """
    app_ctx.session_id = None
    app_ctx.project_root = None
    app_ctx.workspace_id = None
    app_ctx.ipc_manager = None
    app_ctx.dashboard_manager = None
    app_ctx.scheduler_manager = None
    app_ctx.healthcheck_manager = None
    app_ctx.healthcheck_daemon_task = None
    app_ctx.healthcheck_daemon_stop_event = None
    app_ctx.healthcheck_daemon_lock = None
    app_ctx.healthcheck_idle_cycles = 0
    app_ctx.persona_manager = None
    app_ctx.memory_manager = None
    app_ctx.worktree_managers.clear()
    app_ctx.gtrconfig_managers.clear()
    # セッションスコープのデータもクリア
    app_ctx.agents.clear()
    app_ctx._admin_poll_state.clear()
    app_ctx._owner_wait_state.clear()
    app_ctx._admin_last_healthcheck_at.clear()


def _collect_session_names(agents: dict[str, Any]) -> list[str]:
    """エージェント一覧から tmux セッション名を収集する。"""
    session_names: set[str] = set()
    for agent in agents.values():
        session_name = getattr(agent, "session_name", None)
        if session_name:
            session_names.add(session_name)
            continue

        tmux_session = getattr(agent, "tmux_session", None)
        if tmux_session:
            session_names.add(str(tmux_session).split(":", 1)[0])

    return sorted(session_names)


def _clear_config_session_id(app_ctx: AppContext) -> bool:
    """config.json の session_id をクリアする。

    セッション終了時に呼び出され、次回起動時に古い session_id が
    参照されることを防ぐ。

    Args:
        app_ctx: アプリケーションコンテキスト

    Returns:
        クリア成功時 True、ファイル未存在や失敗時 False
    """
    project_root = app_ctx.project_root
    if not project_root:
        return False
    config_file = Path(project_root) / get_mcp_dir() / "config.json"
    if not config_file.exists():
        return False
    try:
        with open(config_file, encoding="utf-8") as f:
            config = json.load(f)
        if "session_id" not in config:
            return False
        del config["session_id"]
        # アトミック書き込み
        content = json.dumps(config, ensure_ascii=False, indent=2)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(config_file.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, str(config_file))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        logger.info(f"config.json から session_id をクリアしました: {config_file}")
        return True
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"config.json の session_id クリアに失敗: {e}")
        return False


def cleanup_orphan_provisional_sessions(
    project_root: str | None,
    mcp_dir_name: str,
    target_session_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """指定された provisional-* セッションディレクトリのみ削除する。"""
    result: dict[str, Any] = {
        "removed_count": 0,
        "removed_dirs": [],
        "errors": [],
    }
    if not project_root:
        return result

    mcp_dir = Path(project_root) / mcp_dir_name
    if not mcp_dir.exists() or not mcp_dir.is_dir():
        return result

    targets = {
        session_id
        for session_id in (target_session_ids or [])
        if isinstance(session_id, str) and session_id.startswith("provisional-")
    }
    if not targets:
        return result

    for target in sorted(targets):
        entry = mcp_dir / target
        if not entry.is_dir():
            continue
        try:
            shutil.rmtree(entry, ignore_errors=False)
            result["removed_count"] += 1
            result["removed_dirs"].append(target)
        except OSError as e:
            logger.warning("provisional ディレクトリ削除に失敗: %s (%s)", entry, e)
            result["errors"].append(f"{target}: {e}")

    return result


async def cleanup_session_resources(
    app_ctx: AppContext,
    remove_worktrees: bool = False,
    repo_path: str | None = None,
) -> dict[str, Any]:
    """セッションリソースの統一クリーンアップ。

    cleanup_workspace / cleanup_on_completion から呼び出される共通処理。
    9つのステップで全リソースを確実に解放する。

    Args:
        app_ctx: アプリケーションコンテキスト
        remove_worktrees: worktree を削除するか
        repo_path: メインリポジトリのパス（worktree 削除に使用）

    Returns:
        各ステップの結果を含む辞書
    """
    results: dict[str, Any] = {
        "terminated_sessions": 0,
        "cleared_agents": 0,
        "removed_worktrees": 0,
        "registry_removed": 0,
        "ipc_cleaned": False,
        "dashboard_cleaned": False,
        "agents_file_deleted": False,
        "config_session_cleared": False,
        "provisional_cleanup": {
            "removed_count": 0,
            "removed_dirs": [],
            "errors": [],
        },
    }

    tmux = app_ctx.tmux
    agents = app_ctx.agents

    # ① tmux セッション kill
    session_names = _collect_session_names(agents)
    results["terminated_sessions"] = await tmux.cleanup_sessions(session_names)
    results["cleared_agents"] = len(agents)

    # ② healthcheck daemon 停止
    try:
        from src.managers.healthcheck_daemon import stop_healthcheck_daemon

        await stop_healthcheck_daemon(app_ctx)
    except Exception as e:
        logger.warning(f"healthcheck daemon 停止に失敗: {e}")

    # ③ IPC cleanup
    if app_ctx.ipc_manager:
        try:
            app_ctx.ipc_manager.cleanup()
            results["ipc_cleaned"] = True
        except Exception as e:
            logger.warning(f"IPC クリーンアップに失敗: {e}")

    # ④ Dashboard cleanup
    if app_ctx.dashboard_manager:
        try:
            app_ctx.dashboard_manager.cleanup()
            results["dashboard_cleaned"] = True
        except Exception as e:
            logger.warning(f"Dashboard クリーンアップに失敗: {e}")

    # ⑤ worktree 削除 (conditional)
    if remove_worktrees and app_ctx.settings.enable_git:
        main_repo_path = repo_path or app_ctx.project_root
        if main_repo_path:
            worktree_errors: list[str] = []
            try:
                from src.tools.helpers import get_worktree_manager

                worktree_manager = get_worktree_manager(app_ctx, main_repo_path)
                worktrees = await worktree_manager.list_worktrees()

                for wt in worktrees:
                    if wt.path == main_repo_path:
                        continue
                    if (
                        "worker" in wt.path.lower()
                        or ".worktrees/" in wt.path
                        or "-worktrees/" in wt.path
                    ):
                        try:
                            success, msg = await worktree_manager.remove_worktree(
                                wt.path, force=True
                            )
                            if success:
                                results["removed_worktrees"] += 1
                                logger.info(f"worktree を削除しました: {wt.path}")
                            else:
                                worktree_errors.append(f"{wt.path}: {msg}")
                        except Exception as e:
                            worktree_errors.append(f"{wt.path}: {e}")
                            logger.warning(f"worktree 削除失敗: {wt.path} - {e}")
            except Exception as e:
                logger.warning(f"WorktreeManager の初期化に失敗: {e}")
                worktree_errors.append(f"初期化エラー: {e}")

            if worktree_errors:
                results["worktree_errors"] = worktree_errors

    # ⑥ グローバルレジストリ削除
    from src.models.agent import AgentRole
    from src.tools.helpers import remove_agents_by_owner

    owner_agent = next(
        (a for a in agents.values() if a.role == AgentRole.OWNER), None
    )
    if owner_agent:
        results["registry_removed"] = remove_agents_by_owner(owner_agent.id)
        logger.info(
            f"レジストリから {results['registry_removed']} エージェントを削除しました"
        )

    # ⑦ agents.json 削除
    from src.tools.helpers_persistence import delete_agents_file

    results["agents_file_deleted"] = delete_agents_file(app_ctx)

    # ⑧ config.json session_id クリア
    results["config_session_cleared"] = _clear_config_session_id(app_ctx)

    # ⑨ provisional-* 残骸削除
    results["provisional_cleanup"] = cleanup_orphan_provisional_sessions(
        app_ctx.project_root,
        app_ctx.settings.mcp_dir,
        target_session_ids=[app_ctx.session_id] if app_ctx.session_id else [],
    )

    # ⑩ インメモリ状態リセット
    _reset_app_context(app_ctx)

    return results


def detect_stale_sessions(project_root: str) -> list[str]:
    """MCP ディレクトリ内の古いセッションディレクトリを検出する。

    agents.json が存在するサブディレクトリを「古いセッション」と判定する。
    正常にクリーンアップされたセッションでは agents.json は削除されるため、
    残存している場合は異常終了の痕跡とみなす。

    Args:
        project_root: プロジェクトルートパス

    Returns:
        古いセッションのディレクトリ名リスト
    """
    mcp_dir = Path(project_root) / get_mcp_dir()
    if not mcp_dir.exists():
        return []
    stale: list[str] = []
    for entry in mcp_dir.iterdir():
        if entry.is_dir() and (entry / "agents.json").exists():
            stale.append(entry.name)
    return sorted(stale)
