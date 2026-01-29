"""ヘルスチェックマネージャー。

エージェントの死活監視を行い、異常を検出したら通知・復旧する。
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
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

    last_heartbeat: datetime | None
    """最後のハートビート時刻"""

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
            "last_heartbeat": (
                self.last_heartbeat.isoformat() if self.last_heartbeat else None
            ),
            "tmux_session_alive": self.tmux_session_alive,
            "error_message": self.error_message,
        }


class HealthcheckManager:
    """エージェントのヘルスチェックを管理する。

    定期的なハートビートの確認と、tmuxセッションの死活監視を行う。
    """

    def __init__(
        self,
        tmux_manager: "TmuxManager",
        agents: dict[str, "Agent"],
        heartbeat_timeout_seconds: int = 300,
    ) -> None:
        """HealthcheckManagerを初期化する。

        Args:
            tmux_manager: tmuxマネージャー
            agents: エージェントの辞書（agent_id -> Agent）
            heartbeat_timeout_seconds: ハートビートタイムアウト（秒）
        """
        self.tmux_manager = tmux_manager
        self.agents = agents
        self.heartbeat_timeout = timedelta(seconds=heartbeat_timeout_seconds)
        self._last_heartbeats: dict[str, datetime] = {}

    def record_heartbeat(self, agent_id: str) -> bool:
        """ハートビートを記録する。

        Args:
            agent_id: エージェントID

        Returns:
            成功した場合True
        """
        if agent_id not in self.agents:
            logger.warning(f"未知のエージェント {agent_id} からのハートビート")
            return False

        self._last_heartbeats[agent_id] = datetime.now()
        logger.debug(f"エージェント {agent_id} のハートビートを記録")
        return True

    def get_last_heartbeat(self, agent_id: str) -> datetime | None:
        """最後のハートビート時刻を取得する。

        Args:
            agent_id: エージェントID

        Returns:
            最後のハートビート時刻、なければNone
        """
        return self._last_heartbeats.get(agent_id)

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
                last_heartbeat=None,
                tmux_session_alive=False,
                error_message="エージェントが見つかりません",
            )

        # tmuxセッション確認
        tmux_alive = await self.tmux_manager.session_exists(agent.tmux_session)

        # ハートビート確認
        last_hb = self._last_heartbeats.get(agent_id)
        hb_timeout = False
        if last_hb:
            hb_timeout = datetime.now() - last_hb > self.heartbeat_timeout
        else:
            # ハートビートが一度も記録されていない場合
            # 作成からタイムアウト時間が経過していればタイムアウトとする
            if datetime.now() - agent.created_at > self.heartbeat_timeout:
                hb_timeout = True

        is_healthy = tmux_alive and not hb_timeout

        error_message = None
        if not is_healthy:
            error_message = self._get_error_message(tmux_alive, hb_timeout)

        return HealthStatus(
            agent_id=agent_id,
            is_healthy=is_healthy,
            last_heartbeat=last_hb,
            tmux_session_alive=tmux_alive,
            error_message=error_message,
        )

    def _get_error_message(self, tmux_alive: bool, hb_timeout: bool) -> str:
        """エラーメッセージを生成する。

        Args:
            tmux_alive: tmuxセッションが生きているか
            hb_timeout: ハートビートタイムアウトか

        Returns:
            エラーメッセージ
        """
        errors = []
        if not tmux_alive:
            errors.append("tmuxセッションが見つかりません")
        if hb_timeout:
            errors.append("ハートビートタイムアウト")
        return ", ".join(errors)

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

        # tmuxセッションが死んでいる場合は再作成
        if not status.tmux_session_alive:
            logger.info(f"エージェント {agent_id} のtmuxセッションを再作成します")
            # worktree_path があればそこで、なければ現在のディレクトリで作成
            working_dir = agent.worktree_path or "."
            success = await self.tmux_manager.create_session(
                agent.tmux_session, working_dir
            )
            if success:
                # ハートビートをリセット
                self._last_heartbeats[agent_id] = datetime.now()
                return True, f"エージェント {agent_id} のtmuxセッションを再作成しました"
            else:
                return False, f"エージェント {agent_id} のtmuxセッション再作成に失敗しました"

        # ハートビートタイムアウトの場合
        # ハートビートをリセットして様子を見る
        self._last_heartbeats[agent_id] = datetime.now()
        return True, f"エージェント {agent_id} のハートビートをリセットしました"

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
            "agents_with_heartbeat": len(self._last_heartbeats),
            "heartbeat_timeout_seconds": self.heartbeat_timeout.total_seconds(),
        }

    def clear_heartbeat(self, agent_id: str) -> bool:
        """エージェントのハートビートをクリアする。

        Args:
            agent_id: エージェントID

        Returns:
            成功した場合True
        """
        if agent_id in self._last_heartbeats:
            del self._last_heartbeats[agent_id]
            return True
        return False

    def clear_all_heartbeats(self) -> int:
        """全てのハートビートをクリアする。

        Returns:
            クリアした数
        """
        count = len(self._last_heartbeats)
        self._last_heartbeats.clear()
        return count
