"""コスト推定マネージャー。

API呼び出し回数を追跡し、コストを推定・警告する。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config.settings import AICli

logger = logging.getLogger(__name__)


# 概算コスト（1000トークンあたり、USD）
COST_PER_1K_TOKENS: dict[str, float] = {
    "claude": 0.015,  # Claude Sonnet 概算
    "codex": 0.01,    # OpenAI Codex 概算
    "gemini": 0.005,  # Gemini Pro 概算
}

# 1回のAPI呼び出しあたりの推定トークン数
ESTIMATED_TOKENS_PER_CALL = 2000


@dataclass
class CostEstimate:
    """コスト推定結果。"""

    total_api_calls: int = 0
    """総API呼び出し回数"""

    estimated_tokens: int = 0
    """推定総トークン数"""

    estimated_cost_usd: float = 0.0
    """推定総コスト（USD）"""

    # モデル別カウント
    claude_calls: int = 0
    """Claude呼び出し回数"""

    codex_calls: int = 0
    """Codex呼び出し回数"""

    gemini_calls: int = 0
    """Gemini呼び出し回数"""

    def to_dict(self) -> dict:
        """辞書に変換する。

        Returns:
            コスト推定の辞書表現
        """
        return {
            "total_api_calls": self.total_api_calls,
            "estimated_tokens": self.estimated_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
            "claude_calls": self.claude_calls,
            "codex_calls": self.codex_calls,
            "gemini_calls": self.gemini_calls,
        }


@dataclass
class ApiCallRecord:
    """API呼び出し記録。"""

    ai_cli: str
    """使用したAI CLI"""

    tokens: int
    """推定トークン数"""

    timestamp: datetime
    """呼び出し時刻"""

    agent_id: str | None = None
    """エージェントID（オプション）"""

    task_id: str | None = None
    """タスクID（オプション）"""


class CostManager:
    """API呼び出しコストを推定・管理するマネージャー。"""

    def __init__(self, warning_threshold_usd: float = 10.0) -> None:
        """CostManagerを初期化する。

        Args:
            warning_threshold_usd: コスト警告の閾値（USD）
        """
        self.warning_threshold = warning_threshold_usd
        self._calls: list[ApiCallRecord] = []
        self._cost_per_1k_tokens = COST_PER_1K_TOKENS.copy()

    def record_call(
        self,
        ai_cli: str,
        estimated_tokens: int | None = None,
        agent_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        """API呼び出しを記録する。

        Args:
            ai_cli: 使用したAI CLI（claude/codex/gemini）
            estimated_tokens: 推定トークン数（Noneでデフォルト値）
            agent_id: エージェントID（オプション）
            task_id: タスクID（オプション）
        """
        tokens = estimated_tokens or ESTIMATED_TOKENS_PER_CALL
        record = ApiCallRecord(
            ai_cli=ai_cli.lower(),
            tokens=tokens,
            timestamp=datetime.now(),
            agent_id=agent_id,
            task_id=task_id,
        )
        self._calls.append(record)
        logger.debug(
            f"API呼び出しを記録: {ai_cli} ({tokens} tokens)"
        )

    def get_estimate(self) -> CostEstimate:
        """コスト推定を取得する。

        Returns:
            コスト推定結果
        """
        estimate = CostEstimate()

        for call in self._calls:
            estimate.total_api_calls += 1
            estimate.estimated_tokens += call.tokens

            ai_cli = call.ai_cli.lower()
            if ai_cli == "claude":
                estimate.claude_calls += 1
            elif ai_cli == "codex":
                estimate.codex_calls += 1
            elif ai_cli == "gemini":
                estimate.gemini_calls += 1

            cost_per_1k = self._cost_per_1k_tokens.get(ai_cli, 0.01)
            estimate.estimated_cost_usd += (call.tokens / 1000) * cost_per_1k

        return estimate

    def check_warning(self) -> str | None:
        """コスト警告をチェックする。

        Returns:
            警告メッセージ、警告なしならNone
        """
        estimate = self.get_estimate()
        if estimate.estimated_cost_usd >= self.warning_threshold:
            return (
                f"警告: 推定コスト (${estimate.estimated_cost_usd:.2f}) が "
                f"閾値 (${self.warning_threshold:.2f}) を超えています"
            )
        return None

    def set_warning_threshold(self, threshold_usd: float) -> None:
        """コスト警告の閾値を設定する。

        Args:
            threshold_usd: 新しい閾値（USD）
        """
        self.warning_threshold = threshold_usd
        logger.info(f"コスト警告閾値を ${threshold_usd:.2f} に設定しました")

    def set_cost_per_1k_tokens(self, ai_cli: str, cost: float) -> None:
        """1000トークンあたりのコストを設定する。

        Args:
            ai_cli: AI CLI名
            cost: 1000トークンあたりのコスト（USD）
        """
        self._cost_per_1k_tokens[ai_cli.lower()] = cost
        logger.info(f"{ai_cli} のコストを ${cost:.4f}/1K tokens に設定しました")

    def reset(self) -> int:
        """呼び出し記録をリセットする。

        Returns:
            削除した記録数
        """
        count = len(self._calls)
        self._calls.clear()
        logger.info(f"コスト記録をリセットしました（{count} 件削除）")
        return count

    def get_calls_by_agent(self, agent_id: str) -> list[ApiCallRecord]:
        """エージェント別の呼び出し記録を取得する。

        Args:
            agent_id: エージェントID

        Returns:
            呼び出し記録のリスト
        """
        return [c for c in self._calls if c.agent_id == agent_id]

    def get_calls_by_task(self, task_id: str) -> list[ApiCallRecord]:
        """タスク別の呼び出し記録を取得する。

        Args:
            task_id: タスクID

        Returns:
            呼び出し記録のリスト
        """
        return [c for c in self._calls if c.task_id == task_id]

    def get_cost_by_agent(self, agent_id: str) -> float:
        """エージェント別のコストを取得する。

        Args:
            agent_id: エージェントID

        Returns:
            推定コスト（USD）
        """
        calls = self.get_calls_by_agent(agent_id)
        cost = 0.0
        for call in calls:
            cost_per_1k = self._cost_per_1k_tokens.get(call.ai_cli.lower(), 0.01)
            cost += (call.tokens / 1000) * cost_per_1k
        return cost

    def get_cost_by_task(self, task_id: str) -> float:
        """タスク別のコストを取得する。

        Args:
            task_id: タスクID

        Returns:
            推定コスト（USD）
        """
        calls = self.get_calls_by_task(task_id)
        cost = 0.0
        for call in calls:
            cost_per_1k = self._cost_per_1k_tokens.get(call.ai_cli.lower(), 0.01)
            cost += (call.tokens / 1000) * cost_per_1k
        return cost

    def get_summary(self) -> dict:
        """コストサマリーを取得する。

        Returns:
            サマリー情報の辞書
        """
        estimate = self.get_estimate()
        warning = self.check_warning()

        return {
            "total_api_calls": estimate.total_api_calls,
            "estimated_tokens": estimate.estimated_tokens,
            "estimated_cost_usd": round(estimate.estimated_cost_usd, 4),
            "warning_threshold_usd": self.warning_threshold,
            "warning_message": warning,
            "by_cli": {
                "claude": estimate.claude_calls,
                "codex": estimate.codex_calls,
                "gemini": estimate.gemini_calls,
            },
        }

    def get_detailed_breakdown(self) -> dict:
        """詳細なコスト内訳を取得する。

        Returns:
            詳細内訳の辞書
        """
        by_agent: dict[str, float] = {}
        by_task: dict[str, float] = {}
        by_cli: dict[str, dict] = {}

        for call in self._calls:
            cost_per_1k = self._cost_per_1k_tokens.get(call.ai_cli.lower(), 0.01)
            call_cost = (call.tokens / 1000) * cost_per_1k

            # エージェント別
            if call.agent_id:
                by_agent[call.agent_id] = (
                    by_agent.get(call.agent_id, 0.0) + call_cost
                )

            # タスク別
            if call.task_id:
                by_task[call.task_id] = by_task.get(call.task_id, 0.0) + call_cost

            # CLI別
            cli = call.ai_cli.lower()
            if cli not in by_cli:
                by_cli[cli] = {"calls": 0, "tokens": 0, "cost": 0.0}
            by_cli[cli]["calls"] += 1
            by_cli[cli]["tokens"] += call.tokens
            by_cli[cli]["cost"] += call_cost

        return {
            "by_agent": by_agent,
            "by_task": by_task,
            "by_cli": by_cli,
        }
