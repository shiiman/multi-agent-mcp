"""レポートテンプレートツールのテスト。"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.config.template_loader import get_template_loader
from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.tmux_manager import TmuxManager
from src.models.agent import Agent, AgentRole, AgentStatus
from src.tools.template import (
    _REPORT_TEMPLATE_CATEGORIES,
    _REPORT_TEMPLATE_DESCRIPTIONS,
    _extract_title_from_template,
    _get_category_for_template,
)


def _make_mock_ctx(git_repo, settings, role=AgentRole.OWNER):
    """テンプレートツール用の MCP Context モックを作成する。"""
    mock_tmux = MagicMock(spec=TmuxManager)
    mock_tmux.settings = settings
    ai_cli = AiCliManager(settings)

    now = datetime.now()
    agent = Agent(
        id="agent-001",
        role=role,
        status=AgentStatus.IDLE,
        tmux_session=None,
        working_dir=str(git_repo),
        created_at=now,
        last_activity=now,
    )
    app_ctx = AppContext(
        settings=settings,
        tmux=mock_tmux,
        ai_cli=ai_cli,
        agents={"agent-001": agent},
        project_root=str(git_repo),
        session_id="test-session",
    )

    mock_ctx = MagicMock()
    mock_ctx.request_context.lifespan_context = app_ctx
    return mock_ctx


class TestReportTemplateHelpers:
    """レポートテンプレートヘルパー関数のテスト。"""

    def test_get_category_for_known_template(self):
        """既知のテンプレートのカテゴリが正しいことを確認。"""
        assert _get_category_for_template("security") == "code_investigation"
        assert _get_category_for_template("performance") == "code_investigation"
        assert _get_category_for_template("integrated_report") == "integrated"
        assert _get_category_for_template("general") == "general"
        assert _get_category_for_template("decision") == "general"

    def test_get_category_for_unknown_template(self):
        """未知のテンプレート名は 'other' を返すことを確認。"""
        assert _get_category_for_template("unknown") == "other"

    def test_extract_title_from_template_with_heading(self):
        """Markdown 見出しからタイトルを抽出できることを確認。"""
        content = "# セキュリティ調査レポート\n\n内容..."
        assert _extract_title_from_template(content) == "セキュリティ調査レポート"

    def test_extract_title_from_template_with_placeholder(self):
        """プレースホルダー付き見出しからタイトルを抽出できることを確認。"""
        content = "# 調査レポート: [テーマ]\n\n内容..."
        assert _extract_title_from_template(content) == "調査レポート: [テーマ]"

    def test_extract_title_from_template_without_heading(self):
        """見出しがない場合は1行目をそのまま返すことを確認。"""
        content = "テスト内容\n2行目"
        assert _extract_title_from_template(content) == "テスト内容"


class TestReportTemplateConstants:
    """レポートテンプレート定数のテスト。"""

    def test_all_categories_have_descriptions(self):
        """全カテゴリのテンプレートに説明が定義されていることを確認。"""
        all_templates = []
        for names in _REPORT_TEMPLATE_CATEGORIES.values():
            all_templates.extend(names)

        for name in all_templates:
            assert name in _REPORT_TEMPLATE_DESCRIPTIONS, (
                f"テンプレート '{name}' の説明が _REPORT_TEMPLATE_DESCRIPTIONS に未定義"
            )

    def test_category_count(self):
        """カテゴリ数が 3 であることを確認。"""
        assert len(_REPORT_TEMPLATE_CATEGORIES) == 3

    def test_total_template_count(self):
        """テンプレート総数が 12 であることを確認。"""
        total = sum(len(v) for v in _REPORT_TEMPLATE_CATEGORIES.values())
        assert total == 12


class TestListReportTemplates:
    """list_report_templates ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_list_report_templates_success(self, git_repo, settings):
        """テンプレート一覧が正常に取得できることを確認。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.template import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        mock_ctx = _make_mock_ctx(git_repo, settings)

        # ツール関数を直接取得して呼び出し
        tool_fn = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "list_report_templates":
                tool_fn = tool.fn
                break
        assert tool_fn is not None, "list_report_templates ツールが登録されていない"

        result = await tool_fn(caller_agent_id="agent-001", ctx=mock_ctx)

        assert result["success"] is True
        assert "templates" in result
        assert "categories" in result
        assert len(result["templates"]) == 12

        # 各テンプレートの構造を確認
        for tmpl in result["templates"]:
            assert "name" in tmpl
            assert "category" in tmpl
            assert "title" in tmpl
            assert "description" in tmpl

    @pytest.mark.asyncio
    async def test_list_report_templates_categories(self, git_repo, settings):
        """カテゴリ分類が正しいことを確認。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.template import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        mock_ctx = _make_mock_ctx(git_repo, settings)

        tool_fn = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "list_report_templates":
                tool_fn = tool.fn
                break

        result = await tool_fn(caller_agent_id="agent-001", ctx=mock_ctx)

        categories = result["categories"]
        assert "code_investigation" in categories
        assert "integrated" in categories
        assert "general" in categories
        assert len(categories["code_investigation"]) == 6
        assert len(categories["integrated"]) == 1
        assert len(categories["general"]) == 5

    @pytest.mark.asyncio
    async def test_list_report_templates_permission_denied(self, git_repo, settings):
        """権限のないロールではエラーが返ることを確認（権限設定による）。"""
        # Worker は list_report_templates を使用可能なので、成功するはず
        from mcp.server.fastmcp import FastMCP

        from src.tools.template import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        # Worker エージェントで呼び出し
        mock_ctx = _make_mock_ctx(git_repo, settings, role=AgentRole.WORKER)

        tool_fn = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "list_report_templates":
                tool_fn = tool.fn
                break

        result = await tool_fn(caller_agent_id="agent-001", ctx=mock_ctx)
        # Worker にも権限を付与しているので成功する
        assert result["success"] is True


