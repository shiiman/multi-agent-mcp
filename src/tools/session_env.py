"""セッションツール向け環境設定ヘルパー。"""

import logging
from pathlib import Path
from typing import Any

from src.config.settings import Settings

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


