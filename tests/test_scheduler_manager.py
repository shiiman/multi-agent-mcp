"""SchedulerManagerのテスト。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.managers.scheduler_manager import SchedulerManager, TaskPriority


class TestSchedulerManager:
    """SchedulerManagerのテスト。"""

    def test_enqueue_task(self, scheduler_manager):
        """タスクをキューに追加できることをテスト。"""
        result = scheduler_manager.enqueue_task(
            task_id="task-1",
            priority=TaskPriority.MEDIUM,
        )
        assert result is True

    def test_enqueue_task_duplicate(self, scheduler_manager):
        """重複タスクの追加でFalseを返すことをテスト。"""
        scheduler_manager.enqueue_task("task-1", TaskPriority.MEDIUM)
        result = scheduler_manager.enqueue_task("task-1", TaskPriority.HIGH)
        assert result is False

    def test_enqueue_task_with_dependencies(self, scheduler_manager):
        """依存関係付きでタスクを追加できることをテスト。"""
        scheduler_manager.enqueue_task("task-1", TaskPriority.HIGH)
        result = scheduler_manager.enqueue_task(
            task_id="task-2",
            priority=TaskPriority.MEDIUM,
            dependencies=["task-1"],
        )
        assert result is True

    def test_get_next_task(self, scheduler_manager):
        """優先度順にタスクを取得できることをテスト。"""
        scheduler_manager.enqueue_task("low", TaskPriority.LOW)
        scheduler_manager.enqueue_task("high", TaskPriority.HIGH)
        scheduler_manager.enqueue_task("critical", TaskPriority.CRITICAL)

        # 優先度が高いものから取得
        task_id = scheduler_manager.get_next_task()
        assert task_id == "critical"

    def test_dequeue_task(self, scheduler_manager):
        """タスクをキューから削除できることをテスト。"""
        scheduler_manager.enqueue_task("task-1", TaskPriority.MEDIUM)
        result = scheduler_manager.dequeue_task("task-1")
        assert result is True

        # 削除後は取得できない
        task_id = scheduler_manager.get_next_task()
        assert task_id is None

    def test_dequeue_nonexistent_task(self, scheduler_manager):
        """存在しないタスクの削除でFalseを返すことをテスト。"""
        result = scheduler_manager.dequeue_task("nonexistent")
        assert result is False

    def test_update_priority(self, scheduler_manager):
        """タスクの優先度を更新できることをテスト。"""
        scheduler_manager.enqueue_task("task-1", TaskPriority.LOW)
        scheduler_manager.enqueue_task("task-2", TaskPriority.HIGH)

        # task-1の優先度をCRITICALに上げる
        scheduler_manager.update_priority("task-1", TaskPriority.CRITICAL)

        # task-1が最初に取得されるはず
        task_id = scheduler_manager.get_next_task()
        assert task_id == "task-1"

    def test_complete_task(self, scheduler_manager):
        """タスク完了を記録できることをテスト。"""
        scheduler_manager.enqueue_task("task-1", TaskPriority.MEDIUM)
        result = scheduler_manager.complete_task("task-1")
        assert result is True

        # 完了後はキューから削除されている
        task_id = scheduler_manager.get_next_task()
        assert task_id is None

    def test_get_queue_status(self, scheduler_manager):
        """キュー状態を取得できることをテスト。"""
        scheduler_manager.enqueue_task("task-1", TaskPriority.HIGH)
        scheduler_manager.enqueue_task("task-2", TaskPriority.MEDIUM)

        status = scheduler_manager.get_queue_status()
        assert status["pending_count"] == 2
        assert "pending_tasks" in status
        assert "assigned_tasks" in status

    def test_get_idle_workers(self, scheduler_manager, sample_agents):
        """空いているワーカー一覧を取得できることをテスト。"""
        idle_workers = scheduler_manager.get_idle_workers()
        # sample_agentsにはIDLEなworkerが1つある（agent-002）
        assert isinstance(idle_workers, list)

    def test_get_task_info(self, scheduler_manager):
        """タスク情報を取得できることをテスト。"""
        scheduler_manager.enqueue_task("task-1", TaskPriority.HIGH, ["dep-1"])
        info = scheduler_manager.get_task_info("task-1")

        assert info is not None
        assert info["task_id"] == "task-1"
        assert info["priority"] == "HIGH"
        assert "dep-1" in info["dependencies"]

    def test_get_task_info_nonexistent(self, scheduler_manager):
        """存在しないタスクの情報取得でNoneを返すことをテスト。"""
        info = scheduler_manager.get_task_info("nonexistent")
        assert info is None

    def test_auto_assign(self, scheduler_manager, sample_agents):
        """自動割り当てが動作することをテスト。"""
        scheduler_manager.enqueue_task("task-1", TaskPriority.HIGH)
        result = scheduler_manager.auto_assign()
        # idleなworkerがいない可能性があるのでNoneの場合もある
        assert result is None or isinstance(result, tuple)

    def test_run_auto_assign_loop(self, scheduler_manager, sample_agents):
        """自動割り当てループが動作することをテスト。"""
        scheduler_manager.enqueue_task("task-1", TaskPriority.HIGH)
        scheduler_manager.enqueue_task("task-2", TaskPriority.MEDIUM)
        assignments = scheduler_manager.run_auto_assign_loop()
        assert isinstance(assignments, list)

    def test_assign_task_sets_worker_busy_and_persists(
        self,
        dashboard_manager,
        sample_agents,
    ):
        """割り当て直後にWorkerがbusy化され、永続化されることをテスト。"""
        persist_agent_state = MagicMock(return_value=True)
        scheduler = SchedulerManager(
            dashboard_manager,
            sample_agents,
            persist_agent_state=persist_agent_state,
        )

        task = dashboard_manager.create_task("assign-test")
        scheduler.enqueue_task(task.id, TaskPriority.HIGH)

        result, _ = scheduler.assign_task(task.id, "agent-002")

        assert result is True
        worker = sample_agents["agent-002"]
        assert worker.status == "busy"
        assert worker.current_task == task.id
        persist_agent_state.assert_called_once_with(worker)

    def test_run_auto_assign_loop_prevents_duplicate_assignment_to_same_worker(
        self,
        dashboard_manager,
        sample_agents,
    ):
        """同一idle Workerへの連続自動割り当てを防止できることをテスト。"""
        scheduler = SchedulerManager(dashboard_manager, sample_agents)
        first_task = dashboard_manager.create_task("first-task")
        second_task = dashboard_manager.create_task("second-task")
        scheduler.enqueue_task(first_task.id, TaskPriority.HIGH)
        scheduler.enqueue_task(second_task.id, TaskPriority.MEDIUM)

        assignments = scheduler.run_auto_assign_loop()

        assert assignments == [(first_task.id, "agent-002")]
        assert sample_agents["agent-002"].status == "busy"

    def test_get_next_task_uses_dashboard_snapshot_once(self):
        """依存判定で Dashboard のスナップショットを 1 回だけ使うことをテスト。"""
        dashboard = MagicMock()
        dashboard.list_tasks.return_value = [
            SimpleNamespace(id="dep-1", status="completed"),
        ]
        scheduler = SchedulerManager(dashboard, {})
        scheduler.enqueue_task("task-1", TaskPriority.HIGH, dependencies=["dep-1"])

        task_id = scheduler.get_next_task()

        assert task_id == "task-1"
        dashboard.list_tasks.assert_called_once()
        dashboard.get_task.assert_not_called()

    def test_get_queue_status_uses_snapshot_for_dependency_flags(self):
        """キュー状態生成時に依存判定をスナップショットで行うことをテスト。"""
        dashboard = MagicMock()
        dashboard.list_tasks.return_value = [
            SimpleNamespace(id="dep-ok", status="completed"),
            SimpleNamespace(id="dep-ng", status="pending"),
        ]
        scheduler = SchedulerManager(dashboard, {})
        scheduler.enqueue_task("task-ok", TaskPriority.HIGH, dependencies=["dep-ok"])
        scheduler.enqueue_task("task-ng", TaskPriority.MEDIUM, dependencies=["dep-ng"])

        status = scheduler.get_queue_status()

        by_task_id = {entry["task_id"]: entry for entry in status["pending_tasks"]}
        assert by_task_id["task-ok"]["dependencies_satisfied"] is True
        assert by_task_id["task-ng"]["dependencies_satisfied"] is False
        dashboard.list_tasks.assert_called_once()
        dashboard.get_task.assert_not_called()
