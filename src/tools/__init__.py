"""MCP Tools モジュール。"""

from mcp.server.fastmcp import FastMCP

from src.tools import (
    agent,
    command,
    dashboard,
    gtrconfig,
    healthcheck,
    ipc,
    memory,
    model_profile,
    persona,
    scheduler,
    screenshot,
    session,
    template,
    worktree,
)


def register_all_tools(mcp: FastMCP) -> None:
    """全ツールをMCPサーバーに登録する。

    Args:
        mcp: FastMCPインスタンス
    """
    # セッション管理
    session.register_tools(mcp)

    # エージェント管理
    agent.register_tools(mcp)

    # コマンド実行
    command.register_tools(mcp)

    # Git worktree管理
    worktree.register_tools(mcp)

    # IPC/メッセージング
    ipc.register_tools(mcp)

    # ダッシュボード/タスク管理（コスト管理を含む）
    dashboard.register_tools(mcp)

    # Gtrconfig
    gtrconfig.register_tools(mcp)

    # テンプレート
    template.register_tools(mcp)

    # スケジューラー
    scheduler.register_tools(mcp)

    # ヘルスチェック
    healthcheck.register_tools(mcp)

    # ペルソナ
    persona.register_tools(mcp)

    # メモリ
    memory.register_tools(mcp)

    # スクリーンショット
    screenshot.register_tools(mcp)

    # モデルプロファイル
    model_profile.register_tools(mcp)
