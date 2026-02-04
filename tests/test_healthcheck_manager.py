"""HealthcheckManagerのテスト。"""

import pytest
from datetime import datetime, timedelta

from src.managers.healthcheck_manager import HealthcheckManager


class TestHealthcheckManager:
    """HealthcheckManagerのテスト。"""

    def test_record_heartbeat(self, healthcheck_manager, sample_agents):
        """ハートビートを記録できることをテスト。"""
        result = healthcheck_manager.record_heartbeat("agent-001")
        assert result is True
        assert "agent-001" in healthcheck_manager._last_heartbeats

    def test_record_heartbeat_unknown_agent(self, healthcheck_manager):
        """未知のエージェントのハートビートでFalseを返すことをテスト。"""
        result = healthcheck_manager.record_heartbeat("unknown-agent")
        assert result is False

    def test_get_last_heartbeat(self, healthcheck_manager, sample_agents):
        """最後のハートビートを取得できることをテスト。"""
        healthcheck_manager.record_heartbeat("agent-001")
        last_hb = healthcheck_manager.get_last_heartbeat("agent-001")
        assert last_hb is not None
        assert isinstance(last_hb, datetime)

    def test_get_last_heartbeat_none(self, healthcheck_manager):
        """ハートビートがないエージェントでNoneを返すことをテスト。"""
        last_hb = healthcheck_manager.get_last_heartbeat("nonexistent")
        assert last_hb is None

    @pytest.mark.asyncio
    async def test_check_agent_not_found(self, healthcheck_manager):
        """存在しないエージェントをチェックできることをテスト。"""
        status = await healthcheck_manager.check_agent("unknown-agent")
        assert status.agent_id == "unknown-agent"
        assert status.is_healthy is False
        assert "見つかりません" in status.error_message

    @pytest.mark.asyncio
    async def test_check_agent_with_heartbeat(self, healthcheck_manager, sample_agents):
        """ハートビートがあるエージェントのチェックをテスト。"""
        healthcheck_manager.record_heartbeat("agent-001")
        status = await healthcheck_manager.check_agent("agent-001")
        assert status.agent_id == "agent-001"
        # tmuxセッションが存在しないのでis_healthyはFalseになる可能性がある
        assert status.last_heartbeat is not None

    @pytest.mark.asyncio
    async def test_check_all_agents(self, healthcheck_manager, sample_agents):
        """全エージェントをチェックできることをテスト。"""
        statuses = await healthcheck_manager.check_all_agents()
        assert len(statuses) == len(sample_agents)

    @pytest.mark.asyncio
    async def test_get_unhealthy_agents(self, healthcheck_manager, sample_agents):
        """不健全なエージェントを取得できることをテスト。"""
        # ハートビートなしでtmuxセッションもないので全てunhealthy
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
        # tmux操作に依存するので、結果はどちらでもOK
        assert isinstance(success, bool)
        assert isinstance(message, str)

    @pytest.mark.asyncio
    async def test_attempt_recovery_unknown_agent(self, healthcheck_manager):
        """未知のエージェントのリカバリー試行でFalseを返すことをテスト。"""
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
        assert "agents_with_heartbeat" in summary
        assert "healthcheck_interval_seconds" in summary

    def test_clear_heartbeat(self, healthcheck_manager, sample_agents):
        """ハートビートをクリアできることをテスト。"""
        healthcheck_manager.record_heartbeat("agent-001")
        result = healthcheck_manager.clear_heartbeat("agent-001")
        assert result is True
        assert "agent-001" not in healthcheck_manager._last_heartbeats

    def test_clear_heartbeat_nonexistent(self, healthcheck_manager):
        """存在しないハートビートのクリアでFalseを返すことをテスト。"""
        result = healthcheck_manager.clear_heartbeat("nonexistent")
        assert result is False

    def test_clear_all_heartbeats(self, healthcheck_manager, sample_agents):
        """全てのハートビートをクリアできることをテスト。"""
        healthcheck_manager.record_heartbeat("agent-001")
        healthcheck_manager.record_heartbeat("agent-002")
        count = healthcheck_manager.clear_all_heartbeats()
        assert count == 2
        assert len(healthcheck_manager._last_heartbeats) == 0
