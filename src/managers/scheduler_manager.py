"""タスクスケジューラーマネージャー。

タスクの優先度管理と、空いているWorkerへの自動割り当てを行う。
"""

import heapq
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.managers.dashboard_manager import DashboardManager
    from src.models.agent import Agent

logger = logging.getLogger(__name__)


class TaskPriority(IntEnum):
    """タスク優先度。"""

    CRITICAL = 0
    """最優先（緊急タスク）"""

    HIGH = 1
    """高優先度"""

    MEDIUM = 2
    """通常優先度"""

    LOW = 3
    """低優先度"""


@dataclass(order=True)
class ScheduledTask:
    """スケジュールされたタスク。"""

    priority: int
    """優先度（小さいほど高優先）"""

    created_at: datetime = field(compare=False)
    """作成日時"""

    task_id: str = field(compare=False)
    """タスクID"""

    dependencies: list[str] = field(default_factory=list, compare=False)
    """依存タスクのIDリスト"""


class SchedulerManager:
    """タスクスケジューラー。

    優先度付きキューでタスクを管理し、
    空いているWorkerへの自動割り当てを行う。
    """

    def __init__(
        self,
        dashboard_manager: "DashboardManager",
        agents: dict[str, "Agent"],
        persist_agent_state: Callable[["Agent"], bool] | None = None,
    ) -> None:
        """SchedulerManagerを初期化する。

        Args:
            dashboard_manager: ダッシュボードマネージャー
            agents: エージェントの辞書（agent_id -> Agent）
            persist_agent_state: エージェント状態永続化コールバック
        """
        self.dashboard_manager = dashboard_manager
        self.agents = agents
        self._persist_agent_state = persist_agent_state
        self._task_queue: list[ScheduledTask] = []
        self._assigned_tasks: dict[str, str] = {}  # task_id -> agent_id
        self._task_map: dict[str, ScheduledTask] = {}  # task_id -> ScheduledTask

    def enqueue_task(
        self,
        task_id: str,
        priority: TaskPriority = TaskPriority.MEDIUM,
        dependencies: list[str] | None = None,
    ) -> bool:
        """タスクをキューに追加する。

        Args:
            task_id: タスクID
            priority: 優先度
            dependencies: 依存タスクのIDリスト

        Returns:
            成功した場合True
        """
        if task_id in self._task_map:
            logger.warning(f"タスク {task_id} は既にキューに存在します")
            return False

        scheduled = ScheduledTask(
            priority=priority.value,
            created_at=datetime.now(),
            task_id=task_id,
            dependencies=dependencies or [],
        )
        heapq.heappush(self._task_queue, scheduled)
        self._task_map[task_id] = scheduled

        logger.info(f"タスク {task_id} をキューに追加しました（優先度: {priority.name}）")
        return True

    def dequeue_task(self, task_id: str) -> bool:
        """タスクをキューから削除する。

        Args:
            task_id: タスクID

        Returns:
            成功した場合True
        """
        if task_id not in self._task_map:
            return False

        del self._task_map[task_id]
        self._task_queue = [t for t in self._task_queue if t.task_id != task_id]
        heapq.heapify(self._task_queue)

        logger.info(f"タスク {task_id} をキューから削除しました")
        return True

    def update_priority(self, task_id: str, priority: TaskPriority) -> bool:
        """タスクの優先度を更新する。

        Args:
            task_id: タスクID
            priority: 新しい優先度

        Returns:
            成功した場合True
        """
        if task_id not in self._task_map:
            return False

        scheduled = self._task_map[task_id]
        # 一度削除して再追加
        self.dequeue_task(task_id)
        self.enqueue_task(task_id, priority, scheduled.dependencies)
        return True

    def _dependencies_satisfied(self, dependencies: list[str]) -> bool:
        """依存タスクが全て完了しているか確認する。

        Args:
            dependencies: 依存タスクのIDリスト

        Returns:
            全て完了している場合True
        """
        for dep_id in dependencies:
            task = self.dashboard_manager.get_task(dep_id)
            if not task or task.status != "completed":
                return False
        return True

    def get_next_task(self) -> str | None:
        """次に実行すべきタスクを取得する（依存関係考慮）。

        Returns:
            タスクID、なければNone
        """
        for scheduled in sorted(self._task_queue):
            if scheduled.task_id in self._assigned_tasks:
                continue
            if self._dependencies_satisfied(scheduled.dependencies):
                return scheduled.task_id
        return None

    def get_idle_workers(self) -> list[str]:
        """空いているWorkerのIDリストを取得する。

        Returns:
            空いているWorkerのIDリスト
        """
        idle_workers = []
        for agent_id, agent in self.agents.items():
            if agent.role == "worker" and agent.status == "idle":
                idle_workers.append(agent_id)
        return idle_workers

    def get_idle_worker(self) -> str | None:
        """空いているWorkerを1つ取得する。

        Returns:
            Worker ID、なければNone
        """
        idle_workers = self.get_idle_workers()
        return idle_workers[0] if idle_workers else None

    def assign_task(self, task_id: str, worker_id: str) -> tuple[bool, str]:
        """タスクをWorkerに割り当てる。

        Args:
            task_id: タスクID
            worker_id: Worker ID

        Returns:
            (成功したか, メッセージ) のタプル
        """
        if task_id not in self._task_map:
            return False, f"タスク {task_id} はキューに存在しません"

        if worker_id not in self.agents:
            return False, f"Worker {worker_id} が見つかりません"

        agent = self.agents[worker_id]
        if agent.role != "worker":
            return False, f"{worker_id} はWorkerではありません"

        if agent.status != "idle":
            return False, f"Worker {worker_id} は現在利用できません（状態: {agent.status}）"

        # 同一Workerへの多重割り当てを防ぐため、先にbusy反映と永続化を行う
        previous_status = agent.status
        previous_task = agent.current_task
        previous_last_activity = agent.last_activity
        now = datetime.now()

        agent.status = "busy"
        agent.current_task = task_id
        agent.last_activity = now
        if self._persist_agent_state:
            self._persist_agent_state(agent)

        # 割り当て
        self._assigned_tasks[task_id] = worker_id
        assigned, message = self.dashboard_manager.assign_task(task_id, worker_id)
        if not assigned:
            # 反映失敗時は状態を戻して整合性を維持する
            self._assigned_tasks.pop(task_id, None)
            agent.status = previous_status
            agent.current_task = previous_task
            agent.last_activity = previous_last_activity
            if self._persist_agent_state:
                self._persist_agent_state(agent)
            return False, message

        logger.info(f"タスク {task_id} を Worker {worker_id} に割り当てました")
        return True, f"タスク {task_id} を Worker {worker_id} に割り当てました"

    def auto_assign(self) -> tuple[str, str] | None:
        """タスクを自動で1つ割り当てる。

        Returns:
            (task_id, worker_id) のタプル、割り当てできなければNone
        """
        task_id = self.get_next_task()
        if not task_id:
            return None

        worker_id = self.get_idle_worker()
        if not worker_id:
            return None

        success, _ = self.assign_task(task_id, worker_id)
        if success:
            return (task_id, worker_id)
        return None

    def run_auto_assign_loop(self) -> list[tuple[str, str]]:
        """空いているWorker全てにタスクを割り当てる。

        Returns:
            割り当てた (task_id, worker_id) のリスト
        """
        assignments = []
        while True:
            result = self.auto_assign()
            if not result:
                break
            assignments.append(result)
        return assignments

    def complete_task(self, task_id: str) -> bool:
        """タスクの完了を記録する。

        Args:
            task_id: タスクID

        Returns:
            成功した場合True
        """
        if task_id in self._assigned_tasks:
            del self._assigned_tasks[task_id]

        return self.dequeue_task(task_id)

    def get_queue_status(self) -> dict:
        """キューの状態を取得する。

        Returns:
            状態情報の辞書
        """
        pending = []
        for scheduled in sorted(self._task_queue):
            if scheduled.task_id not in self._assigned_tasks:
                pending.append({
                    "task_id": scheduled.task_id,
                    "priority": TaskPriority(scheduled.priority).name,
                    "created_at": scheduled.created_at.isoformat(),
                    "dependencies": scheduled.dependencies,
                    "dependencies_satisfied": self._dependencies_satisfied(
                        scheduled.dependencies
                    ),
                })

        assigned = [
            {"task_id": tid, "worker_id": wid}
            for tid, wid in self._assigned_tasks.items()
        ]

        return {
            "pending_count": len(pending),
            "assigned_count": len(assigned),
            "pending_tasks": pending,
            "assigned_tasks": assigned,
            "idle_workers": self.get_idle_workers(),
        }

    def get_task_info(self, task_id: str) -> dict | None:
        """タスクのスケジューラー情報を取得する。

        Args:
            task_id: タスクID

        Returns:
            タスク情報、見つからなければNone
        """
        if task_id not in self._task_map:
            return None

        scheduled = self._task_map[task_id]
        return {
            "task_id": scheduled.task_id,
            "priority": TaskPriority(scheduled.priority).name,
            "created_at": scheduled.created_at.isoformat(),
            "dependencies": scheduled.dependencies,
            "assigned_to": self._assigned_tasks.get(task_id),
        }
