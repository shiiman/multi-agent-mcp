"""エージェント状態管理モジュール。"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from src.config.settings import Settings
from src.managers.tmux_manager import (
    MAIN_SESSION,
    MAIN_WINDOW_PANE_ADMIN,
    MAIN_WINDOW_WORKER_PANES,
)
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
            # 役割別カウント（use_enum_values=True のため既に文字列）
            role = agent.role
            by_role[role] = by_role.get(role, 0) + 1

            # ステータス別カウント（use_enum_values=True のため既に文字列）
            status = agent.status
            by_status[status] = by_status.get(status, 0) + 1

        return {
            "total_agents": total,
            "by_role": by_role,
            "by_status": by_status,
            "assigned_worktrees": len(self.assignments),
        }

    # ========== グリッドレイアウト関連メソッド ==========

    def get_pane_for_role(
        self, role: AgentRole, worker_index: int = 0
    ) -> tuple[str, int, int] | None:
        """ロールに対応するペイン位置を取得する（単一セッション方式）。

        Args:
            role: エージェントの役割
            worker_index: Worker番号（0始まり、roleがWORKERの場合のみ使用）

        Returns:
            (session_name, window_index, pane_index) のタプル、
            Owner の場合は None（tmux ペインに配置しない）
        """
        if role == AgentRole.OWNER:
            # Owner は tmux ペインに配置しない（実行AIエージェントが担う）
            return None
        elif role == AgentRole.ADMIN:
            return MAIN_SESSION, 0, MAIN_WINDOW_PANE_ADMIN
        elif role == AgentRole.WORKER:
            # Worker 1-6 はメインウィンドウ
            if worker_index < 6:
                # ペイン番号: 1, 2, 3, 4, 5, 6
                pane_index = 1 + worker_index
                return MAIN_SESSION, 0, pane_index
            else:
                # Worker 7以降は追加ウィンドウ（10ペイン/ウィンドウ、2×5）
                extra_worker_index = worker_index - 6
                window_index = 1 + (extra_worker_index // 10)
                pane_index = extra_worker_index % 10
                return MAIN_SESSION, window_index, pane_index
        else:
            raise ValueError(f"不明なロール: {role}")

    def is_pane_occupied(self, session_name: str, window_index: int, pane_index: int) -> bool:
        """指定したペインが使用中か確認する。

        Args:
            session_name: セッション名
            window_index: ウィンドウインデックス
            pane_index: ペインインデックス

        Returns:
            使用中の場合True
        """
        for agent in self.agents.values():
            if (
                agent.session_name == session_name
                and agent.window_index == window_index
                and agent.pane_index == pane_index
            ):
                return True
        return False

    def get_all_pane_assignments(self) -> dict[tuple[str, int, int], str]:
        """全ペインの割り当て状況を取得する。

        Returns:
            {(session_name, window_index, pane_index): agent_id} の辞書
        """
        assignments = {}
        for agent in self.agents.values():
            if (
                agent.session_name is not None
                and agent.window_index is not None
                and agent.pane_index is not None
            ):
                key = (agent.session_name, agent.window_index, agent.pane_index)
                assignments[key] = agent.id
        return assignments

    def get_next_worker_slot(self, settings: Settings) -> tuple[int, int] | None:
        """次に利用可能なWorkerスロット（ウィンドウ, ペイン）を取得する。

        Args:
            settings: 設定オブジェクト

        Returns:
            (window_index, pane_index) のタプル、空きがない場合はNone
        """
        total_workers = self.count_workers()
        if total_workers >= settings.max_workers:
            return None

        # 使用中のペイン位置を収集
        used_slots = set()
        for agent in self.agents.values():
            if (
                agent.role == AgentRole.WORKER
                and agent.status != AgentStatus.TERMINATED
                and agent.window_index is not None
                and agent.pane_index is not None
            ):
                used_slots.add((agent.window_index, agent.pane_index))

        # メインウィンドウ（Worker 1-6）の空きを探す
        for pane_index in MAIN_WINDOW_WORKER_PANES:
            if (0, pane_index) not in used_slots:
                return (0, pane_index)

        # 追加ウィンドウの空きを探す
        panes_per_extra = settings.workers_per_extra_window
        extra_worker_index = 0
        while total_workers + extra_worker_index < settings.max_workers:
            window_index = 1 + (extra_worker_index // panes_per_extra)
            pane_index = extra_worker_index % panes_per_extra
            if (window_index, pane_index) not in used_slots:
                return (window_index, pane_index)
            extra_worker_index += 1

        return None

    def count_workers(self) -> int:
        """Workerエージェントの数を取得する。

        Returns:
            Worker数
        """
        return len(
            [
                a
                for a in self.agents.values()
                if a.role == AgentRole.WORKER and a.status != AgentStatus.TERMINATED
            ]
        )

    async def ensure_sessions_exist(self, settings: Settings, working_dir: str) -> tuple[bool, str]:
        """メインセッションが存在することを確認し、なければ作成する。

        単一セッション方式: 左右50:50分離レイアウト
        - 左半分: Owner + Admin
        - 右半分: Worker 1-6

        Args:
            settings: 設定オブジェクト
            working_dir: 作業ディレクトリ

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        # メインセッション（単一セッション方式）
        if not await self.tmux.create_main_session(working_dir):
            return False, "メインセッションの作成に失敗しました"

        return True, "メインセッションを作成しました"

    async def ensure_worker_window_exists(
        self, project_name: str, window_index: int, settings: Settings
    ) -> bool:
        """指定したWorkerウィンドウが存在することを確認し、なければ作成する。

        Args:
            project_name: プロジェクト名（セッション名の一部）
            window_index: ウィンドウインデックス（1以上：追加ウィンドウ）
            settings: 設定オブジェクト

        Returns:
            成功した場合True
        """
        # メインウィンドウ（0）は create_main_session で作成済み
        if window_index == 0:
            return True

        # 追加ウィンドウの作成
        return await self.tmux.add_extra_worker_window(
            project_name=project_name,
            window_index=window_index,
            rows=settings.extra_worker_rows,
            cols=settings.extra_worker_cols,
        )
