"""セッションツール向け環境設定ヘルパー。"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.config.settings import Settings, load_settings_for_project
from src.tools.helpers_git import resolve_main_repo_root

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


def _generate_per_worker_env_lines(
    s: Settings, v: Callable[[object], str],
) -> str:
    """Worker 1〜16 の per-worker CLI/MODEL 行を生成する。"""
    default_model = v(s.model_profile_performance_worker_model)
    default_cli = v(s.worker_cli_uniform)
    lines: list[str] = []
    for i in range(1, 17):
        cli_val = getattr(s, f"worker_cli_{i}", None)
        model_val = getattr(s, f"worker_model_{i}", None)
        cli_str = v(cli_val) if cli_val else default_cli
        model_str = v(model_val) if model_val else default_model
        lines.append(f"MCP_WORKER_CLI_{i}={cli_str}")
        lines.append(f"MCP_WORKER_MODEL_{i}={model_str}")
    return "\n".join(lines)


def generate_env_template(settings: Settings | None = None) -> str:
    """設定可能な変数とデフォルト値を含む .env テンプレートを生成する。

    Settings クラスのデフォルト値から動的に生成するため、
    値の管理は settings.py の一元管理となる。

    Returns:
        .env ファイルの内容
    """
    s = settings or load_settings_for_project(Path.cwd())
    v = _format_env_value

    # 長い変数名の値を事前に取得（E501 対策）
    std_admin_think = v(s.model_profile_standard_admin_thinking_tokens)
    std_worker_think = v(s.model_profile_standard_worker_thinking_tokens)
    std_admin_effort = v(s.model_profile_standard_admin_reasoning_effort)
    std_worker_effort = v(s.model_profile_standard_worker_reasoning_effort)
    perf_admin_think = v(
        s.model_profile_performance_admin_thinking_tokens
    )
    perf_worker_think = v(
        s.model_profile_performance_worker_thinking_tokens
    )
    perf_admin_effort = v(s.model_profile_performance_admin_reasoning_effort)
    perf_worker_effort = v(s.model_profile_performance_worker_reasoning_effort)

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

# uniform: 全 Worker 同じCLI / per-worker: Worker 1..16 を個別設定
MCP_WORKER_CLI_MODE={v(s.worker_cli_mode)}

# standard プロファイル設定（バランス重視）
MCP_MODEL_PROFILE_STANDARD_CLI={v(s.model_profile_standard_cli)}
MCP_MODEL_PROFILE_STANDARD_ADMIN_MODEL={v(s.model_profile_standard_admin_model)}
MCP_MODEL_PROFILE_STANDARD_WORKER_MODEL={v(s.model_profile_standard_worker_model)}
MCP_MODEL_PROFILE_STANDARD_MAX_WORKERS={v(s.model_profile_standard_max_workers)}
MCP_MODEL_PROFILE_STANDARD_ADMIN_THINKING_TOKENS={std_admin_think}
MCP_MODEL_PROFILE_STANDARD_WORKER_THINKING_TOKENS={std_worker_think}
MCP_MODEL_PROFILE_STANDARD_ADMIN_REASONING_EFFORT={std_admin_effort}
MCP_MODEL_PROFILE_STANDARD_WORKER_REASONING_EFFORT={std_worker_effort}

# performance プロファイル設定（性能重視）
MCP_MODEL_PROFILE_PERFORMANCE_CLI={v(s.model_profile_performance_cli)}
MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_MODEL={v(s.model_profile_performance_admin_model)}
MCP_MODEL_PROFILE_PERFORMANCE_WORKER_MODEL={v(s.model_profile_performance_worker_model)}
MCP_MODEL_PROFILE_PERFORMANCE_MAX_WORKERS={v(s.model_profile_performance_max_workers)}
MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_THINKING_TOKENS={perf_admin_think}
MCP_MODEL_PROFILE_PERFORMANCE_WORKER_THINKING_TOKENS={perf_worker_think}
MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_REASONING_EFFORT={perf_admin_effort}
MCP_MODEL_PROFILE_PERFORMANCE_WORKER_REASONING_EFFORT={perf_worker_effort}

# ========== Worker CLI モード ==========
# MCP_WORKER_CLI_MODEがper-workerの時のみ有効
{_generate_per_worker_env_lines(s, v)}

# ========== CLI 別デフォルトモデル ==========
# CLIとMODELが誤った組み合わせになっていた場合、デフォルトモデルに置き換えられる
# Claude CLI
MCP_CLI_DEFAULT_CLAUDE_ADMIN_MODEL={v(s.cli_default_claude_admin_model)}
MCP_CLI_DEFAULT_CLAUDE_WORKER_MODEL={v(s.cli_default_claude_worker_model)}

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

# モデル別 1000トークン単価テーブル（JSON）
MCP_MODEL_COST_TABLE_JSON={v(s.model_cost_table_json)}
MCP_MODEL_COST_DEFAULT_PER_1K={v(s.model_cost_default_per_1k)}

# ========== ヘルスチェック設定 ==========
# ヘルスチェックの実行間隔（秒）
MCP_HEALTHCHECK_INTERVAL_SECONDS={v(s.healthcheck_interval_seconds)}

# tmux 連続送信時の最小待機秒数（全CLI共通）
MCP_SEND_COOLDOWN_SECONDS={v(s.send_cooldown_seconds)}

# 無応答判定の閾値（秒）
MCP_HEALTHCHECK_STALL_TIMEOUT_SECONDS={v(s.healthcheck_stall_timeout_seconds)}

# in_progress タスクの無通信判定閾値（秒）
MCP_HEALTHCHECK_IN_PROGRESS_NO_IPC_TIMEOUT_SECONDS={v(s.healthcheck_in_progress_no_ipc_timeout_seconds)}

# 同一 worker/task の復旧試行上限
MCP_HEALTHCHECK_MAX_RECOVERY_ATTEMPTS={v(s.healthcheck_max_recovery_attempts)}

# 実作業なし状態が続いた場合に daemon を停止する連続回数
MCP_HEALTHCHECK_IDLE_STOP_CONSECUTIVE={v(s.healthcheck_idle_stop_consecutive)}

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

    try:
        project_root = Path(resolve_main_repo_root(working_dir))
    except ValueError:
        project_root = Path(working_dir).expanduser()

    if settings is None:
        settings = load_settings_for_project(project_root)

    mcp_dir = project_root / settings.mcp_dir
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
        env_file.write_text(generate_env_template(settings=settings))
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
        "project_root": str(project_root),
    }
