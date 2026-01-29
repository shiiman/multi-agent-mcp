"""設定管理モジュール。"""

from enum import Enum

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


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
    """

    model_config = ConfigDict(env_prefix="MCP_")

    # エージェント設定
    max_workers: int = 6
    """Workerエージェントの最大数（デフォルト: メインウィンドウに収まる6）"""

    # tmux設定
    tmux_prefix: str = "mcp-agent"
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

    # ワークスペース設定
    workspace_base_dir: str = "/tmp/mcp-workspaces"
    """ワークスペースのベースディレクトリ"""

    # メッセージ設定
    message_retention_seconds: int = 3600
    """メッセージの保持時間（秒）"""

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
