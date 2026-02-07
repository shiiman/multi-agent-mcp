"""cost_capture.py のユニットテスト。"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.agent import Agent, AgentRole, AgentStatus
from src.tools.cost_capture import (
    capture_claude_actual_cost_for_agent,
    extract_claude_statusline_cost,
)


class TestExtractClaudeStatuslineCost:
    """extract_claude_statusline_cost のテスト。"""

    def test_extract_emoji_pattern(self):
        """💰 パターンからコストを抽出する。"""
        output = "some text\n💰 $12.34\nmore text"
        result = extract_claude_statusline_cost(output)
        assert result is not None
        assert result[0] == 12.34
        assert "💰" in result[1]

    def test_extract_cost_keyword_before_dollar(self):
        """Cost $X.XX パターンからコストを抽出する。"""
        output = "Cost: $5.67"
        result = extract_claude_statusline_cost(output)
        assert result is not None
        assert result[0] == 5.67

    def test_extract_cost_keyword_after_dollar(self):
        """$X.XX Cost パターンからコストを抽出する。"""
        output = "$3.21 COST"
        result = extract_claude_statusline_cost(output)
        assert result is not None
        assert result[0] == 3.21

    def test_no_cost_found_returns_none(self):
        """コスト情報がない場合は None を返す。"""
        output = "no cost information here\njust regular text"
        result = extract_claude_statusline_cost(output)
        assert result is None

    def test_empty_string_returns_none(self):
        """空文字列は None を返す。"""
        result = extract_claude_statusline_cost("")
        assert result is None

    def test_prefers_last_line_with_cost(self):
        """複数行にコスト情報がある場合、最後の行を優先する。"""
        output = "💰 $1.00\n💰 $2.00\n💰 $3.00"
        result = extract_claude_statusline_cost(output)
        assert result is not None
        assert result[0] == 3.00

    def test_integer_cost(self):
        """小数点なしの整数コストも抽出できる。"""
        output = "💰 $10"
        result = extract_claude_statusline_cost(output)
        assert result is not None
        assert result[0] == 10.0

    def test_zero_cost(self):
        """$0 のコストも抽出できる。"""
        output = "💰 $0"
        result = extract_claude_statusline_cost(output)
        assert result is not None
        assert result[0] == 0.0


class TestCaptureClaudeActualCostForAgent:
    """capture_claude_actual_cost_for_agent のテスト。"""

    def _make_worker_agent(self, ai_cli=None) -> Agent:
        """テスト用の Worker エージェントを作成する。"""
        now = datetime.now()
        return Agent(
            id="worker-001",
            role=AgentRole.WORKER,
            status=AgentStatus.BUSY,
            tmux_session="test:0.1",
            session_name="test",
            window_index=0,
            pane_index=1,
            working_dir="/tmp",
            created_at=now,
            last_activity=now,
            ai_cli=ai_cli,
            current_task="task-001",
        )

    def _make_app_ctx(self, capture_output="💰 $5.50"):
        """テスト用の app_ctx を作成する。"""
        app_ctx = MagicMock()
        app_ctx.tmux.capture_pane_by_index = AsyncMock(return_value=capture_output)
        app_ctx.ai_cli.get_default_cli.return_value = MagicMock(value="claude")
        app_ctx.settings.estimated_tokens_per_call = 4000
        app_ctx.settings.get_worker_model.return_value = "sonnet"

        # dashboard モック
        mock_dashboard = MagicMock()
        mock_cost = MagicMock()
        mock_cost.calls = []
        mock_dashboard.get_dashboard.return_value = MagicMock(cost=mock_cost)
        mock_dashboard.record_api_call = MagicMock()

        return app_ctx, mock_dashboard

    @pytest.mark.asyncio
    async def test_non_claude_cli_returns_none(self):
        """Claude 以外の CLI では None を返す。"""
        agent = self._make_worker_agent()
        agent.ai_cli = MagicMock(value="codex")
        app_ctx = MagicMock()

        result = await capture_claude_actual_cost_for_agent(app_ctx, agent)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_pane_info_returns_none(self):
        """pane 情報がない場合は None を返す。"""
        agent = self._make_worker_agent()
        agent.session_name = None
        app_ctx = MagicMock()
        app_ctx.ai_cli.get_default_cli.return_value = MagicMock(value="claude")

        result = await capture_claude_actual_cost_for_agent(app_ctx, agent)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_cost_in_output_returns_none(self):
        """出力にコスト情報がない場合は None を返す。"""
        agent = self._make_worker_agent()
        app_ctx, mock_dashboard = self._make_app_ctx(capture_output="no cost here")

        result = await capture_claude_actual_cost_for_agent(app_ctx, agent)
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_cost_capture(self):
        """正常なコストキャプチャが updated=True を返す。"""
        agent = self._make_worker_agent()
        app_ctx, mock_dashboard = self._make_app_ctx(capture_output="💰 $5.50")

        with (
            patch("src.tools.cost_capture.ensure_dashboard_manager", return_value=mock_dashboard),
            patch(
                "src.tools.cost_capture.get_current_profile_settings",
                return_value={"worker_model": "sonnet", "admin_model": "opus"},
            ),
        ):
            result = await capture_claude_actual_cost_for_agent(app_ctx, agent)

        assert result is not None
        assert result["updated"] is True
        assert result["actual_cost_usd"] == 5.50

    @pytest.mark.asyncio
    async def test_already_recorded_returns_not_updated(self):
        """既に記録済みのコストは updated=False を返す。"""
        agent = self._make_worker_agent()
        app_ctx, mock_dashboard = self._make_app_ctx(capture_output="💰 $5.50")

        # 既に記録済みのコールを設定
        mock_call = MagicMock()
        mock_call.agent_id = "worker-001"
        mock_call.status_line = "💰 $5.50"
        mock_cost = MagicMock()
        mock_cost.calls = [mock_call]
        mock_dashboard.get_dashboard.return_value = MagicMock(cost=mock_cost)

        with patch("src.tools.cost_capture.ensure_dashboard_manager", return_value=mock_dashboard):
            result = await capture_claude_actual_cost_for_agent(app_ctx, agent)

        assert result is not None
        assert result["updated"] is False
        assert result["actual_cost_usd"] == 5.50
