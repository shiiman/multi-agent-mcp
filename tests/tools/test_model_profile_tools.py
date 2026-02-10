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
        assert "MCP_MODEL_PROFILE_ACTIVE=performance" in env_file.read_text(encoding="utf-8")
        loaded_config = json.loads(config_file.read_text(encoding="utf-8"))
        assert "model_profile_active" not in loaded_config
