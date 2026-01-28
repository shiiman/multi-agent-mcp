"""セッション管理 MCP Tools。"""

import os
from typing import Any


async def init_workspace(
    workspace_path: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """ワークスペースを初期化する。

    ディレクトリの作成と基本的な設定を行う。

    Args:
        workspace_path: ワークスペースのパス
        context: MCPコンテキスト（settings, tmux, agentsを含む）

    Returns:
        初期化結果
    """
    settings = context["settings"]

    # ワークスペースディレクトリを作成
    full_path = os.path.join(settings.workspace_base_dir, workspace_path)

    try:
        os.makedirs(full_path, exist_ok=True)
        return {
            "success": True,
            "workspace_path": full_path,
            "message": f"ワークスペースを初期化しました: {full_path}",
        }
    except OSError as e:
        return {
            "success": False,
            "error": f"ワークスペースの初期化に失敗しました: {e}",
        }


async def cleanup_workspace(
    context: dict[str, Any],
) -> dict[str, Any]:
    """ワークスペースをクリーンアップする。

    全エージェントを終了し、リソースを解放する。

    Args:
        context: MCPコンテキスト（settings, tmux, agentsを含む）

    Returns:
        クリーンアップ結果
    """
    tmux = context["tmux"]
    agents = context["agents"]

    # 全セッションを終了
    terminated_count = await tmux.cleanup_all_sessions()

    # エージェント情報をクリア
    agent_count = len(agents)
    agents.clear()

    return {
        "success": True,
        "terminated_sessions": terminated_count,
        "cleared_agents": agent_count,
        "message": (
            f"{terminated_count} セッションを終了、"
            f"{agent_count} エージェント情報をクリアしました"
        ),
    }


def register_tools(mcp: Any) -> None:
    """セッション管理Toolsを登録する。

    Args:
        mcp: FastMCPインスタンス
    """

    @mcp.tool()
    async def init_workspace_tool(workspace_path: str) -> dict[str, Any]:
        """ワークスペースを初期化する。

        Args:
            workspace_path: ワークスペースのパス（ベースディレクトリからの相対パス）

        Returns:
            初期化結果（success, workspace_path, message または error）
        """
        ctx = mcp.get_context()
        return await init_workspace(workspace_path, ctx)

    @mcp.tool()
    async def cleanup_workspace_tool() -> dict[str, Any]:
        """ワークスペースをクリーンアップする。

        全エージェントを終了し、リソースを解放する。

        Returns:
            クリーンアップ結果（success, terminated_sessions, cleared_agents, message）
        """
        ctx = mcp.get_context()
        return await cleanup_workspace(ctx)
