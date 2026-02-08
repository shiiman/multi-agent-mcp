"""Multi-Agent MCP Server エントリーポイント。"""

import json
import logging
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src.config.settings import get_mcp_dir, load_settings_for_project
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


def _save_shutdown_state(app_ctx: AppContext) -> bool:
    """シャットダウン時の状態をファイルに保存する。

    次回起動時にリカバリ用として現在のセッション情報を記録する。
    best-effort で動作し、失敗しても例外を投げない。

    Args:
        app_ctx: アプリケーションコンテキスト

    Returns:
        保存成功時 True
    """
    project_root = app_ctx.project_root
    if not project_root:
        return False

    mcp_dir = Path(project_root) / get_mcp_dir()
    if not mcp_dir.exists():
        return False

    shutdown_file = mcp_dir / "shutdown_state.json"
    try:
        state = {
            "session_id": app_ctx.session_id,
            "agent_count": len(app_ctx.agents),
            "agent_ids": list(app_ctx.agents.keys()),
        }
        content = json.dumps(state, ensure_ascii=False, indent=2)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(mcp_dir), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, str(shutdown_file))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        logger.info(f"シャットダウン状態を保存しました: {shutdown_file}")
        return True
    except (OSError, ValueError) as e:
        logger.warning(f"シャットダウン状態の保存に失敗: {e}")
        return False


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
    settings = load_settings_for_project(Path.cwd())
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

        # best-effort: 次回起動時のリカバリ用に現在状態をファイルに保存
        try:
            _save_shutdown_state(app_ctx)
        except Exception as e:
            logger.warning(f"シャットダウン状態の保存に失敗: {e}")

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
