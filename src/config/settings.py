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
    max_workers: int = 5
    """Workerエージェントの最大数"""

    # tmux設定
    tmux_prefix: str = "mcp-agent"
    """tmuxセッション名のプレフィックス"""

    # ワークスペース設定
    workspace_base_dir: str = "/tmp/mcp-workspaces"
    """ワークスペースのベースディレクトリ"""

    # メッセージ設定
    message_retention_seconds: int = 3600
    """メッセージの保持時間（秒）"""

    # AI CLI設定
    default_ai_cli: AICli = Field(default=AICli.CLAUDE, description="デフォルトのAI CLI")
    """デフォルトで使用するAI CLI"""

    claude_code_command: str = "claude"
    """Claude Code CLIのコマンド（後方互換性のため維持）"""

    # コスト設定
    cost_warning_threshold_usd: float = 10.0
    """コスト警告の閾値（USD）"""

    # ヘルスチェック設定
    healthcheck_interval_seconds: int = 300
    """ヘルスチェックの間隔（秒）"""

    heartbeat_timeout_seconds: int = 300
    """ハートビートタイムアウト（秒）"""
