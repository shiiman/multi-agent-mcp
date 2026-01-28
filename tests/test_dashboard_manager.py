"""DashboardManagerのテスト。"""


from src.models.dashboard import TaskStatus


class TestDashboardManager:
    """DashboardManagerのテスト。"""

    def test_create_task(self, dashboard_manager):
        """タスク作成をテスト。"""
        task = dashboard_manager.create_task(
            title="Test Task",
            description="Test description",
        )

        assert task.id is not None
        assert task.title == "Test Task"
        assert task.status == TaskStatus.PENDING

    def test_update_task_status(self, dashboard_manager):
        """タスクステータス更新をテスト。"""
        task = dashboard_manager.create_task(title="Test Task")

        success, message = dashboard_manager.update_task_status(
            task_id=task.id,
            status=TaskStatus.IN_PROGRESS,
            progress=25,
        )

        assert success is True

        # 更新後のタスクを確認
        updated_task = dashboard_manager.get_task(task.id)
        assert updated_task.status == TaskStatus.IN_PROGRESS
        assert updated_task.progress == 25
        assert updated_task.started_at is not None

    def test_complete_task(self, dashboard_manager):
        """タスク完了をテスト。"""
        task = dashboard_manager.create_task(title="Test Task")

        dashboard_manager.update_task_status(
            task_id=task.id,
            status=TaskStatus.IN_PROGRESS,
        )

        success, _ = dashboard_manager.update_task_status(
            task_id=task.id,
            status=TaskStatus.COMPLETED,
        )

        assert success is True

        updated_task = dashboard_manager.get_task(task.id)
        assert updated_task.status == TaskStatus.COMPLETED
        assert updated_task.progress == 100
        assert updated_task.completed_at is not None

    def test_fail_task(self, dashboard_manager):
        """タスク失敗をテスト。"""
        task = dashboard_manager.create_task(title="Test Task")

        success, _ = dashboard_manager.update_task_status(
            task_id=task.id,
            status=TaskStatus.FAILED,
            error_message="Something went wrong",
        )

        assert success is True

        updated_task = dashboard_manager.get_task(task.id)
        assert updated_task.status == TaskStatus.FAILED
        assert updated_task.error_message == "Something went wrong"

    def test_assign_task(self, dashboard_manager):
        """タスク割り当てをテスト。"""
        task = dashboard_manager.create_task(title="Test Task")

        success, _ = dashboard_manager.assign_task(
            task_id=task.id,
            agent_id="agent-001",
            branch="feature/test",
            worktree_path="/path/to/worktree",
        )

        assert success is True

        updated_task = dashboard_manager.get_task(task.id)
        assert updated_task.assigned_agent_id == "agent-001"
        assert updated_task.branch == "feature/test"
        assert updated_task.worktree_path == "/path/to/worktree"

    def test_list_tasks(self, dashboard_manager):
        """タスク一覧をテスト。"""
        dashboard_manager.create_task(title="Task 1")
        dashboard_manager.create_task(title="Task 2")
        dashboard_manager.create_task(title="Task 3")

        tasks = dashboard_manager.list_tasks()

        assert len(tasks) == 3

    def test_list_tasks_by_status(self, dashboard_manager):
        """ステータスでフィルタされたタスク一覧をテスト。"""
        task1 = dashboard_manager.create_task(title="Task 1")
        task2 = dashboard_manager.create_task(title="Task 2")
        dashboard_manager.create_task(title="Task 3")

        # task1 を進行中に
        dashboard_manager.update_task_status(task1.id, TaskStatus.IN_PROGRESS)
        # task2 を完了に
        dashboard_manager.update_task_status(task2.id, TaskStatus.COMPLETED)

        pending_tasks = dashboard_manager.list_tasks(status=TaskStatus.PENDING)
        completed_tasks = dashboard_manager.list_tasks(status=TaskStatus.COMPLETED)

        assert len(pending_tasks) == 1
        assert len(completed_tasks) == 1

    def test_list_tasks_by_agent(self, dashboard_manager):
        """エージェントでフィルタされたタスク一覧をテスト。"""
        task1 = dashboard_manager.create_task(title="Task 1")
        task2 = dashboard_manager.create_task(title="Task 2")

        dashboard_manager.assign_task(task1.id, "agent-001")
        dashboard_manager.assign_task(task2.id, "agent-002")

        agent1_tasks = dashboard_manager.list_tasks(agent_id="agent-001")

        assert len(agent1_tasks) == 1
        assert agent1_tasks[0].assigned_agent_id == "agent-001"

    def test_remove_task(self, dashboard_manager):
        """タスク削除をテスト。"""
        task = dashboard_manager.create_task(title="Test Task")

        success, _ = dashboard_manager.remove_task(task.id)

        assert success is True
        assert dashboard_manager.get_task(task.id) is None

    def test_get_summary(self, dashboard_manager):
        """サマリー取得をテスト。"""
        task1 = dashboard_manager.create_task(title="Task 1")
        task2 = dashboard_manager.create_task(title="Task 2")

        dashboard_manager.update_task_status(task1.id, TaskStatus.COMPLETED)
        dashboard_manager.update_task_status(task2.id, TaskStatus.FAILED)

        summary = dashboard_manager.get_summary()

        assert summary["total_tasks"] == 2
        assert summary["completed_tasks"] == 1
        assert summary["failed_tasks"] == 1

    def test_update_nonexistent_task(self, dashboard_manager):
        """存在しないタスクの更新をテスト。"""
        success, message = dashboard_manager.update_task_status(
            task_id="nonexistent",
            status=TaskStatus.IN_PROGRESS,
        )

        assert success is False
        assert "見つかりません" in message
