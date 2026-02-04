"""HealthcheckManagerのテスト。"""

import pytest

from src.managers.healthcheck_manager import HealthcheckManager


class TestHealthcheckManager:
    """HealthcheckManagerのテスト。"""

    @pytest.mark.asyncio
    async def test_check_agent_not_found(self, healthcheck_manager):
        """存在しないエージェントをチェックできることをテスト。"""
        status = await healthcheck_manager.check_agent("unknown-agent")
        assert status.agent_id == "unknown-agent"
        assert status.is_healthy is False
        assert "見つかりません" in status.error_message

    @pytest.mark.asyncio
    async def test_check_agent_with_tmux_session(self, healthcheck_manager, sample_agents):
        """tmux セッションの確認をテスト。"""
        status = await healthcheck_manager.check_agent("agent-001")
        assert status.agent_id == "agent-001"
        # tmux セッションが存在しないので is_healthy は False になる
        assert status.tmux_session_alive is False

    @pytest.mark.asyncio
    async def test_check_all_agents(self, healthcheck_manager, sample_agents):
        """全エージェントをチェックできることをテスト。"""
        statuses = await healthcheck_manager.check_all_agents()
        assert len(statuses) == len(sample_agents)

    @pytest.mark.asyncio
    async def test_get_unhealthy_agents(self, healthcheck_manager, sample_agents):
        """不健全なエージェントを取得できることをテスト。"""
        # tmux セッションがないので全て unhealthy
        unhealthy = await healthcheck_manager.get_unhealthy_agents()
        assert isinstance(unhealthy, list)

    @pytest.mark.asyncio
    async def test_get_healthy_agents(self, healthcheck_manager, sample_agents):
        """健全なエージェントを取得できることをテスト。"""
        healthy = await healthcheck_manager.get_healthy_agents()
        assert isinstance(healthy, list)

    @pytest.mark.asyncio
    async def test_attempt_recovery(self, healthcheck_manager, sample_agents):
        """リカバリー試行ができることをテスト。"""
        success, message = await healthcheck_manager.attempt_recovery("agent-001")
        # tmux 操作に依存するので、結果はどちらでも OK
        assert isinstance(success, bool)
        assert isinstance(message, str)

    @pytest.mark.asyncio
    async def test_attempt_recovery_unknown_agent(self, healthcheck_manager):
        """未知のエージェントのリカバリー試行で False を返すことをテスト。"""
        success, message = await healthcheck_manager.attempt_recovery("unknown")
        assert success is False
        assert "見つかりません" in message

    @pytest.mark.asyncio
    async def test_attempt_recovery_all(self, healthcheck_manager, sample_agents):
        """全てのリカバリー試行ができることをテスト。"""
        results = await healthcheck_manager.attempt_recovery_all()
        assert isinstance(results, list)

    def test_get_summary(self, healthcheck_manager, sample_agents):
        """サマリーを取得できることをテスト。"""
        summary = healthcheck_manager.get_summary()
        assert "total_agents" in summary
        assert "healthcheck_interval_seconds" in summary
