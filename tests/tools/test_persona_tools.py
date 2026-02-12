"""ペルソナ管理ツールのテスト。"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.context import AppContext
from src.managers.ai_cli_manager import AiCliManager
from src.managers.tmux_manager import TmuxManager
from src.models.agent import Agent, AgentRole, AgentStatus


def _get_tool_fn(mcp, tool_name: str):
    """MCP ツール関数をツール名から取得するヘルパー。"""
    for tool in mcp._tool_manager._tools.values():
        if tool.name == tool_name:
            return tool.fn
    return None


@pytest.fixture
def persona_test_ctx(git_repo, settings):
    """ペルソナツールテスト用の AppContext を作成する。"""
    mock_tmux = MagicMock(spec=TmuxManager)
    mock_tmux.settings = settings
    ai_cli = AiCliManager(settings)

    ctx = AppContext(
        settings=settings,
        tmux=mock_tmux,
        ai_cli=ai_cli,
        agents={},
        project_root=str(git_repo),
        session_id="test-session",
    )
    yield ctx


@pytest.fixture
def persona_mock_ctx(persona_test_ctx):
    """MCP Context のモック。"""
    mock = MagicMock()
    mock.request_context.lifespan_context = persona_test_ctx
    return mock


def _add_agent(mock_ctx, agent_id: str, role: AgentRole, working_dir: str) -> None:
    """テスト用にエージェントを追加するヘルパー。"""
    app_ctx = mock_ctx.request_context.lifespan_context
    now = datetime.now()
    app_ctx.agents[agent_id] = Agent(
        id=agent_id,
        role=role,
        status=AgentStatus.IDLE,
        tmux_session="test:0.1" if role == AgentRole.WORKER else None,
        working_dir=working_dir,
        created_at=now,
        last_activity=now,
    )


def _register_tools():
    """ペルソナツールを登録した FastMCP インスタンスを返す。"""
    from mcp.server.fastmcp import FastMCP

    from src.tools.persona import register_tools

    mcp = FastMCP("test")
    register_tools(mcp)
    return mcp


class TestDetectTaskType:
    """detect_task_type ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_detect_code_task(self, persona_mock_ctx, git_repo):
        """コード実装タスクを検出できることをテスト。"""
        mcp = _register_tools()
        detect = _get_tool_fn(mcp, "detect_task_type")
        _add_agent(persona_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        result = await detect(
            task_description="新しいAPIエンドポイントを実装する",
            caller_agent_id="admin-001",
            ctx=persona_mock_ctx,
        )

        assert result["success"] is True
        assert result["task_type"] == "code"
        assert "persona" in result
        assert "name" in result["persona"]

    @pytest.mark.asyncio
    async def test_detect_test_task(self, persona_mock_ctx, git_repo):
        """テストタスクを検出できることをテスト。"""
        mcp = _register_tools()
        detect = _get_tool_fn(mcp, "detect_task_type")
        _add_agent(persona_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        result = await detect(
            task_description="ユニットテストを追加してカバレッジを上げる",
            caller_agent_id="admin-001",
            ctx=persona_mock_ctx,
        )

        assert result["success"] is True
        assert result["task_type"] == "test"

    @pytest.mark.asyncio
    async def test_detect_debug_task(self, persona_mock_ctx, git_repo):
        """デバッグタスクを検出できることをテスト。"""
        mcp = _register_tools()
        detect = _get_tool_fn(mcp, "detect_task_type")
        _add_agent(persona_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        result = await detect(
            task_description="ログインエラーのバグを修正する",
            caller_agent_id="admin-001",
            ctx=persona_mock_ctx,
        )

        assert result["success"] is True
        assert result["task_type"] == "debug"

    @pytest.mark.asyncio
    async def test_detect_unknown_task(self, persona_mock_ctx, git_repo):
        """不明なタスクタイプを返すことをテスト。"""
        mcp = _register_tools()
        detect = _get_tool_fn(mcp, "detect_task_type")
        _add_agent(persona_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        result = await detect(
            task_description="なんとなく作業する",
            caller_agent_id="admin-001",
            ctx=persona_mock_ctx,
        )

        assert result["success"] is True
        assert "task_type" in result

    @pytest.mark.asyncio
    async def test_detect_worker_denied(self, persona_mock_ctx, git_repo):
        """Worker からの呼び出しが拒否されることをテスト。"""
        mcp = _register_tools()
        detect = _get_tool_fn(mcp, "detect_task_type")
        _add_agent(persona_mock_ctx, "worker-001", AgentRole.WORKER, str(git_repo))

        result = await detect(
            task_description="テスト",
            caller_agent_id="worker-001",
            ctx=persona_mock_ctx,
        )

        assert result["success"] is False
        assert "使用禁止" in result["error"]


class TestGetOptimalPersona:
    """get_optimal_persona ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_optimal_persona_success(self, persona_mock_ctx, git_repo):
        """最適ペルソナを取得できることをテスト。"""
        mcp = _register_tools()
        get_persona = _get_tool_fn(mcp, "get_optimal_persona")
        _add_agent(persona_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        result = await get_persona(
            task_description="コードレビューを実施する",
            caller_agent_id="admin-001",
            ctx=persona_mock_ctx,
        )

        assert result["success"] is True
        assert "persona" in result
        assert "name" in result["persona"]
        assert "description" in result["persona"]
        assert "system_prompt_addition" in result

    @pytest.mark.asyncio
    async def test_get_optimal_persona_returns_prompt(self, persona_mock_ctx, git_repo):
        """system_prompt_addition が空でないことをテスト。"""
        mcp = _register_tools()
        get_persona = _get_tool_fn(mcp, "get_optimal_persona")
        _add_agent(persona_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        result = await get_persona(
            task_description="リファクタリングを行う",
            caller_agent_id="admin-001",
            ctx=persona_mock_ctx,
        )

        assert result["success"] is True
        assert len(result["system_prompt_addition"]) > 0

    @pytest.mark.asyncio
    async def test_get_optimal_persona_owner_allowed(self, persona_mock_ctx, git_repo):
        """Owner からの呼び出しが許可されることをテスト。"""
        mcp = _register_tools()
        get_persona = _get_tool_fn(mcp, "get_optimal_persona")
        _add_agent(persona_mock_ctx, "owner-001", AgentRole.OWNER, str(git_repo))

        result = await get_persona(
            task_description="設計作業をする",
            caller_agent_id="owner-001",
            ctx=persona_mock_ctx,
        )

        assert result["success"] is True


class TestListPersonas:
    """list_personas ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_list_personas_success(self, persona_mock_ctx, git_repo):
        """ペルソナ一覧を取得できることをテスト。"""
        mcp = _register_tools()
        list_personas = _get_tool_fn(mcp, "list_personas")
        _add_agent(persona_mock_ctx, "admin-001", AgentRole.ADMIN, str(git_repo))

        result = await list_personas(
            caller_agent_id="admin-001",
            ctx=persona_mock_ctx,
        )

        assert result["success"] is True
        assert "personas" in result
        assert "count" in result
        assert result["count"] > 0
        assert isinstance(result["personas"], list)

        # 各ペルソナに必要なフィールドがあるか確認
        for persona in result["personas"]:
            assert "task_type" in persona
            assert "name" in persona
            assert "description" in persona

    @pytest.mark.asyncio
    async def test_list_personas_worker_denied(self, persona_mock_ctx, git_repo):
        """Worker からの呼び出しが拒否されることをテスト。"""
        mcp = _register_tools()
        list_personas = _get_tool_fn(mcp, "list_personas")
        _add_agent(persona_mock_ctx, "worker-001", AgentRole.WORKER, str(git_repo))

        result = await list_personas(
            caller_agent_id="worker-001",
            ctx=persona_mock_ctx,
        )

        assert result["success"] is False
        assert "使用禁止" in result["error"]
