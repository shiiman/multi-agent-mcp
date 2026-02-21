"""Dashboard のタスク更新ロジック mixin。"""

import logging
import re
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import ClassVar, TypeVar

from src.config.settings import get_mcp_dir
from src.models.dashboard import (
    ChecklistItem,
    Dashboard,
    TaskInfo,
    TaskLog,
    TaskStatus,
    normalize_task_id,
)

logger = logging.getLogger(__name__)

_DashboardMutationResult = TypeVar("_DashboardMutationResult")


class DashboardTasksMixin:
    """Dashboard のタスク CRUD・ファイル配布機能を提供する mixin。"""

    _TERMINAL_TASK_STATUSES: ClassVar[set[TaskStatus]] = {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }
    _ALLOWED_TASK_TRANSITIONS: ClassVar[dict[TaskStatus, set[TaskStatus]]] = {
        TaskStatus.PENDING: {
            TaskStatus.PENDING,
            TaskStatus.IN_PROGRESS,
            TaskStatus.BLOCKED,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.IN_PROGRESS: {
            TaskStatus.IN_PROGRESS,
            TaskStatus.BLOCKED,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.BLOCKED: {
            TaskStatus.BLOCKED,
            TaskStatus.IN_PROGRESS,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.COMPLETED: {TaskStatus.COMPLETED},
        TaskStatus.FAILED: {TaskStatus.FAILED},
        TaskStatus.CANCELLED: {TaskStatus.CANCELLED},
    }

    def get_dashboard(self) -> Dashboard:
        """現在のダッシュボードを取得する。

        Returns:
            Dashboard オブジェクト
        """
        return self._read_dashboard()

    def _mutate_dashboard(
        self,
        mutator: Callable[[Dashboard], _DashboardMutationResult],
        *,
        write_back: bool = True,
    ) -> _DashboardMutationResult:
        """Dashboard 変更をロック付きトランザクションで実行する。"""
        return self.run_dashboard_transaction(mutator, write_back=write_back)

    def _resolve_task(self, dashboard: Dashboard, task_id: str) -> TaskInfo | None:
        """task_id を exact / normalized / unique prefix で解決する。"""
        task = dashboard.get_task(task_id)
        if task:
            return task

        normalized_target = normalize_task_id(task_id)
        if not normalized_target:
            return None

        normalized_matches = [
            t for t in dashboard.tasks if normalize_task_id(t.id) == normalized_target
        ]
        if len(normalized_matches) == 1:
            return normalized_matches[0]

        prefix_matches = [
            t for t in dashboard.tasks if normalize_task_id(t.id).startswith(normalized_target)
        ]
        if len(prefix_matches) == 1:
            return prefix_matches[0]
        return None

    @staticmethod
    def _sanitize_task_file_part(value: str) -> str:
        """タスクファイル名向けに安全な文字列へ変換する。"""
        cleaned = re.sub(r"[^0-9A-Za-z_-]+", "_", value or "").strip("_").lower()
        return cleaned or "unknown"

    @staticmethod
    def _release_agent_from_task(dashboard: Dashboard, task_id: str) -> None:
        """指定タスクに紐づくエージェントの current_task_id をクリアし idle にする。"""
        for agent_summary in dashboard.agents:
            if agent_summary.current_task_id == task_id:
                agent_summary.current_task_id = None
                if agent_summary.role == "worker":
                    agent_summary.status = "idle"

    # ------------------------------------------------------------------
    # タスク管理メソッド
    # ------------------------------------------------------------------

    def create_task(
        self,
        title: str,
        description: str = "",
        assigned_agent_id: str | None = None,
        branch: str | None = None,
        worktree_path: str | None = None,
        metadata: dict | None = None,
    ) -> TaskInfo:
        """新しいタスクを作成する。

        Args:
            title: タスクタイトル
            description: タスク説明（metadata に保持）
            assigned_agent_id: 割り当て先エージェントID
            branch: 作業ブランチ
            worktree_path: worktreeパス
            metadata: 追加メタデータ

        Returns:
            作成されたTaskInfo
        """

        def _create(dashboard: Dashboard) -> TaskInfo:
            task_metadata = metadata.copy() if metadata else {}
            if description:
                task_metadata["requested_description"] = description

            task = TaskInfo(
                id=str(uuid.uuid4()),
                title=title,
                description="",
                task_file_path=None,
                status=TaskStatus.PENDING,
                assigned_agent_id=assigned_agent_id,
                branch=branch,
                worktree_path=worktree_path,
                metadata=task_metadata,
                created_at=datetime.now(),
            )

            dashboard.tasks.append(task)
            dashboard.calculate_stats()
            return task

        task = self._mutate_dashboard(_create)

        logger.info(f"タスクを作成しました: {task.id} - {title}")
        return task

    def _validate_task_transition(
        self, old_status: TaskStatus, new_status: TaskStatus
    ) -> tuple[bool, str | None]:
        """タスク状態遷移が許可されるか検証する。"""
        allowed_statuses = self._ALLOWED_TASK_TRANSITIONS.get(old_status, {old_status})
        if new_status in allowed_statuses:
            return True, None

        if old_status in self._TERMINAL_TASK_STATUSES:
            return (
                False,
                (
                    f"終端状態 ({old_status.value}) から {new_status.value} へは遷移できません。"
                    "再開には reopen_task を使用してください。"
                ),
            )
        return (
            False,
            f"状態遷移が許可されていません: {old_status.value} -> {new_status.value}",
        )

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        progress: int | None = None,
        error_message: str | None = None,
    ) -> tuple[bool, str]:
        """タスクのステータスを更新する。

        Args:
            task_id: タスクID
            status: 新しいステータス
            progress: 進捗率
            error_message: エラーメッセージ

        Returns:
            (成功フラグ, メッセージ) のタプル
        """

        def _update(dashboard: Dashboard) -> tuple[bool, str]:
            task = self._resolve_task(dashboard, task_id)
            if not task:
                return False, f"タスク {task_id} が見つかりません"

            old_status = task.status
            is_valid, error = self._validate_task_transition(old_status, status)
            if not is_valid:
                return False, error or "状態遷移が許可されていません"

            now = datetime.now()
            task.status = status

            if progress is not None:
                task.progress = progress

            if error_message is not None:
                task.error_message = error_message
            elif status != TaskStatus.FAILED:
                task.error_message = None

            if status == TaskStatus.IN_PROGRESS:
                if (
                    old_status in (TaskStatus.PENDING, TaskStatus.BLOCKED)
                    and task.started_at is None
                ):
                    task.started_at = now
                if dashboard.session_started_at is None:
                    dashboard.session_started_at = task.started_at or now
                task.completed_at = None
                task.metadata["last_in_progress_update_at"] = now.isoformat()
                if task.assigned_agent_id:
                    for agent_summary in dashboard.agents:
                        if agent_summary.agent_id == task.assigned_agent_id:
                            agent_summary.current_task_id = task.id
                            if agent_summary.role == "worker":
                                agent_summary.status = "busy"
                            break
            elif status in self._TERMINAL_TASK_STATUSES:
                if task.started_at is None:
                    # pending -> completed/failed の直遷移でも開始時刻を欠損させない。
                    task.started_at = now
                if dashboard.session_started_at is None:
                    dashboard.session_started_at = task.started_at or now
                task.completed_at = now
                if status == TaskStatus.COMPLETED:
                    task.progress = 100
                self._release_agent_from_task(dashboard, task.id)
            elif status == TaskStatus.PENDING:
                task.completed_at = None

            has_active_tasks = any(
                t.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED)
                for t in dashboard.tasks
            )
            if dashboard.tasks and not has_active_tasks:
                dashboard.session_finished_at = now
            else:
                dashboard.session_finished_at = None

            dashboard.calculate_stats()
            logger.info(f"タスク {task.id} のステータスを更新: {old_status} -> {status}")
            return True, f"ステータスを更新しました: {status.value}"

        return self._mutate_dashboard(_update)

    def reopen_task(self, task_id: str, reset_progress: bool = False) -> tuple[bool, str]:
        """終端状態タスクを PENDING に戻す。

        Args:
            task_id: タスクID
            reset_progress: True の場合は進捗率を 0 に戻す

        Returns:
            (成功フラグ, メッセージ) のタプル
        """

        def _reopen(dashboard: Dashboard) -> tuple[bool, str]:
            task = self._resolve_task(dashboard, task_id)
            if not task:
                return False, f"タスク {task_id} が見つかりません"
            if task.status not in self._TERMINAL_TASK_STATUSES:
                return (
                    False,
                    f"タスク {task.id} は終端状態ではありません（現在: {task.status.value}）",
                )

            now = datetime.now()
            old_status = task.status
            task.status = TaskStatus.PENDING
            task.started_at = None
            task.completed_at = None
            task.error_message = None
            if reset_progress:
                task.progress = 0
            task.metadata["reopened_at"] = now.isoformat()
            dashboard.session_finished_at = None

            self._release_agent_from_task(dashboard, task.id)

            dashboard.calculate_stats()
            logger.info(f"タスク {task.id} を再開しました: {old_status} -> pending")
            return True, "タスクを再開しました: pending"

        return self._mutate_dashboard(_reopen)

    def assign_task(
        self,
        task_id: str,
        agent_id: str,
        branch: str | None = None,
        worktree_path: str | None = None,
    ) -> tuple[bool, str]:
        """タスクをエージェントに割り当てる。

        Args:
            task_id: タスクID
            agent_id: エージェントID
            branch: 作業ブランチ
            worktree_path: worktreeパス

        Returns:
            (成功フラグ, メッセージ) のタプル
        """

        def _assign(dashboard: Dashboard) -> tuple[bool, str]:
            task = self._resolve_task(dashboard, task_id)
            if not task:
                return False, f"タスク {task_id} が見つかりません"

            previous_agent_id = task.assigned_agent_id
            task.assigned_agent_id = agent_id
            if branch:
                task.branch = branch
            if worktree_path:
                task.worktree_path = worktree_path

            if previous_agent_id and previous_agent_id != agent_id:
                for agent_summary in dashboard.agents:
                    if (
                        agent_summary.agent_id == previous_agent_id
                        and agent_summary.current_task_id == task.id
                    ):
                        agent_summary.current_task_id = None
                        if agent_summary.role == "worker":
                            agent_summary.status = "idle"
                        break

            # エージェントの current_task_id も更新
            for agent_summary in dashboard.agents:
                if agent_summary.agent_id == agent_id:
                    if task.status not in self._TERMINAL_TASK_STATUSES:
                        agent_summary.current_task_id = task.id
                        if agent_summary.role == "worker":
                            agent_summary.status = "busy"
                    break

            dashboard.calculate_stats()
            logger.info(f"タスク {task.id} をエージェント {agent_id} に割り当てました")
            return True, f"タスクを割り当てました: {agent_id}"

        return self._mutate_dashboard(_assign)

    def remove_task(self, task_id: str) -> tuple[bool, str]:
        """タスクを削除する。

        Args:
            task_id: タスクID

        Returns:
            (成功フラグ, メッセージ) のタプル
        """

        def _remove(dashboard: Dashboard) -> tuple[bool, str]:
            task = self._resolve_task(dashboard, task_id)
            if not task:
                return False, f"タスク {task_id} が見つかりません"

            dashboard.tasks = [t for t in dashboard.tasks if t.id != task.id]
            self._release_agent_from_task(dashboard, task.id)
            dashboard.calculate_stats()
            logger.info(f"タスク {task.id} を削除しました")
            return True, "タスクを削除しました"

        return self._mutate_dashboard(_remove)

    def get_task(self, task_id: str) -> TaskInfo | None:
        """タスクを取得する。

        Args:
            task_id: タスクID

        Returns:
            TaskInfo、見つからない場合はNone
        """
        dashboard = self._read_dashboard()
        return self._resolve_task(dashboard, task_id)

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        agent_id: str | None = None,
    ) -> list[TaskInfo]:
        """タスク一覧を取得する。

        Args:
            status: フィルターするステータス
            agent_id: フィルターするエージェントID

        Returns:
            TaskInfoのリスト
        """
        dashboard = self._read_dashboard()
        tasks = dashboard.tasks

        if status is not None:
            tasks = [t for t in tasks if t.status == status]

        if agent_id is not None:
            tasks = [t for t in tasks if t.assigned_agent_id == agent_id]

        return tasks

    def update_task_checklist(
        self,
        task_id: str,
        checklist: list[dict[str, bool | str]] | None = None,
        log_message: str | None = None,
    ) -> tuple[bool, str]:
        """タスクのチェックリストとログを更新する。

        Args:
            task_id: タスクID
            checklist: チェックリストアイテムのリスト
                [{"text": "...", "completed": True/False}, ...]
            log_message: 追加するログメッセージ

        Returns:
            (成功フラグ, メッセージ) のタプル
        """

        def _update_checklist(dashboard: Dashboard) -> tuple[bool, str]:
            task = self._resolve_task(dashboard, task_id)
            if not task:
                return False, f"タスク {task_id} が見つかりません"

            # チェックリストを更新
            if checklist is not None:
                task.checklist = [
                    ChecklistItem(text=item["text"], completed=item.get("completed", False))
                    for item in checklist
                ]
                # チェックリストから進捗を計算
                if task.checklist:
                    completed_count = sum(1 for item in task.checklist if item.completed)
                    task.progress = int((completed_count / len(task.checklist)) * 100)

            # ログを追加（最新5件を保持）
            if log_message:
                task.logs.append(TaskLog(message=log_message))
                task.logs = task.logs[-5:]  # 最新5件のみ保持

            dashboard.calculate_stats()
            logger.info(f"タスク {task.id} のチェックリスト/ログを更新しました")
            return True, "チェックリスト/ログを更新しました"

        return self._mutate_dashboard(_update_checklist)

    # ------------------------------------------------------------------
    # タスクファイル管理メソッド（ファイルベースのタスク配布）
    # ------------------------------------------------------------------

    def write_task_file(
        self,
        project_root: Path,
        session_id: str,
        task_id: str,
        agent_label: str,
        task_content: str,
    ) -> Path:
        """タスクファイルを作成する（Markdown形式）。"""
        safe_label = self._sanitize_task_file_part(agent_label)
        safe_task_id = self._sanitize_task_file_part(task_id)
        task_dir = project_root / get_mcp_dir() / session_id / "tasks"
        task_dir.mkdir(parents=True, exist_ok=True)
        task_file = task_dir / f"{safe_label}_{safe_task_id}.md"
        task_file.write_text(task_content, encoding="utf-8")
        try:
            relative_path = str(task_file.relative_to(project_root))
        except ValueError:
            relative_path = str(task_file)

        def _update_task_path(dashboard: Dashboard) -> None:
            task = self._resolve_task(dashboard, task_id)
            if task:
                task.task_file_path = relative_path
                task.description = relative_path
                dashboard.calculate_stats()

        self._mutate_dashboard(_update_task_path)
        logger.info(f"タスクファイルを作成しました: {task_file}")
        return task_file

    def get_task_file_path(
        self, project_root: Path, session_id: str, task_id: str, agent_label: str
    ) -> Path:
        """タスクファイルパスを取得する。"""
        safe_label = self._sanitize_task_file_part(agent_label)
        safe_task_id = self._sanitize_task_file_part(task_id)
        tasks_dir = project_root / get_mcp_dir() / session_id / "tasks"
        return tasks_dir / f"{safe_label}_{safe_task_id}.md"

    def read_task_file(
        self, project_root: Path, session_id: str, task_id: str, agent_label: str
    ) -> str | None:
        """タスクファイルを読み取る。"""
        task_file = self.get_task_file_path(project_root, session_id, task_id, agent_label)
        if task_file.exists():
            return task_file.read_text(encoding="utf-8")
        return None

    def clear_task_file(
        self, project_root: Path, session_id: str, task_id: str, agent_label: str
    ) -> bool:
        """タスクファイルを削除する。"""
        task_file = self.get_task_file_path(project_root, session_id, task_id, agent_label)
        if task_file.exists():
            task_file.unlink()
            logger.info(f"タスクファイルを削除しました: {task_file}")
            return True
        return False

    # ------------------------------------------------------------------
    # セッション・プロセス管理
    # ------------------------------------------------------------------

    def increment_process_crash_count(self) -> int:
        """プロセスクラッシュ回数を1件加算する。"""

        def _increment(dashboard: Dashboard) -> int:
            dashboard.process_crash_count += 1
            dashboard.calculate_stats()
            return dashboard.process_crash_count

        return self._mutate_dashboard(_increment)

    def increment_process_recovery_count(self) -> int:
        """プロセス復旧回数を1件加算する。"""

        def _increment(dashboard: Dashboard) -> int:
            dashboard.process_recovery_count += 1
            dashboard.calculate_stats()
            return dashboard.process_recovery_count

        return self._mutate_dashboard(_increment)

    def mark_session_finished(self) -> None:
        """セッション終了時刻を現在時刻で記録する。"""

        def _mark(dashboard: Dashboard) -> None:
            dashboard.session_finished_at = datetime.now()
            dashboard.calculate_stats()

        self._mutate_dashboard(_mark)
