"""メモリ管理ツールのテスト。"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.dashboard_manager import DashboardManager
from src.managers.ipc_manager import IPCManager
from src.managers.memory_manager import MemoryManager
from src.managers.persona_manager import PersonaManager
from src.managers.scheduler_manager import SchedulerManager
from src.managers.tmux_manager import TmuxManager
from src.models.agent import Agent, AgentRole, AgentStatus


@pytest.fixture
def memory_test_ctx(git_repo, settings):
    """メモリツールテスト用のAppContextを作成する。"""
    # モック tmux マネージャー
    mock_tmux = MagicMock(spec=TmuxManager)
    mock_tmux.settings = settings

    # AI CLI マネージャー
    ai_cli = AiCliManager(settings)

    # IPC マネージャー
    ipc_dir = git_repo / ".ipc"
    ipc = IPCManager(str(ipc_dir))
    ipc.initialize()

    # ダッシュボードマネージャー
    dashboard_dir = git_repo / ".dashboard"
    dashboard = DashboardManager(
        workspace_id="test-workspace",
        workspace_path=str(git_repo),
        dashboard_dir=str(dashboard_dir),
    )
    dashboard.initialize()

    # メモリマネージャー
    memory_dir = git_repo / ".memory"
    memory = MemoryManager(str(memory_dir))

    # ペルソナマネージャー
    persona = PersonaManager()

    # スケジューラーマネージャー
    scheduler = SchedulerManager(dashboard, {})

    ctx = AppContext(
        settings=settings,
        tmux=mock_tmux,
        ai_cli=ai_cli,
        agents={},
        ipc_manager=ipc,
        dashboard_manager=dashboard,
        scheduler_manager=scheduler,
        memory_manager=memory,
        persona_manager=persona,
        workspace_id="test-workspace",
        project_root=str(git_repo),
        session_id="test-session",
    )

    yield ctx

    # クリーンアップ
    ipc.cleanup()
    dashboard.cleanup()


@pytest.fixture
def memory_mock_ctx(memory_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = memory_test_ctx
    return mock


class TestSaveToMemory:
    """save_to_memory ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_save_project_memory(self, memory_mock_ctx, git_repo):
        """プロジェクトメモリに保存できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.memory import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        save_to_memory = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "save_to_memory":
                save_to_memory = tool.fn
                break

        # Owner を追加
        app_ctx = memory_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await save_to_memory(
            key="test-knowledge",
            content="これはテスト用の知識です。",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        assert result["success"] is True
        assert "entry" in result
        assert result["entry"]["key"] == "test-knowledge"

    @pytest.mark.asyncio
    async def test_save_with_tags(self, memory_mock_ctx, git_repo):
        """タグ付きでメモリに保存できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.memory import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        save_to_memory = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "save_to_memory":
                save_to_memory = tool.fn
                break

        # Owner を追加
        app_ctx = memory_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await save_to_memory(
            key="tagged-knowledge",
            content="タグ付きの知識です。",
            tags=["test", "important"],
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        assert result["success"] is True
        assert result["entry"]["tags"] == ["test", "important"]


class TestRetrieveFromMemory:
    """retrieve_from_memory ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_retrieve_existing_entry(self, memory_mock_ctx, git_repo):
        """保存されたエントリを検索できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.memory import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        save_to_memory = None
        retrieve_from_memory = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "save_to_memory":
                save_to_memory = tool.fn
            elif tool.name == "retrieve_from_memory":
                retrieve_from_memory = tool.fn

        # Owner を追加
        app_ctx = memory_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        # まず保存
        await save_to_memory(
            key="search-test",
            content="これは検索テスト用のコンテンツです。Python に関する情報。",
            tags=["python", "test"],
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        # 検索
        result = await retrieve_from_memory(
            query="Python",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        assert result["success"] is True
        assert result["count"] >= 1

    @pytest.mark.asyncio
    async def test_retrieve_nonexistent_returns_empty(self, memory_mock_ctx, git_repo):
        """存在しないクエリで空の結果を返すことをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.memory import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        retrieve_from_memory = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "retrieve_from_memory":
                retrieve_from_memory = tool.fn
                break

        # Owner を追加
        app_ctx = memory_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await retrieve_from_memory(
            query="存在しないキーワード12345",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        assert result["success"] is True
        assert result["count"] == 0


class TestGetMemoryEntry:
    """get_memory_entry ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_existing_entry(self, memory_mock_ctx, git_repo):
        """キーでエントリを取得できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.memory import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        save_to_memory = None
        get_memory_entry = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "save_to_memory":
                save_to_memory = tool.fn
            elif tool.name == "get_memory_entry":
                get_memory_entry = tool.fn

        # Owner を追加
        app_ctx = memory_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        # 保存
        await save_to_memory(
            key="get-test",
            content="取得テスト用のコンテンツ",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        # 取得
        result = await get_memory_entry(
            key="get-test",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        assert result["success"] is True
        assert result["entry"]["key"] == "get-test"

    @pytest.mark.asyncio
    async def test_get_nonexistent_entry_fails(self, memory_mock_ctx, git_repo):
        """存在しないキーでエラーになることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.memory import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        get_memory_entry = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "get_memory_entry":
                get_memory_entry = tool.fn
                break

        # Owner を追加
        app_ctx = memory_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        result = await get_memory_entry(
            key="nonexistent-key",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        assert result["success"] is False
        assert "見つかりません" in result["error"]


class TestListMemoryEntries:
    """list_memory_entries ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_list_all_entries(self, memory_mock_ctx, git_repo):
        """全エントリを一覧表示できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.memory import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        save_to_memory = None
        list_memory_entries = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "save_to_memory":
                save_to_memory = tool.fn
            elif tool.name == "list_memory_entries":
                list_memory_entries = tool.fn

        # Owner を追加
        app_ctx = memory_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        # 複数保存
        await save_to_memory(
            key="entry-1",
            content="エントリ1",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )
        await save_to_memory(
            key="entry-2",
            content="エントリ2",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        # 一覧取得
        result = await list_memory_entries(
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        assert result["success"] is True
        assert result["count"] >= 2

    @pytest.mark.asyncio
    async def test_list_with_tag_filter(self, memory_mock_ctx, git_repo):
        """タグでフィルタリングできることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.memory import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        save_to_memory = None
        list_memory_entries = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "save_to_memory":
                save_to_memory = tool.fn
            elif tool.name == "list_memory_entries":
                list_memory_entries = tool.fn

        # Owner を追加
        app_ctx = memory_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        # 異なるタグで保存
        await save_to_memory(
            key="tag-a-entry",
            content="タグAのエントリ",
            tags=["tag-a"],
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )
        await save_to_memory(
            key="tag-b-entry",
            content="タグBのエントリ",
            tags=["tag-b"],
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        # タグでフィルタ
        result = await list_memory_entries(
            tags=["tag-a"],
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        assert result["success"] is True
        # tag-a を持つエントリのみ
        for entry in result["entries"]:
            assert "tag-a" in entry["tags"]


class TestDeleteMemoryEntry:
    """delete_memory_entry ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_delete_existing_entry(self, memory_mock_ctx, git_repo):
        """エントリを削除できることをテスト。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.memory import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        save_to_memory = None
        delete_memory_entry = None
        get_memory_entry = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "save_to_memory":
                save_to_memory = tool.fn
            elif tool.name == "delete_memory_entry":
                delete_memory_entry = tool.fn
            elif tool.name == "get_memory_entry":
                get_memory_entry = tool.fn

        # Owner を追加
        app_ctx = memory_mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir=str(git_repo),
            created_at=now,
            last_activity=now,
        )

        # 保存
        await save_to_memory(
            key="delete-test",
            content="削除テスト用",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        # 削除
        result = await delete_memory_entry(
            key="delete-test",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        assert result["success"] is True

        # 存在しないことを確認
        get_result = await get_memory_entry(
            key="delete-test",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )
        assert get_result["success"] is False


class TestMemoryArchiveTools:
    """メモリアーカイブ関連ツールのテスト。"""

    def _setup_tools(self):
        """アーカイブ関連ツールを取得するヘルパー。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.memory import register_tools

        mcp = FastMCP("test")
        register_tools(mcp)

        tools = {}
        for tool in mcp._tool_manager._tools.values():
            tools[tool.name] = tool.fn
        return tools

    def _add_owner(self, mock_ctx, working_dir):
        """Owner エージェントを追加するヘルパー。"""
        app_ctx = mock_ctx.request_context.lifespan_context
        now = datetime.now()
        app_ctx.agents["owner-001"] = Agent(
            id="owner-001",
            role=AgentRole.OWNER,
            status=AgentStatus.IDLE,
            tmux_session=None,
            working_dir=working_dir,
            created_at=now,
            last_activity=now,
        )

    @pytest.mark.asyncio
    async def test_search_archive_empty(self, memory_mock_ctx, git_repo):
        """アーカイブが空の場合に空の結果を返すことをテスト。"""
        tools = self._setup_tools()
        self._add_owner(memory_mock_ctx, str(git_repo))

        result = await tools["search_memory_archive"](
            query="test",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        assert result["success"] is True
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_list_archive_empty(self, memory_mock_ctx, git_repo):
        """アーカイブが空の場合に空の結果を返すことをテスト。"""
        tools = self._setup_tools()
        self._add_owner(memory_mock_ctx, str(git_repo))

        result = await tools["list_memory_archive"](
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        assert result["success"] is True
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_get_archive_summary(self, memory_mock_ctx, git_repo):
        """アーカイブサマリーを取得できることをテスト。"""
        tools = self._setup_tools()
        self._add_owner(memory_mock_ctx, str(git_repo))

        result = await tools["get_memory_archive_summary"](
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        assert result["success"] is True
        assert "summary" in result
        assert result["summary"]["total_entries"] == 0

    @pytest.mark.asyncio
    async def test_restore_nonexistent_key_fails(self, memory_mock_ctx, git_repo):
        """存在しないキーの復元がエラーになることをテスト。"""
        tools = self._setup_tools()
        self._add_owner(memory_mock_ctx, str(git_repo))

        result = await tools["restore_from_memory_archive"](
            key="nonexistent-key",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        assert result["success"] is False
        assert "見つかりません" in result["error"]

    @pytest.mark.asyncio
    async def test_archive_roundtrip(self, memory_mock_ctx, git_repo):
        """保存→prune→アーカイブ検索→復元のラウンドトリップをテスト。"""
        tools = self._setup_tools()
        self._add_owner(memory_mock_ctx, str(git_repo))

        # まずエントリを保存
        await tools["save_to_memory"](
            key="archive-test",
            content="アーカイブテスト用コンテンツ",
            tags=["archive", "roundtrip"],
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        # TTL を非常に短くして prune でアーカイブに移動
        app_ctx = memory_mock_ctx.request_context.lifespan_context
        memory = app_ctx.memory_manager
        # TTL=0 にしてエントリをアーカイブに移動させる
        original_ttl = memory.ttl_days
        memory.ttl_days = 0
        # エントリの更新日時を古くする
        entry = memory.entries.get("archive-test")
        if entry:
            from datetime import timedelta
            entry.updated_at = datetime.now() - timedelta(days=1)
        pruned = memory.prune()
        memory.ttl_days = original_ttl

        assert pruned >= 1

        # アーカイブを検索
        search_result = await tools["search_memory_archive"](
            query="アーカイブテスト",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )
        assert search_result["success"] is True
        assert search_result["count"] >= 1

        # アーカイブ一覧を取得
        list_result = await tools["list_memory_archive"](
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )
        assert list_result["success"] is True
        assert list_result["count"] >= 1

        # サマリーを取得
        summary_result = await tools["get_memory_archive_summary"](
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )
        assert summary_result["success"] is True
        assert summary_result["summary"]["total_entries"] >= 1

        # アーカイブから復元
        restore_result = await tools["restore_from_memory_archive"](
            key="archive-test",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )
        assert restore_result["success"] is True
        assert "復元しました" in restore_result["message"]

        # 復元後にメインメモリで取得できることを確認
        get_result = await tools["get_memory_entry"](
            key="archive-test",
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )
        assert get_result["success"] is True
        assert get_result["entry"]["key"] == "archive-test"

    @pytest.mark.asyncio
    async def test_search_archive_with_tags(self, memory_mock_ctx, git_repo):
        """タグ付きでアーカイブを検索できることをテスト。"""
        tools = self._setup_tools()
        self._add_owner(memory_mock_ctx, str(git_repo))

        # エントリを保存してアーカイブ
        app_ctx = memory_mock_ctx.request_context.lifespan_context
        memory = app_ctx.memory_manager

        await tools["save_to_memory"](
            key="tag-archive-a",
            content="タグAのコンテンツ",
            tags=["alpha"],
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )
        await tools["save_to_memory"](
            key="tag-archive-b",
            content="タグBのコンテンツ",
            tags=["beta"],
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        # prune でアーカイブに移動
        from datetime import timedelta
        original_ttl = memory.ttl_days
        memory.ttl_days = 0
        for e in memory.entries.values():
            e.updated_at = datetime.now() - timedelta(days=1)
        memory.prune()
        memory.ttl_days = original_ttl

        # タグ alpha のみ検索
        result = await tools["search_memory_archive"](
            query="コンテンツ",
            tags=["alpha"],
            caller_agent_id="owner-001",
            ctx=memory_mock_ctx,
        )

        assert result["success"] is True
        for entry in result["entries"]:
            assert "alpha" in entry["tags"]
