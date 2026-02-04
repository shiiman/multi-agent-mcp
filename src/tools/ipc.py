"""IPC/メッセージング管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.context import AppContext
from src.models.message import MessagePriority, MessageType
from src.tools.helpers import check_tool_permission, ensure_ipc_manager


def register_tools(mcp: FastMCP) -> None:
    """IPC/メッセージング管理ツールを登録する。"""

    @mcp.tool()
    async def send_message(
        sender_id: str,
        receiver_id: str | None,
        message_type: str,
        content: str,
        subject: str = "",
        priority: str = "normal",
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェント間でメッセージを送信する。

        Args:
            sender_id: 送信元エージェントID
            receiver_id: 宛先エージェントID（Noneでブロードキャスト）
            message_type: メッセージタイプ（task_assign, task_complete, etc.）
            content: メッセージ内容
            subject: 件名（オプション）
            priority: 優先度（low/normal/high/urgent）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            送信結果（success, message_id, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "send_message", caller_agent_id)
        if role_error:
            return role_error

        ipc = ensure_ipc_manager(app_ctx)

        # メッセージタイプの検証
        try:
            msg_type = MessageType(message_type)
        except ValueError:
            valid_types = [t.value for t in MessageType]
            return {
                "success": False,
                "error": f"無効なメッセージタイプです: {message_type}（有効: {valid_types}）",
            }

        # 優先度の検証
        try:
            msg_priority = MessagePriority(priority)
        except ValueError:
            valid_priorities = [p.value for p in MessagePriority]
            return {
                "success": False,
                "error": f"無効な優先度です: {priority}（有効: {valid_priorities}）",
            }

        # 送信者がIPCに登録されているか確認
        if sender_id not in ipc.get_all_agent_ids():
            ipc.register_agent(sender_id)

        # 受信者の確認（ブロードキャスト以外）
        if receiver_id and receiver_id not in ipc.get_all_agent_ids():
            ipc.register_agent(receiver_id)

        message = ipc.send_message(
            sender_id=sender_id,
            receiver_id=receiver_id,
            message_type=msg_type,
            content=content,
            subject=subject,
            priority=msg_priority,
        )

        return {
            "success": True,
            "message_id": message.id,
            "message": (
                "ブロードキャストを送信しました"
                if receiver_id is None
                else f"メッセージを {receiver_id} に送信しました"
            ),
        }

    @mcp.tool()
    async def read_messages(
        agent_id: str,
        unread_only: bool = False,
        message_type: str | None = None,
        mark_as_read: bool = True,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェントのメッセージを読み取る。

        Args:
            agent_id: エージェントID
            unread_only: 未読のみ取得するか
            message_type: フィルターするメッセージタイプ
            mark_as_read: 既読としてマークするか
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            メッセージ一覧（success, messages, count または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "read_messages", caller_agent_id)
        if role_error:
            return role_error

        ipc = ensure_ipc_manager(app_ctx)

        # メッセージタイプの検証
        msg_type = None
        if message_type:
            try:
                msg_type = MessageType(message_type)
            except ValueError:
                valid_types = [t.value for t in MessageType]
                return {
                    "success": False,
                    "error": (
                        f"無効なメッセージタイプです: {message_type}"
                        f"（有効: {valid_types}）"
                    ),
                }

        # エージェントが登録されていなければ登録
        if agent_id not in ipc.get_all_agent_ids():
            ipc.register_agent(agent_id)

        messages = ipc.read_messages(
            agent_id=agent_id,
            unread_only=unread_only,
            message_type=msg_type,
            mark_as_read=mark_as_read,
        )

        return {
            "success": True,
            "messages": [m.model_dump(mode="json") for m in messages],
            "count": len(messages),
        }

    @mcp.tool()
    async def get_unread_count(
        agent_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェントの未読メッセージ数を取得する。

        Args:
            agent_id: エージェントID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            未読数（success, agent_id, unread_count）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_unread_count", caller_agent_id)
        if role_error:
            return role_error

        ipc = ensure_ipc_manager(app_ctx)

        if agent_id not in ipc.get_all_agent_ids():
            ipc.register_agent(agent_id)

        count = ipc.get_unread_count(agent_id)

        return {
            "success": True,
            "agent_id": agent_id,
            "unread_count": count,
        }

    @mcp.tool()
    async def clear_messages(
        agent_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェントのメッセージをクリアする。

        ※ Owner と Admin のみ使用可能。

        Args:
            agent_id: エージェントID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            クリア結果（success, agent_id, deleted_count, message）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "clear_messages", caller_agent_id)
        if role_error:
            return role_error

        ipc = ensure_ipc_manager(app_ctx)

        if agent_id not in ipc.get_all_agent_ids():
            return {
                "success": False,
                "error": f"エージェント {agent_id} のキューが見つかりません",
            }

        deleted_count = ipc.clear_messages(agent_id)

        return {
            "success": True,
            "agent_id": agent_id,
            "deleted_count": deleted_count,
            "message": f"{deleted_count} 件のメッセージを削除しました",
        }

    @mcp.tool()
    async def register_agent_to_ipc(
        agent_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """エージェントをIPCシステムに登録する。

        Args:
            agent_id: エージェントID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            登録結果（success, agent_id, message）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "register_agent_to_ipc", caller_agent_id)
        if role_error:
            return role_error

        ipc = ensure_ipc_manager(app_ctx)

        ipc.register_agent(agent_id)

        return {
            "success": True,
            "agent_id": agent_id,
            "message": f"エージェント {agent_id} をIPCに登録しました",
        }
