"""ダッシュボード管理モジュール。

複数プロセス対応: 読み取り専用操作には mtime ベースの短命キャッシュを使用し、
書き込み操作は毎回ファイルから読み書きする。
YAML Front Matter 付き Markdown で統一管理。
"""

import asyncio
import fcntl
import logging
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.managers.dashboard_cost import DashboardCostMixin
from src.managers.dashboard_reader_mixin import DashboardReaderMixin
from src.managers.dashboard_rendering_mixin import DashboardRenderingMixin
from src.managers.dashboard_writer_mixin import DashboardWriterMixin
from src.models.agent import AgentRole, AgentStatus
from src.models.dashboard import Dashboard, TaskStatus, normalize_task_id
from src.models.message import Message, MessageType

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.context import AppContext

logger = logging.getLogger(__name__)


class DashboardManager(
    DashboardReaderMixin,
    DashboardWriterMixin,
    DashboardRenderingMixin,
    DashboardCostMixin,
):
    """ダッシュボードを管理するクラス。"""

    def __init__(
        self,
        workspace_id: str,
        workspace_path: str,
        dashboard_dir: str,
        settings: "Settings | None" = None,
    ) -> None:
        from src.config.settings import load_settings_for_project

        self.workspace_id = workspace_id
        self.workspace_path = workspace_path
        self.dashboard_dir = Path(dashboard_dir)
        self.settings = settings or load_settings_for_project(workspace_path)
        self._dashboard_lock_timeout_seconds = 1.0
        # 読み取り専用操作用の mtime_ns ベースキャッシュ
        self._read_cache: Dashboard | None = None
        self._read_cache_mtime: int = 0
        # DashboardSyncMixin の IPC 同期キャッシュ属性を初期化
        self._ipc_sync_cache_ipc_dir: str | None = None
        self._ipc_sync_cache_messages: list | None = None
        self._ipc_sync_cache_cursors: dict[str, str] | None = None
        self._ipc_sync_cache_mtime: int = 0

    @staticmethod
    def _is_event_loop_running() -> bool:
        """現在スレッドで event loop が実行中か判定する。"""
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    def initialize(self) -> None:
        """ダッシュボード環境を初期化する。"""
        self.dashboard_dir.mkdir(parents=True, exist_ok=True)
        dashboard_path = self._get_dashboard_path()
        if not dashboard_path.exists():
            dashboard = Dashboard(
                workspace_id=self.workspace_id,
                workspace_path=self.workspace_path,
                session_started_at=datetime.now(),
            )
            self._write_dashboard(dashboard)
        logger.info(f"ダッシュボード環境を初期化しました: {self.dashboard_dir}")

    def cleanup(self) -> None:
        """ダッシュボード環境をクリーンアップする。

        dashboard.md / messages.md はセッション履歴として永続保持するため削除しない。
        """
        logger.info("ダッシュボード環境をクリーンアップしました（dashboard/messages は保持）")

    def _get_dashboard_path(self) -> Path:
        return self.dashboard_dir / "dashboard.md"

    def _get_messages_path(self) -> Path:
        return self.dashboard_dir / "messages.md"

    def _get_dashboard_lock_path(self) -> Path:
        return self.dashboard_dir / "dashboard.lock"

    def _read_dashboard_snapshot(self) -> Dashboard:
        """読み取り専用の Dashboard スナップショットを取得する。

        writer は atomic replace で更新するため、read-only path では
        更新系ロックを取らずに最新ファイルを参照する。
        """
        dashboard_path = self._get_dashboard_path()
        try:
            current_mtime_ns = dashboard_path.stat().st_mtime_ns
        except OSError:
            current_mtime_ns = 0

        if (
            self._read_cache is not None
            and current_mtime_ns == self._read_cache_mtime
            and current_mtime_ns != 0
        ):
            return self._read_cache

        dashboard = self._read_dashboard_unlocked()

        try:
            refreshed_mtime_ns = dashboard_path.stat().st_mtime_ns
        except OSError:
            refreshed_mtime_ns = current_mtime_ns

        self._read_cache = dashboard
        self._read_cache_mtime = refreshed_mtime_ns
        return dashboard

    @contextmanager
    def _dashboard_file_lock(self) -> None:
        """Dashboard 読み書き用の排他ロックを取得する。"""
        lock_path = self._get_dashboard_lock_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        started_at = time.monotonic()
        running_in_event_loop = self._is_event_loop_running()

        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as e:
                    if running_in_event_loop:
                        msg = f"dashboard lock busy in event loop context: {lock_path}"
                        raise TimeoutError(msg) from e
                    elapsed = time.monotonic() - started_at
                    if elapsed >= self._dashboard_lock_timeout_seconds:
                        msg = (
                            "dashboard lock timeout "
                            f"({self._dashboard_lock_timeout_seconds:.2f}s): {lock_path}"
                        )
                        raise TimeoutError(msg) from e
                    time.sleep(0.01)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @asynccontextmanager
    async def _dashboard_file_lock_async(self):
        """Dashboard 読み書き用の排他ロックを非同期で取得する。

        fcntl.flock のビジーウェイトを asyncio.to_thread() でスレッドに委譲し、
        イベントループをブロックしない。
        """
        lock_path = self._get_dashboard_lock_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        timeout = self._dashboard_lock_timeout_seconds

        def _acquire_lock(fileno: int) -> None:
            """ブロッキングなロック取得をワーカースレッドで実行する。"""
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    fcntl.flock(fileno, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return
                except BlockingIOError:
                    time.sleep(0.01)
            # タイムアウト — ブロッキングフォールバックは使わず例外を送出
            raise asyncio.TimeoutError(
                f"Dashboard ファイルロックの取得がタイムアウトしました ({timeout}秒)"
            )

        lock_file = None
        try:
            lock_file = open(lock_path, "a+", encoding="utf-8")  # noqa: SIM115
            await asyncio.to_thread(_acquire_lock, lock_file.fileno())
            yield
        finally:
            if lock_file is not None:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
                lock_file.close()

    @staticmethod
    def _persist_agent_state(app_ctx: "AppContext", agent: Any) -> bool:
        """タスク反映に伴う agent 状態変更を永続化する。

        agent_persistence.save_agent_to_file() に委譲する。
        """
        from src.managers.agent_persistence import save_agent_to_file

        return save_agent_to_file(app_ctx, agent)

    def _update_reporter_agent(
        self,
        app_ctx: "AppContext",
        reporter: str | None,
        task_id: str,
        *,
        assign_task: bool,
    ) -> None:
        """タスクメッセージの reporter エージェント状態を更新・永続化する。

        Args:
            app_ctx: アプリケーションコンテキスト
            reporter: reporter エージェント ID
            task_id: 対象タスク ID
            assign_task: True=タスクをアサイン（BUSY）、False=タスクを解除（IDLE）
        """
        if not reporter or reporter not in app_ctx.agents:
            return
        agent = app_ctx.agents[reporter]
        if assign_task:
            agent.current_task = task_id
            if str(agent.role) == AgentRole.WORKER.value:
                agent.status = AgentStatus.BUSY
        else:
            if agent.current_task == task_id:
                agent.current_task = None
            if str(agent.role) == AgentRole.WORKER.value:
                agent.status = AgentStatus.IDLE
        self._persist_agent_state(app_ctx, agent)

    def apply_task_messages(
        self,
        app_ctx: "AppContext",
        messages: list[Message],
    ) -> tuple[bool, int, list[str], list[str], list[str]]:
        """タスク関連 IPC メッセージを Dashboard へ反映する。

        全メッセージの status/checklist 適用を単一の run_dashboard_transaction 内で行い、
        ファイルロック・読み込み・書き込みをそれぞれ1回に集約する。
        save_markdown_dashboard は別途末尾で1回呼ぶ。

        Args:
            app_ctx: アプリケーションコンテキスト
            messages: read_messages で取得したメッセージ

        Returns:
            (
                dashboard_updated,
                applied_count,
                skipped_reasons,
                ack_message_ids,
                deferred_message_ids,
            )
        """
        task_message_types = {
            MessageType.TASK_PROGRESS,
            MessageType.TASK_COMPLETE,
            MessageType.TASK_FAILED,
        }
        task_messages = [m for m in messages if m.message_type in task_message_types]
        if not task_messages:
            return False, 0, [], [], []

        # トランザクション外で task_map を構築（_read_dashboard_snapshot はキャッシュ活用）
        task_map: dict[str, str] = {}
        for task in self.list_tasks():
            normalized = normalize_task_id(task.id)
            if normalized:
                task_map[normalized] = task.id

        # トランザクション外で収集する reporter 情報（ファイルI/O不要）
        # (reporter, task_id, assign_task) のリスト：適用成功後に処理
        reporter_updates: list[tuple[str | None, str, bool]] = []

        applied = 0
        skipped_reasons: list[str] = []
        ack_message_ids: list[str] = []
        deferred_message_ids: list[str] = []

        # --- task_id 解決フェーズ（トランザクション外・ファイルアクセスなし）---
        # メッセージを (task_id, msg) のペアに変換し、解決できないものは先に defer する
        resolved: list[tuple[str, Message]] = []
        for msg in task_messages:
            raw_task_id = msg.metadata.get("task_id")
            normalized_task_id = msg.metadata.get("normalized_task_id") or normalize_task_id(
                raw_task_id
            )
            if not normalized_task_id:
                skipped_reasons.append("missing_task_id")
                deferred_message_ids.append(msg.id)
                continue

            task_id = task_map.get(normalized_task_id)
            if not task_id:
                skipped_reasons.append(f"task_not_found:{normalized_task_id}")
                deferred_message_ids.append(msg.id)
                continue

            resolved.append((task_id, msg))

        # --- 単一トランザクションで全メッセージを適用 ---
        def _apply_all(dashboard: Dashboard) -> None:
            nonlocal applied
            for task_id, msg in resolved:
                try:
                    if msg.message_type == MessageType.TASK_PROGRESS:
                        progress = msg.metadata.get("progress", 0)
                        checklist = msg.metadata.get("checklist")
                        message_text = msg.metadata.get("message")
                        reporter = msg.metadata.get("reporter")

                        status_ok, status_msg = self._apply_status_to_dashboard(
                            dashboard, task_id, TaskStatus.IN_PROGRESS, progress
                        )
                        if not status_ok:
                            skipped_reasons.append(
                                f"status_update_rejected:{task_id}:{status_msg}"
                            )
                            deferred_message_ids.append(msg.id)
                            continue

                        # QUAL-005: checklist 更新失敗はステータス更新済みなので
                        # warning を記録するが applied として扱う
                        if checklist:
                            checklist_ok, checklist_msg = self._apply_checklist_to_dashboard(
                                dashboard, task_id, checklist, log_message=message_text
                            )
                            if not checklist_ok:
                                skipped_reasons.append(
                                    f"checklist_update_error:{task_id}:{checklist_msg}"
                                )

                        reporter_updates.append((reporter, task_id, True))

                    elif msg.message_type == MessageType.TASK_COMPLETE:
                        reporter = msg.metadata.get("reporter")
                        task = self._resolve_task(dashboard, task_id)
                        if task and task.status == TaskStatus.COMPLETED:
                            skipped_reasons.append(f"already_completed:{task_id}")
                            ack_message_ids.append(msg.id)
                            continue

                        status_ok, status_msg = self._apply_status_to_dashboard(
                            dashboard, task_id, TaskStatus.COMPLETED, progress=100
                        )
                        if not status_ok:
                            skipped_reasons.append(
                                f"status_update_rejected:{task_id}:{status_msg}"
                            )
                            deferred_message_ids.append(msg.id)
                            continue

                        reporter_updates.append((reporter, task_id, False))

                    elif msg.message_type == MessageType.TASK_FAILED:
                        reporter = msg.metadata.get("reporter")
                        task = self._resolve_task(dashboard, task_id)
                        if task and task.status == TaskStatus.FAILED:
                            skipped_reasons.append(f"already_failed:{task_id}")
                            ack_message_ids.append(msg.id)
                            continue

                        status_ok, status_msg = self._apply_status_to_dashboard(
                            dashboard, task_id, TaskStatus.FAILED
                        )
                        if not status_ok:
                            skipped_reasons.append(
                                f"status_update_rejected:{task_id}:{status_msg}"
                            )
                            deferred_message_ids.append(msg.id)
                            continue

                        reporter_updates.append((reporter, task_id, False))

                    applied += 1
                    ack_message_ids.append(msg.id)

                except (OSError, ValueError, KeyError, TypeError) as e:
                    logger.debug("タスク %s の Dashboard 更新をスキップ: %s", task_id, e)
                    skipped_reasons.append(f"update_error:{task_id}")
                    deferred_message_ids.append(msg.id)

        # 解決済みメッセージがある場合のみ書き込みトランザクションを実行する。
        # 読み込み/書き込みフェーズで例外が発生した場合は何も永続化されていないため、
        # 解決済みメッセージを全て defer し直す（旧実装の per-message defer 挙動を維持し、
        # 例外を呼び出し元へ伝播させない）。捕捉する例外型は旧実装の per-message
        # try/except と同じ (OSError, ValueError, KeyError, TypeError) に揃える。
        if resolved:
            try:
                self.run_dashboard_transaction(_apply_all)
            except (OSError, ValueError, KeyError, TypeError) as e:
                logger.debug("Dashboard トランザクションに失敗、全件 defer: %s", e)
                applied = 0
                reporter_updates.clear()
                for _task_id, failed_msg in resolved:
                    if failed_msg.id in ack_message_ids:
                        ack_message_ids.remove(failed_msg.id)
                    if failed_msg.id not in deferred_message_ids:
                        deferred_message_ids.append(failed_msg.id)
                skipped_reasons.append("transaction_write_failed")

        # reporter エージェント状態の永続化（ファイルI/O・トランザクション外）
        for reporter, task_id, assign_task in reporter_updates:
            self._update_reporter_agent(app_ctx, reporter, task_id, assign_task=assign_task)

        # task_messages が存在する場合は（全件 defer でも）旧実装どおり Markdown を同期する。
        try:
            if app_ctx.session_id and app_ctx.project_root:
                self.save_markdown_dashboard(Path(app_ctx.project_root), app_ctx.session_id)
        except OSError as e:
            logger.debug("Markdown ダッシュボード更新をスキップ: %s", e)

        return True, applied, skipped_reasons, ack_message_ids, deferred_message_ids
