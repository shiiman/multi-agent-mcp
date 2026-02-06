"""ヘルスチェックマネージャー。

エージェントの死活監視を行い、異常を検出したら通知・復旧する。
tmux セッションの存在確認のみで健全性を判断する。
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.managers.tmux_manager import TmuxManager
    from src.models.agent import Agent

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """エージェントのヘルス状態。"""

    agent_id: str
    """エージェントID"""

    is_healthy: bool
    """健全かどうか"""

    tmux_session_alive: bool
    """tmuxセッションが生きているか"""

    error_message: str | None = None
    """エラーメッセージ"""

    def to_dict(self) -> dict:
        """辞書に変換する。

        Returns:
            ヘルス状態の辞書表現
        """
        return {
            "agent_id": self.agent_id,
            "is_healthy": self.is_healthy,
            "tmux_session_alive": self.tmux_session_alive,
            "error_message": self.error_message,
        }


class HealthcheckManager:
    """エージェントのヘルスチェックを管理する。

    tmux セッションの死活監視のみで健全性を判断する。
    """

    def __init__(
        self,
        tmux_manager: "TmuxManager",
        agents: dict[str, "Agent"],
        healthcheck_interval_seconds: int = 60,
    ) -> None:
        """HealthcheckManagerを初期化する。

        Args:
            tmux_manager: tmuxマネージャー
            agents: エージェントの辞書（agent_id -> Agent）
            healthcheck_interval_seconds: ヘルスチェック間隔（秒）。現在は使用されていないが、
                                          将来的な定期チェック用に保持。
        """
        self.tmux_manager = tmux_manager
        self.agents = agents
        self.healthcheck_interval_seconds = healthcheck_interval_seconds

    @staticmethod
    def _resolve_session_name(agent: "Agent") -> str | None:
        """Agent から tmux のセッション名を解決する。"""
        if getattr(agent, "session_name", None):
            return agent.session_name

        tmux_session = getattr(agent, "tmux_session", None)
        if tmux_session:
            return str(tmux_session).split(":", 1)[0]
        return None

    async def check_agent(self, agent_id: str) -> HealthStatus:
        """単一エージェントのヘルスチェックを行う。

        Args:
            agent_id: エージェントID

        Returns:
            ヘルス状態
        """
        agent = self.agents.get(agent_id)
        if not agent:
            return HealthStatus(
                agent_id=agent_id,
                is_healthy=False,
                tmux_session_alive=False,
                error_message="エージェントが見つかりません",
            )

        # tmux セッション確認のみで健全性を判断
        session_name = self._resolve_session_name(agent)
        if not session_name:
            return HealthStatus(
                agent_id=agent_id,
                is_healthy=False,
                tmux_session_alive=False,
                error_message="tmux セッション情報が未設定です",
            )

        tmux_alive = await self.tmux_manager.session_exists(session_name)

        is_healthy = tmux_alive
        error_message = None if is_healthy else "tmux セッションが見つかりません"

        return HealthStatus(
            agent_id=agent_id,
            is_healthy=is_healthy,
            tmux_session_alive=tmux_alive,
            error_message=error_message,
        )

    async def check_all_agents(self) -> list[HealthStatus]:
        """全エージェントのヘルスチェックを行う。

        Returns:
            ヘルス状態のリスト
        """
        statuses = []
        for agent_id in self.agents:
            status = await self.check_agent(agent_id)
            statuses.append(status)
        return statuses

    async def get_unhealthy_agents(self) -> list[HealthStatus]:
        """異常なエージェント一覧を取得する。

        Returns:
            異常なエージェントのヘルス状態リスト
        """
        all_status = await self.check_all_agents()
        return [s for s in all_status if not s.is_healthy]

    async def get_healthy_agents(self) -> list[HealthStatus]:
        """健全なエージェント一覧を取得する。

        Returns:
            健全なエージェントのヘルス状態リスト
        """
        all_status = await self.check_all_agents()
        return [s for s in all_status if s.is_healthy]

    async def attempt_recovery(self, agent_id: str) -> tuple[bool, str]:
        """エージェントの復旧を試みる。

        tmux セッションが死んでいる場合は再作成する。

        Args:
            agent_id: エージェントID

        Returns:
            (成功したか, メッセージ) のタプル
        """
        status = await self.check_agent(agent_id)

        if status.is_healthy:
            return True, f"エージェント {agent_id} は既に健全です"

        agent = self.agents.get(agent_id)
        if not agent:
            return False, f"エージェント {agent_id} が見つかりません"

        # tmux セッションを再作成
        logger.info(f"エージェント {agent_id} の tmux セッションを再作成します")
        working_dir = agent.worktree_path or "."
        session_name = self._resolve_session_name(agent)
        if not session_name:
            return False, f"エージェント {agent_id} の tmux セッション情報がありません"
        success = await self.tmux_manager.create_session(
            session_name, working_dir
        )
        if success:
            return True, f"エージェント {agent_id} の tmux セッションを再作成しました"
        else:
            return False, f"エージェント {agent_id} の tmux セッション再作成に失敗しました"

    async def attempt_recovery_all(self) -> list[tuple[str, bool, str]]:
        """全ての異常なエージェントの復旧を試みる。

        Returns:
            (agent_id, 成功したか, メッセージ) のリスト
        """
        unhealthy = await self.get_unhealthy_agents()
        results = []
        for status in unhealthy:
            success, message = await self.attempt_recovery(status.agent_id)
            results.append((status.agent_id, success, message))
        return results

    def get_summary(self) -> dict:
        """ヘルスチェックのサマリーを取得する。

        Returns:
            サマリー情報の辞書
        """
        return {
            "total_agents": len(self.agents),
            "healthcheck_interval_seconds": self.healthcheck_interval_seconds,
        }
