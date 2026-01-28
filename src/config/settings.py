"""設定管理モジュール。"""

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


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

    # Claude Code設定
    claude_code_command: str = "claude"
    """Claude Code CLIのコマンド"""
