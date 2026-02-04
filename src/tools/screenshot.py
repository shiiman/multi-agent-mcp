"""スクリーンショット管理ツール。"""

import base64
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.settings import Settings
from src.context import AppContext


def _get_mcp_dir() -> str:
    """Settings から MCP ディレクトリ名を取得する。"""
    return Settings().mcp_dir


def register_tools(mcp: FastMCP) -> None:
    """スクリーンショット管理ツールを登録する。"""

    @mcp.tool()
    async def get_screenshot_dir(ctx: Context = None) -> dict[str, Any]:
        """スクリーンショットディレクトリを取得する。

        Returns:
            ディレクトリ情報（success, path, exists）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        if not app_ctx.project_root:
            return {
                "success": False,
                "error": "project_root が設定されていません",
            }

        screenshot_dir = Path(app_ctx.project_root) / _get_mcp_dir() / "screenshot"

        return {
            "success": True,
            "path": str(screenshot_dir),
            "exists": screenshot_dir.exists(),
        }

    @mcp.tool()
    async def list_screenshots(
        limit: int = 10,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """スクリーンショット一覧を取得する（最新順）。

        Args:
            limit: 最大取得件数（デフォルト: 10）

        Returns:
            スクリーンショット一覧（success, screenshots, count）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        settings = app_ctx.settings

        if not app_ctx.project_root:
            return {
                "success": False,
                "error": "project_root が設定されていません",
            }

        screenshot_dir = Path(app_ctx.project_root) / _get_mcp_dir() / "screenshot"
        if not screenshot_dir.exists():
            return {
                "success": False,
                "error": f"ディレクトリが存在しません: {screenshot_dir}",
            }

        # 対象拡張子のファイルを収集
        files = []
        for ext in settings.screenshot_extensions:
            files.extend(screenshot_dir.glob(f"*{ext}"))

        # 更新日時で降順ソート
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

        # limit 件に制限
        files = files[:limit]

        screenshots = []
        for f in files:
            stat = f.stat()
            screenshots.append({
                "filename": f.name,
                "path": str(f),
                "size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
            })

        return {
            "success": True,
            "screenshots": screenshots,
            "count": len(screenshots),
        }

    @mcp.tool()
    async def read_screenshot(
        filename: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """指定したスクリーンショットを読み取る（Base64）。

        Args:
            filename: ファイル名

        Returns:
            画像データ（success, filename, base64_data, mime_type）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        if not app_ctx.project_root:
            return {
                "success": False,
                "error": "project_root が設定されていません",
            }

        screenshot_dir = Path(app_ctx.project_root) / _get_mcp_dir() / "screenshot"
        file_path = screenshot_dir / filename

        if not file_path.exists():
            return {
                "success": False,
                "error": f"ファイルが見つかりません: {filename}",
            }

        # 拡張子から MIME タイプを推定
        ext = file_path.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        mime_type = mime_map.get(ext, "application/octet-stream")

        # Base64 エンコード
        with open(file_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")

        return {
            "success": True,
            "filename": filename,
            "path": str(file_path),
            "base64_data": data,
            "mime_type": mime_type,
            "size_bytes": file_path.stat().st_size,
        }

    @mcp.tool()
    async def read_latest_screenshot(ctx: Context = None) -> dict[str, Any]:
        """最新のスクリーンショットを読み取る（Base64）。

        Returns:
            画像データ（success, filename, base64_data, mime_type）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        settings = app_ctx.settings

        if not app_ctx.project_root:
            return {
                "success": False,
                "error": "project_root が設定されていません",
            }

        screenshot_dir = Path(app_ctx.project_root) / _get_mcp_dir() / "screenshot"
        if not screenshot_dir.exists():
            return {
                "success": False,
                "error": f"ディレクトリが存在しません: {screenshot_dir}",
            }

        # 対象拡張子のファイルを収集
        files = []
        for ext in settings.screenshot_extensions:
            files.extend(screenshot_dir.glob(f"*{ext}"))

        if not files:
            return {
                "success": False,
                "error": "スクリーンショットが見つかりません",
            }

        # 最新ファイルを取得
        latest = max(files, key=lambda f: f.stat().st_mtime)

        # 拡張子から MIME タイプを推定
        ext = latest.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        mime_type = mime_map.get(ext, "application/octet-stream")

        # Base64 エンコード
        with open(latest, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")

        return {
            "success": True,
            "filename": latest.name,
            "path": str(latest),
            "base64_data": data,
            "mime_type": mime_type,
            "size_bytes": latest.stat().st_size,
        }
