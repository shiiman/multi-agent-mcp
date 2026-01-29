"""MetricsManagerのテスト。"""

import tempfile
from pathlib import Path

from src.managers.metrics_manager import MetricsManager


class TestMetricsManager:
    """MetricsManagerのテスト。"""

    def test_start_task(self, metrics_manager):
        """タスク開始を記録できることをテスト。"""
        metrics_manager.start_task("task-1", "agent-1")
        metrics = metrics_manager.get_task_metrics("task-1")

        assert metrics is not None
        assert metrics.task_id == "task-1"
        assert metrics.agent_id == "agent-1"
        assert metrics.status == "in_progress"

    def test_complete_task_success(self, metrics_manager):
        """タスク成功を記録できることをテスト。"""
        metrics_manager.start_task("task-1", "agent-1")
        metrics_manager.complete_task("task-1", success=True)

        metrics = metrics_manager.get_task_metrics("task-1")
        assert metrics.status == "completed"
        assert metrics.completed_at is not None

    def test_complete_task_failure(self, metrics_manager):
        """タスク失敗を記録できることをテスト。"""
        metrics_manager.start_task("task-1", "agent-1")
        metrics_manager.complete_task("task-1", success=False)

        metrics = metrics_manager.get_task_metrics("task-1")
        assert metrics.status == "failed"

    def test_get_agent_metrics(self, metrics_manager):
        """エージェントメトリクスを取得できることをテスト。"""
        metrics_manager.start_task("task-1", "agent-1")
        metrics_manager.complete_task("task-1", success=True)

        agent_metrics = metrics_manager.get_agent_metrics("agent-1")
        assert agent_metrics.agent_id == "agent-1"
        assert agent_metrics.tasks_completed == 1

    def test_get_agent_metrics_with_failures(self, metrics_manager):
        """失敗を含むエージェントメトリクスをテスト。"""
        metrics_manager.start_task("task-1", "agent-1")
        metrics_manager.complete_task("task-1", success=True)
        metrics_manager.start_task("task-2", "agent-1")
        metrics_manager.complete_task("task-2", success=False)

        agent_metrics = metrics_manager.get_agent_metrics("agent-1")
        assert agent_metrics.tasks_completed == 1
        assert agent_metrics.tasks_failed == 1
        assert agent_metrics.success_rate == 0.5

    def test_get_workspace_metrics(self, metrics_manager, sample_agents):
        """ワークスペースメトリクスを取得できることをテスト。"""
        metrics_manager.start_task("task-1", "agent-1")
        metrics_manager.complete_task("task-1", success=True)
        metrics_manager.start_task("task-2", "agent-2")

        workspace_metrics = metrics_manager.get_workspace_metrics(sample_agents)
        assert workspace_metrics.total_tasks == 2
        assert workspace_metrics.completed_tasks == 1
        assert workspace_metrics.in_progress_tasks == 1

    def test_get_all_task_metrics(self, metrics_manager):
        """全タスクメトリクスを取得できることをテスト。"""
        metrics_manager.start_task("task-1", "agent-1")
        metrics_manager.start_task("task-2", "agent-2")

        all_metrics = metrics_manager.get_all_task_metrics()
        assert len(all_metrics) == 2

    def test_get_all_agent_metrics(self, metrics_manager):
        """全エージェントメトリクスを取得できることをテスト。"""
        metrics_manager.start_task("task-1", "agent-1")
        metrics_manager.complete_task("task-1", success=True)
        metrics_manager.start_task("task-2", "agent-2")
        metrics_manager.complete_task("task-2", success=True)

        all_metrics = metrics_manager.get_all_agent_metrics()
        assert len(all_metrics) == 2

    def test_export_to_json(self, metrics_manager):
        """JSONエクスポートができることをテスト。"""
        metrics_manager.start_task("task-1", "agent-1")
        metrics_manager.complete_task("task-1", success=True)

        json_str = metrics_manager.export_to_json()
        assert "task-1" in json_str
        assert "agent-1" in json_str

    def test_export_to_json_file(self, metrics_manager):
        """JSONファイルエクスポートができることをテスト。"""
        metrics_manager.start_task("task-1", "agent-1")

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "metrics.json"
            metrics_manager.export_to_json(str(filepath))
            assert filepath.exists()

    def test_export_to_csv(self, metrics_manager):
        """CSVエクスポートができることをテスト。"""
        metrics_manager.start_task("task-1", "agent-1")
        metrics_manager.complete_task("task-1", success=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "metrics.csv"
            metrics_manager.export_to_csv(str(filepath))
            assert filepath.exists()

            content = filepath.read_text()
            assert "task_id" in content
            assert "task-1" in content

    def test_reset(self, metrics_manager):
        """メトリクスリセットができることをテスト。"""
        metrics_manager.start_task("task-1", "agent-1")
        metrics_manager.reset()

        all_metrics = metrics_manager.get_all_task_metrics()
        assert len(all_metrics) == 0

    def test_get_summary(self, metrics_manager):
        """サマリーを取得できることをテスト。"""
        metrics_manager.start_task("task-1", "agent-1")
        metrics_manager.complete_task("task-1", success=True)
        metrics_manager.start_task("task-2", "agent-1")
        metrics_manager.complete_task("task-2", success=False)

        summary = metrics_manager.get_summary()
        assert summary["total_tasks"] == 2
        assert summary["completed_tasks"] == 1
        assert summary["failed_tasks"] == 1
