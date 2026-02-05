"""ダッシュボード/タスク管理ツール。"""

import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)

from src.context import AppContext
from src.models.dashboard import TaskStatus
from src.models.message import MessagePriority, MessageType
from src.tools.helpers import (
    check_role_permission,
    check_tool_permission,
    ensure_dashboard_manager,
    ensure_ipc_manager,
    ensure_memory_manager,
    ensure_metrics_manager,
    find_agents_by_role,
    sync_agents_from_file,
)


def register_tools(mcp: FastMCP) -> None:
    """ダッシュボード/タスク管理ツールを登録する。"""

    @mcp.tool()
    async def create_task(
        title: str,
        description: str = "",
        assigned_agent_id: str | None = None,
        branch: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """新しいタスクを作成する。

        ※ Owner と Admin のみ使用可能。

        Args:
            title: タスクタイトル
            description: タスク説明
            assigned_agent_id: 割り当て先エージェントID（オプション）
            branch: 作業ブランチ（オプション）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            作成結果（success, task, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "create_task", caller_agent_id)
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        task = dashboard.create_task(
            title=title,
            description=description,
            assigned_agent_id=assigned_agent_id,
            branch=branch,
        )

        return {
            "success": True,
            "task": task.model_dump(mode="json"),
            "message": f"タスクを作成しました: {task.id}",
        }

    @mcp.tool()
    async def update_task_status(
        task_id: str,
        status: str,
        progress: int | None = None,
        error_message: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスクのステータスを更新する。

        ※ Admin のみ使用可能。Worker は report_task_completion を使用してください。

        Args:
            task_id: タスクID
            status: 新しいステータス（pending/in_progress/completed/failed/blocked）
            progress: 進捗率（0-100）
            error_message: エラーメッセージ（failedの場合）
            caller_agent_id: 呼び出し元エージェントID（ロールチェック用）

        Returns:
            更新結果（success, task_id, status, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "update_task_status", caller_agent_id)
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        # ステータスの検証
        try:
            task_status = TaskStatus(status)
        except ValueError:
            valid_statuses = [s.value for s in TaskStatus]
            return {
                "success": False,
                "error": f"無効なステータスです: {status}（有効: {valid_statuses}）",
            }

        success, message = dashboard.update_task_status(
            task_id=task_id,
            status=task_status,
            progress=progress,
            error_message=error_message,
        )

        return {
            "success": success,
            "task_id": task_id,
            "status": status if success else None,
            "message": message,
        }

    @mcp.tool()
    async def assign_task_to_agent(
        task_id: str,
        agent_id: str,
        branch: str | None = None,
        worktree_path: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスクをエージェントに割り当てる。

        ※ Admin のみ使用可能。

        Args:
            task_id: タスクID
            agent_id: エージェントID
            branch: 作業ブランチ（オプション）
            worktree_path: worktreeパス（オプション）
            caller_agent_id: 呼び出し元エージェントID（ロールチェック用）

        Returns:
            割り当て結果（success, task_id, agent_id, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "assign_task_to_agent", caller_agent_id)
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        # ファイルからエージェント情報を同期
        sync_agents_from_file(app_ctx)

        # エージェントの存在確認
        if agent_id not in app_ctx.agents:
            return {
                "success": False,
                "error": f"エージェント {agent_id} が見つかりません",
            }

        success, message = dashboard.assign_task(
            task_id=task_id,
            agent_id=agent_id,
            branch=branch,
            worktree_path=worktree_path,
        )

        return {
            "success": success,
            "task_id": task_id,
            "agent_id": agent_id if success else None,
            "message": message,
        }

    @mcp.tool()
    async def list_tasks(
        status: str | None = None,
        agent_id: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスク一覧を取得する。

        Args:
            status: フィルターするステータス（オプション）
            agent_id: フィルターするエージェントID（オプション）
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            タスク一覧（success, tasks, count または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "list_tasks", caller_agent_id)
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        # ステータスの検証
        task_status = None
        if status:
            try:
                task_status = TaskStatus(status)
            except ValueError:
                valid_statuses = [s.value for s in TaskStatus]
                return {
                    "success": False,
                    "error": f"無効なステータスです: {status}（有効: {valid_statuses}）",
                }

        tasks = dashboard.list_tasks(status=task_status, agent_id=agent_id)

        return {
            "success": True,
            "tasks": [t.model_dump(mode="json") for t in tasks],
            "count": len(tasks),
        }

    @mcp.tool()
    async def report_task_progress(
        task_id: str,
        progress: int | None = None,
        message: str | None = None,
        checklist: list[dict] | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """Worker がタスクの進捗を報告する。

        Worker は 10% ごとに進捗を報告することで、Admin と Owner が
        リアルタイムで作業状況を把握できます。

        チェックリストを使用する場合、進捗率は自動計算されます。

        ※ Worker のみ使用可能。

        Args:
            task_id: タスクID
            progress: 進捗率（0-100、10% 単位で報告推奨。checklist使用時は自動計算）
            message: 進捗メッセージ（現在の作業内容など、ログに追加されます）
            checklist: チェックリスト [{"text": "項目名", "completed": true/false}, ...]
            caller_agent_id: 呼び出し元エージェントID（Worker のID）

        Returns:
            報告結果（success, task_id, progress, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "report_task_progress", caller_agent_id)
        if role_error:
            return role_error

        # progress の検証（checklist がある場合は自動計算されるためスキップ可）
        if progress is not None and not (0 <= progress <= 100):
            return {
                "success": False,
                "error": f"無効な進捗率です: {progress}（有効: 0-100）",
            }

        dashboard = ensure_dashboard_manager(app_ctx)

        # チェックリストがある場合は update_task_checklist を使用
        if checklist is not None or message is not None:
            try:
                success, update_msg = dashboard.update_task_checklist(
                    task_id=task_id,
                    checklist=checklist,
                    log_message=message,
                )
                if not success:
                    logger.warning(f"チェックリスト/ログ更新に失敗: {update_msg}")
            except Exception as e:
                logger.warning(f"チェックリスト/ログ更新に失敗: {e}")

        # progress が明示的に指定された場合はステータスも更新
        if progress is not None:
            try:
                success, update_msg = dashboard.update_task_status(
                    task_id=task_id,
                    status=TaskStatus.IN_PROGRESS,
                    progress=progress,
                )
                if not success:
                    logger.warning(f"Dashboard の進捗更新に失敗: {update_msg}")
            except Exception as e:
                logger.warning(f"Dashboard の進捗更新に失敗: {e}")

        # 最新のタスク情報を取得
        task = dashboard.get_task(task_id)
        actual_progress = task.progress if task else (progress or 0)

        # Admin にも進捗を通知（IPC メッセージ）
        admin_notified = False
        try:
            admin_ids = find_agents_by_role(app_ctx, "admin")
            if admin_ids:
                ipc = ensure_ipc_manager(app_ctx)
                ipc.send_message(
                    sender_id=caller_agent_id,
                    receiver_id=admin_ids[0],
                    message_type=MessageType.TASK_PROGRESS,
                    subject=f"進捗報告: {task_id} ({actual_progress}%)",
                    content=message or f"タスク {task_id} の進捗: {actual_progress}%",
                    priority=MessagePriority.NORMAL,
                    metadata={
                        "task_id": task_id,
                        "progress": actual_progress,
                        "reporter": caller_agent_id,
                    },
                )
                admin_notified = True
        except Exception as e:
            logger.warning(f"Admin への進捗通知に失敗: {e}")

        # Markdown ダッシュボードも更新
        markdown_updated = False
        if app_ctx.session_id and app_ctx.project_root:
            try:
                dashboard = ensure_dashboard_manager(app_ctx)
                dashboard.save_markdown_dashboard(
                    app_ctx.project_root, app_ctx.session_id
                )
                markdown_updated = True
            except Exception as e:
                logger.warning(f"Markdown ダッシュボード更新に失敗: {e}")

        return {
            "success": True,
            "task_id": task_id,
            "progress": actual_progress,
            "admin_notified": admin_notified,
            "markdown_updated": markdown_updated,
            "message": f"進捗 {actual_progress}% を報告しました",
        }

    @mcp.tool()
    async def report_task_completion(
        task_id: str,
        status: str,
        message: str,
        summary: str | None = None,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """Worker が Admin にタスク完了を報告する。

        Worker はこのツールを使って Admin に作業結果を報告します。
        Admin が受け取って dashboard を更新します。
        自動的にメモリ保存とメトリクス更新も行います。

        ※ Worker のみ使用可能。

        Args:
            task_id: 完了したタスクのID
            status: 結果ステータス（"completed" | "failed"）
            message: 完了報告メッセージ（作業内容の要約）
            summary: タスク結果のサマリー（メモリに保存、省略時はmessageを使用）
            caller_agent_id: 呼び出し元エージェントID（Worker のID）

        Returns:
            報告結果（success, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "report_task_completion", caller_agent_id)
        if role_error:
            return role_error

        # Admin を検索
        admin_ids = find_agents_by_role(app_ctx, "admin")
        if not admin_ids:
            return {
                "success": False,
                "error": "Admin エージェントが見つかりません",
            }

        # 最初の Admin に報告（通常は1人のみ）
        admin_id = admin_ids[0]

        # status の検証
        if status not in ["completed", "failed"]:
            return {
                "success": False,
                "error": f"無効なステータスです: {status}（有効: completed, failed）",
            }

        # Dashboard を直接更新（Worker からでも更新可能にする）
        dashboard_updated = False
        try:
            dashboard = ensure_dashboard_manager(app_ctx)
            task_status = TaskStatus.COMPLETED if status == "completed" else TaskStatus.FAILED
            dashboard.update_task_status(
                task_id=task_id,
                status=task_status,
                error_message=message if status == "failed" else None,
            )
            dashboard_updated = True
            logger.info(f"タスク {task_id} のステータスを {status} に更新しました")
        except Exception as e:
            logger.warning(f"Dashboard の更新に失敗: {e}")

        # IPC マネージャーを取得（自動初期化）
        ipc = ensure_ipc_manager(app_ctx)

        # タスク完了報告を送信
        ipc.send_message(
            sender_id=caller_agent_id,
            receiver_id=admin_id,
            message_type=MessageType.TASK_COMPLETE if status == "completed" else MessageType.ERROR,
            subject=f"タスク報告: {task_id} ({status})",
            content=message,
            priority=MessagePriority.HIGH,
            metadata={
                "task_id": task_id,
                "status": status,
                "reporter": caller_agent_id,
            },
        )

        # 自動メモリ保存（タスク結果を記録）
        memory_saved = False
        try:
            memory_manager = ensure_memory_manager(app_ctx)
            memory_content = summary if summary else message
            memory_manager.save(
                key=f"task:{task_id}:result",
                content=f"[{status}] {memory_content}",
                tags=["task", status, task_id],
            )
            memory_saved = True
        except Exception:
            pass  # メモリ保存失敗は致命的ではない

        # 自動メトリクス更新
        metrics_updated = False
        try:
            metrics = ensure_metrics_manager(app_ctx)
            metrics.record_task_completion(
                task_id=task_id,
                agent_id=caller_agent_id,
                status=status,
            )
            metrics_updated = True
        except Exception:
            pass  # メトリクス更新失敗は致命的ではない

        # Markdown ダッシュボードも更新
        markdown_updated = False
        if app_ctx.session_id and app_ctx.project_root:
            try:
                dashboard = ensure_dashboard_manager(app_ctx)
                dashboard.save_markdown_dashboard(
                    app_ctx.project_root, app_ctx.session_id
                )
                markdown_updated = True
            except Exception as e:
                logger.warning(f"Markdown ダッシュボード更新に失敗: {e}")

        return {
            "success": True,
            "message": f"Admin ({admin_id}) に報告を送信しました",
            "task_id": task_id,
            "reported_status": status,
            "dashboard_updated": dashboard_updated,
            "markdown_updated": markdown_updated,
            "memory_saved": memory_saved,
            "metrics_updated": metrics_updated,
        }

    @mcp.tool()
    async def get_task(
        task_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスクの詳細を取得する。

        Args:
            task_id: タスクID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            タスク詳細（success, task または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_task", caller_agent_id)
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        task = dashboard.get_task(task_id)
        if not task:
            return {
                "success": False,
                "error": f"タスク {task_id} が見つかりません",
            }

        return {
            "success": True,
            "task": task.model_dump(mode="json"),
        }

    @mcp.tool()
    async def remove_task(
        task_id: str,
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """タスクを削除する。

        ※ Owner と Admin のみ使用可能。

        Args:
            task_id: タスクID
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            削除結果（success, task_id, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "remove_task", caller_agent_id)
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        success, message = dashboard.remove_task(task_id)

        return {
            "success": success,
            "task_id": task_id,
            "message": message,
        }

    @mcp.tool()
    async def get_dashboard(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """ダッシュボード全体を取得する。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            ダッシュボード情報（success, dashboard）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_dashboard", caller_agent_id)
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        # ファイルからエージェント情報を同期（他の MCP インスタンスで作成されたエージェントを取得）
        sync_agents_from_file(app_ctx)

        # エージェント情報を Dashboard に同期
        for agent in app_ctx.agents.values():
            dashboard.update_agent_summary(agent)

        dashboard_data = dashboard.get_dashboard()

        return {
            "success": True,
            "dashboard": dashboard_data.model_dump(mode="json"),
        }

    @mcp.tool()
    async def get_dashboard_summary(
        caller_agent_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """ダッシュボードのサマリーを取得する。

        Args:
            caller_agent_id: 呼び出し元エージェントID（必須）

        Returns:
            サマリー情報（success, summary）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context

        # ロールチェック
        role_error = check_tool_permission(app_ctx, "get_dashboard_summary", caller_agent_id)
        if role_error:
            return role_error

        dashboard = ensure_dashboard_manager(app_ctx)

        # ファイルからエージェント情報を同期（他の MCP インスタンスで作成されたエージェントを取得）
        sync_agents_from_file(app_ctx)

        # エージェント情報を Dashboard に同期
        for agent in app_ctx.agents.values():
            dashboard.update_agent_summary(agent)

        summary = dashboard.get_summary()

        return {
            "success": True,
            "summary": summary,
        }
