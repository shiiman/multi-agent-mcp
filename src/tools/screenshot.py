"""スクリーンショット管理ツール。"""

import base64
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.tools.helpers import require_permission

# スクリーンショット MIME マップ
_SCREENSHOT_MIME_MAP: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _read_image_as_base64(file_path: Path) -> tuple[str, str, int]:
    """画像ファイルを Base64 エンコードし MIME タイプとサイズを返す。

    Args:
        file_path: 画像ファイルのパス

    Returns:
        (base64_data, mime_type, size_bytes) のタプル
    """
    ext = file_path.suffix.lower()
    mime_type = _SCREENSHOT_MIME_MAP.get(ext, "application/octet-stream")
    with open(file_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return data, mime_type, file_path.stat().st_size


def register_tools(mcp: FastMCP) -> None:
    """スクリーンショット管理ツールを登録する。"""

    @mcp.tool()
    async def get_screenshot_dir(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """スクリーンショットディレクトリを取得する。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            ディレクトリ情報（success, path, exists）
        """
        app_ctx, role_error = require_permission(ctx, "get_screenshot_dir", caller_agent_id)
        if role_error:
            return role_error

        if not app_ctx.project_root:
            return {
                "success": False,
                "error": "project_root が設定されていません",
            }

        screenshot_dir = Path(app_ctx.project_root) / app_ctx.settings.mcp_dir / "screenshot"

        return {
            "success": True,
            "path": str(screenshot_dir),
            "exists": screenshot_dir.exists(),
        }

    @mcp.tool()
    async def list_screenshots(
        limit: int = 10,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """スクリーンショット一覧を取得する（最新順）。

        Args:
            limit: 最大取得件数（デフォルト: 10）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            スクリーンショット一覧（success, screenshots, count）
        """
        app_ctx, role_error = require_permission(ctx, "list_screenshots", caller_agent_id)
        if role_error:
            return role_error

        settings = app_ctx.settings

        if not app_ctx.project_root:
            return {
                "success": False,
                "error": "project_root が設定されていません",
            }

        screenshot_dir = Path(app_ctx.project_root) / app_ctx.settings.mcp_dir / "screenshot"
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
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """指定したスクリーンショットを読み取る（Base64）。

        Args:
            filename: ファイル名
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            画像データ（success, filename, base64_data, mime_type）
        """
        app_ctx, role_error = require_permission(ctx, "read_screenshot", caller_agent_id)
        if role_error:
            return role_error

        if not app_ctx.project_root:
            return {
                "success": False,
                "error": "project_root が設定されていません",
            }

        screenshot_dir = (
            Path(app_ctx.project_root) / app_ctx.settings.mcp_dir / "screenshot"
        ).resolve()
        file_path = (screenshot_dir / filename).resolve()

        try:
            file_path.relative_to(screenshot_dir)
        except ValueError:
            return {
                "success": False,
                "error": f"path traversal は許可されていません: {filename}",
            }

        if not file_path.exists():
            return {
                "success": False,
                "error": f"ファイルが見つかりません: {filename}",
            }

        data, mime_type, size_bytes = _read_image_as_base64(file_path)

        return {
            "success": True,
            "filename": filename,
            "path": str(file_path),
            "base64_data": data,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
        }

    @mcp.tool()
    async def read_latest_screenshot(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """最新のスクリーンショットを読み取る（Base64）。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            画像データ（success, filename, base64_data, mime_type）
        """
        app_ctx, role_error = require_permission(ctx, "read_latest_screenshot", caller_agent_id)
        if role_error:
            return role_error

        settings = app_ctx.settings

        if not app_ctx.project_root:
            return {
                "success": False,
                "error": "project_root が設定されていません",
            }

        screenshot_dir = Path(app_ctx.project_root) / app_ctx.settings.mcp_dir / "screenshot"
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

        data, mime_type, size_bytes = _read_image_as_base64(latest)

        return {
            "success": True,
            "filename": latest.name,
            "path": str(latest),
            "base64_data": data,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
        }
