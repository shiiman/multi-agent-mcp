"""テンプレート管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.template_loader import get_template_loader
from src.config.templates import get_template, get_template_names, list_templates
from src.tools.helpers import require_permission

# レポートテンプレートのカテゴリ分類
_REPORT_TEMPLATE_CATEGORIES: dict[str, list[str]] = {
    "code_investigation": [
        "security",
        "performance",
        "code_quality",
        "architecture",
        "testing",
        "maintainability",
    ],
    "integrated": ["integrated_report"],
    "general": [
        "tech_research",
        "comparison",
        "incident",
        "general",
        "decision",
    ],
}

# レポートテンプレートの説明
_REPORT_TEMPLATE_DESCRIPTIONS: dict[str, str] = {
    "security": "Severity Matrix 型。OWASP準拠の脆弱性分類",
    "performance": "Table-Driven 型。数値ベースのパフォーマンス分析",
    "code_quality": "Findings Card 型。コード品質の指摘を折りたたみカードで管理",
    "architecture": "GitHub Admonition 型。設計原則とモジュール分析",
    "testing": "Checklist / Audit 型。チェックリストベースのテスト評価",
    "maintainability": "Findings Card 型。技術的負債と運用性の分析",
    "integrated_report": "タスク指向型。全カテゴリの問題点を優先度付きタスクリストに統合",
    "tech_research": "GitHub Admonition + 比較テーブル型。技術調査・Web調査",
    "comparison": "Table-Driven 型。ツール・サービス比較",
    "incident": "Timeline 型。障害/インシデント調査",
    "general": "Executive Summary 型。汎用調査レポート",
    "decision": "ADR 応用型。意思決定記録",
}


def _get_category_for_template(name: str) -> str:
    """テンプレート名からカテゴリを返す。"""
    for category, names in _REPORT_TEMPLATE_CATEGORIES.items():
        if name in names:
            return category
    return "other"


def _extract_title_from_template(content: str) -> str:
    """テンプレート内容の1行目から見出しタイトルを抽出する。"""
    first_line = content.split("\n", 1)[0].strip()
    if first_line.startswith("# "):
        return first_line[2:].strip()
    return first_line


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
        app_ctx, role_error = require_permission(ctx, "list_workspace_templates", caller_agent_id)
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
        app_ctx, role_error = require_permission(ctx, "get_workspace_template", caller_agent_id)
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
        app_ctx, role_error = require_permission(ctx, "get_role_guide", caller_agent_id)
        if role_error:
            return role_error

        from src.config.workflow_guides import get_role_guide as _get_role_guide

        guide = _get_role_guide(role, enable_git=app_ctx.settings.enable_git)

        if not guide:
            from src.config.workflow_guides import list_role_guides as _list_role_guides

            available_roles = _list_role_guides()
            return {
                "success": False,
                "error": f"ロール '{role}' が見つかりません。有効なロール: {available_roles}",
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
        app_ctx, role_error = require_permission(ctx, "list_role_guides", caller_agent_id)
        if role_error:
            return role_error

        from src.config.workflow_guides import list_role_guides as _list_role_guides

        return {
            "success": True,
            "roles": _list_role_guides(),
        }

    @mcp.tool()
    async def list_report_templates(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """利用可能なレポートテンプレート一覧を取得する。

        レポート作成時に使用できるテンプレートの一覧を返します。
        テンプレートは「コード調査」「統合レポート」「汎用調査」の
        3カテゴリに分類されています。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            テンプレート一覧（success, templates, categories）
        """
        app_ctx, role_error = require_permission(
            ctx, "list_report_templates", caller_agent_id
        )
        if role_error:
            return role_error

        loader = get_template_loader()

        templates = []
        for name in loader.list_templates_in("reports"):
            try:
                content = loader.load("reports", name)
                title = _extract_title_from_template(content)
            except FileNotFoundError:
                title = name

            templates.append({
                "name": name,
                "category": _get_category_for_template(name),
                "title": title,
                "description": _REPORT_TEMPLATE_DESCRIPTIONS.get(name, ""),
            })

        return {
            "success": True,
            "templates": templates,
            "categories": _REPORT_TEMPLATE_CATEGORIES,
        }

    @mcp.tool()
    async def get_report_template(
        template_name: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """レポートテンプレートの内容を取得する。

        指定されたレポートテンプレートの全文を返します。
        テンプレートをコピーして、プレースホルダーを実際の内容に
        置き換えてレポートを作成してください。

        Args:
            template_name: テンプレート名（拡張子なし。例: "security", "general"）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            テンプレート内容（success, template_name, category, content または error）
        """
        app_ctx, role_error = require_permission(
            ctx, "get_report_template", caller_agent_id
        )
        if role_error:
            return role_error

        loader = get_template_loader()
        try:
            content = loader.load("reports", template_name)
        except FileNotFoundError:
            # 利用可能なテンプレート名を一覧で提示
            available = loader.list_templates_in("reports")
            return {
                "success": False,
                "error": f"レポートテンプレート '{template_name}' が見つかりません。"
                f" 有効なテンプレート: {available}",
            }

        return {
            "success": True,
            "template_name": template_name,
            "category": _get_category_for_template(template_name),
            "description": _REPORT_TEMPLATE_DESCRIPTIONS.get(template_name, ""),
            "content": content,
        }
