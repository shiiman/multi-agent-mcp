"""テンプレート管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.templates import get_template, get_template_names, list_templates


def register_tools(mcp: FastMCP) -> None:
    """テンプレート管理ツールを登録する。"""

    @mcp.tool()
    async def list_workspace_templates(ctx: Context = None) -> dict[str, Any]:
        """利用可能なテンプレート一覧を取得する。

        Returns:
            テンプレート一覧（success, templates, names）
        """
        templates = list_templates()

        return {
            "success": True,
            "templates": [t.to_dict() for t in templates],
            "names": get_template_names(),
        }

    @mcp.tool()
    async def get_workspace_template(
        template_name: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """特定テンプレートの詳細を取得する。

        Args:
            template_name: テンプレート名

        Returns:
            テンプレート詳細（success, template または error）
        """
        template = get_template(template_name)

        if not template:
            return {
                "success": False,
                "error": f"テンプレート '{template_name}' が見つかりません。"
                f"有効なテンプレート: {get_template_names()}",
            }

        return {
            "success": True,
            "template": template.to_dict(),
        }
