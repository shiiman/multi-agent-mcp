"""Multi-Agent MCP Server エントリーポイント。"""

import logging
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

    app_ctx = AppContext(settings=settings, tmux=tmux, ai_cli=ai_cli)
    try:
        yield app_ctx
    finally:
        # クリーンアップ
        logger.info("サーバーをシャットダウンしています...")
        try:
            from src.managers.healthcheck_daemon import stop_healthcheck_daemon

            await stop_healthcheck_daemon(app_ctx)
        except Exception as e:
            logger.warning(f"healthcheck daemon 停止時に警告: {e}")
        # サーバー停止時に tmux セッションを強制終了しない。
        # セッション終了は cleanup_workspace / cleanup_on_completion で明示的に行う。
        logger.info("tmux セッションの自動クリーンアップはスキップしました")


# FastMCPサーバーを作成
mcp = FastMCP("Multi-Agent MCP", lifespan=app_lifespan)

# 全ツールを登録
register_all_tools(mcp)


def main() -> None:
    """MCPサーバーを起動する。"""
    mcp.run()


if __name__ == "__main__":
    main()
