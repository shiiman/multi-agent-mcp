"""model_profile ツールのテスト。"""

import json

import pytest


class TestSwitchModelProfile:
    """switch_model_profile ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_switch_model_profile_updates_env_only(self, mock_mcp_context, temp_dir):
        """profile は .env にのみ永続化し、config.json へは保存しない。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.model_profile import register_tools

        app_ctx = mock_mcp_context.request_context.lifespan_context
        app_ctx.project_root = str(temp_dir)
        app_ctx.settings.enable_git = False

        mcp_dir = temp_dir / app_ctx.settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        env_file = mcp_dir / ".env"
        env_file.write_text(
            "MCP_MODEL_PROFILE_ACTIVE=standard\n",
            encoding="utf-8",
        )
        config_file = mcp_dir / "config.json"
        config_file.write_text(
            json.dumps({"enable_git": False}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        mcp = FastMCP("test")
        register_tools(mcp)
        switch_model_profile = next(
            tool.fn
            for tool in mcp._tool_manager._tools.values()
            if tool.name == "switch_model_profile"
        )

        result = await switch_model_profile(
            profile="performance",
            caller_agent_id="agent-001",
            ctx=mock_mcp_context,
        )

        assert result["success"] is True
        assert result["current_profile"] == "performance"
        assert result["persistence_policy"]["canonical_store"] == ".multi-agent-mcp/.env"
        assert result["persistence_policy"]["updated_env_key"] == "MCP_MODEL_PROFILE_ACTIVE"
        assert result["persistence_policy"]["config_json_persists_profile"] is False
        assert "MCP_MODEL_PROFILE_ACTIVE=performance" in env_file.read_text(encoding="utf-8")
        loaded_config = json.loads(config_file.read_text(encoding="utf-8"))
        assert "model_profile_active" not in loaded_config

    @pytest.mark.asyncio
    async def test_switch_model_profile_never_writes_profile_to_config_json(
        self, mock_mcp_context, temp_dir
    ):
        """config.json に profile 由来キーがあっても switch は書き換えない。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.model_profile import register_tools

        app_ctx = mock_mcp_context.request_context.lifespan_context
        app_ctx.project_root = str(temp_dir)
        app_ctx.settings.enable_git = False

        mcp_dir = temp_dir / app_ctx.settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        env_file = mcp_dir / ".env"
        env_file.write_text(
            "MCP_MODEL_PROFILE_ACTIVE=standard\n",
            encoding="utf-8",
        )
        config_file = mcp_dir / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "enable_git": False,
                    "model_profile_active": "stale-standard",
                    "MCP_MODEL_PROFILE_ACTIVE": "stale-standard",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        config_before = config_file.read_text(encoding="utf-8")

        mcp = FastMCP("test")
        register_tools(mcp)
        switch_model_profile = next(
            tool.fn
            for tool in mcp._tool_manager._tools.values()
            if tool.name == "switch_model_profile"
        )

        result = await switch_model_profile(
            profile="performance",
            caller_agent_id="agent-001",
            ctx=mock_mcp_context,
        )

        assert result["success"] is True
        assert "MCP_MODEL_PROFILE_ACTIVE=performance" in env_file.read_text(encoding="utf-8")
        assert config_file.read_text(encoding="utf-8") == config_before


class TestGetModelProfile:
    """get_model_profile ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_model_profile_ignores_config_json_profile_keys(
        self, mock_mcp_context, temp_dir, monkeypatch
    ):
        """モデルプロファイルは .env を正準とし、config.json の同名キーを無視する。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.helpers import refresh_app_settings
        from src.tools.model_profile import register_tools

        monkeypatch.delenv("MCP_MODEL_PROFILE_ACTIVE", raising=False)

        app_ctx = mock_mcp_context.request_context.lifespan_context
        app_ctx.project_root = str(temp_dir)
        app_ctx.settings.enable_git = False

        mcp_dir = temp_dir / app_ctx.settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        env_file = mcp_dir / ".env"
        env_file.write_text(
            "MCP_MODEL_PROFILE_ACTIVE=standard\n",
            encoding="utf-8",
        )
        config_file = mcp_dir / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "enable_git": False,
                    "model_profile_active": "performance",
                    "MCP_MODEL_PROFILE_ACTIVE": "performance",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        refresh_app_settings(app_ctx, str(temp_dir))

        mcp = FastMCP("test")
        register_tools(mcp)
        get_model_profile = next(
            tool.fn
            for tool in mcp._tool_manager._tools.values()
            if tool.name == "get_model_profile"
        )

        result = await get_model_profile(
            caller_agent_id="agent-001",
            ctx=mock_mcp_context,
        )

        assert result["success"] is True
        assert result["active_profile"] == "standard"
        assert result["persistence_policy"]["canonical_store"] == ".multi-agent-mcp/.env"
        assert result["worker_model"]["policy"] == (
            "profile-default, per-worker override when worker_cli_mode=per-worker"
        )
        assert "mode" not in result["worker_model"]
        assert "uniform" not in result["worker_model"]


class TestGetModelProfileSettings:
    """get_model_profile_settings ツールのテスト。"""

    @pytest.mark.asyncio
    async def test_get_model_profile_settings_uses_worker_model_policy(
        self, mock_mcp_context, temp_dir
    ):
        """worker_model は mode/uniform ではなく policy を返す。"""
        from mcp.server.fastmcp import FastMCP

        from src.tools.model_profile import register_tools

        app_ctx = mock_mcp_context.request_context.lifespan_context
        app_ctx.project_root = str(temp_dir)
        app_ctx.settings.enable_git = False

        mcp = FastMCP("test")
        register_tools(mcp)
        get_model_profile_settings = next(
            tool.fn
            for tool in mcp._tool_manager._tools.values()
            if tool.name == "get_model_profile_settings"
        )

        result = await get_model_profile_settings(
            caller_agent_id="agent-001",
            ctx=mock_mcp_context,
        )

        assert result["success"] is True
        assert result["worker_model"]["policy"] == (
            "profile-default, per-worker override when worker_cli_mode=per-worker"
        )
        assert "mode" not in result["worker_model"]
        assert "uniform" not in result["worker_model"]
