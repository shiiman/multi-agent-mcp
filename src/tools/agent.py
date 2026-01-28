"""エージェント管理 MCP Tools。"""

import uuid
from datetime import datetime
from typing import Any

from src.models.agent import Agent, AgentRole, AgentStatus


async def create_agent(
    role: str,
    working_dir: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """新しいエージェントを作成する。

    Args:
        role: エージェントの役割（owner/admin/worker）
        working_dir: 作業ディレクトリのパス
        context: MCPコンテキスト

    Returns:
        作成結果
    """
    settings = context["settings"]
    tmux = context["tmux"]
    agents = context["agents"]

    # 役割の検証
    try:
        agent_role = AgentRole(role)
    except ValueError:
        return {
            "success": False,
            "error": f"無効な役割です: {role}（有効: owner, admin, worker）",
        }

    # Worker数の上限チェック
    if agent_role == AgentRole.WORKER:
        worker_count = sum(1 for a in agents.values() if a.role == AgentRole.WORKER)
        if worker_count >= settings.max_workers:
            return {
                "success": False,
                "error": f"Worker数が上限（{settings.max_workers}）に達しています",
            }

    # Owner/Adminの重複チェック
    if agent_role in (AgentRole.OWNER, AgentRole.ADMIN):
        existing = [a for a in agents.values() if a.role == agent_role]
        if existing:
            return {
                "success": False,
                "error": f"{agent_role.value}は既に存在します（ID: {existing[0].id}）",
            }

    # エージェントIDを生成
    agent_id = str(uuid.uuid4())[:8]

    # tmuxセッションを作成
    success = await tmux.create_session(agent_id, working_dir)
    if not success:
        return {
            "success": False,
            "error": "tmuxセッションの作成に失敗しました",
        }

    # エージェント情報を登録
    now = datetime.now()
    agent = Agent(
        id=agent_id,
        role=agent_role,
        status=AgentStatus.IDLE,
        tmux_session=agent_id,
        created_at=now,
        last_activity=now,
    )
    agents[agent_id] = agent

    return {
        "success": True,
        "agent": agent.model_dump(mode="json"),
        "message": f"エージェント {agent_id}（{role}）を作成しました",
    }


async def list_agents(context: dict[str, Any]) -> dict[str, Any]:
    """全エージェントの一覧を取得する。

    Args:
        context: MCPコンテキスト

    Returns:
        エージェント一覧
    """
    agents = context["agents"]

    agent_list = [a.model_dump(mode="json") for a in agents.values()]

    return {
        "success": True,
        "agents": agent_list,
        "count": len(agent_list),
    }


async def get_agent_status(agent_id: str, context: dict[str, Any]) -> dict[str, Any]:
    """指定エージェントの詳細ステータスを取得する。

    Args:
        agent_id: エージェントID
        context: MCPコンテキスト

    Returns:
        エージェント詳細
    """
    agents = context["agents"]
    tmux = context["tmux"]

    agent = agents.get(agent_id)
    if not agent:
        return {
            "success": False,
            "error": f"エージェント {agent_id} が見つかりません",
        }

    # tmuxセッションの存在確認
    session_exists = await tmux.session_exists(agent.tmux_session)

    return {
        "success": True,
        "agent": agent.model_dump(mode="json"),
        "session_active": session_exists,
    }


async def terminate_agent(agent_id: str, context: dict[str, Any]) -> dict[str, Any]:
    """エージェントを終了する。

    Args:
        agent_id: 終了するエージェントID
        context: MCPコンテキスト

    Returns:
        終了結果
    """
    tmux = context["tmux"]
    agents = context["agents"]

    agent = agents.get(agent_id)
    if not agent:
        return {
            "success": False,
            "error": f"エージェント {agent_id} が見つかりません",
        }

    # tmuxセッションを終了
    await tmux.kill_session(agent.tmux_session)

    # エージェント情報を削除
    del agents[agent_id]

    return {
        "success": True,
        "agent_id": agent_id,
        "message": f"エージェント {agent_id} を終了しました",
    }


def register_tools(mcp: Any) -> None:
    """エージェント管理Toolsを登録する。

    Args:
        mcp: FastMCPインスタンス
    """

    @mcp.tool()
    async def create_agent_tool(role: str, working_dir: str) -> dict[str, Any]:
        """新しいエージェントを作成し、tmuxセッションを起動する。

        Args:
            role: エージェントの役割（owner/admin/worker）
            working_dir: 作業ディレクトリのパス

        Returns:
            作成結果（success, agent, message または error）
        """
        ctx = mcp.get_context()
        return await create_agent(role, working_dir, ctx)

    @mcp.tool()
    async def list_agents_tool() -> dict[str, Any]:
        """全エージェントの一覧を取得する。

        Returns:
            エージェント一覧（success, agents, count）
        """
        ctx = mcp.get_context()
        return await list_agents(ctx)

    @mcp.tool()
    async def get_agent_status_tool(agent_id: str) -> dict[str, Any]:
        """指定エージェントの詳細ステータスを取得する。

        Args:
            agent_id: エージェントID

        Returns:
            エージェント詳細（success, agent, session_active または error）
        """
        ctx = mcp.get_context()
        return await get_agent_status(agent_id, ctx)

    @mcp.tool()
    async def terminate_agent_tool(agent_id: str) -> dict[str, Any]:
        """エージェントを終了し、tmuxセッションを削除する。

        Args:
            agent_id: 終了するエージェントID

        Returns:
            終了結果（success, agent_id, message または error）
        """
        ctx = mcp.get_context()
        return await terminate_agent(agent_id, ctx)
