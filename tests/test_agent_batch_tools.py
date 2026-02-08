"""agent_batch_tools のユニットテスト。"""

from datetime import datetime

from src.models.agent import Agent, AgentRole, AgentStatus
from src.tools.agent_batch_tools import _validate_batch_capacity


def _make_worker_agent(
    agent_id="worker-001",
    status=AgentStatus.IDLE,
) -> Agent:
    now = datetime.now()
    return Agent(
        id=agent_id,
        role=AgentRole.WORKER,
        status=status,
        tmux_session="test:0.1",
        session_name="test",
        window_index=0,
        pane_index=1,
        working_dir="/tmp",
        created_at=now,
        last_activity=now,
    )


class TestValidateBatchCapacity:
    """_validate_batch_capacity のテスト。"""

    def test_excludes_terminated_from_capacity(self):
        """T19: TERMINATED Worker がキャパシティ計算から除外される。"""
        agents = {}
        # 2 IDLE Workers
        agents["w-1"] = _make_worker_agent("w-1", status=AgentStatus.IDLE)
        agents["w-2"] = _make_worker_agent("w-2", status=AgentStatus.IDLE)
        # 1 TERMINATED Worker（カウント対象外）
        agents["w-3"] = _make_worker_agent("w-3", status=AgentStatus.TERMINATED)

        worker_configs = [
            {"task_id": "t1", "task_content": "task 1"},
        ]

        # profile_max_workers=3 だが、TERMINATED を除外すると現在 2 名のため新規 1 名作成可能
        reusable, reuse_count, error = _validate_batch_capacity(
            agents, worker_configs, reuse_idle_workers=False, profile_max_workers=3
        )
        assert error is None
        assert reuse_count == 0

    def test_capacity_error_when_limit_reached(self):
        """TERMINATED を除外した後に上限に達している場合はエラーを返す。"""
        agents = {}
        # 3 IDLE Workers
        for i in range(1, 4):
            agents[f"w-{i}"] = _make_worker_agent(f"w-{i}", status=AgentStatus.IDLE)
        # 1 TERMINATED Worker（カウント対象外）
        agents["w-term"] = _make_worker_agent("w-term", status=AgentStatus.TERMINATED)

        worker_configs = [
            {"task_id": "t1", "task_content": "task 1"},
        ]

        # profile_max_workers=3 で実質 3 名稼働中のため新規作成不可
        reusable, reuse_count, error = _validate_batch_capacity(
            agents, worker_configs, reuse_idle_workers=False, profile_max_workers=3
        )
        assert error is not None
        assert "上限を超えます" in error["error"]
