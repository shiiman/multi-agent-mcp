"""Dashboard のエージェント集計・ステータス更新ロジック mixin。"""

import logging
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING

from src.models.agent import Agent
from src.models.dashboard import (
    AgentSummary,
    Dashboard,
    MessageSummary,
    TaskStatus,
)

if TYPE_CHECKING:
    from src.managers.agent_manager import AgentManager
    from src.managers.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


class DashboardAgentMixin:
    """Dashboard のエージェントサマリー・集計・メッセージ機能を提供する mixin。"""

    # ------------------------------------------------------------------
    # 共通ヘルパー
    # ------------------------------------------------------------------

    def _build_agent_summary(self, agent: Agent) -> AgentSummary:
        """Agent オブジェクトから AgentSummary を生成する。"""
        return AgentSummary(
            agent_id=agent.id,
            name=self._compute_agent_name(agent),
            role=agent.role,  # use_enum_values=True のため既に文字列
            status=agent.status,  # use_enum_values=True のため既に文字列
            current_task_id=agent.current_task,
            worktree_path=agent.worktree_path,
            branch=None,  # 別途取得が必要
            last_activity=agent.last_activity,
        )

    def _compute_agent_name(self, agent: Agent) -> str:
        """Agent から表示名を計算する。"""
        role = str(agent.role)
        if role == "owner":
            return "owner"
        if role == "admin":
            return "admin"
        cli = (
            agent.ai_cli.value if hasattr(agent.ai_cli, "value") else str(agent.ai_cli or "worker")
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

    # ------------------------------------------------------------------
    # エージェントサマリー管理
    # ------------------------------------------------------------------

    def update_agent_summary(self, agent: Agent) -> None:
        """エージェントサマリーを更新する。

        Args:
            agent: Agentオブジェクト
        """

        def _update_agent(dashboard: Dashboard) -> None:
            existing = dashboard.get_agent(agent.id)
            summary = self._build_agent_summary(agent)

            if existing:
                idx = next(i for i, a in enumerate(dashboard.agents) if a.agent_id == agent.id)
                dashboard.agents[idx] = summary
            else:
                dashboard.agents.append(summary)

            dashboard.calculate_stats()

        self._mutate_dashboard(_update_agent)

    def sync_agent_summaries(self, agents: Iterable[Agent]) -> None:
        """複数 Agent からサマリー一覧を一括同期する。"""

        def _sync(dashboard: Dashboard) -> None:
            dashboard.agents = [self._build_agent_summary(agent) for agent in agents]
            dashboard.calculate_stats()

        self._mutate_dashboard(_sync)

    def remove_agent_summary(self, agent_id: str) -> None:
        """エージェントサマリーを削除する。

        Args:
            agent_id: エージェントID
        """

        def _remove_agent(dashboard: Dashboard) -> None:
            dashboard.agents = [a for a in dashboard.agents if a.agent_id != agent_id]
            dashboard.calculate_stats()

        self._mutate_dashboard(_remove_agent)

    # ------------------------------------------------------------------
    # ワークスペース統計
    # ------------------------------------------------------------------

    async def update_worktree_stats(
        self,
        worktree_manager: "WorktreeManager",
    ) -> None:
        """worktree統計を更新する。

        Args:
            worktree_manager: WorktreeManager インスタンス
        """
        worktrees = await worktree_manager.list_worktrees()

        def _update_worktree(dashboard: Dashboard) -> None:
            dashboard.total_worktrees = len(worktrees)

            # アクティブなworktree（未完了タスクに紐づくもの）をカウント
            assigned_paths = {
                t.worktree_path
                for t in dashboard.tasks
                if t.worktree_path
                and t.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            }
            dashboard.active_worktrees = len([wt for wt in worktrees if wt.path in assigned_paths])
            dashboard.calculate_stats()

        self._mutate_dashboard(_update_worktree)

    # ------------------------------------------------------------------
    # エージェント同期
    # ------------------------------------------------------------------

    def sync_from_agent_manager(self, agent_manager: "AgentManager") -> None:
        """AgentManagerからエージェント情報を同期する。

        Args:
            agent_manager: AgentManager インスタンス
        """

        self.sync_agent_summaries(agent_manager.agents.values())

    # ------------------------------------------------------------------
    # サマリー取得
    # ------------------------------------------------------------------

    def get_summary(self) -> dict:
        """ダッシュボードのサマリーを取得する。

        Returns:
            サマリー情報の辞書
        """
        dashboard = self._read_dashboard_snapshot()
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
            "session_started_at": (
                dashboard.session_started_at.isoformat() if dashboard.session_started_at else None
            ),
            "session_finished_at": (
                dashboard.session_finished_at.isoformat() if dashboard.session_finished_at else None
            ),
            "process_crash_count": dashboard.process_crash_count,
            "process_recovery_count": dashboard.process_recovery_count,
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

    # ------------------------------------------------------------------
    # メッセージ管理
    # ------------------------------------------------------------------

    def add_message(
        self,
        sender_id: str,
        receiver_id: str | None,
        message_type: str,
        subject: str,
        content: str,
    ) -> None:
        """Dashboard 表示用メッセージを messages.md に追記保存する。"""

        def _append(dashboard: Dashboard) -> None:
            message = MessageSummary(
                sender_id=sender_id,
                receiver_id=receiver_id,
                message_type=message_type,
                subject=subject,
                content=content,
                created_at=datetime.now(),
            )
            dashboard.messages.append(message)
            self._append_message_markdown(dashboard, message)

        self._mutate_dashboard(_append, write_back=False)
