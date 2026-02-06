"""設定管理モジュール。"""

import os
from enum import Enum
from pathlib import Path

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


def get_project_env_file() -> str | None:
    """プロジェクト別 .env ファイルのパスを取得。

    MCP_PROJECT_ROOT 環境変数が設定されている場合、
    {project_root}/.multi-agent-mcp/.env を返す。

    Returns:
        .env ファイルのパス（存在する場合）、または None
    """
    project_root = os.getenv("MCP_PROJECT_ROOT")
    if project_root:
        env_file = Path(project_root) / ".multi-agent-mcp" / ".env"
        if env_file.exists():
            return str(env_file)
    return None


class AICli(str, Enum):
    """サポートするAI CLIツール。"""

    CLAUDE = "claude"
    """Claude Code CLI"""

    CODEX = "codex"
    """OpenAI Codex CLI"""

    GEMINI = "gemini"
    """Google Gemini CLI"""


class TerminalApp(str, Enum):
    """サポートするターミナルアプリ。"""

    AUTO = "auto"
    """自動検出（ghostty → iTerm2 → Terminal.app）"""

    GHOSTTY = "ghostty"
    """Ghostty"""

    ITERM2 = "iterm2"
    """iTerm2"""

    TERMINAL = "terminal"
    """macOS Terminal.app"""


class ModelProfile(str, Enum):
    """モデルプロファイル。

    タスクの重要度に応じてモデルやリソースを切り替える。
    """

    STANDARD = "standard"
    """標準プロファイル - コスト重視、Sonnet"""

    PERFORMANCE = "performance"
    """高性能プロファイル - 性能重視、Opus"""


# モデル定数（重複を避けるため一元管理）
class ModelDefaults:
    """デフォルトモデル名の定数。"""

    # Claude CLI
    OPUS = "opus"
    """Claude Opus モデル（Claude CLI が最新バージョンに自動解決）"""

    SONNET = "sonnet"
    """Claude Sonnet モデル（Claude CLI が最新バージョンに自動解決）"""

    # Codex CLI
    CODEX_DEFAULT = "gpt-5.3-codex"
    """Codex デフォルトモデル"""

    # Gemini CLI
    GEMINI_DEFAULT = "gemini-3-pro"
    """Gemini デフォルトモデル"""

    GEMINI_LIGHT = "gemini-3-flash"
    """Gemini 軽量モデル"""

    # CLI 別デフォルトモデルマッピング
    CLI_DEFAULTS: dict[str, dict[str, str]] = {
        "claude": {"admin": OPUS, "worker": SONNET},
        "codex": {"admin": CODEX_DEFAULT, "worker": CODEX_DEFAULT},
        "gemini": {"admin": GEMINI_DEFAULT, "worker": GEMINI_LIGHT},
    }

    # Claude 固有のモデル名（非 Claude CLI で使用された場合、CLI デフォルトに置換）
    CLAUDE_ALIASES: set[str] = {"opus", "sonnet", "haiku", "default"}


def resolve_model_for_cli(
    cli: str,
    model: str | None,
    role: str = "worker",
    cli_defaults: dict[str, dict[str, str]] | None = None,
) -> str | None:
    """CLI に応じてモデル名を解決する。

    Claude 固有の省略名（opus, sonnet）が非 Claude CLI で使われた場合、
    CLI のデフォルトモデルにフォールバックする。

    Args:
        cli: AI CLI 名（"claude", "codex", "gemini"）
        model: 設定されたモデル名
        role: ロール（"admin" or "worker"）
        cli_defaults: CLI 別デフォルトモデルマッピング（Settings から構築）。
            None の場合は ModelDefaults.CLI_DEFAULTS を使用。

    Returns:
        解決されたモデル名（None の場合は None を返す）
    """
    if model is None:
        return None

    # Claude CLI の場合はそのまま返す
    if cli == "claude":
        return model

    # 非 Claude CLI で Claude 固有のモデル名が設定されている場合、CLI デフォルトに置換
    if model in ModelDefaults.CLAUDE_ALIASES:
        defaults_map = cli_defaults if cli_defaults is not None else ModelDefaults.CLI_DEFAULTS
        defaults = defaults_map.get(cli, {})
        return defaults.get(role, model)

    # ユーザーが CLI 固有のモデル名を明示指定した場合はそのまま返す
    return model


