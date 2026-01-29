"""CostManagerのテスト。"""

from src.managers.cost_manager import CostManager


class TestCostManager:
    """CostManagerのテスト。"""

    def test_record_call(self, cost_manager):
        """API呼び出しを記録できることをテスト。"""
        cost_manager.record_call("claude")
        estimate = cost_manager.get_estimate()
        assert estimate.total_api_calls == 1
        assert estimate.claude_calls == 1

    def test_record_call_multiple_clis(self, cost_manager):
        """複数CLIの呼び出しを記録できることをテスト。"""
        cost_manager.record_call("claude")
        cost_manager.record_call("codex")
        cost_manager.record_call("gemini")

        estimate = cost_manager.get_estimate()
        assert estimate.total_api_calls == 3
        assert estimate.claude_calls == 1
        assert estimate.codex_calls == 1
        assert estimate.gemini_calls == 1

    def test_record_call_with_tokens(self, cost_manager):
        """トークン数指定でAPI呼び出しを記録できることをテスト。"""
        cost_manager.record_call("claude", estimated_tokens=5000)
        estimate = cost_manager.get_estimate()
        assert estimate.estimated_tokens == 5000

    def test_record_call_with_agent_id(self, cost_manager):
        """エージェントID付きで記録できることをテスト。"""
        cost_manager.record_call("claude", agent_id="agent-1")
        calls = cost_manager.get_calls_by_agent("agent-1")
        assert len(calls) == 1
        assert calls[0].agent_id == "agent-1"

    def test_record_call_with_task_id(self, cost_manager):
        """タスクID付きで記録できることをテスト。"""
        cost_manager.record_call("claude", task_id="task-1")
        calls = cost_manager.get_calls_by_task("task-1")
        assert len(calls) == 1
        assert calls[0].task_id == "task-1"

    def test_get_estimate_cost(self, cost_manager):
        """コスト推定が計算されることをテスト。"""
        cost_manager.record_call("claude", estimated_tokens=1000)
        estimate = cost_manager.get_estimate()

        # claude: $0.015/1K tokens
        assert estimate.estimated_cost_usd > 0

    def test_check_warning_below_threshold(self, cost_manager):
        """閾値以下で警告なしをテスト。"""
        cost_manager.record_call("claude")
        warning = cost_manager.check_warning()
        assert warning is None

    def test_check_warning_above_threshold(self, cost_manager):
        """閾値超過で警告が出ることをテスト。"""
        # 閾値を低く設定
        cost_manager.set_warning_threshold(0.01)

        # 大量のトークンを記録
        cost_manager.record_call("claude", estimated_tokens=10000)

        warning = cost_manager.check_warning()
        assert warning is not None
        assert "警告" in warning

    def test_set_warning_threshold(self, cost_manager):
        """警告閾値を設定できることをテスト。"""
        cost_manager.set_warning_threshold(50.0)
        assert cost_manager.warning_threshold == 50.0

    def test_set_cost_per_1k_tokens(self, cost_manager):
        """トークン単価を設定できることをテスト。"""
        cost_manager.set_cost_per_1k_tokens("claude", 0.02)
        assert cost_manager._cost_per_1k_tokens["claude"] == 0.02

    def test_reset(self, cost_manager):
        """記録リセットができることをテスト。"""
        cost_manager.record_call("claude")
        cost_manager.record_call("claude")
        count = cost_manager.reset()

        assert count == 2
        estimate = cost_manager.get_estimate()
        assert estimate.total_api_calls == 0

    def test_get_cost_by_agent(self, cost_manager):
        """エージェント別コストを取得できることをテスト。"""
        cost_manager.record_call("claude", estimated_tokens=1000, agent_id="agent-1")
        cost_manager.record_call("claude", estimated_tokens=2000, agent_id="agent-2")

        cost_agent_1 = cost_manager.get_cost_by_agent("agent-1")
        cost_agent_2 = cost_manager.get_cost_by_agent("agent-2")

        assert cost_agent_1 < cost_agent_2

    def test_get_cost_by_task(self, cost_manager):
        """タスク別コストを取得できることをテスト。"""
        cost_manager.record_call("claude", estimated_tokens=1000, task_id="task-1")
        cost_manager.record_call("codex", estimated_tokens=1000, task_id="task-1")

        cost = cost_manager.get_cost_by_task("task-1")
        assert cost > 0

    def test_get_summary(self, cost_manager):
        """サマリーを取得できることをテスト。"""
        cost_manager.record_call("claude")
        cost_manager.record_call("codex")

        summary = cost_manager.get_summary()
        assert summary["total_api_calls"] == 2
        assert "estimated_cost_usd" in summary
        assert "warning_threshold_usd" in summary
        assert "by_cli" in summary

    def test_get_detailed_breakdown(self, cost_manager):
        """詳細内訳を取得できることをテスト。"""
        cost_manager.record_call("claude", agent_id="agent-1", task_id="task-1")
        cost_manager.record_call("codex", agent_id="agent-2", task_id="task-2")

        breakdown = cost_manager.get_detailed_breakdown()
        assert "by_agent" in breakdown
        assert "by_task" in breakdown
        assert "by_cli" in breakdown
        assert "agent-1" in breakdown["by_agent"]
        assert "task-1" in breakdown["by_task"]

    def test_estimate_to_dict(self, cost_manager):
        """CostEstimate.to_dictが動作することをテスト。"""
        cost_manager.record_call("claude")
        estimate = cost_manager.get_estimate()
        d = estimate.to_dict()

        assert "total_api_calls" in d
        assert "estimated_cost_usd" in d
        assert "claude_calls" in d
