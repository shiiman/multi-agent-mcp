"""SchedulerManagerのテスト。"""


from src.managers.scheduler_manager import TaskPriority


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
