"""ペルソナ管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.tools.helpers import ensure_persona_manager


def register_tools(mcp: FastMCP) -> None:
    """ペルソナ管理ツールを登録する。"""

    @mcp.tool()
    async def detect_task_type(
        task_description: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスクの説明からタスクタイプを検出する。

        Args:
            task_description: タスクの説明文

        Returns:
            検出結果（success, task_type, persona）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        persona = ensure_persona_manager(app_ctx)

        task_type = persona.detect_task_type(task_description)
        persona_info = persona.get_persona(task_type)

        return {
            "success": True,
            "task_type": task_type.value,
            "persona": {
                "name": persona_info.name,
                "description": persona_info.description,
            },
        }

    @mcp.tool()
    async def get_optimal_persona(
        task_description: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスクに最適なペルソナを取得する。

        Args:
            task_description: タスクの説明文

        Returns:
            ペルソナ情報（success, persona, system_prompt_addition）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        persona_manager = ensure_persona_manager(app_ctx)

        persona = persona_manager.get_optimal_persona(task_description)

        return {
            "success": True,
            "persona": {
                "name": persona.name,
                "description": persona.description,
            },
            "system_prompt_addition": persona.system_prompt_addition,
        }

    @mcp.tool()
    async def list_personas(ctx: Context = None) -> dict[str, Any]:
        """利用可能なペルソナ一覧を取得する。

        Returns:
            ペルソナ一覧（success, personas, count）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        persona_manager = ensure_persona_manager(app_ctx)

        personas = persona_manager.list_personas()

        return {
            "success": True,
            "personas": personas,
            "count": len(personas),
        }
