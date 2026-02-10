"""メモリ管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.tools.helpers import (
    ensure_memory_manager,
    require_permission,
)


def register_tools(mcp: FastMCP) -> None:
    """メモリ管理ツールを登録する。"""

    # ========== Memory Tools (Layer 1: Project-local) ==========

    @mcp.tool()
    async def save_to_memory(
        key: str,
        content: str,
        tags: list[str] | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """知識をメモリに保存する。

        Args:
            key: エントリのキー（一意な識別子）
            content: 保存するコンテンツ
            tags: タグのリスト（オプション）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            保存結果（success, entry, message）
        """
        app_ctx, role_error = require_permission(ctx, "save_to_memory", caller_agent_id)
        if role_error:
            return role_error

        memory = ensure_memory_manager(app_ctx)

        entry = memory.save(key, content, tags)

        return {
            "success": True,
            "entry": memory.to_dict(entry),
            "message": f"メモリに保存しました: {key}",
        }

    @mcp.tool()
    async def retrieve_from_memory(
        query: str,
        tags: list[str] | None = None,
        limit: int = 10,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """メモリから知識を検索する。

        Args:
            query: 検索クエリ
            tags: フィルタリングするタグ（オプション）
            limit: 最大結果数
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            検索結果（success, entries, count）
        """
        app_ctx, role_error = require_permission(ctx, "retrieve_from_memory", caller_agent_id)
        if role_error:
            return role_error

        memory = ensure_memory_manager(app_ctx)

        entries = memory.search(query, tags, limit)

        return {
            "success": True,
            "entries": [memory.to_dict(e) for e in entries],
            "count": len(entries),
        }

    @mcp.tool()
    async def get_memory_entry(
        key: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """キーでメモリエントリを取得する。

        Args:
            key: エントリのキー
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            エントリ情報（success, entry または error）
        """
        app_ctx, role_error = require_permission(ctx, "get_memory_entry", caller_agent_id)
        if role_error:
            return role_error

        memory = ensure_memory_manager(app_ctx)

        entry = memory.get(key)

        if not entry:
            return {
                "success": False,
                "error": f"メモリエントリ '{key}' が見つかりません",
            }

        return {
            "success": True,
            "entry": memory.to_dict(entry),
        }

    @mcp.tool()
    async def list_memory_entries(
        tags: list[str] | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """メモリエントリ一覧を取得する。

        Args:
            tags: フィルタリングするタグ（オプション）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            エントリ一覧（success, entries, count）
        """
        app_ctx, role_error = require_permission(ctx, "list_memory_entries", caller_agent_id)
        if role_error:
            return role_error

        memory = ensure_memory_manager(app_ctx)

        entries = memory.list_by_tags(tags) if tags else memory.list_all()

        return {
            "success": True,
            "entries": [memory.to_dict(e) for e in entries],
            "count": len(entries),
        }

    @mcp.tool()
    async def delete_memory_entry(
        key: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """メモリエントリを削除する。

        ※ Owner と Admin のみ使用可能。

        Args:
            key: 削除するエントリのキー
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            削除結果（success, key, message）
        """
        app_ctx, role_error = require_permission(ctx, "delete_memory_entry", caller_agent_id)
        if role_error:
            return role_error

        memory = ensure_memory_manager(app_ctx)

        success = memory.delete(key)

        if not success:
            return {
                "success": False,
                "error": f"メモリエントリ '{key}' が見つかりません",
            }

        return {
            "success": True,
            "key": key,
            "message": f"メモリエントリを削除しました: {key}",
        }

    @mcp.tool()
    async def get_memory_summary(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """メモリのサマリー情報を取得する。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            サマリー情報（success, summary）
        """
        app_ctx, role_error = require_permission(ctx, "get_memory_summary", caller_agent_id)
        if role_error:
            return role_error

        memory = ensure_memory_manager(app_ctx)

        summary = memory.get_summary()

        return {
            "success": True,
            "summary": summary,
        }

    # ========== Memory Archive Tools (Layer 3) ==========

    @mcp.tool()
    async def search_memory_archive(
        query: str,
        tags: list[str] | None = None,
        limit: int = 10,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """アーカイブされたメモリを検索する。

        prune で移動されたエントリを検索できる。

        ※ Owner と Admin のみ使用可能。

        Args:
            query: 検索クエリ
            tags: フィルタリングするタグ（オプション）
            limit: 最大結果数
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            検索結果（success, entries, count）
        """
        app_ctx, role_error = require_permission(ctx, "search_memory_archive", caller_agent_id)
        if role_error:
            return role_error

        memory = ensure_memory_manager(app_ctx)

        entries = memory.search_archive(query, tags, limit)

        return {
            "success": True,
            "entries": [memory.to_dict(e) for e in entries],
            "count": len(entries),
        }

    @mcp.tool()
    async def list_memory_archive(
        limit: int | None = 50,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """アーカイブされたメモリエントリ一覧を取得する。

        ※ Owner と Admin のみ使用可能。

        Args:
            limit: 最大結果数（デフォルト: 50）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            エントリ一覧（success, entries, count）
        """
        app_ctx, role_error = require_permission(ctx, "list_memory_archive", caller_agent_id)
        if role_error:
            return role_error

        memory = ensure_memory_manager(app_ctx)

        entries = memory.list_archive(limit)

        return {
            "success": True,
            "entries": [memory.to_dict(e) for e in entries],
            "count": len(entries),
        }

    @mcp.tool()
    async def restore_from_memory_archive(
        key: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """アーカイブからメモリエントリを復元する。

        ※ Owner と Admin のみ使用可能。

        Args:
            key: 復元するエントリのキー
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            復元結果（success, entry, message または error）
        """
        app_ctx, role_error = require_permission(
            ctx, "restore_from_memory_archive", caller_agent_id
        )
        if role_error:
            return role_error

        memory = ensure_memory_manager(app_ctx)

        entry = memory.restore_from_archive(key)

        if not entry:
            return {
                "success": False,
                "error": f"アーカイブにエントリ '{key}' が見つかりません",
            }

        return {
            "success": True,
            "entry": memory.to_dict(entry),
            "message": f"アーカイブから復元しました: {key}",
        }

    @mcp.tool()
    async def get_memory_archive_summary(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """アーカイブのサマリー情報を取得する。

        ※ Owner と Admin のみ使用可能。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            サマリー情報（success, summary）
        """
        app_ctx, role_error = require_permission(ctx, "get_memory_archive_summary", caller_agent_id)
        if role_error:
            return role_error

        memory = ensure_memory_manager(app_ctx)

        summary = memory.get_archive_summary()

        return {
            "success": True,
            "summary": summary,
        }
