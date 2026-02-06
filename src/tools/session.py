"""セッション管理ツール。"""

import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.settings import Settings
from src.context import AppContext
from src.managers.tmux_manager import get_project_name
from src.tools.helpers import (
    get_gtrconfig_manager,
    get_worktree_manager,
    require_permission,
)

logger = logging.getLogger(__name__)


def _format_env_value(value: object) -> str:
    """Settings の値を .env 形式の文字列に変換する。"""
    import json
    from enum import Enum

    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def generate_env_template() -> str:
    """設定可能な変数とデフォルト値を含む .env テンプレートを生成する。

    Settings クラスのデフォルト値から動的に生成するため、
    値の管理は settings.py の一元管理となる。

    Returns:
        .env ファイルの内容
    """
    s = Settings()
    v = _format_env_value

    # 長い変数名の値を事前に取得（E501 対策）
    std_admin_think = v(s.model_profile_standard_admin_thinking_tokens)
    std_worker_think = v(s.model_profile_standard_worker_thinking_tokens)
    perf_admin_think = v(
        s.model_profile_performance_admin_thinking_tokens
    )
    perf_worker_think = v(
        s.model_profile_performance_worker_thinking_tokens
    )

    return f"""# Multi-Agent MCP プロジェクト設定
# 環境変数で上書きされます（環境変数 > .env > デフォルト）

# ========== 基本設定 ==========
# MCP 設定ディレクトリ名
MCP_MCP_DIR={v(s.mcp_dir)}

# ========== エージェント設定 ==========
# Worker エージェントの最大数
MCP_MAX_WORKERS={v(s.max_workers)}

# ========== Worktree 設定 ==========
# git worktree を使用するか（false で Non-Worktree モード）
MCP_ENABLE_WORKTREE={v(s.enable_worktree)}

# ========== tmux 設定 ==========
# メインウィンドウ名（Admin + Worker 1-6）
MCP_WINDOW_NAME_MAIN={v(s.window_name_main)}

# 追加 Worker ウィンドウ名のプレフィックス（workers-2, workers-3, ...）
MCP_WINDOW_NAME_WORKER_PREFIX={v(s.window_name_worker_prefix)}

# メインウィンドウの Worker エリア設定（左右50:50分離）
MCP_MAIN_WORKER_ROWS={v(s.main_worker_rows)}
MCP_MAIN_WORKER_COLS={v(s.main_worker_cols)}
MCP_WORKERS_PER_MAIN_WINDOW={v(s.workers_per_main_window)}

# 追加ウィンドウの設定（Worker 7 以降）
MCP_EXTRA_WORKER_ROWS={v(s.extra_worker_rows)}
MCP_EXTRA_WORKER_COLS={v(s.extra_worker_cols)}
MCP_WORKERS_PER_EXTRA_WINDOW={v(s.workers_per_extra_window)}

# ========== ターミナル設定 ==========
# デフォルトのターミナルアプリ（auto / ghostty / iterm2 / terminal）
MCP_DEFAULT_TERMINAL={v(s.default_terminal)}

# ========== モデルプロファイル ==========
# 現在のプロファイル（standard / performance）
MCP_MODEL_PROFILE_ACTIVE={v(s.model_profile_active)}

# standard プロファイル設定（バランス重視）
# Admin は Opus、Worker は Sonnet（Claude CLI の場合）
# CLI を変更した場合、Claude 固有モデル名は CLI デフォルトに解決されます
MCP_MODEL_PROFILE_STANDARD_CLI={v(s.model_profile_standard_cli)}
MCP_MODEL_PROFILE_STANDARD_ADMIN_MODEL={v(s.model_profile_standard_admin_model)}
MCP_MODEL_PROFILE_STANDARD_WORKER_MODEL={v(s.model_profile_standard_worker_model)}
MCP_MODEL_PROFILE_STANDARD_MAX_WORKERS={v(s.model_profile_standard_max_workers)}
MCP_MODEL_PROFILE_STANDARD_ADMIN_THINKING_TOKENS={std_admin_think}
MCP_MODEL_PROFILE_STANDARD_WORKER_THINKING_TOKENS={std_worker_think}

# performance プロファイル設定（性能重視）
# Admin/Worker ともに Opus（Claude CLI の場合）
# CLI を変更した場合、Claude 固有モデル名は CLI デフォルトに解決されます
MCP_MODEL_PROFILE_PERFORMANCE_CLI={v(s.model_profile_performance_cli)}
MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_MODEL={v(s.model_profile_performance_admin_model)}
MCP_MODEL_PROFILE_PERFORMANCE_WORKER_MODEL={v(s.model_profile_performance_worker_model)}
MCP_MODEL_PROFILE_PERFORMANCE_MAX_WORKERS={v(s.model_profile_performance_max_workers)}
MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_THINKING_TOKENS={perf_admin_think}
MCP_MODEL_PROFILE_PERFORMANCE_WORKER_THINKING_TOKENS={perf_worker_think}

# ========== CLI 別デフォルトモデル ==========
# Claude 固有モデル名（opus, sonnet 等）が非 Claude CLI で使われた場合のフォールバック先
# Codex CLI
MCP_CLI_DEFAULT_CODEX_ADMIN_MODEL={v(s.cli_default_codex_admin_model)}
MCP_CLI_DEFAULT_CODEX_WORKER_MODEL={v(s.cli_default_codex_worker_model)}

# Gemini CLI
MCP_CLI_DEFAULT_GEMINI_ADMIN_MODEL={v(s.cli_default_gemini_admin_model)}
MCP_CLI_DEFAULT_GEMINI_WORKER_MODEL={v(s.cli_default_gemini_worker_model)}

# ========== コスト設定 ==========
# コスト警告の閾値（USD）
MCP_COST_WARNING_THRESHOLD_USD={v(s.cost_warning_threshold_usd)}

# 1回の API 呼び出しあたりの推定トークン数
MCP_ESTIMATED_TOKENS_PER_CALL={v(s.estimated_tokens_per_call)}

# 1000 トークンあたりのコスト（USD）
MCP_COST_PER_1K_TOKENS_CLAUDE={v(s.cost_per_1k_tokens_claude)}
MCP_COST_PER_1K_TOKENS_CODEX={v(s.cost_per_1k_tokens_codex)}
MCP_COST_PER_1K_TOKENS_GEMINI={v(s.cost_per_1k_tokens_gemini)}

# ========== ヘルスチェック設定 ==========
# ヘルスチェックの間隔（秒）- Admin が Worker の状態を確認する間隔
# 応答がなければ即座に異常と判断
MCP_HEALTHCHECK_INTERVAL_SECONDS={v(s.healthcheck_interval_seconds)}

# ========== 品質チェック設定 ==========
# 品質チェックの最大イテレーション回数
MCP_QUALITY_CHECK_MAX_ITERATIONS={v(s.quality_check_max_iterations)}

# 同一問題の繰り返し上限（この回数を超えたら Owner に相談）
MCP_QUALITY_CHECK_SAME_ISSUE_LIMIT={v(s.quality_check_same_issue_limit)}

# ========== メモリ設定 ==========
# メモリの最大エントリ数
MCP_MEMORY_MAX_ENTRIES={v(s.memory_max_entries)}

# メモリエントリの保持期間（日）
MCP_MEMORY_TTL_DAYS={v(s.memory_ttl_days)}

# ========== スクリーンショット設定 ==========
# スクリーンショットとして認識する拡張子（JSON形式）
MCP_SCREENSHOT_EXTENSIONS={v(s.screenshot_extensions)}
"""


