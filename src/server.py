"""Multi-Agent MCP Server エントリーポイント。"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from src.config.settings import Settings
from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.tmux_manager import TmuxManager
from src.tools import register_all_tools

# ログ設定（stderrに出力）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """サーバーライフサイクルを管理する。

    Args:
        server: FastMCPサーバーインスタンス

    Yields:
        アプリケーションコンテキスト
    """
    logger.info("Multi-Agent MCP Server を起動しています...")

    # リソースを初期化
    settings = Settings()
    tmux = TmuxManager(settings)
    ai_cli = AiCliManager(settings)

    try:
        yield AppContext(settings=settings, tmux=tmux, ai_cli=ai_cli)
    finally:
        # クリーンアップ
        logger.info("サーバーをシャットダウンしています...")
        count = await tmux.cleanup_all_sessions()
        logger.info(f"{count} セッションをクリーンアップしました")


# FastMCPサーバーを作成
mcp = FastMCP("Multi-Agent MCP", lifespan=app_lifespan)

# 全ツールを登録
register_all_tools(mcp)


def main() -> None:
    """MCPサーバーを起動する。"""
    mcp.run()


if __name__ == "__main__":
    main()
