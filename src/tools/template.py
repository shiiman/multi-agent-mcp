"""テンプレート管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.templates import get_template, get_template_names, list_templates
from src.config.workflow_guides import get_role_guide, list_role_guides
from src.context import AppContext
from src.tools.helpers import check_tool_permission


def register_tools(mcp: FastMCP) -> None:
    """テンプレート管理ツールを登録する。"""

    @mcp.tool()
    async def list_workspace_templates(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """利用可能なテンプレート一覧を取得する。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            テンプレート一覧（success, templates, names）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "list_workspace_templates", caller_agent_id)
        if role_error:
            return role_error

        templates = list_templates()

        return {
            "success": True,
            "templates": [t.to_dict() for t in templates],
            "names": get_template_names(),
        }

    @mcp.tool()
    async def get_workspace_template(
        template_name: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """特定テンプレートの詳細を取得する。

        Args:
            template_name: テンプレート名
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            テンプレート詳細（success, template または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_workspace_template", caller_agent_id)
        if role_error:
            return role_error

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
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """ロール別の振る舞いガイドを取得する。

        templates/{role}.md からテンプレートを読み込み、
        各ロールの責務、やること/やらないこと、振る舞いを取得します。

        Args:
            role: ロール名（owner, admin, worker）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            ロールガイド（success, guide または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_role_guide", caller_agent_id)
        if role_error:
            return role_error

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
    async def list_role_guides(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """利用可能なロールガイド一覧を取得する。

        templates/ ディレクトリ内の .md ファイルを検索します。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            ロール名のリスト
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "list_role_guides", caller_agent_id)
        if role_error:
            return role_error

        from src.config.workflow_guides import list_role_guides as _list_role_guides

        return {
            "success": True,
            "roles": _list_role_guides(),
        }
