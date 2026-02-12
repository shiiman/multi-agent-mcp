"""ダッシュボードコスト管理 Mixin。

DashboardManager のコスト関連メソッドを分離するための Mixin クラス。
"""

import logging
from datetime import datetime

from src.models.dashboard import ApiCallRecord, CostInfo, Dashboard

logger = logging.getLogger(__name__)


class DashboardCostMixin:
    """コスト管理メソッドを提供する Mixin クラス。

    DashboardManager と組み合わせて使用する。
    _read_dashboard() と _write_dashboard() は DashboardManager で定義される。
    """

    _SUPPORTED_COST_CLI_KEYS = ("claude", "codex", "gemini", "cursor")

    def record_api_call(
        self,
        ai_cli: str,
        model: str | None = None,
        estimated_tokens: int | None = None,
        agent_id: str | None = None,
        task_id: str | None = None,
        actual_cost_usd: float | None = None,
        status_line: str | None = None,
        cost_source: str | None = None,
    ) -> None:
        """API呼び出しを記録する。

        Args:
            ai_cli: 使用したAI CLI（claude/codex/gemini/cursor）
            model: 使用モデル
            estimated_tokens: 推定トークン数（Noneでデフォルト値）
            agent_id: エージェントID（オプション）
            task_id: タスクID（オプション）
            actual_cost_usd: 実測コスト（Claude の statusLine から抽出時のみ）
            status_line: コスト抽出元の statusLine
            cost_source: コスト種別（actual / estimated）
        """
        settings = self.settings
        normalized_cli = ai_cli.lower()
        tokens = estimated_tokens or settings.estimated_tokens_per_call
        estimated_cost = (tokens / 1000) * self._get_cost_per_1k_tokens(
            normalized_cli,
            model,
        )

        # 実測コストは Claude のみ許可
        source = (cost_source or ("actual" if actual_cost_usd is not None else "estimated")).lower()
        if normalized_cli != "claude" or source != "actual":
            actual_cost_usd = None
            status_line = None
            source = "estimated"

        def _record(dashboard: Dashboard) -> None:
            record = ApiCallRecord(
                ai_cli=normalized_cli,
                model=model,
                tokens=tokens,
                estimated_cost_usd=estimated_cost,
                actual_cost_usd=actual_cost_usd,
                cost_source=source,
                status_line=status_line,
                timestamp=datetime.now(),
                agent_id=agent_id,
                task_id=task_id,
            )
            dashboard.cost.calls.append(record)

            if (
                source == "actual"
                and actual_cost_usd is not None
                and agent_id
                and normalized_cli == "claude"
            ):
                dashboard.cost.actual_cost_by_agent[agent_id] = actual_cost_usd

            # 統計を再計算
            self._recalculate_cost_stats(dashboard)

        self.run_dashboard_transaction(_record)

        logger.debug(
            "API呼び出しを記録: %s (%s tokens, source=%s)",
            normalized_cli,
            tokens,
            source,
        )

    def _get_cost_per_1k_tokens(self, ai_cli: str, model: str | None) -> float:
        """モデル別の 1000 トークンあたりコストを取得する。"""
        settings = self.settings
        table = settings.get_model_cost_table()
        lookup_model = model
        if not lookup_model:
            defaults = settings.get_cli_default_models().get(ai_cli, {})
            lookup_model = defaults.get("worker")
        if lookup_model:
            key = f"{ai_cli}:{lookup_model}"
            if key in table:
                return table[key]
        return settings.model_cost_default_per_1k

    def _calculate_call_cost(self, call: ApiCallRecord) -> float:
        """単一 API 呼び出しのコストを計算する。"""
        rate = self._get_cost_per_1k_tokens(call.ai_cli.lower(), call.model)
        return (call.tokens / 1000) * rate

    def _count_calls_by_cli(self, calls: list[ApiCallRecord]) -> dict[str, int]:
        """CLI 別の呼び出し回数をカウントする。"""
        counts: dict[str, int] = {cli: 0 for cli in self._SUPPORTED_COST_CLI_KEYS}
        for call in calls:
            cli = call.ai_cli.lower()
            counts[cli] = counts.get(cli, 0) + 1
        return counts

    def _recalculate_cost_stats(self, dashboard: Dashboard) -> None:
        """コスト統計を再計算する（内部メソッド）。

        Args:
            dashboard: Dashboardオブジェクト
        """
        latest_actual_by_agent: dict[str, float] = {}
        for call in dashboard.cost.calls:
            if (
                call.ai_cli.lower() == "claude"
                and call.cost_source == "actual"
                and call.actual_cost_usd is not None
                and call.agent_id
            ):
                latest_actual_by_agent[call.agent_id] = call.actual_cost_usd

        # 実測値は通知回数ではなく agent ごとの最新スナップショットを採用する
        dashboard.cost.actual_cost_by_agent = latest_actual_by_agent

        dashboard.cost.total_api_calls = len(dashboard.cost.calls)
        dashboard.cost.estimated_tokens = sum(c.tokens for c in dashboard.cost.calls)
        dashboard.cost.estimated_cost_usd = sum(c.estimated_cost_usd for c in dashboard.cost.calls)
        dashboard.cost.actual_cost_usd = sum(latest_actual_by_agent.values())
        estimated_non_actual = sum(
            c.estimated_cost_usd for c in dashboard.cost.calls if c.cost_source != "actual"
        )
        dashboard.cost.total_cost_usd = dashboard.cost.actual_cost_usd + estimated_non_actual

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
            "actual_cost_usd": round(cost.actual_cost_usd, 4),
            "total_cost_usd": round(cost.total_cost_usd, 4),
            "claude_calls": cli_counts.get("claude", 0),
            "codex_calls": cli_counts.get("codex", 0),
            "gemini_calls": cli_counts.get("gemini", 0),
            "cursor_calls": cli_counts.get("cursor", 0),
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
            "actual_cost_usd": round(cost.actual_cost_usd, 4),
            "total_cost_usd": round(cost.total_cost_usd, 4),
            "warning_threshold_usd": cost.warning_threshold_usd,
            "warning_message": warning,
            "by_cli": {
                "claude": cli_counts.get("claude", 0),
                "codex": cli_counts.get("codex", 0),
                "gemini": cli_counts.get("gemini", 0),
                "cursor": cli_counts.get("cursor", 0),
            },
        }

    def check_cost_warning(self) -> str | None:
        """コスト警告をチェックする。

        Returns:
            警告メッセージ、警告なしならNone
        """
        dashboard = self._read_dashboard()
        cost = dashboard.cost

        if cost.total_cost_usd >= cost.warning_threshold_usd:
            return (
                f"警告: 合算コスト (${cost.total_cost_usd:.2f}) が "
                f"閾値 (${cost.warning_threshold_usd:.2f}) を超えています"
            )
        return None

    def set_cost_warning_threshold(self, threshold_usd: float) -> None:
        """コスト警告の閾値を設定する。

        Args:
            threshold_usd: 新しい閾値（USD）
        """

        def _set(dashboard: Dashboard) -> None:
            dashboard.cost.warning_threshold_usd = threshold_usd

        self.run_dashboard_transaction(_set)
        logger.info(f"コスト警告閾値を ${threshold_usd:.2f} に設定しました")

    def reset_cost_counter(self) -> int:
        """コスト記録をリセットする。

        Returns:
            削除した記録数
        """

        def _reset(dashboard: Dashboard) -> int:
            count = len(dashboard.cost.calls)
            dashboard.cost = CostInfo()
            return count

        count = self.run_dashboard_transaction(_reset)
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
        estimated_non_actual = sum(
            c.estimated_cost_usd
            for c in dashboard.cost.calls
            if c.agent_id == agent_id and c.cost_source != "actual"
        )
        return estimated_non_actual + dashboard.cost.actual_cost_by_agent.get(agent_id, 0.0)

    def get_cost_by_task(self, task_id: str) -> float:
        """タスク別のコストを取得する。

        Args:
            task_id: タスクID

        Returns:
            推定コスト（USD）
        """
        dashboard = self._read_dashboard()
        return sum(
            c.actual_cost_usd
            if c.cost_source == "actual" and c.actual_cost_usd is not None
            else c.estimated_cost_usd
            for c in dashboard.cost.calls
            if c.task_id == task_id
        )

    def get_cost_detailed_breakdown(self) -> dict:
        """詳細なコスト内訳を取得する。

        Returns:
            詳細内訳の辞書
        """
        dashboard = self._read_dashboard()

        by_agent_estimated_non_actual: dict[str, float] = {}
        by_task: dict[str, float] = {}
        by_cli: dict[str, dict] = {
            cli: {"calls": 0, "tokens": 0, "cost": 0.0} for cli in self._SUPPORTED_COST_CLI_KEYS
        }
        by_model: dict[str, dict] = {}

        for call in dashboard.cost.calls:
            call_cost = (
                call.actual_cost_usd
                if call.cost_source == "actual" and call.actual_cost_usd is not None
                else call.estimated_cost_usd
            )

            # エージェント別（estimated/non-actual のみ加算。actual は最新値を後で上書き）
            if call.agent_id and call.cost_source != "actual":
                by_agent_estimated_non_actual[call.agent_id] = (
                    by_agent_estimated_non_actual.get(call.agent_id, 0.0) + call_cost
                )

            # タスク別
            if call.task_id:
                by_task[call.task_id] = by_task.get(call.task_id, 0.0) + call_cost

            # CLI別
            cli = call.ai_cli.lower()
            cli_stats = by_cli.setdefault(cli, {"calls": 0, "tokens": 0, "cost": 0.0})
            cli_stats["calls"] += 1
            cli_stats["tokens"] += call.tokens
            cli_stats["cost"] += call_cost

            model_key = call.model or "unknown"
            if model_key not in by_model:
                by_model[model_key] = {"calls": 0, "tokens": 0, "cost": 0.0}
            by_model[model_key]["calls"] += 1
            by_model[model_key]["tokens"] += call.tokens
            by_model[model_key]["cost"] += call_cost

        by_agent: dict[str, float] = {}
        agent_ids = set(by_agent_estimated_non_actual.keys()) | set(
            dashboard.cost.actual_cost_by_agent.keys()
        )
        for agent_id in agent_ids:
            by_agent[agent_id] = by_agent_estimated_non_actual.get(
                agent_id, 0.0
            ) + dashboard.cost.actual_cost_by_agent.get(agent_id, 0.0)

        return {
            "by_agent": by_agent,
            "by_task": by_task,
            "by_cli": by_cli,
            "by_model": by_model,
        }
