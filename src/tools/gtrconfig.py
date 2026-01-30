"""Gtrconfig管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.tools.helpers import get_gtrconfig_manager


def register_tools(mcp: FastMCP) -> None:
    """Gtrconfig管理ツールを登録する。"""

    @mcp.tool()
    async def check_gtrconfig(project_path: str, ctx: Context = None) -> dict[str, Any]:
        """Gtrconfigの存在確認と内容取得。

        Args:
            project_path: プロジェクトのルートパス

        Returns:
            Gtrconfig状態（success, status）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        gtrconfig = get_gtrconfig_manager(app_ctx, project_path)

        status = gtrconfig.get_status()

        return {
            "success": True,
            "status": status,
        }

    @mcp.tool()
    async def analyze_project_for_gtrconfig(
        project_path: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """プロジェクト構造を解析して推奨設定を提案する。

        Args:
            project_path: プロジェクトのルートパス

        Returns:
            推奨設定（success, recommended_config）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
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
        generate_example: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """Gtrconfigを自動生成する。

        Args:
            project_path: プロジェクトのルートパス
            overwrite: 既存ファイルを上書きするか
            generate_example: .gtrconfig.example も生成するか

        Returns:
            生成結果（success, config, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        gtrconfig = get_gtrconfig_manager(app_ctx, project_path)

        success, result = gtrconfig.generate(overwrite)

        if not success:
            return {
                "success": False,
                "error": result,
            }

        # .gtrconfig.example も生成
        if generate_example:
            gtrconfig.generate_example()

        return {
            "success": True,
            "config": result,
            "message": ".gtrconfig を生成しました",
        }