def _setup_mcp_directories(
    working_dir: str, settings: Settings | None = None, session_id: str | None = None
) -> dict[str, Any]:
    """MCP ディレクトリと .env ファイルをセットアップする。

    Args:
        working_dir: 作業ディレクトリのパス
        settings: MCP 設定（省略時は新規作成）
        session_id: セッションID（Admin/Worker で共有、省略時は None）

    Returns:
        セットアップ結果（created_dirs, env_created, env_path, config_created）
    """
    import json

    if settings is None:
        settings = Settings()

    mcp_dir = Path(working_dir) / settings.mcp_dir
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

    # config.json 作成（mcp_tool_prefix, session_id を保存、MCP インスタンス間で共有）
    # 注意: project_root はグローバルレジストリ (~/.multi-agent-mcp/agents/) で管理
    config_file = mcp_dir / "config.json"
    config_created = False
    # MCP ツールの完全名プレフィックス（AI CLI が MCP ツールを呼び出す際に使用）
    mcp_tool_prefix = "mcp__multi-agent-mcp__"
    config_data = {
        "mcp_tool_prefix": mcp_tool_prefix,
    }
    # session_id が指定されている場合は保存（必須）
    if session_id:
        config_data["session_id"] = session_id
    if not config_file.exists():
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        config_created = True
        logger.info(f"config.json を作成しました: {config_file}")
    else:
        # 既存の config.json を更新（mcp_tool_prefix, session_id が変わっている場合）
        try:
            with open(config_file, encoding="utf-8") as f:
                existing = json.load(f)
            updated = False
            # project_root が残っていたら削除（グローバルレジストリに移行済み）
            if "project_root" in existing:
                del existing["project_root"]
                updated = True
            if existing.get("mcp_tool_prefix") != mcp_tool_prefix:
                existing["mcp_tool_prefix"] = mcp_tool_prefix
                updated = True
            # session_id が指定されている場合は更新
            if session_id and existing.get("session_id") != session_id:
                existing["session_id"] = session_id
                updated = True
            if updated:
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(existing, f, ensure_ascii=False, indent=2)
                logger.info(f"config.json を更新しました: {config_file}")
        except Exception as e:
            logger.warning(f"config.json の読み込みに失敗: {e}")

    return {
        "created_dirs": created_dirs,
        "env_created": env_created,
        "env_path": str(env_file),
        "config_created": config_created,
        "config_path": str(config_file),
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

        # クリーンアップ実行
        tmux = app_ctx.tmux
        agents = app_ctx.agents

        terminated_count = await tmux.cleanup_all_sessions()
        agent_count = len(agents)

        # グローバルレジストリからエージェント情報を削除
        from src.models.agent import AgentRole
        from src.tools.helpers import remove_agents_by_owner

        owner_agent = next(
            (a for a in agents.values() if a.role == AgentRole.OWNER),
            None,
        )
        registry_removed = 0
        if owner_agent:
            registry_removed = remove_agents_by_owner(owner_agent.id)
            logger.info(f"レジストリから {registry_removed} エージェントを削除しました")

        agents.clear()

        # worktree を削除（git worktree list から取得）
        removed_worktrees = 0
        worktree_errors = []

        # repo_path が指定されていない場合は project_root を使用
        main_repo_path = repo_path or app_ctx.project_root

        if main_repo_path:
            try:
                worktree_manager = get_worktree_manager(app_ctx, main_repo_path)
                worktrees = await worktree_manager.list_worktrees()

                # メインリポジトリ以外の worktree を削除
                for wt in worktrees:
                    # メインリポジトリ自体はスキップ
                    if wt.path == main_repo_path:
                        continue

                    # worktree ディレクトリ名に "worker" が含まれるものを削除
                    # または -worktrees/ 配下のものを削除
                    if "worker" in wt.path.lower() or "-worktrees/" in wt.path:
                        try:
                            success, msg = await worktree_manager.remove_worktree(
                                wt.path, force=True
                            )
                            if success:
                                removed_worktrees += 1
                                logger.info(f"worktree を削除しました: {wt.path}")
                            else:
                                worktree_errors.append(f"{wt.path}: {msg}")
                        except Exception as e:
                            worktree_errors.append(f"{wt.path}: {e}")
                            logger.warning(f"worktree 削除失敗: {wt.path} - {e}")
            except Exception as e:
                logger.warning(f"WorktreeManager の初期化に失敗: {e}")
                worktree_errors.append(f"初期化エラー: {e}")

        # ブランチ削除は WorktreeManager.remove_worktree が自動で行う
        # (gtr rm または native 実装で worker- ブランチを削除)

        result = {
            "success": True,
            "terminated_sessions": terminated_count,
            "cleared_agents": agent_count,
            "removed_worktrees": removed_worktrees,
            "registry_removed": registry_removed,
            "was_forced": force and not status["is_all_completed"],
            **status,
            "message": (
                f"クリーンアップ完了: {terminated_count}セッション終了, "
                f"{agent_count}エージェントクリア, "
                f"{removed_worktrees}worktree削除, "
                f"{registry_removed}レジストリ削除"
            ),
        }

        if worktree_errors:
            result["worktree_errors"] = worktree_errors

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
            return {
                "success": False,
                "error": (
                    f"tmux セッション '{project_name}' は既に存在します。"
                    "重複初期化は許可されていません。"
                ),
            }

        # session_id を設定（後続の create_agent 等で使用）
        if session_id:
            app_ctx.session_id = session_id

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

                            # .gtrconfig をコミット
                            try:
                                import asyncio

                                proc = await asyncio.create_subprocess_exec(
                                    "git", "add", ".gtrconfig",
                                    cwd=working_dir,
                                    stdout=asyncio.subprocess.PIPE,
                                    stderr=asyncio.subprocess.PIPE,
                                )
                                await proc.communicate()

                                if proc.returncode == 0:
                                    commit_msg = (
                                        "chore: add .gtrconfig"
                                        " for gtr worktree runner"
                                    )
                                    proc = await asyncio.create_subprocess_exec(
                                        "git", "commit", "-m", commit_msg,
                                        cwd=working_dir,
                                        stdout=asyncio.subprocess.PIPE,
                                        stderr=asyncio.subprocess.PIPE,
                                    )
                                    await proc.communicate()
                                    if proc.returncode == 0:
                                        gtr_status["gtrconfig_committed"] = True
                                        logger.info(".gtrconfig をコミットしました")
                                    else:
                                        logger.warning(".gtrconfig のコミットに失敗しました")
                            except Exception as e:
                                logger.warning(f".gtrconfig のコミットに失敗: {e}")
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
        app_ctx.project_root = working_dir
        logger.info(f"project_root を設定しました: {working_dir}")

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
