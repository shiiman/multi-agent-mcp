"""モデルプロファイル管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.settings import ModelProfile
from src.context import AppContext
from src.tools.helpers import check_tool_permission


def get_profile_settings(app_ctx: AppContext, profile: ModelProfile) -> dict[str, Any]:
    """指定されたプロファイルの設定を取得する。

    Args:
        app_ctx: アプリケーションコンテキスト
        profile: モデルプロファイル

    Returns:
        プロファイル設定の辞書
    """
    settings = app_ctx.settings

    if profile == ModelProfile.STANDARD:
        return {
            "profile": profile.value,
            "ai_cli": settings.model_profile_standard_cli.value,
            "admin_model": settings.model_profile_standard_admin_model,
            "worker_model": settings.model_profile_standard_worker_model,
            "max_workers": settings.model_profile_standard_max_workers,
            "thinking_multiplier": settings.model_profile_standard_thinking_multiplier,
        }
    else:  # PERFORMANCE
        return {
            "profile": profile.value,
            "ai_cli": settings.model_profile_performance_cli.value,
            "admin_model": settings.model_profile_performance_admin_model,
            "worker_model": settings.model_profile_performance_worker_model,
            "max_workers": settings.model_profile_performance_max_workers,
            "thinking_multiplier": settings.model_profile_performance_thinking_multiplier,
        }


def get_current_profile_settings(app_ctx: AppContext) -> dict[str, Any]:
    """現在アクティブなプロファイルの設定を取得する。

    Args:
        app_ctx: アプリケーションコンテキスト

    Returns:
        現在のプロファイル設定の辞書
    """
    return get_profile_settings(app_ctx, app_ctx.settings.model_profile_active)


def register_tools(mcp: FastMCP) -> None:
    """モデルプロファイル管理ツールを登録する。"""

    @mcp.tool()
    async def get_model_profile(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """現在のモデルプロファイルを取得する。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            プロファイル情報（success, active_profile, settings）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_model_profile", caller_agent_id)
        if role_error:
            return role_error

        settings = app_ctx.settings

        current_settings = get_current_profile_settings(app_ctx)

        return {
            "success": True,
            "active_profile": settings.model_profile_active.value,
            "settings": current_settings,
            "available_profiles": [p.value for p in ModelProfile],
        }

    @mcp.tool()
    async def switch_model_profile(
        profile: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """モデルプロファイルを切り替える。

        ※ Owner のみ使用可能。

        Args:
            profile: 切り替え先プロファイル（standard/performance）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            切り替え結果（success, previous_profile, current_profile, settings）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "switch_model_profile", caller_agent_id)
        if role_error:
            return role_error

        settings = app_ctx.settings

        # プロファイルの検証
        try:
            new_profile = ModelProfile(profile)
        except ValueError:
            valid_profiles = [p.value for p in ModelProfile]
            return {
                "success": False,
                "error": f"無効なプロファイルです: {profile}（有効: {valid_profiles}）",
            }

        previous_profile = settings.model_profile_active
        settings.model_profile_active = new_profile

        new_settings = get_profile_settings(app_ctx, new_profile)

        return {
            "success": True,
            "previous_profile": previous_profile.value,
            "current_profile": new_profile.value,
            "settings": new_settings,
            "message": (
                f"プロファイルを {previous_profile.value} → {new_profile.value} に切り替えました"
            ),
        }

    @mcp.tool()
    async def get_model_profile_settings(
        profile: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """モデルプロファイルの設定詳細を取得する。

        Args:
            profile: プロファイル名（省略時は全プロファイル）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            プロファイル設定の詳細
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_model_profile_settings", caller_agent_id)
        if role_error:
            return role_error

        settings = app_ctx.settings

        if profile:
            # 特定のプロファイル
            try:
                target_profile = ModelProfile(profile)
            except ValueError:
                valid_profiles = [p.value for p in ModelProfile]
                return {
                    "success": False,
                    "error": f"無効なプロファイルです: {profile}（有効: {valid_profiles}）",
                }

            profile_settings = get_profile_settings(app_ctx, target_profile)
            return {
                "success": True,
                "profile": target_profile.value,
                "is_active": target_profile == settings.model_profile_active,
                "settings": profile_settings,
            }
        else:
            # 全プロファイル
            all_profiles = {}
            for p in ModelProfile:
                all_profiles[p.value] = get_profile_settings(app_ctx, p)

            return {
                "success": True,
                "active_profile": settings.model_profile_active.value,
                "profiles": all_profiles,
            }
