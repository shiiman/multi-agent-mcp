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

    # エージェント設定
    max_workers: int = 6
    """Workerエージェントの最大数（デフォルト: メインウィンドウに収まる6）"""

    # tmux設定
    tmux_prefix: str = "multi-agent-mcp"
    """tmuxセッション名のプレフィックス"""

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

    extra_worker_cols: int = 6
    """追加ウィンドウの列数"""

    workers_per_extra_window: int = 12
    """追加ウィンドウのWorker数（extra_worker_rows × extra_worker_cols）"""

    # AI CLI設定
    default_ai_cli: AICli = Field(default=AICli.CLAUDE, description="デフォルトのAI CLI")
    """デフォルトで使用するAI CLI"""

    # コスト設定
    cost_warning_threshold_usd: float = 10.0
    """コスト警告の閾値（USD）"""

    # ヘルスチェック設定
    healthcheck_interval_seconds: int = 300
    """ヘルスチェックの間隔（秒）"""

    heartbeat_timeout_seconds: int = 300
    """ハートビートタイムアウト（秒）"""

    # ターミナル設定
    default_terminal: TerminalApp = Field(
        default=TerminalApp.AUTO, description="デフォルトのターミナルアプリ"
    )
    """デフォルトで使用するターミナルアプリ"""

    # Extended Thinking 設定（ロール別）
    owner_thinking_tokens: int = 0
    """Owner の思考トークン数（0 = 即断即決モード）"""

    admin_thinking_tokens: int = 1000
    """Admin の思考トークン数（中程度の思考）"""

    worker_thinking_tokens: int = 10000
    """Worker の思考トークン数（深い思考が可能）"""

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
    model_profile_standard_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="standard プロファイルで使用するモデル",
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
    model_profile_performance_model: str = Field(
        default="claude-opus-4-20250514",
        description="performance プロファイルで使用するモデル",
    )
    model_profile_performance_max_workers: int = Field(
        default=16,
        description="performance プロファイルの Worker 数上限",
    )
    model_profile_performance_thinking_multiplier: float = Field(
        default=2.0,
        description="performance プロファイルの思考トークン倍率",
    )

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
