"""メモリ管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.tools.helpers import ensure_global_memory_manager, ensure_memory_manager


def register_tools(mcp: FastMCP) -> None:
    """メモリ管理ツールを登録する。"""

    # ========== Memory Tools (Layer 1: Project-local) ==========

    @mcp.tool()
    async def save_to_memory(
        key: str,
        content: str,
        tags: list[str] | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """知識をメモリに保存する。

        Args:
            key: エントリのキー（一意な識別子）
            content: 保存するコンテンツ
            tags: タグのリスト（オプション）

        Returns:
            保存結果（success, entry, message）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
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
        ctx: Context = None,
    ) -> dict[str, Any]:
        """メモリから知識を検索する。

        Args:
            query: 検索クエリ
            tags: フィルタリングするタグ（オプション）
            limit: 最大結果数

        Returns:
            検索結果（success, entries, count）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        memory = ensure_memory_manager(app_ctx)

        entries = memory.search(query, tags, limit)

        return {
            "success": True,
            "entries": [memory.to_dict(e) for e in entries],
            "count": len(entries),
        }

    @mcp.tool()
    async def get_memory_entry(key: str, ctx: Context = None) -> dict[str, Any]:
        """キーでメモリエントリを取得する。

        Args:
            key: エントリのキー

        Returns:
            エントリ情報（success, entry または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
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
        ctx: Context = None,
    ) -> dict[str, Any]:
        """メモリエントリ一覧を取得する。

        Args:
            tags: フィルタリングするタグ（オプション）

        Returns:
            エントリ一覧（success, entries, count）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        memory = ensure_memory_manager(app_ctx)

        if tags:
            entries = memory.list_by_tags(tags)
        else:
            entries = memory.list_all()

        return {
            "success": True,
            "entries": [memory.to_dict(e) for e in entries],
            "count": len(entries),
        }

    @mcp.tool()
    async def delete_memory_entry(key: str, ctx: Context = None) -> dict[str, Any]:
        """メモリエントリを削除する。

        Args:
            key: 削除するエントリのキー

        Returns:
            削除結果（success, key, message）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
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
    async def get_memory_summary(ctx: Context = None) -> dict[str, Any]:
        """メモリのサマリー情報を取得する。

        Returns:
            サマリー情報（success, summary）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
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
        ctx: Context = None,
    ) -> dict[str, Any]:
        """アーカイブされたメモリを検索する。

        prune で移動されたエントリを検索できる。

        Args:
            query: 検索クエリ
            tags: フィルタリングするタグ（オプション）
            limit: 最大結果数

        Returns:
            検索結果（success, entries, count）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
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
        ctx: Context = None,
    ) -> dict[str, Any]:
        """アーカイブされたメモリエントリ一覧を取得する。

        Args:
            limit: 最大結果数（デフォルト: 50）

        Returns:
            エントリ一覧（success, entries, count）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        memory = ensure_memory_manager(app_ctx)

        entries = memory.list_archive(limit)

        return {
            "success": True,
            "entries": [memory.to_dict(e) for e in entries],
            "count": len(entries),
        }

    @mcp.tool()
    async def restore_from_memory_archive(key: str, ctx: Context = None) -> dict[str, Any]:
        """アーカイブからメモリエントリを復元する。

        Args:
            key: 復元するエントリのキー

        Returns:
            復元結果（success, entry, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
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
    async def get_memory_archive_summary(ctx: Context = None) -> dict[str, Any]:
        """アーカイブのサマリー情報を取得する。

        Returns:
            サマリー情報（success, summary）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        memory = ensure_memory_manager(app_ctx)

        summary = memory.get_archive_summary()

        return {
            "success": True,
            "summary": summary,
        }

    # ========== Global Memory Tools (Layer 2) ==========

    @mcp.tool()
    async def save_to_global_memory(
        key: str,
        content: str,
        tags: list[str] | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """知識をグローバルメモリに保存する（全プロジェクト共通）。

        保存先: ~/.multi-agent-mcp/memory/memory.json

        Args:
            key: エントリのキー（一意な識別子）
            content: 保存するコンテンツ
            tags: タグのリスト（オプション）

        Returns:
            保存結果（success, entry, message）
        """
        memory = ensure_global_memory_manager()

        entry = memory.save(key, content, tags)

        return {
            "success": True,
            "entry": memory.to_dict(entry),
            "message": f"グローバルメモリに保存しました: {key}",
        }

    @mcp.tool()
    async def retrieve_from_global_memory(
        query: str,
        tags: list[str] | None = None,
        limit: int = 10,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """グローバルメモリから知識を検索する（全プロジェクト共通）。

        Args:
            query: 検索クエリ
            tags: フィルタリングするタグ（オプション）
            limit: 最大結果数

        Returns:
            検索結果（success, entries, count）
        """
        memory = ensure_global_memory_manager()

        entries = memory.search(query, tags, limit)

        return {
            "success": True,
            "entries": [memory.to_dict(e) for e in entries],
            "count": len(entries),
        }

    @mcp.tool()
    async def list_global_memory_entries(
        tags: list[str] | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """グローバルメモリエントリ一覧を取得する（全プロジェクト共通）。

        Args:
            tags: フィルタリングするタグ（オプション）

        Returns:
            エントリ一覧（success, entries, count）
        """
        memory = ensure_global_memory_manager()

        if tags:
            entries = memory.list_by_tags(tags)
        else:
            entries = memory.list_all()

        return {
            "success": True,
            "entries": [memory.to_dict(e) for e in entries],
            "count": len(entries),
        }

    @mcp.tool()
    async def get_global_memory_summary(ctx: Context = None) -> dict[str, Any]:
        """グローバルメモリのサマリー情報を取得する（全プロジェクト共通）。

        Returns:
            サマリー情報（success, summary）
        """
        memory = ensure_global_memory_manager()

        summary = memory.get_summary()

        return {
            "success": True,
            "summary": summary,
        }

    @mcp.tool()
    async def delete_global_memory_entry(key: str, ctx: Context = None) -> dict[str, Any]:
        """グローバルメモリエントリを削除する（全プロジェクト共通）。

        Args:
            key: 削除するエントリのキー

        Returns:
            削除結果（success, key, message）
        """
        memory = ensure_global_memory_manager()

        success = memory.delete(key)

        if not success:
            return {
                "success": False,
                "error": f"グローバルメモリエントリ '{key}' が見つかりません",
            }

        return {
            "success": True,
            "key": key,
            "message": f"グローバルメモリエントリを削除しました: {key}",
        }

    # ========== Global Memory Archive Tools (Layer 2) ==========

    @mcp.tool()
    async def search_global_memory_archive(
        query: str,
        tags: list[str] | None = None,
        limit: int = 10,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """グローバルアーカイブを検索する（全プロジェクト共通）。

        Args:
            query: 検索クエリ
            tags: フィルタリングするタグ（オプション）
            limit: 最大結果数

        Returns:
            検索結果（success, entries, count）
        """
        memory = ensure_global_memory_manager()

        entries = memory.search_archive(query, tags, limit)

        return {
            "success": True,
            "entries": [memory.to_dict(e) for e in entries],
            "count": len(entries),
        }

    @mcp.tool()
    async def list_global_memory_archive(
        limit: int | None = 50,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """グローバルアーカイブエントリ一覧を取得する（全プロジェクト共通）。

        Args:
            limit: 最大結果数（デフォルト: 50）

        Returns:
            エントリ一覧（success, entries, count）
        """
        memory = ensure_global_memory_manager()

        entries = memory.list_archive(limit)

        return {
            "success": True,
            "entries": [memory.to_dict(e) for e in entries],
            "count": len(entries),
        }

    @mcp.tool()
    async def restore_from_global_memory_archive(
        key: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """グローバルアーカイブからエントリを復元する（全プロジェクト共通）。

        Args:
            key: 復元するエントリのキー

        Returns:
            復元結果（success, entry, message または error）
        """
        memory = ensure_global_memory_manager()

        entry = memory.restore_from_archive(key)

        if not entry:
            return {
                "success": False,
                "error": f"グローバルアーカイブにエントリ '{key}' が見つかりません",
            }

        return {
            "success": True,
            "entry": memory.to_dict(entry),
            "message": f"グローバルアーカイブから復元しました: {key}",
        }

    @mcp.tool()
    async def get_global_memory_archive_summary(ctx: Context = None) -> dict[str, Any]:
        """グローバルアーカイブのサマリー情報を取得する（全プロジェクト共通）。

        Returns:
            サマリー情報（success, summary）
        """
        memory = ensure_global_memory_manager()

        summary = memory.get_archive_summary()

        return {
            "success": True,
            "summary": summary,
        }