# AI CLI のデフォルトコマンドマッピング
DEFAULT_AI_CLI_COMMANDS: dict[str, str] = {
    AICli.CLAUDE: "claude",
    AICli.CODEX: "codex",
    AICli.GEMINI: "gemini",
}


class Settings(BaseSettings):
    """MCP サーバーの設定。

    環境変数で上書き可能。プレフィックスは MCP_。
    例: MCP_MAX_WORKERS=10

    優先順位:
    1. 環境変数（最優先）
    2. プロジェクト別 .env ファイル（{project}/.multi-agent-mcp/.env）
    3. デフォルト値
    """

    model_config = ConfigDict(
        env_prefix="MCP_",
        env_file=get_project_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MCP ディレクトリ設定
    mcp_dir: str = ".multi-agent-mcp"
    """MCP 設定ディレクトリ名（デフォルト: .multi-agent-mcp）"""

    # Worktree 設定
    enable_worktree: bool = True
    """git worktree を使用するか（デフォルト: True）。
    False にすると Worker は全て同一ディレクトリで作業する。"""

    # エージェント設定
    max_workers: int = 6
    """Workerエージェントの最大数（デフォルト: メインウィンドウに収まる6）"""

    # tmux設定
    window_name_main: str = "main"
    """メインウィンドウ名（Admin + Worker 1-6）"""

    window_name_worker_prefix: str = "workers-"
    """追加 Worker ウィンドウ名のプレフィックス（workers-2, workers-3, ...）"""

    # tmux グリッド設定（メインウィンドウ: 左右50:50分離）
    main_worker_rows: int = 2
    """メインウィンドウのWorkerエリア行数"""

    main_worker_cols: int = 3
    """メインウィンドウのWorkerエリア列数"""

    workers_per_main_window: int = 6
    """メインウィンドウのWorker数（main_worker_rows × main_worker_cols）"""

    # tmux グリッド設定（追加ウィンドウ: Worker 7以降）
    extra_worker_rows: int = 2
    """追加ウィンドウの行数"""

    extra_worker_cols: int = 5
    """追加ウィンドウの列数"""

    workers_per_extra_window: int = 10
    """追加ウィンドウのWorker数（extra_worker_rows × extra_worker_cols）"""

    # コスト設定
    cost_warning_threshold_usd: float = 10.0
    """コスト警告の閾値（USD）"""

    # ヘルスチェック設定
    healthcheck_interval_seconds: int = 60
    """ヘルスチェックの間隔（秒）- Admin が Worker の状態を確認する間隔。
    応答がなければ即座に異常と判断する。"""

    # ターミナル設定
    default_terminal: TerminalApp = Field(
        default=TerminalApp.AUTO, description="デフォルトのターミナルアプリ"
    )
    """デフォルトで使用するターミナルアプリ"""

    # Extended Thinking 設定（ロール別）
    owner_thinking_tokens: int = 0
    """Owner の思考トークン数（0 = 即断即決モード）"""

    admin_thinking_tokens: int = 4000
    """Admin の思考トークン数（中程度の思考）"""

    worker_thinking_tokens: int = 1000
    """Worker の思考トークン数（軽量な思考）"""

    # モデルプロファイル設定
    model_profile_active: ModelProfile = Field(
        default=ModelProfile.STANDARD,
        description="現在のモデルプロファイル",
    )
    """現在アクティブなモデルプロファイル"""

    # standard プロファイル設定
    model_profile_standard_cli: AICli = Field(
        default=AICli.CLAUDE,
        description="standard プロファイルで使用する AI CLI",
    )
    model_profile_standard_admin_model: str = Field(
        default=ModelDefaults.OPUS,
        description="standard プロファイルで Admin が使用するモデル",
    )
    model_profile_standard_worker_model: str = Field(
        default=ModelDefaults.SONNET,
        description="standard プロファイルで Worker が使用するモデル",
    )
    model_profile_standard_max_workers: int = Field(
        default=6,
        description="standard プロファイルの Worker 数上限",
    )
    model_profile_standard_thinking_multiplier: float = Field(
        default=1.0,
        description="standard プロファイルの思考トークン倍率",
    )

    # performance プロファイル設定
    model_profile_performance_cli: AICli = Field(
        default=AICli.CLAUDE,
        description="performance プロファイルで使用する AI CLI",
    )
    model_profile_performance_admin_model: str = Field(
        default=ModelDefaults.OPUS,
        description="performance プロファイルで Admin が使用するモデル",
    )
    model_profile_performance_worker_model: str = Field(
        default=ModelDefaults.OPUS,
        description="performance プロファイルで Worker が使用するモデル",
    )
    model_profile_performance_max_workers: int = Field(
        default=16,
        description="performance プロファイルの Worker 数上限",
    )
    model_profile_performance_thinking_multiplier: float = Field(
        default=2.0,
        description="performance プロファイルの思考トークン倍率",
    )

    # CLI 別デフォルトモデル設定（Claude 固有名が非 Claude CLI で使われた場合のフォールバック）
    cli_default_codex_admin_model: str = Field(
        default=ModelDefaults.CODEX_DEFAULT,
        description="Codex CLI の Admin デフォルトモデル",
    )
    """Codex CLI で Admin に使用するデフォルトモデル"""

    cli_default_codex_worker_model: str = Field(
        default=ModelDefaults.CODEX_DEFAULT,
        description="Codex CLI の Worker デフォルトモデル",
    )
    """Codex CLI で Worker に使用するデフォルトモデル"""

    cli_default_gemini_admin_model: str = Field(
        default=ModelDefaults.GEMINI_DEFAULT,
        description="Gemini CLI の Admin デフォルトモデル",
    )
    """Gemini CLI で Admin に使用するデフォルトモデル"""

    cli_default_gemini_worker_model: str = Field(
        default=ModelDefaults.GEMINI_LIGHT,
        description="Gemini CLI の Worker デフォルトモデル",
    )
    """Gemini CLI で Worker に使用するデフォルトモデル"""

    # スクリーンショット設定
    screenshot_extensions: list[str] = Field(
        default=[".png", ".jpg", ".jpeg", ".gif", ".webp"],
        description="スクリーンショットとして認識する拡張子",
    )
    """対象とする画像拡張子"""

    # 品質チェック・イテレーション設定
    quality_check_max_iterations: int = Field(
        default=5,
        description="品質チェックの最大イテレーション回数",
    )
    """品質チェックの最大イテレーション回数（デフォルト: 5）"""

    quality_check_same_issue_limit: int = Field(
        default=3,
        description="同一問題の繰り返し上限（超えたら Owner に相談）",
    )
    """同一問題の繰り返し上限（デフォルト: 3）"""

    # メモリ設定
    memory_max_entries: int = Field(
        default=1000,
        description="メモリの最大エントリ数",
    )
    """メモリの最大エントリ数（デフォルト: 1000）"""

    memory_ttl_days: int = Field(
        default=90,
        description="メモリエントリの保持期間（日）",
    )
    """メモリエントリの保持期間（デフォルト: 90日）"""

    # コスト推定設定
    estimated_tokens_per_call: int = Field(
        default=2000,
        description="1回のAPI呼び出しあたりの推定トークン数",
    )
    """1回のAPI呼び出しあたりの推定トークン数（デフォルト: 2000）"""

    cost_per_1k_tokens_claude: float = Field(
        default=0.015,
        description="Claude の 1000 トークンあたりのコスト（USD）",
    )
    """Claude Sonnet 概算コスト（デフォルト: $0.015/1K tokens）"""

    cost_per_1k_tokens_codex: float = Field(
        default=0.01,
        description="Codex の 1000 トークンあたりのコスト（USD）",
    )
    """OpenAI Codex 概算コスト（デフォルト: $0.01/1K tokens）"""

    cost_per_1k_tokens_gemini: float = Field(
        default=0.005,
        description="Gemini の 1000 トークンあたりのコスト（USD）",
    )
    """Gemini Pro 概算コスト（デフォルト: $0.005/1K tokens）"""


# Settings シングルトンキャッシュ
_settings_instance: Settings | None = None


def get_mcp_dir() -> str:
    """MCP ディレクトリ名を取得する（キャッシュ付き）。

    Settings インスタンスをキャッシュして、毎回の生成オーバーヘッドを削減する。

    Returns:
        MCP ディレクトリ名（デフォルト: .multi-agent-mcp）
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance.mcp_dir
