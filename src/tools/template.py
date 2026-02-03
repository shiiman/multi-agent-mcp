"""テンプレート管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.templates import get_template, get_template_names, list_templates
from src.config.workflow_guides import get_role_guide, list_role_guides


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

    @mcp.tool()
    async def get_role_guide(
        role: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """ロール別の振る舞いガイドを取得する。

        templates/{role}.md からテンプレートを読み込み、
        各ロールの責務、やること/やらないこと、振る舞いを取得します。

        Args:
            role: ロール名（owner, admin, worker）

        Returns:
            ロールガイド（success, guide または error）
        """
        from src.config.workflow_guides import get_role_guide as _get_role_guide

        guide = _get_role_guide(role)

        if not guide:
            available_roles = list_role_guides()
            return {
                "success": False,
                "error": f"ロール '{role}' が見つかりません。"
                f"有効なロール: {available_roles}",
            }

        return {
            "success": True,
            "guide": guide.to_dict(),
        }

    @mcp.tool()
    async def list_role_guides(ctx: Context = None) -> dict[str, Any]:
        """利用可能なロールガイド一覧を取得する。

        templates/ ディレクトリ内の .md ファイルを検索します。

        Returns:
            ロール名のリスト
        """
        from src.config.workflow_guides import list_role_guides as _list_role_guides

        return {
            "success": True,
            "roles": _list_role_guides(),
        }
