"""ダッシュボード管理モジュール。"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.models.agent import Agent
from src.models.dashboard import (
    AgentSummary,
    Dashboard,
    TaskInfo,
    TaskStatus,
)

if TYPE_CHECKING:
    from src.managers.agent_manager import AgentManager
    from src.managers.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


class DashboardManager:
    """ダッシュボードを管理するクラス。"""

    def __init__(
        self,
        workspace_id: str,
        workspace_path: str,
        dashboard_dir: str,
    ) -> None:
        """DashboardManagerを初期化する。

        Args:
            workspace_id: ワークスペースID
            workspace_path: ワークスペースパス
            dashboard_dir: ダッシュボードファイルを保存するディレクトリ
        """
        self.workspace_id = workspace_id
        self.workspace_path = workspace_path
        self.dashboard_dir = Path(dashboard_dir)
        self.dashboard = Dashboard(
            workspace_id=workspace_id,
            workspace_path=workspace_path,
        )

    def initialize(self) -> None:
        """ダッシュボード環境を初期化する。"""
        self.dashboard_dir.mkdir(parents=True, exist_ok=True)
        self._save_dashboard()
        logger.info(f"ダッシュボード環境を初期化しました: {self.dashboard_dir}")

    def cleanup(self) -> None:
        """ダッシュボード環境をクリーンアップする。"""
        dashboard_path = self._get_dashboard_path()
        if dashboard_path.exists():
            try:
                dashboard_path.unlink()
            except OSError as e:
                logger.warning(f"ダッシュボードファイル削除エラー: {e}")
        logger.info("ダッシュボード環境をクリーンアップしました")

    def _get_dashboard_path(self) -> Path:
        """ダッシュボードファイルパスを取得する。"""
        return self.dashboard_dir / f"dashboard_{self.workspace_id}.json"

    def _save_dashboard(self) -> None:
        """ダッシュボードをファイルに保存する。"""
        dashboard_path = self._get_dashboard_path()
        try:
            with open(dashboard_path, "w", encoding="utf-8") as f:
                json.dump(
                    self.dashboard.model_dump(mode="json"),
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except OSError as e:
            logger.error(f"ダッシュボード保存エラー: {e}")

    def _load_dashboard(self) -> None:
        """ダッシュボードをファイルから読み込む。"""
        dashboard_path = self._get_dashboard_path()
        if dashboard_path.exists():
            try:
                with open(dashboard_path, encoding="utf-8") as f:
                    data = json.load(f)
                    self.dashboard = Dashboard(**data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"ダッシュボード読み込みエラー: {e}")

    def get_dashboard(self) -> Dashboard:
        """現在のダッシュボードを取得する。

        Returns:
            Dashboard オブジェクト
        """
        self._load_dashboard()
        return self.dashboard

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
            description: タスク説明
            assigned_agent_id: 割り当て先エージェントID
            branch: 作業ブランチ
            worktree_path: worktreeパス
            metadata: 追加メタデータ

        Returns:
            作成されたTaskInfo
        """
        task = TaskInfo(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            status=TaskStatus.PENDING,
            assigned_agent_id=assigned_agent_id,
            branch=branch,
            worktree_path=worktree_path,
            metadata=metadata or {},
            created_at=datetime.now(),
        )

        self.dashboard.tasks.append(task)
        self.dashboard.calculate_stats()
        self._save_dashboard()

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
        task = self.dashboard.get_task(task_id)
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
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            task.completed_at = now
            if status == TaskStatus.COMPLETED:
                task.progress = 100

        self.dashboard.calculate_stats()
        self._save_dashboard()

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
        task = self.dashboard.get_task(task_id)
        if not task:
            return False, f"タスク {task_id} が見つかりません"

        task.assigned_agent_id = agent_id
        if branch:
            task.branch = branch
        if worktree_path:
            task.worktree_path = worktree_path

        self._save_dashboard()

        logger.info(f"タスク {task_id} をエージェント {agent_id} に割り当てました")
        return True, f"タスクを割り当てました: {agent_id}"

    def remove_task(self, task_id: str) -> tuple[bool, str]:
        """タスクを削除する。

        Args:
            task_id: タスクID

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        task = self.dashboard.get_task(task_id)
        if not task:
            return False, f"タスク {task_id} が見つかりません"

        self.dashboard.tasks = [t for t in self.dashboard.tasks if t.id != task_id]
        self.dashboard.calculate_stats()
        self._save_dashboard()

        logger.info(f"タスク {task_id} を削除しました")
        return True, "タスクを削除しました"

    def get_task(self, task_id: str) -> TaskInfo | None:
        """タスクを取得する。

        Args:
            task_id: タスクID

        Returns:
            TaskInfo、見つからない場合はNone
        """
        return self.dashboard.get_task(task_id)

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
        tasks = self.dashboard.tasks

        if status is not None:
            tasks = [t for t in tasks if t.status == status]

        if agent_id is not None:
            tasks = [t for t in tasks if t.assigned_agent_id == agent_id]

        return tasks

    # エージェントサマリー管理メソッド

    def update_agent_summary(self, agent: Agent) -> None:
        """エージェントサマリーを更新する。

        Args:
            agent: Agentオブジェクト
        """
        # 既存のサマリーを検索
        existing = self.dashboard.get_agent(agent.id)

        summary = AgentSummary(
            agent_id=agent.id,
            role=agent.role.value,
            status=agent.status.value,
            current_task_id=agent.current_task,
            worktree_path=agent.worktree_path,
            branch=None,  # 別途取得が必要
            last_activity=agent.last_activity,
        )

        if existing:
            # 既存のサマリーを更新
            idx = next(
                i
                for i, a in enumerate(self.dashboard.agents)
                if a.agent_id == agent.id
            )
            self.dashboard.agents[idx] = summary
        else:
            # 新規追加
            self.dashboard.agents.append(summary)

        self.dashboard.calculate_stats()
        self._save_dashboard()

    def remove_agent_summary(self, agent_id: str) -> None:
        """エージェントサマリーを削除する。

        Args:
            agent_id: エージェントID
        """
        self.dashboard.agents = [
            a for a in self.dashboard.agents if a.agent_id != agent_id
        ]
        self.dashboard.calculate_stats()
        self._save_dashboard()

    # ワークスペース統計更新メソッド

    async def update_worktree_stats(
        self,
        worktree_manager: "WorktreeManager",
    ) -> None:
        """worktree統計を更新する。

        Args:
            worktree_manager: WorktreeManager インスタンス
        """
        worktrees = await worktree_manager.list_worktrees()
        self.dashboard.total_worktrees = len(worktrees)

        # アクティブなworktree（エージェントに割り当てられている）をカウント
        assigned_paths = {
            a.worktree_path for a in self.dashboard.agents if a.worktree_path
        }
        self.dashboard.active_worktrees = len(
            [wt for wt in worktrees if wt.path in assigned_paths]
        )

        self._save_dashboard()

    def sync_from_agent_manager(self, agent_manager: "AgentManager") -> None:
        """AgentManagerからエージェント情報を同期する。

        Args:
            agent_manager: AgentManager インスタンス
        """
        self.dashboard.agents = []
        for agent in agent_manager.agents.values():
            self.update_agent_summary(agent)

        self.dashboard.calculate_stats()
        self._save_dashboard()

    def get_summary(self) -> dict:
        """ダッシュボードのサマリーを取得する。

        Returns:
            サマリー情報の辞書
        """
        self._load_dashboard()
        return {
            "workspace_id": self.dashboard.workspace_id,
            "total_agents": self.dashboard.total_agents,
            "active_agents": self.dashboard.active_agents,
            "total_tasks": self.dashboard.total_tasks,
            "completed_tasks": self.dashboard.completed_tasks,
            "failed_tasks": self.dashboard.failed_tasks,
            "pending_tasks": len(
                self.dashboard.get_tasks_by_status(TaskStatus.PENDING)
            ),
            "in_progress_tasks": len(
                self.dashboard.get_tasks_by_status(TaskStatus.IN_PROGRESS)
            ),
            "total_worktrees": self.dashboard.total_worktrees,
            "active_worktrees": self.dashboard.active_worktrees,
            "updated_at": self.dashboard.updated_at.isoformat(),
        }