class TestGetReportTemplate:
    """get_report_template ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_report_template_success(self, git_repo, settings):
        """有効なテンプレート名でコンテンツが取得できることを確認。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.template import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        mock_ctx = _make_mock_ctx(git_repo, settings)

        tool_fn = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_report_template":
                tool_fn = tool.fn
                break
        assert tool_fn is not None, "get_report_template ツールが登録されていない"

        result = await tool_fn(
            template_name="security",
            caller_agent_id="agent-001",
            ctx=mock_ctx,
        )

        assert result["success"] is True
        assert result["template_name"] == "security"
        assert result["category"] == "code_investigation"
        assert "content" in result
        assert "セキュリティ" in result["content"]

    @pytest.mark.asyncio
    async def test_get_report_template_not_found(self, git_repo, settings):
        """存在しないテンプレート名でエラーが返ることを確認。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.template import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        mock_ctx = _make_mock_ctx(git_repo, settings)

        tool_fn = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_report_template":
                tool_fn = tool.fn
                break

        result = await tool_fn(
            template_name="nonexistent",
            caller_agent_id="agent-001",
            ctx=mock_ctx,
        )

        assert result["success"] is False
        assert "error" in result
        assert "nonexistent" in result["error"]

    @pytest.mark.asyncio
    async def test_get_report_template_all_templates_loadable(self, git_repo, settings):
        """全テンプレートが正常にロードできることを確認。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.template import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        mock_ctx = _make_mock_ctx(git_repo, settings)

        tool_fn = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_report_template":
                tool_fn = tool.fn
                break

        all_templates = []
        for names in _REPORT_TEMPLATE_CATEGORIES.values():
            all_templates.extend(names)

        for name in all_templates:
            result = await tool_fn(
                template_name=name,
                caller_agent_id="agent-001",
                ctx=mock_ctx,
            )
            assert result["success"] is True, (
                f"テンプレート '{name}' のロードに失敗: {result.get('error')}"
            )
            assert len(result["content"]) > 0, (
                f"テンプレート '{name}' のコンテンツが空"
            )


