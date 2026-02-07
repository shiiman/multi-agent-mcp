"""グローバルメモリ管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.tools.helpers import (
    ensure_global_memory_manager,
    require_permission,
)


def register_tools(mcp: FastMCP) -> None:
    """グローバルメモリ管理ツールを登録する。"""

    # ========== Global Memory Tools (Layer 2) ==========

    @mcp.tool()
    async def save_to_global_memory(
        key: str,
        content: str,
        tags: list[str] | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """知識をグローバルメモリに保存する（全プロジェクト共通）。

        保存先: ~/.multi-agent-mcp/memory/

        Args:
            key: エントリのキー（一意な識別子）
            content: 保存するコンテンツ
            tags: タグのリスト（オプション）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            保存結果（success, entry, message）
        """
        app_ctx, role_error = require_permission(ctx, "save_to_global_memory", caller_agent_id)
        if role_error:
            return role_error

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
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """グローバルメモリから知識を検索する（全プロジェクト共通）。

        Args:
            query: 検索クエリ
            tags: フィルタリングするタグ（オプション）
            limit: 最大結果数
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            検索結果（success, entries, count）
        """
        app_ctx, role_error = require_permission(
            ctx, "retrieve_from_global_memory", caller_agent_id
        )
        if role_error:
            return role_error

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
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """グローバルメモリエントリ一覧を取得する（全プロジェクト共通）。

        Args:
            tags: フィルタリングするタグ（オプション）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            エントリ一覧（success, entries, count）
        """
        app_ctx, role_error = require_permission(ctx, "list_global_memory_entries", caller_agent_id)
        if role_error:
            return role_error

        memory = ensure_global_memory_manager()

        entries = memory.list_by_tags(tags) if tags else memory.list_all()

        return {
            "success": True,
            "entries": [memory.to_dict(e) for e in entries],
            "count": len(entries),
        }

    @mcp.tool()
    async def get_global_memory_summary(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """グローバルメモリのサマリー情報を取得する（全プロジェクト共通）。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            サマリー情報（success, summary）
        """
        app_ctx, role_error = require_permission(ctx, "get_global_memory_summary", caller_agent_id)
        if role_error:
            return role_error

        memory = ensure_global_memory_manager()

        summary = memory.get_summary()

        return {
            "success": True,
            "summary": summary,
        }

    @mcp.tool()
    async def delete_global_memory_entry(
        key: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """グローバルメモリエントリを削除する（全プロジェクト共通）。

        ※ Owner と Admin のみ使用可能。

        Args:
            key: 削除するエントリのキー
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            削除結果（success, key, message）
        """
        app_ctx, role_error = require_permission(ctx, "delete_global_memory_entry", caller_agent_id)
        if role_error:
            return role_error

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
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """グローバルアーカイブを検索する（全プロジェクト共通）。

        ※ Owner と Admin のみ使用可能。

        Args:
            query: 検索クエリ
            tags: フィルタリングするタグ（オプション）
            limit: 最大結果数
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            検索結果（success, entries, count）
        """
        app_ctx, role_error = require_permission(
            ctx, "search_global_memory_archive", caller_agent_id
        )
        if role_error:
            return role_error

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
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """グローバルアーカイブエントリ一覧を取得する（全プロジェクト共通）。

        ※ Owner と Admin のみ使用可能。

        Args:
            limit: 最大結果数（デフォルト: 50）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            エントリ一覧（success, entries, count）
        """
        app_ctx, role_error = require_permission(ctx, "list_global_memory_archive", caller_agent_id)
        if role_error:
            return role_error

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
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """グローバルアーカイブからエントリを復元する（全プロジェクト共通）。

        ※ Owner と Admin のみ使用可能。

        Args:
            key: 復元するエントリのキー
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            復元結果（success, entry, message または error）
        """
        app_ctx, role_error = require_permission(
            ctx,
            "restore_from_global_memory_archive",
            caller_agent_id,
        )
        if role_error:
            return role_error

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
    async def get_global_memory_archive_summary(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """グローバルアーカイブのサマリー情報を取得する（全プロジェクト共通）。

        ※ Owner と Admin のみ使用可能。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            サマリー情報（success, summary）
        """
        app_ctx, role_error = require_permission(
            ctx,
            "get_global_memory_archive_summary",
            caller_agent_id,
        )
        if role_error:
            return role_error

        memory = ensure_global_memory_manager()

        summary = memory.get_archive_summary()

        return {
            "success": True,
            "summary": summary,
        }
