"""MCP Tools モジュール。"""

from mcp.server.fastmcp import FastMCP

from src.tools import (
    agent,
    command,
    dashboard,
    dashboard_cost_tools,
    gtrconfig,
    healthcheck,
    ipc,
    memory,
    memory_global,
    merge,
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

    # 完了タスクの統合
    merge.register_tools(mcp)

    # IPC/メッセージング
    ipc.register_tools(mcp)

    # ダッシュボード/タスク管理
    dashboard.register_tools(mcp)

    # コスト管理
    dashboard_cost_tools.register_tools(mcp)

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

    # メモリ（プロジェクトローカル + アーカイブ）
    memory.register_tools(mcp)

    # グローバルメモリ
    memory_global.register_tools(mcp)

    # スクリーンショット
    screenshot.register_tools(mcp)

    # モデルプロファイル
    model_profile.register_tools(mcp)