class TestReportTemplateInjection:
    """_prepare_worker_task_content のレポートテンプレート注入テスト。"""

    def _make_app_ctx(self, git_repo, settings):
        """テスト用の AppContext を作成する。"""
        mock_tmux = MagicMock(spec=TmuxManager)
        mock_tmux.settings = settings
        ai_cli = AiCliManager(settings)
        now = datetime.now()
        agent = Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.IDLE,
            tmux_session="test:0.1",
            working_dir=str(git_repo),
            session_name="test",
            window_index=0,
            pane_index=1,
            created_at=now,
            last_activity=now,
        )
        app_ctx = AppContext(
            settings=settings,
            tmux=mock_tmux,
            ai_cli=ai_cli,
            agents={"worker-001": agent},
            project_root=str(git_repo),
            session_id="test-session",
        )
        return app_ctx, agent

    def test_prepare_worker_task_content_with_report_template(self, git_repo, settings):
        """report_template 指定時にテンプレートのファイルパスが注入されること。"""
        from src.tools.agent_helpers import _prepare_worker_task_content

        app_ctx, agent = self._make_app_ctx(git_repo, settings)

        project_root, task_file = _prepare_worker_task_content(
            app_ctx=app_ctx,
            agent=agent,
            task_content="セキュリティ調査を実施してください",
            task_id="task-001",
            branch="feature/test",
            worktree_path=str(git_repo),
            session_id="test-session",
            enable_worktree=False,
            caller_agent_id="admin-001",
            report_template="security",
        )

        # タスクファイルの内容を読み込んで検証
        content = task_file.read_text(encoding="utf-8")
        assert "## レポート出力形式" in content
        assert "テンプレートファイル:" in content

        # ワークスペース内のミラーパスを指していること（settings.mcp_dir を使用）
        mirror_path = str(
            project_root / settings.mcp_dir / "runtime" / "templates" / "reports" / "security.md"
        )
        assert mirror_path in content

    def test_prepare_worker_task_content_without_report_template(self, git_repo, settings):
        """report_template=None の場合はレポートセクションが含まれないこと。"""
        from src.tools.agent_helpers import _prepare_worker_task_content

        app_ctx, agent = self._make_app_ctx(git_repo, settings)

        project_root, task_file = _prepare_worker_task_content(
            app_ctx=app_ctx,
            agent=agent,
            task_content="通常の実装タスク",
            task_id="task-002",
            branch="feature/test",
            worktree_path=str(git_repo),
            session_id="test-session",
            enable_worktree=False,
            caller_agent_id="admin-001",
        )

        content = task_file.read_text(encoding="utf-8")
        assert "## レポート出力形式" not in content

    def test_prepare_worker_task_content_with_invalid_template(self, git_repo, settings):
        """存在しないテンプレート名でもエラーにならないこと。"""
        from src.tools.agent_helpers import _prepare_worker_task_content

        app_ctx, agent = self._make_app_ctx(git_repo, settings)

        # 例外が発生しないことを確認
        project_root, task_file = _prepare_worker_task_content(
            app_ctx=app_ctx,
            agent=agent,
            task_content="不正なテンプレート指定のタスク",
            task_id="task-003",
            branch="feature/test",
            worktree_path=str(git_repo),
            session_id="test-session",
            enable_worktree=False,
            caller_agent_id="admin-001",
            report_template="nonexistent_template",
        )

        # テンプレートパスが注入されないこと
        content = task_file.read_text(encoding="utf-8")
        assert "## レポート出力形式" not in content

    def test_prepare_worker_task_content_mirror_copy_oserror(self, git_repo, settings):
        """ミラーコピー時の OSError でもエラーにならないこと。"""
        from unittest.mock import patch

        from src.tools.agent_helpers import _prepare_worker_task_content

        app_ctx, agent = self._make_app_ctx(git_repo, settings)

        # shutil.copyfile が OSError を発生させる
        with patch("src.tools.agent_helpers.shutil.copyfile", side_effect=OSError("ディスク容量不足")):
            project_root, task_file = _prepare_worker_task_content(
                app_ctx=app_ctx,
                agent=agent,
                task_content="OSError テスト",
                task_id="task-004",
                branch="feature/test",
                worktree_path=str(git_repo),
                session_id="test-session",
                enable_worktree=False,
                caller_agent_id="admin-001",
                report_template="security",
            )

        # OSError 時はレポートセクションが注入されないこと
        content = task_file.read_text(encoding="utf-8")
        assert "## レポート出力形式" not in content

    def test_report_template_path_exists(self):
        """テンプレートのファイルパス解決が正しいことを確認。"""
        loader = get_template_loader()
        template_path = loader._base_dir / "reports" / "security.md"
        assert template_path.exists(), f"テンプレートファイルが見つかりません: {template_path}"
