"""コマンド実行 MCP Tools。"""

from datetime import datetime
from typing import Any

from src.models.agent import AgentRole, AgentStatus


async def send_command(
    agent_id: str,
    command: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """エージェントにコマンドを送信する。

    Args:
        agent_id: 対象エージェントID
        command: 実行するコマンド
        context: MCPコンテキスト

    Returns:
        送信結果
    """
    tmux = context["tmux"]
    agents = context["agents"]

    agent = agents.get(agent_id)
    if not agent:
        return {
            "success": False,
            "error": f"エージェント {agent_id} が見つかりません",
        }

    # コマンドを送信
    success = await tmux.send_keys(agent.tmux_session, command)

    if success:
        # エージェント状態を更新
        agent.status = AgentStatus.BUSY
        agent.last_activity = datetime.now()

    return {
        "success": success,
        "agent_id": agent_id,
        "command": command,
        "message": "コマンドを送信しました" if success else "コマンド送信に失敗しました",
    }


async def get_output(
    agent_id: str,
    lines: int,
    context: dict[str, Any],
) -> dict[str, Any]:
    """エージェントの出力を取得する。

    Args:
        agent_id: 対象エージェントID
        lines: 取得する行数
        context: MCPコンテキスト

    Returns:
        出力内容
    """
    tmux = context["tmux"]
    agents = context["agents"]

    agent = agents.get(agent_id)
    if not agent:
        return {
            "success": False,
            "error": f"エージェント {agent_id} が見つかりません",
        }

    # 出力をキャプチャ
    output = await tmux.capture_pane(agent.tmux_session, lines)

    return {
        "success": True,
        "agent_id": agent_id,
        "lines": lines,
        "output": output,
    }


async def broadcast_command(
    command: str,
    role: str | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    """全エージェント（または特定役割）にコマンドをブロードキャストする。

    Args:
        command: 実行するコマンド
        role: 対象の役割（省略時は全員）
        context: MCPコンテキスト

    Returns:
        送信結果
    """
    tmux = context["tmux"]
    agents = context["agents"]

    # 役割フィルタの検証
    target_role = None
    if role:
        try:
            target_role = AgentRole(role)
        except ValueError:
            return {
                "success": False,
                "error": f"無効な役割です: {role}（有効: owner, admin, worker）",
            }

    results: dict[str, bool] = {}
    now = datetime.now()

    for agent_id, agent in agents.items():
        # 役割フィルタ
        if target_role and agent.role != target_role:
            continue

        # コマンドを送信
        success = await tmux.send_keys(agent.tmux_session, command)
        results[agent_id] = success

        if success:
            agent.last_activity = now

    success_count = sum(1 for v in results.values() if v)
    total_count = len(results)

    return {
        "success": True,
        "command": command,
        "role_filter": role,
        "results": results,
        "summary": f"{success_count}/{total_count} エージェントに送信成功",
    }


def register_tools(mcp: Any) -> None:
    """コマンド実行Toolsを登録する。

    Args:
        mcp: FastMCPインスタンス
    """

    @mcp.tool()
    async def send_command_tool(agent_id: str, command: str) -> dict[str, Any]:
        """指定エージェントにコマンドを送信する。

        Args:
            agent_id: 対象エージェントID
            command: 実行するコマンド

        Returns:
            送信結果（success, agent_id, command, message または error）
        """
        ctx = mcp.get_context()
        return await send_command(agent_id, command, ctx)

    @mcp.tool()
    async def get_output_tool(agent_id: str, lines: int = 50) -> dict[str, Any]:
        """エージェントのtmux出力を取得する。

        Args:
            agent_id: 対象エージェントID
            lines: 取得する行数（デフォルト: 50）

        Returns:
            出力内容（success, agent_id, lines, output または error）
        """
        ctx = mcp.get_context()
        return await get_output(agent_id, lines, ctx)

    @mcp.tool()
    async def broadcast_command_tool(
        command: str, role: str | None = None
    ) -> dict[str, Any]:
        """全エージェント（または特定役割）にコマンドをブロードキャストする。

        Args:
            command: 実行するコマンド
            role: 対象の役割（省略時は全員、有効: owner/admin/worker）

        Returns:
            送信結果（success, command, role_filter, results, summary または error）
        """
        ctx = mcp.get_context()
        return await broadcast_command(command, role, ctx)
