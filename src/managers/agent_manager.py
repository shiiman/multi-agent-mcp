"""エージェント状態管理モジュール。"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from src.models.agent import Agent, AgentRole, AgentStatus
from src.models.workspace import WorktreeAssignment

if TYPE_CHECKING:
    from src.managers.tmux_manager import TmuxManager
    from src.managers.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


class AgentManager:
    """エージェントの状態とworktree割り当てを管理するクラス。"""

    def __init__(
        self,
        tmux: "TmuxManager",
        worktree: "WorktreeManager | None" = None,
    ) -> None:
        """AgentManagerを初期化する。

        Args:
            tmux: TmuxManagerインスタンス
            worktree: WorktreeManagerインスタンス（オプション）
        """
        self.tmux = tmux
        self.worktree = worktree
        self.agents: dict[str, Agent] = {}
        self.assignments: dict[str, WorktreeAssignment] = {}

    def get_agent(self, agent_id: str) -> Agent | None:
        """エージェントを取得する。

        Args:
            agent_id: エージェントID

        Returns:
            Agentオブジェクト、見つからない場合はNone
        """
        return self.agents.get(agent_id)

    def get_agents_by_role(self, role: AgentRole) -> list[Agent]:
        """指定した役割のエージェント一覧を取得する。

        Args:
            role: エージェントの役割

        Returns:
            該当するAgentのリスト
        """
        return [a for a in self.agents.values() if a.role == role]

    def get_idle_workers(self) -> list[Agent]:
        """待機中のWorkerエージェント一覧を取得する。

        Returns:
            待機中のWorkerのリスト
        """
        return [
            a
            for a in self.agents.values()
            if a.role == AgentRole.WORKER and a.status == AgentStatus.IDLE
        ]

    def get_busy_workers(self) -> list[Agent]:
        """作業中のWorkerエージェント一覧を取得する。

        Returns:
            作業中のWorkerのリスト
        """
        return [
            a
            for a in self.agents.values()
            if a.role == AgentRole.WORKER and a.status == AgentStatus.BUSY
        ]

    async def assign_worktree(
        self,
        agent_id: str,
        worktree_path: str,
        branch: str,
    ) -> tuple[bool, str]:
        """エージェントにworktreeを割り当てる。

        Args:
            agent_id: エージェントID
            worktree_path: worktreeのパス
            branch: ブランチ名

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        agent = self.get_agent(agent_id)
        if not agent:
            return False, f"エージェント {agent_id} が見つかりません"

        # 既存の割り当てを確認
        if agent_id in self.assignments:
            old_assignment = self.assignments[agent_id]
            logger.info(
                f"エージェント {agent_id} の割り当てを変更: "
                f"{old_assignment.worktree_path} -> {worktree_path}"
            )

        # 割り当てを更新
        assignment = WorktreeAssignment(
            agent_id=agent_id,
            worktree_path=worktree_path,
            branch=branch,
            assigned_at=datetime.now(),
        )
        self.assignments[agent_id] = assignment

        # エージェント情報も更新
        agent.worktree_path = worktree_path
        agent.last_activity = datetime.now()

        logger.info(f"エージェント {agent_id} に worktree を割り当てました: {worktree_path}")
        return True, f"worktree を割り当てました: {worktree_path}"

    async def unassign_worktree(self, agent_id: str) -> tuple[bool, str]:
        """エージェントからworktree割り当てを解除する。

        Args:
            agent_id: エージェントID

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        agent = self.get_agent(agent_id)
        if not agent:
            return False, f"エージェント {agent_id} が見つかりません"

        if agent_id not in self.assignments:
            return False, f"エージェント {agent_id} にはworktreeが割り当てられていません"

        del self.assignments[agent_id]
        agent.worktree_path = None
        agent.last_activity = datetime.now()

        logger.info(f"エージェント {agent_id} のworktree割り当てを解除しました")
        return True, "worktree割り当てを解除しました"

    def get_assignment(self, agent_id: str) -> WorktreeAssignment | None:
        """エージェントのworktree割り当て情報を取得する。

        Args:
            agent_id: エージェントID

        Returns:
            WorktreeAssignment、割り当てがない場合はNone
        """
        return self.assignments.get(agent_id)

    def get_agent_by_worktree(self, worktree_path: str) -> Agent | None:
        """指定したworktreeに割り当てられているエージェントを取得する。

        Args:
            worktree_path: worktreeのパス

        Returns:
            Agent、見つからない場合はNone
        """
        for assignment in self.assignments.values():
            if assignment.worktree_path == worktree_path:
                return self.get_agent(assignment.agent_id)
        return None

    async def update_agent_status(
        self,
        agent_id: str,
        status: AgentStatus,
        current_task: str | None = None,
    ) -> tuple[bool, str]:
        """エージェントのステータスを更新する。

        Args:
            agent_id: エージェントID
            status: 新しいステータス
            current_task: 現在のタスク（オプション）

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        agent = self.get_agent(agent_id)
        if not agent:
            return False, f"エージェント {agent_id} が見つかりません"

        agent.status = status
        agent.last_activity = datetime.now()
        if current_task is not None:
            agent.current_task = current_task

        logger.info(f"エージェント {agent_id} のステータスを更新: {status.value}")
        return True, f"ステータスを更新しました: {status.value}"

    def get_summary(self) -> dict:
        """エージェント管理のサマリーを取得する。

        Returns:
            サマリー情報の辞書
        """
        total = len(self.agents)
        by_role = {}
        by_status = {}

        for agent in self.agents.values():
            # 役割別カウント
            role = agent.role.value
            by_role[role] = by_role.get(role, 0) + 1

            # ステータス別カウント
            status = agent.status.value
            by_status[status] = by_status.get(status, 0) + 1

        return {
            "total_agents": total,
            "by_role": by_role,
            "by_status": by_status,
            "assigned_worktrees": len(self.assignments),
        }
