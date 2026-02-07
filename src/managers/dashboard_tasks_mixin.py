"""Dashboard のタスク/エージェント更新ロジック mixin。"""

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.config.settings import get_mcp_dir
from src.models.agent import Agent
from src.models.dashboard import (
    AgentSummary,
    ChecklistItem,
    Dashboard,
    MessageSummary,
    TaskInfo,
    TaskLog,
    TaskStatus,
)

if TYPE_CHECKING:
    from src.managers.agent_manager import AgentManager
    from src.managers.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


class DashboardTasksMixin:
    """Dashboard のタスク・集計・ファイル配布機能を提供する mixin。"""

    def get_dashboard(self) -> Dashboard:
        """現在のダッシュボードを取得する。

        Returns:
            Dashboard オブジェクト
        """
        return self._read_dashboard()

    @staticmethod
    def _normalize_task_id(task_id: str | None) -> str:
        """task_id を比較用に正規化する。"""
        if not task_id:
            return ""
        normalized = task_id.strip().lower()
        for prefix in ("task:", "task_", "task-"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
                break
        return normalized

    def _resolve_task(self, dashboard: Dashboard, task_id: str) -> TaskInfo | None:
        """task_id を exact / normalized / unique prefix で解決する。"""
        task = dashboard.get_task(task_id)
        if task:
            return task

        normalized_target = self._normalize_task_id(task_id)
        if not normalized_target:
            return None

        normalized_matches = [
            t for t in dashboard.tasks if self._normalize_task_id(t.id) == normalized_target
        ]
        if len(normalized_matches) == 1:
            return normalized_matches[0]

        prefix_matches = [
            t for t in dashboard.tasks if self._normalize_task_id(t.id).startswith(normalized_target)
        ]
        if len(prefix_matches) == 1:
            return prefix_matches[0]
        return None

    @staticmethod
    def _sanitize_task_file_part(value: str) -> str:
        """タスクファイル名向けに安全な文字列へ変換する。"""
        cleaned = re.sub(r"[^0-9A-Za-z_-]+", "_", value or "").strip("_").lower()
        return cleaned or "unknown"

    # タスク管理メソッド

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
        dashboard = self._read_dashboard()
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
        self._write_dashboard(dashboard)

        logger.info(f"タスクを作成しました: {task.id} - {title}")
        return task

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
        dashboard = self._read_dashboard()

        task = self._resolve_task(dashboard, task_id)
        if not task:
            return False, f"タスク {task_id} が見つかりません"

        old_status = task.status
        task.status = status

        if progress is not None:
            task.progress = progress

        if error_message is not None:
            task.error_message = error_message

        # ステータス変更時の日時記録
        now = datetime.now()
        if status == TaskStatus.IN_PROGRESS and old_status == TaskStatus.PENDING:
            task.started_at = now
            if task.assigned_agent_id:
                for agent_summary in dashboard.agents:
                    if agent_summary.agent_id == task.assigned_agent_id:
                        agent_summary.current_task_id = task.id
                        agent_summary.status = "busy"
                        break
        if status == TaskStatus.IN_PROGRESS:
            task.metadata["last_in_progress_update_at"] = now.isoformat()
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            task.completed_at = now
            if status == TaskStatus.COMPLETED:
                task.progress = 100
            for agent_summary in dashboard.agents:
                if agent_summary.current_task_id == task.id:
                    agent_summary.current_task_id = None
                    if agent_summary.role == "worker":
                        agent_summary.status = "idle"

        dashboard.calculate_stats()
        self._write_dashboard(dashboard)

        logger.info(f"タスク {task_id} のステータスを更新: {old_status} -> {status}")
        return True, f"ステータスを更新しました: {status.value}"

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
        dashboard = self._read_dashboard()

        task = self._resolve_task(dashboard, task_id)
        if not task:
            return False, f"タスク {task_id} が見つかりません"

        task.assigned_agent_id = agent_id
        if branch:
            task.branch = branch
        if worktree_path:
            task.worktree_path = worktree_path

        # エージェントの current_task_id も更新
        for agent_summary in dashboard.agents:
            if agent_summary.agent_id == agent_id:
                agent_summary.current_task_id = task.id
                if agent_summary.role == "worker":
                    agent_summary.status = "busy"
                break

        self._write_dashboard(dashboard)

        logger.info(f"タスク {task_id} をエージェント {agent_id} に割り当てました")
        return True, f"タスクを割り当てました: {agent_id}"

    def remove_task(self, task_id: str) -> tuple[bool, str]:
        """タスクを削除する。

        Args:
            task_id: タスクID

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        dashboard = self._read_dashboard()

        task = self._resolve_task(dashboard, task_id)
        if not task:
            return False, f"タスク {task_id} が見つかりません"

        dashboard.tasks = [t for t in dashboard.tasks if t.id != task_id]
        dashboard.calculate_stats()
        self._write_dashboard(dashboard)

        logger.info(f"タスク {task_id} を削除しました")
        return True, "タスクを削除しました"

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
        dashboard = self._read_dashboard()

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

        self._write_dashboard(dashboard)

        logger.info(f"タスク {task_id} のチェックリスト/ログを更新しました")
        return True, "チェックリスト/ログを更新しました"

    # エージェントサマリー管理メソッド

    def update_agent_summary(self, agent: Agent) -> None:
        """エージェントサマリーを更新する。

        Args:
            agent: Agentオブジェクト
        """
        dashboard = self._read_dashboard()

        # 既存のサマリーを検索
        existing = dashboard.get_agent(agent.id)

        summary = AgentSummary(
            agent_id=agent.id,
            name=self._compute_agent_name(agent),
            role=agent.role,  # use_enum_values=True のため既に文字列
            status=agent.status,  # use_enum_values=True のため既に文字列
            current_task_id=agent.current_task,
            worktree_path=agent.worktree_path,
            branch=None,  # 別途取得が必要
            last_activity=agent.last_activity,
        )

        if existing:
            # 既存のサマリーを更新
            idx = next(
                i
                for i, a in enumerate(dashboard.agents)
                if a.agent_id == agent.id
            )
            dashboard.agents[idx] = summary
        else:
            # 新規追加
            dashboard.agents.append(summary)

        dashboard.calculate_stats()
        self._write_dashboard(dashboard)

    def remove_agent_summary(self, agent_id: str) -> None:
        """エージェントサマリーを削除する。

        Args:
            agent_id: エージェントID
        """
        dashboard = self._read_dashboard()

        dashboard.agents = [
            a for a in dashboard.agents if a.agent_id != agent_id
        ]
        dashboard.calculate_stats()
        self._write_dashboard(dashboard)

    # ワークスペース統計更新メソッド

    async def update_worktree_stats(
        self,
        worktree_manager: "WorktreeManager",
    ) -> None:
        """worktree統計を更新する。

        Args:
            worktree_manager: WorktreeManager インスタンス
        """
        dashboard = self._read_dashboard()

        worktrees = await worktree_manager.list_worktrees()
        dashboard.total_worktrees = len(worktrees)

        # アクティブなworktree（未完了タスクに紐づくもの）をカウント
        assigned_paths = {
            t.worktree_path
            for t in dashboard.tasks
            if t.worktree_path
            and t.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        }
        dashboard.active_worktrees = len(
            [wt for wt in worktrees if wt.path in assigned_paths]
        )

        self._write_dashboard(dashboard)

    def sync_from_agent_manager(self, agent_manager: "AgentManager") -> None:
        """AgentManagerからエージェント情報を同期する。

        Args:
            agent_manager: AgentManager インスタンス
        """
        dashboard = self._read_dashboard()
        dashboard.agents = []

        for agent in agent_manager.agents.values():
            summary = AgentSummary(
                agent_id=agent.id,
                name=self._compute_agent_name(agent),
                role=agent.role,
                status=agent.status,
                current_task_id=agent.current_task,
                worktree_path=agent.worktree_path,
                branch=None,
                last_activity=agent.last_activity,
            )
            dashboard.agents.append(summary)

        dashboard.calculate_stats()
        self._write_dashboard(dashboard)

    def get_summary(self) -> dict:
        """ダッシュボードのサマリーを取得する。

        Returns:
            サマリー情報の辞書
        """
        dashboard = self._read_dashboard()
        cost = dashboard.cost
        pending_tasks = len(dashboard.get_tasks_by_status(TaskStatus.PENDING))
        in_progress_tasks = len(dashboard.get_tasks_by_status(TaskStatus.IN_PROGRESS))
        all_tasks_completed = (
            dashboard.total_tasks > 0
            and pending_tasks == 0
            and in_progress_tasks == 0
            and dashboard.failed_tasks == 0
        )
        return {
            "workspace_id": dashboard.workspace_id,
            "total_agents": dashboard.total_agents,
            "active_agents": dashboard.active_agents,
            "total_tasks": dashboard.total_tasks,
            "completed_tasks": dashboard.completed_tasks,
            "failed_tasks": dashboard.failed_tasks,
            "pending_tasks": pending_tasks,
            "in_progress_tasks": in_progress_tasks,
            "all_tasks_completed": all_tasks_completed,
            "total_worktrees": dashboard.total_worktrees,
            "active_worktrees": dashboard.active_worktrees,
            "updated_at": dashboard.updated_at.isoformat(),
            "cost": {
                "total_api_calls": cost.total_api_calls,
                "estimated_tokens": cost.estimated_tokens,
                "estimated_cost_usd": round(cost.estimated_cost_usd, 4),
                "actual_cost_usd": round(cost.actual_cost_usd, 4),
                "total_cost_usd": round(cost.total_cost_usd, 4),
                "warning_threshold_usd": cost.warning_threshold_usd,
            },
        }

    def _compute_agent_name(self, agent: Agent) -> str:
        """Agent から表示名を計算する。"""
        role = str(agent.role)
        if role == "owner":
            return "owner"
        if role == "admin":
            return "admin"
        cli = (
            agent.ai_cli.value
            if hasattr(agent.ai_cli, "value")
            else str(agent.ai_cli or "worker")
        )
        return self._build_worker_name(
            agent.id,
            cli,
            window_index=agent.window_index,
            pane_index=agent.pane_index,
        )

    def get_agent_label(self, agent: Agent) -> str:
        """Agent の表示名を返す（task file 命名にも利用）。"""
        return self._compute_agent_name(agent)

    def add_message(
        self,
        sender_id: str,
        receiver_id: str | None,
        message_type: str,
        subject: str,
        content: str,
    ) -> None:
        """Dashboard 表示用メッセージを messages.md に追記保存する。"""
        dashboard = self._read_dashboard()
        dashboard.messages.append(
            MessageSummary(
                sender_id=sender_id,
                receiver_id=receiver_id,
                message_type=message_type,
                subject=subject,
                content=content,
                created_at=datetime.now(),
            )
        )
        self._write_messages_markdown(dashboard)

    # タスクファイル管理メソッド（ファイルベースのタスク配布）

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

        dashboard = self._read_dashboard()
        task = self._resolve_task(dashboard, task_id)
        if task:
            task.task_file_path = relative_path
            task.description = relative_path
            self._write_dashboard(dashboard)
        logger.info(f"タスクファイルを作成しました: {task_file}")
        return task_file

    def get_task_file_path(
        self, project_root: Path, session_id: str, task_id: str, agent_label: str
    ) -> Path:
        """タスクファイルパスを取得する。"""
        safe_label = self._sanitize_task_file_part(agent_label)
        safe_task_id = self._sanitize_task_file_part(task_id)
        return project_root / get_mcp_dir() / session_id / "tasks" / f"{safe_label}_{safe_task_id}.md"

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

    # Markdown ダッシュボード生成メソッド
