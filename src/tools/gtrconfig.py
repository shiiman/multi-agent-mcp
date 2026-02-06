"""Gtrconfig管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.tools.helpers import get_gtrconfig_manager, require_permission


def register_tools(mcp: FastMCP) -> None:
    """Gtrconfig管理ツールを登録する。"""

    @mcp.tool()
    async def check_gtrconfig(
        project_path: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """Gtrconfigの存在確認と内容取得。

        ※ Owner と Admin のみ使用可能。

        Args:
            project_path: プロジェクトのルートパス
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            Gtrconfig状態（success, status）
        """
        app_ctx, role_error = require_permission(ctx, "check_gtrconfig", caller_agent_id)
        if role_error:
            return role_error

        gtrconfig = get_gtrconfig_manager(app_ctx, project_path)

        status = gtrconfig.get_status()

        return {
            "success": True,
            "status": status,
        }

    @mcp.tool()
    async def analyze_project_for_gtrconfig(
        project_path: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """プロジェクト構造を解析して推奨設定を提案する。

        ※ Owner と Admin のみ使用可能。

        Args:
            project_path: プロジェクトのルートパス
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            推奨設定（success, recommended_config）
        """
        app_ctx, role_error = require_permission(
            ctx, "analyze_project_for_gtrconfig", caller_agent_id
        )
        if role_error:
            return role_error

        gtrconfig = get_gtrconfig_manager(app_ctx, project_path)

        config = gtrconfig.analyze_project()

        return {
            "success": True,
            "recommended_config": config,
        }

    @mcp.tool()
    async def generate_gtrconfig(
        project_path: str,
        overwrite: bool = False,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """Gtrconfigを自動生成する。

        ※ Owner のみ使用可能。

        Args:
            project_path: プロジェクトのルートパス
            overwrite: 既存ファイルを上書きするか
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            生成結果（success, config, message または error）
        """
        app_ctx, role_error = require_permission(ctx, "generate_gtrconfig", caller_agent_id)
        if role_error:
            return role_error

        gtrconfig = get_gtrconfig_manager(app_ctx, project_path)

        success, result = gtrconfig.generate(overwrite)

        if not success:
            return {
                "success": False,
                "error": result,
            }

        return {
            "success": True,
            "config": result,
            "message": ".gtrconfig を生成しました",
        }
