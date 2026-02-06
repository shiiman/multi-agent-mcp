"""ダッシュボードコスト管理 Mixin。

DashboardManager のコスト関連メソッドを分離するための Mixin クラス。
"""

import logging
from datetime import datetime

from src.config.settings import Settings
from src.models.dashboard import ApiCallRecord, CostInfo, Dashboard

logger = logging.getLogger(__name__)


class DashboardCostMixin:
    """コスト管理メソッドを提供する Mixin クラス。

    DashboardManager と組み合わせて使用する。
    _read_dashboard() と _write_dashboard() は DashboardManager で定義される。
    """

    def record_api_call(
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
        settings = Settings()
        tokens = estimated_tokens or settings.estimated_tokens_per_call

        dashboard = self._read_dashboard()
        record = ApiCallRecord(
            ai_cli=ai_cli.lower(),
            tokens=tokens,
            timestamp=datetime.now(),
            agent_id=agent_id,
            task_id=task_id,
        )
        dashboard.cost.calls.append(record)

        # 統計を再計算
        self._recalculate_cost_stats(dashboard)
        self._write_dashboard(dashboard)

        logger.debug(f"API呼び出しを記録: {ai_cli} ({tokens} tokens)")

    def _get_cost_per_1k_tokens(self) -> dict[str, float]:
        """CLI 別の 1000 トークンあたりコストを取得する。"""
        settings = Settings()
        return {
            "claude": settings.cost_per_1k_tokens_claude,
            "codex": settings.cost_per_1k_tokens_codex,
            "gemini": settings.cost_per_1k_tokens_gemini,
        }

    def _calculate_call_cost(self, call: ApiCallRecord) -> float:
        """単一 API 呼び出しのコストを計算する。"""
        rates = self._get_cost_per_1k_tokens()
        rate = rates.get(call.ai_cli.lower(), 0.01)
        return (call.tokens / 1000) * rate

    def _count_calls_by_cli(self, calls: list[ApiCallRecord]) -> dict[str, int]:
        """CLI 別の呼び出し回数をカウントする。"""
        counts: dict[str, int] = {}
        for call in calls:
            cli = call.ai_cli.lower()
            counts[cli] = counts.get(cli, 0) + 1
        return counts

    def _recalculate_cost_stats(self, dashboard: Dashboard) -> None:
        """コスト統計を再計算する（内部メソッド）。

        Args:
            dashboard: Dashboardオブジェクト
        """
        dashboard.cost.total_api_calls = len(dashboard.cost.calls)
        dashboard.cost.estimated_tokens = sum(c.tokens for c in dashboard.cost.calls)
        dashboard.cost.estimated_cost_usd = sum(
            self._calculate_call_cost(c) for c in dashboard.cost.calls
        )

    def get_cost_estimate(self) -> dict:
        """コスト推定を取得する。

        Returns:
            コスト推定情報の辞書
        """
        dashboard = self._read_dashboard()
        cost = dashboard.cost
        cli_counts = self._count_calls_by_cli(cost.calls)

        return {
            "total_api_calls": cost.total_api_calls,
            "estimated_tokens": cost.estimated_tokens,
            "estimated_cost_usd": round(cost.estimated_cost_usd, 4),
            "claude_calls": cli_counts.get("claude", 0),
            "codex_calls": cli_counts.get("codex", 0),
            "gemini_calls": cli_counts.get("gemini", 0),
        }

    def get_cost_summary(self) -> dict:
        """コストサマリーを取得する。

        Returns:
            サマリー情報の辞書
        """
        dashboard = self._read_dashboard()
        cost = dashboard.cost
        warning = self.check_cost_warning()
        cli_counts = self._count_calls_by_cli(cost.calls)

        return {
            "total_api_calls": cost.total_api_calls,
            "estimated_tokens": cost.estimated_tokens,
            "estimated_cost_usd": round(cost.estimated_cost_usd, 4),
            "warning_threshold_usd": cost.warning_threshold_usd,
            "warning_message": warning,
            "by_cli": {
                "claude": cli_counts.get("claude", 0),
                "codex": cli_counts.get("codex", 0),
                "gemini": cli_counts.get("gemini", 0),
            },
        }

    def check_cost_warning(self) -> str | None:
        """コスト警告をチェックする。

        Returns:
            警告メッセージ、警告なしならNone
        """
        dashboard = self._read_dashboard()
        cost = dashboard.cost

        if cost.estimated_cost_usd >= cost.warning_threshold_usd:
            return (
                f"警告: 推定コスト (${cost.estimated_cost_usd:.2f}) が "
                f"閾値 (${cost.warning_threshold_usd:.2f}) を超えています"
            )
        return None

    def set_cost_warning_threshold(self, threshold_usd: float) -> None:
        """コスト警告の閾値を設定する。

        Args:
            threshold_usd: 新しい閾値（USD）
        """
        dashboard = self._read_dashboard()
        dashboard.cost.warning_threshold_usd = threshold_usd
        self._write_dashboard(dashboard)
        logger.info(f"コスト警告閾値を ${threshold_usd:.2f} に設定しました")

    def reset_cost_counter(self) -> int:
        """コスト記録をリセットする。

        Returns:
            削除した記録数
        """
        dashboard = self._read_dashboard()
        count = len(dashboard.cost.calls)
        dashboard.cost = CostInfo()
        self._write_dashboard(dashboard)
        logger.info(f"コスト記録をリセットしました（{count} 件削除）")
        return count

    def get_cost_by_agent(self, agent_id: str) -> float:
        """エージェント別のコストを取得する。

        Args:
            agent_id: エージェントID

        Returns:
            推定コスト（USD）
        """
        dashboard = self._read_dashboard()
        return sum(
            self._calculate_call_cost(c)
            for c in dashboard.cost.calls
            if c.agent_id == agent_id
        )

    def get_cost_by_task(self, task_id: str) -> float:
        """タスク別のコストを取得する。

        Args:
            task_id: タスクID

        Returns:
            推定コスト（USD）
        """
        dashboard = self._read_dashboard()
        return sum(
            self._calculate_call_cost(c)
            for c in dashboard.cost.calls
            if c.task_id == task_id
        )

    def get_cost_detailed_breakdown(self) -> dict:
        """詳細なコスト内訳を取得する。

        Returns:
            詳細内訳の辞書
        """
        dashboard = self._read_dashboard()

        by_agent: dict[str, float] = {}
        by_task: dict[str, float] = {}
        by_cli: dict[str, dict] = {}

        for call in dashboard.cost.calls:
            call_cost = self._calculate_call_cost(call)

            # エージェント別
            if call.agent_id:
                by_agent[call.agent_id] = by_agent.get(call.agent_id, 0.0) + call_cost

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
