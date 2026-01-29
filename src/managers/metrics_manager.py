"""メトリクス収集マネージャー。

実行時間、成功率、タスク完了数などの統計を収集・提供する。
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.agent import Agent

logger = logging.getLogger(__name__)


@dataclass
class TaskMetrics:
    """タスクメトリクス。"""

    task_id: str
    """タスクID"""

    started_at: datetime | None = None
    """開始時刻"""

    completed_at: datetime | None = None
    """完了時刻"""

    status: str = "pending"
    """状態（pending, in_progress, completed, failed）"""

    agent_id: str | None = None
    """担当エージェントID"""

    @property
    def duration(self) -> timedelta | None:
        """実行時間を取得する。

        Returns:
            実行時間、計測できない場合None
        """
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None

    def to_dict(self) -> dict:
        """辞書に変換する。

        Returns:
            メトリクスの辞書表現
        """
        return {
            "task_id": self.task_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "status": self.status,
            "agent_id": self.agent_id,
            "duration_seconds": (
                self.duration.total_seconds() if self.duration else None
            ),
        }


@dataclass
class AgentMetrics:
    """エージェントメトリクス。"""

    agent_id: str
    """エージェントID"""

    tasks_completed: int = 0
    """完了タスク数"""

    tasks_failed: int = 0
    """失敗タスク数"""

    total_duration: timedelta = field(default_factory=lambda: timedelta())
    """合計作業時間"""

    @property
    def success_rate(self) -> float:
        """成功率を取得する。

        Returns:
            成功率（0.0-1.0）
        """
        total = self.tasks_completed + self.tasks_failed
        if total == 0:
            return 0.0
        return self.tasks_completed / total

    @property
    def average_duration(self) -> timedelta | None:
        """平均作業時間を取得する。

        Returns:
            平均作業時間、計測できない場合None
        """
        if self.tasks_completed == 0:
            return None
        return self.total_duration / self.tasks_completed

    def to_dict(self) -> dict:
        """辞書に変換する。

        Returns:
            メトリクスの辞書表現
        """
        return {
            "agent_id": self.agent_id,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "success_rate": self.success_rate,
            "total_duration_seconds": self.total_duration.total_seconds(),
            "average_duration_seconds": (
                self.average_duration.total_seconds()
                if self.average_duration
                else None
            ),
        }


@dataclass
class WorkspaceMetrics:
    """ワークスペースメトリクス。"""

    total_tasks: int = 0
    """総タスク数"""

    completed_tasks: int = 0
    """完了タスク数"""

    failed_tasks: int = 0
    """失敗タスク数"""

    pending_tasks: int = 0
    """保留タスク数"""

    in_progress_tasks: int = 0
    """進行中タスク数"""

    total_agents: int = 0
    """総エージェント数"""

    active_agents: int = 0
    """アクティブエージェント数"""

    total_duration: timedelta = field(default_factory=lambda: timedelta())
    """合計作業時間"""

    @property
    def completion_rate(self) -> float:
        """完了率を取得する。

        Returns:
            完了率（0.0-1.0）
        """
        if self.total_tasks == 0:
            return 0.0
        return self.completed_tasks / self.total_tasks

    @property
    def success_rate(self) -> float:
        """成功率を取得する（完了したもののうち成功したものの割合）。

        Returns:
            成功率（0.0-1.0）
        """
        finished = self.completed_tasks + self.failed_tasks
        if finished == 0:
            return 0.0
        return self.completed_tasks / finished

    def to_dict(self) -> dict:
        """辞書に変換する。

        Returns:
            メトリクスの辞書表現
        """
        return {
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "pending_tasks": self.pending_tasks,
            "in_progress_tasks": self.in_progress_tasks,
            "total_agents": self.total_agents,
            "active_agents": self.active_agents,
            "completion_rate": self.completion_rate,
            "success_rate": self.success_rate,
            "total_duration_seconds": self.total_duration.total_seconds(),
        }


class MetricsManager:
    """メトリクス収集・管理を行うマネージャー。"""

    def __init__(self, metrics_dir: str | None = None) -> None:
        """MetricsManagerを初期化する。

        Args:
            metrics_dir: メトリクス保存ディレクトリ（オプション）
        """
        self._task_metrics: dict[str, TaskMetrics] = {}
        self._agent_metrics: dict[str, AgentMetrics] = defaultdict(
            lambda: AgentMetrics(agent_id="")
        )
        self._metrics_dir = Path(metrics_dir) if metrics_dir else None

    def start_task(self, task_id: str, agent_id: str) -> None:
        """タスク開始を記録する。

        Args:
            task_id: タスクID
            agent_id: 担当エージェントID
        """
        self._task_metrics[task_id] = TaskMetrics(
            task_id=task_id,
            started_at=datetime.now(),
            status="in_progress",
            agent_id=agent_id,
        )
        logger.debug(f"タスク {task_id} の開始を記録（エージェント: {agent_id}）")

    def complete_task(self, task_id: str, success: bool = True) -> None:
        """タスク完了を記録する。

        Args:
            task_id: タスクID
            success: 成功したかどうか
        """
        if task_id not in self._task_metrics:
            # 開始記録がない場合は新規作成
            self._task_metrics[task_id] = TaskMetrics(task_id=task_id)

        metrics = self._task_metrics[task_id]
        metrics.completed_at = datetime.now()
        metrics.status = "completed" if success else "failed"

        # エージェントメトリクス更新
        if metrics.agent_id:
            agent_metrics = self._agent_metrics[metrics.agent_id]
            agent_metrics.agent_id = metrics.agent_id
            if success:
                agent_metrics.tasks_completed += 1
                if metrics.duration:
                    agent_metrics.total_duration += metrics.duration
            else:
                agent_metrics.tasks_failed += 1

        logger.debug(
            f"タスク {task_id} の完了を記録（成功: {success}）"
        )

    def get_task_metrics(self, task_id: str) -> TaskMetrics | None:
        """タスクのメトリクスを取得する。

        Args:
            task_id: タスクID

        Returns:
            タスクメトリクス、見つからない場合None
        """
        return self._task_metrics.get(task_id)

    def get_agent_metrics(self, agent_id: str) -> AgentMetrics:
        """エージェントのメトリクスを取得する。

        Args:
            agent_id: エージェントID

        Returns:
            エージェントメトリクス
        """
        if agent_id not in self._agent_metrics:
            self._agent_metrics[agent_id] = AgentMetrics(agent_id=agent_id)
        return self._agent_metrics[agent_id]

    def get_workspace_metrics(
        self,
        agents: dict[str, "Agent"],
    ) -> WorkspaceMetrics:
        """ワークスペース全体のメトリクスを取得する。

        Args:
            agents: エージェントの辞書

        Returns:
            ワークスペースメトリクス
        """
        metrics = WorkspaceMetrics(
            total_agents=len(agents),
            active_agents=len([a for a in agents.values() if a.status == "busy"]),
        )

        for task_metrics in self._task_metrics.values():
            metrics.total_tasks += 1
            if task_metrics.status == "completed":
                metrics.completed_tasks += 1
            elif task_metrics.status == "failed":
                metrics.failed_tasks += 1
            elif task_metrics.status == "in_progress":
                metrics.in_progress_tasks += 1
            else:
                metrics.pending_tasks += 1

            if task_metrics.duration:
                metrics.total_duration += task_metrics.duration

        return metrics

    def get_all_task_metrics(self) -> list[TaskMetrics]:
        """全タスクのメトリクスを取得する。

        Returns:
            タスクメトリクスのリスト
        """
        return list(self._task_metrics.values())

    def get_all_agent_metrics(self) -> list[AgentMetrics]:
        """全エージェントのメトリクスを取得する。

        Returns:
            エージェントメトリクスのリスト
        """
        return list(self._agent_metrics.values())

    def export_to_json(self, filepath: str | None = None) -> str:
        """メトリクスをJSONにエクスポートする。

        Args:
            filepath: 出力ファイルパス（オプション）

        Returns:
            JSON文字列
        """
        data = {
            "exported_at": datetime.now().isoformat(),
            "tasks": [m.to_dict() for m in self._task_metrics.values()],
            "agents": [m.to_dict() for m in self._agent_metrics.values()],
        }
        json_str = json.dumps(data, ensure_ascii=False, indent=2)

        if filepath:
            Path(filepath).write_text(json_str, encoding="utf-8")
            logger.info(f"メトリクスをエクスポートしました: {filepath}")

        return json_str

    def export_to_csv(self, filepath: str) -> None:
        """タスクメトリクスをCSVにエクスポートする。

        Args:
            filepath: 出力ファイルパス
        """
        import csv

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "task_id", "agent_id", "status", "started_at",
                "completed_at", "duration_seconds"
            ])
            for metrics in self._task_metrics.values():
                writer.writerow([
                    metrics.task_id,
                    metrics.agent_id or "",
                    metrics.status,
                    metrics.started_at.isoformat() if metrics.started_at else "",
                    metrics.completed_at.isoformat() if metrics.completed_at else "",
                    metrics.duration.total_seconds() if metrics.duration else "",
                ])

        logger.info(f"タスクメトリクスをCSVエクスポートしました: {filepath}")

    def reset(self) -> None:
        """全メトリクスをリセットする。"""
        self._task_metrics.clear()
        self._agent_metrics.clear()
        logger.info("メトリクスをリセットしました")

    def get_summary(self) -> dict:
        """メトリクスのサマリーを取得する。

        Returns:
            サマリー情報の辞書
        """
        total_tasks = len(self._task_metrics)
        completed = sum(
            1 for m in self._task_metrics.values() if m.status == "completed"
        )
        failed = sum(1 for m in self._task_metrics.values() if m.status == "failed")
        in_progress = sum(
            1 for m in self._task_metrics.values() if m.status == "in_progress"
        )

        total_duration = sum(
            (m.duration.total_seconds() for m in self._task_metrics.values()
             if m.duration),
            0.0,
        )

        return {
            "total_tasks": total_tasks,
            "completed_tasks": completed,
            "failed_tasks": failed,
            "in_progress_tasks": in_progress,
            "pending_tasks": total_tasks - completed - failed - in_progress,
            "total_agents_tracked": len(self._agent_metrics),
            "total_duration_seconds": total_duration,
            "average_duration_seconds": (
                total_duration / completed if completed > 0 else 0
            ),
        }
