"""DashboardManagerのテスト。"""

import json
import re
from datetime import datetime

import pytest

from src.managers.dashboard_manager import DashboardManager
from src.models.dashboard import AgentSummary, MessageSummary, TaskStatus


class TestDashboardManagerInitialize:
    """DashboardManager.initialize() のテスト。"""

    def test_initialize_does_not_overwrite_existing(self, temp_dir):
        """initialize() が既存の Dashboard ファイルを上書きしないことをテスト。"""
        dashboard_dir = temp_dir / "dashboard"
        manager = DashboardManager(
            workspace_id="test-ws",
            workspace_path=str(temp_dir),
            dashboard_dir=str(dashboard_dir),
        )
        # 初回: ファイルが作成される
        manager.initialize()
        task = manager.create_task(title="Existing Task")
        assert manager.get_task(task.id) is not None

        # 2回目 initialize: 別プロセスを模擬
        manager2 = DashboardManager(
            workspace_id="test-ws",
            workspace_path=str(temp_dir),
            dashboard_dir=str(dashboard_dir),
        )
        manager2.initialize()

        # 既存タスクが保持されていることを確認
        preserved_task = manager2.get_task(task.id)
        assert preserved_task is not None
        assert preserved_task.title == "Existing Task"


class TestDashboardManagerCleanup:
    """DashboardManager.cleanup() のテスト。"""

    def test_cleanup_preserves_dashboard_and_messages(self, temp_dir):
        """cleanup() が dashboard/messages を削除しないことをテスト。"""
        dashboard_dir = temp_dir / "dashboard"
        manager = DashboardManager(
            workspace_id="test-ws",
            workspace_path=str(temp_dir),
            dashboard_dir=str(dashboard_dir),
        )
        manager.initialize()
        manager.create_task(title="Preserved Task")
        manager.add_message(
            sender_id="admin-001",
            receiver_id="owner-001",
            message_type="status_update",
            subject="",
            content="test message",
        )

        dashboard_path = dashboard_dir / "dashboard.md"
        messages_path = dashboard_dir / "messages.md"
        assert dashboard_path.exists()
        assert messages_path.exists()

        manager.cleanup()

        assert dashboard_path.exists()
        assert messages_path.exists()


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
        summary = dashboard_manager.get_summary()
        assert summary["session_started_at"] is not None

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
        summary = dashboard_manager.get_summary()
        assert summary["session_finished_at"] is not None

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

    def test_reassign_task_clears_previous_agent_current_task(self, dashboard_manager):
        """再割り当て時に旧担当の current_task_id がクリアされることをテスト。"""
        dashboard = dashboard_manager.get_dashboard()
        dashboard.agents.extend(
            [
                AgentSummary(
                    agent_id="worker-001",
                    role="worker",
                    status="busy",
                    current_task_id=None,
                    worktree_path=None,
                    branch=None,
                    last_activity=datetime.now(),
                ),
                AgentSummary(
                    agent_id="worker-002",
                    role="worker",
                    status="idle",
                    current_task_id=None,
                    worktree_path=None,
                    branch=None,
                    last_activity=datetime.now(),
                ),
            ]
        )
        dashboard_manager._write_dashboard(dashboard)

        task = dashboard_manager.create_task(title="Reassign Target")
        dashboard_manager.assign_task(task.id, "worker-001")
        first = dashboard_manager.get_dashboard()
        assert first.get_agent("worker-001").current_task_id == task.id

        dashboard_manager.assign_task(task.id, "worker-002")
        updated = dashboard_manager.get_dashboard()
        old_agent = updated.get_agent("worker-001")
        new_agent = updated.get_agent("worker-002")
        assert old_agent is not None
        assert old_agent.current_task_id is None
        assert new_agent is not None
        assert new_agent.current_task_id == task.id

    def test_update_task_status_rejects_terminal_to_in_progress(self, dashboard_manager):
        """終端状態から in_progress への直接遷移を拒否することをテスト。"""
        task = dashboard_manager.create_task(title="Terminal Task")
        dashboard_manager.update_task_status(task.id, TaskStatus.COMPLETED)

        success, message = dashboard_manager.update_task_status(
            task.id, TaskStatus.IN_PROGRESS
        )
        assert success is False
        assert "reopen_task" in message

    def test_reopen_task_from_terminal(self, dashboard_manager):
        """reopen_task で終端状態タスクを pending に戻せることをテスト。"""
        task = dashboard_manager.create_task(title="Reopen Target")
        dashboard_manager.update_task_status(task.id, TaskStatus.COMPLETED)

        success, message = dashboard_manager.reopen_task(task.id, reset_progress=True)
        assert success is True
        assert "再開" in message
        reopened = dashboard_manager.get_task(task.id)
        assert reopened.status == TaskStatus.PENDING
        assert reopened.progress == 0
        assert reopened.completed_at is None

    def test_reopen_task_resets_started_at(self, dashboard_manager):
        """reopen_task で started_at がリセットされることをテスト。"""
        task = dashboard_manager.create_task(title="Reopen StartedAt Target")
        dashboard_manager.update_task_status(task.id, TaskStatus.IN_PROGRESS, progress=10)
        in_progress = dashboard_manager.get_task(task.id)
        assert in_progress.started_at is not None
        dashboard_manager.update_task_status(task.id, TaskStatus.COMPLETED)

        success, _ = dashboard_manager.reopen_task(task.id)

        assert success is True
        reopened = dashboard_manager.get_task(task.id)
        assert reopened.status == TaskStatus.PENDING
        assert reopened.started_at is None

    def test_reopen_task_rejects_non_terminal(self, dashboard_manager):
        """reopen_task は終端状態以外を拒否することをテスト。"""
        task = dashboard_manager.create_task(title="Not Terminal")
        dashboard_manager.update_task_status(task.id, TaskStatus.IN_PROGRESS, progress=10)

        success, message = dashboard_manager.reopen_task(task.id)
        assert success is False
        assert "終端状態ではありません" in message

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

    def test_parse_yaml_front_matter_invalid_returns_none(self, dashboard_manager):
        """不正な front matter では None を返すことをテスト。"""
        content = "# no front matter"
        assert dashboard_manager._parse_yaml_front_matter(content) is None


class TestTaskFileManagement:
    """タスクファイル管理機能のテスト。"""

    def test_write_task_file(self, dashboard_manager, temp_dir):
        """タスクファイル作成をテスト。"""
        project_root = temp_dir / "project"
        project_root.mkdir()

        task_content = "# Task\n\nDo something important."
        task_file = dashboard_manager.write_task_file(
            project_root=project_root,
            session_id="123",
            task_id="task-001",
            agent_label="claude1",
            task_content=task_content,
        )

        assert task_file.exists()
        assert task_file.read_text(encoding="utf-8") == task_content
        assert task_file.name == "claude1_task-001.md"
        assert ".multi-agent-mcp/123/tasks" in str(task_file)

    def test_get_task_file_path(self, dashboard_manager, temp_dir):
        """タスクファイルパス取得をテスト。"""
        project_root = temp_dir / "project"

        path = dashboard_manager.get_task_file_path(
            project_root=project_root,
            session_id="456",
            task_id="task-002",
            agent_label="codex2",
        )

        expected = project_root / ".multi-agent-mcp" / "456" / "tasks" / "codex2_task-002.md"
        assert path == expected

    def test_read_task_file(self, dashboard_manager, temp_dir):
        """タスクファイル読み取りをテスト。"""
        project_root = temp_dir / "project"
        project_root.mkdir()

        task_content = "# Read Test\n\nContent here."
        dashboard_manager.write_task_file(
            project_root=project_root,
            session_id="789",
            task_id="task-003",
            agent_label="gemini3",
            task_content=task_content,
        )

        read_content = dashboard_manager.read_task_file(
            project_root=project_root,
            session_id="789",
            task_id="task-003",
            agent_label="gemini3",
        )

        assert read_content == task_content


class TestDashboardMarkdownSync:
    """Markdown 同期処理の追加テスト。"""

    def test_dashboard_lock_fails_fast_in_event_loop_context(
        self, dashboard_manager, monkeypatch
    ):
        """event loop 実行中は lock 待機を行わず即座に timeout することをテスト。"""
        sleep_calls: list[float] = []

        def _always_blocking(*_args, **_kwargs):
            raise BlockingIOError("lock busy")

        monkeypatch.setattr("fcntl.flock", _always_blocking)
        monkeypatch.setattr(
            dashboard_manager,
            "_is_event_loop_running",
            lambda: True,
        )
        monkeypatch.setattr(
            "src.managers.dashboard_manager.time.sleep",
            lambda seconds: sleep_calls.append(seconds),
        )

        with pytest.raises(TimeoutError, match="event loop context"):
            dashboard_manager.get_dashboard()

        assert sleep_calls == []

    def test_save_markdown_dashboard_ignores_invalid_last_activity(
        self, dashboard_manager, temp_dir
    ):
        """agents.json の不正な last_activity を無視して保存できることをテスト。"""
        project_root = temp_dir / "project"
        project_root.mkdir()

        session_dir = dashboard_manager.dashboard_dir.parent
        agents_path = session_dir / "agents.json"
        agents_path.parent.mkdir(parents=True, exist_ok=True)
        agents_path.write_text(
            json.dumps(
                {
                    "agent-001": {
                        "id": "agent-001",
                        "role": "worker",
                        "status": "idle",
                        "last_activity": "not-a-datetime",
                    }
                }
            ),
            encoding="utf-8",
        )

        md_path = dashboard_manager.save_markdown_dashboard(project_root, "session-1")
        assert md_path.exists()
        dashboard = dashboard_manager.get_dashboard()
        assert len(dashboard.agents) == 1
        assert dashboard.agents[0].last_activity is None

    def test_save_markdown_dashboard_exposes_structured_sync_failure_report(
        self, dashboard_manager, temp_dir
    ):
        """同期失敗が構造化レポートとして取得できることをテスト。"""
        project_root = temp_dir / "project"
        project_root.mkdir()

        session_dir = dashboard_manager.dashboard_dir.parent
        agents_path = session_dir / "agents.json"
        agents_path.parent.mkdir(parents=True, exist_ok=True)
        agents_path.write_text("{invalid-json", encoding="utf-8")

        md_path = dashboard_manager.save_markdown_dashboard(project_root, "session-sync-error")

        report = dashboard_manager.get_last_sync_report()
        assert md_path.exists()
        assert report is not None
        assert report["success"] is False
        assert report["agents_sync"]["success"] is False
        assert report["agents_sync"]["error"]["type"] == "JSONDecodeError"
        assert report["ipc_sync"]["success"] is True
        assert report["messages_write"]["success"] is True

    def test_save_markdown_dashboard_sets_session_metadata(self, dashboard_manager, temp_dir):
        """dashboard front matter にセッション統計が保存されることをテスト。"""
        project_root = temp_dir / "project"
        project_root.mkdir()
        task = dashboard_manager.create_task(title="Meta Task")
        dashboard_manager.update_task_status(task.id, TaskStatus.IN_PROGRESS)
        dashboard_manager.increment_process_crash_count()
        dashboard_manager.increment_process_recovery_count()
        dashboard_manager.update_task_status(task.id, TaskStatus.COMPLETED)

        md_path = dashboard_manager.save_markdown_dashboard(project_root, "session-meta")
        content = md_path.read_text(encoding="utf-8")
        assert "session_started_at:" in content
        assert "session_finished_at:" in content
        assert "process_crash_count: 1" in content
        assert "process_recovery_count: 1" in content

    def test_save_markdown_dashboard_records_started_at_on_first_save(
        self, dashboard_manager, temp_dir
    ):
        """初回保存時に session_started_at を記録することをテスト。"""
        project_root = temp_dir / "project"
        project_root.mkdir()

        md_path = dashboard_manager.save_markdown_dashboard(project_root, "session-initial")
        content = md_path.read_text(encoding="utf-8")
        front_matter = dashboard_manager._parse_yaml_front_matter(content)

        assert front_matter is not None
        assert front_matter.get("session_started_at") is not None
        assert "**開始時刻**: -" not in content

    def test_read_task_file_not_exists(self, dashboard_manager, temp_dir):
        """存在しないタスクファイル読み取りをテスト。"""
        project_root = temp_dir / "project"

        read_content = dashboard_manager.read_task_file(
            project_root=project_root,
            session_id="999",
            task_id="task-999",
            agent_label="nonexistent",
        )

        assert read_content is None

    def test_clear_task_file(self, dashboard_manager, temp_dir):
        """タスクファイル削除をテスト。"""
        project_root = temp_dir / "project"
        project_root.mkdir()

        # ファイルを作成
        task_file = dashboard_manager.write_task_file(
            project_root=project_root,
            session_id="delete-test",
            task_id="task-delete",
            agent_label="admin",
            task_content="To be deleted",
        )
        assert task_file.exists()

        # 削除
        success = dashboard_manager.clear_task_file(
            project_root=project_root,
            session_id="delete-test",
            task_id="task-delete",
            agent_label="admin",
        )

        assert success is True
        assert not task_file.exists()

    def test_clear_task_file_not_exists(self, dashboard_manager, temp_dir):
        """存在しないタスクファイル削除をテスト。"""
        project_root = temp_dir / "project"

        success = dashboard_manager.clear_task_file(
            project_root=project_root,
            session_id="nonexistent",
            task_id="task-none",
            agent_label="nonexistent",
        )

        assert success is False


class TestMarkdownDashboard:
    """Markdownダッシュボード機能のテスト。"""

    def test_generate_markdown_dashboard(self, dashboard_manager):
        """Markdownダッシュボード生成をテスト。"""
        # タスクを作成
        dashboard_manager.create_task(title="Task 1", description="First task")
        task2 = dashboard_manager.create_task(title="Task 2", description="Second task")
        dashboard_manager.update_task_status(task2.id, TaskStatus.IN_PROGRESS)

        md_content = dashboard_manager.generate_markdown_dashboard()

        # 基本的な構造を確認
        assert "# Multi-Agent Dashboard" in md_content
        assert "## エージェント状態" in md_content
        assert "## タスク状態" in md_content
        assert "## 統計" in md_content
        assert "開始時刻" in md_content
        assert "更新時刻" in md_content
        assert "終了時刻" in md_content
        assert md_content.index("**開始時刻**") < md_content.index("**更新時刻**")
        assert md_content.index("**更新時刻**") < md_content.index("**終了時刻**")

        # タスク情報が含まれていることを確認
        assert "Task 1" in md_content
        assert "Task 2" in md_content

        # 統計情報が含まれていることを確認
        assert "総タスク数" in md_content
        assert "完了タスク" in md_content

    def test_save_markdown_dashboard(self, dashboard_manager, temp_dir):
        """Markdownダッシュボード保存をテスト。"""
        project_root = temp_dir / "project"
        project_root.mkdir()

        dashboard_manager.create_task(title="Dashboard Test Task")

        md_path = dashboard_manager.save_markdown_dashboard(
            project_root=project_root,
            session_id="dashboard-test",
        )

        assert md_path.exists()
        assert md_path.name == "dashboard.md"
        # パスは .dashboard または .multi-agent-mcp/{session_id}/dashboard のいずれかを含む
        assert ".dashboard" in str(md_path) or ".multi-agent-mcp" in str(md_path)

        content = md_path.read_text(encoding="utf-8")
        assert "# Multi-Agent Dashboard" in content
        assert "Dashboard Test Task" in content

    def test_save_markdown_dashboard_uses_cli_worker_name(self, dashboard_manager):
        """agents.json 同期時に worker 名が CLI + 番号になることをテスト。"""
        session_dir = dashboard_manager.dashboard_dir.parent
        agents_file = session_dir / "agents.json"
        agents_file.write_text(
            json.dumps(
                {
                    "worker-a": {
                        "id": "worker-a",
                        "role": "worker",
                        "status": "idle",
                        "current_task": None,
                        "worktree_path": None,
                        "window_index": 0,
                        "pane_index": 1,
                        "ai_cli": "claude",
                        "last_activity": datetime.now().isoformat(),
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        project_root = session_dir / "project"
        project_root.mkdir(exist_ok=True)
        dashboard_manager.save_markdown_dashboard(project_root, "test-session")

        md_content = dashboard_manager.generate_markdown_dashboard()
        assert "`claude1`" in md_content

    def test_markdown_dashboard_with_completed_task(self, dashboard_manager, temp_dir):
        """完了タスクを含むMarkdownダッシュボードをテスト。"""
        project_root = temp_dir / "project"
        project_root.mkdir()

        task = dashboard_manager.create_task(title="Completed Task")
        dashboard_manager.update_task_status(task.id, TaskStatus.COMPLETED)

        md_content = dashboard_manager.generate_markdown_dashboard()

        # 完了タスクのemojiが含まれていることを確認
        assert "✅" in md_content
        assert "Completed Task" in md_content

    def test_markdown_status_label_is_japanese_but_internal_status_is_compatible(
        self, dashboard_manager
    ):
        """表示は日本語、内部 status は英語トークンを維持することをテスト。"""
        task = dashboard_manager.create_task(title="In Progress Task")
        dashboard_manager.update_task_status(task.id, TaskStatus.IN_PROGRESS, progress=33)

        md_content = dashboard_manager.generate_markdown_dashboard()
        assert "🔄 進行中" in md_content
        assert "🔄 in_progress" not in md_content

        loaded = dashboard_manager.get_task(task.id)
        assert loaded is not None
        assert loaded.status == TaskStatus.IN_PROGRESS
        assert loaded.status.value == "in_progress"

    def test_task_worktree_is_rendered_as_relative_path(self, dashboard_manager, temp_dir):
        """タスクの Worktree が workspace 相対パスで表示されることをテスト。"""
        dashboard = dashboard_manager.get_dashboard()
        dashboard.agents.append(
            AgentSummary(
                agent_id="worker-001",
                role="worker",
                status="busy",
                current_task_id=None,
                worktree_path=str(temp_dir / "worktrees" / "feature-worker-1"),
                branch=None,
                last_activity=datetime.now(),
            )
        )
        dashboard.calculate_stats()
        dashboard_manager._write_dashboard(dashboard)
        dashboard_manager.create_task(
            title="Worktree Task",
            assigned_agent_id="worker-001",
            worktree_path=str(temp_dir / "worktrees" / "feature-worker-1"),
        )

        md_content = dashboard_manager.generate_markdown_dashboard()
        assert "| ID | 名前 | 役割 | 状態 | 現在のタスク |" in md_content
        assert "| ID | タイトル | 状態 | 担当 | 進捗 | 開始 | 終了 | worktree |" in md_content
        assert "`worker-001`" in md_content
        assert "<code>worktrees/feature-worker-1</code>" in md_content
        assert str(temp_dir) not in md_content

    def test_task_worktree_column_hidden_when_worktree_disabled(
        self, dashboard_manager, temp_dir, monkeypatch
    ):
        """MCP_ENABLE_WORKTREE=false のとき worktree 列を表示しないことをテスト。"""
        monkeypatch.setenv("MCP_ENABLE_WORKTREE", "false")
        dashboard_manager.create_task(
            title="No Worktree Task",
            worktree_path=str(temp_dir / "worktrees" / "feature-worker-1"),
        )

        md_content = dashboard_manager.generate_markdown_dashboard()
        assert "| ID | タイトル | 状態 | 担当 | 進捗 | 開始 | 終了 | worktree |" not in md_content
        assert "| ID | タイトル | 状態 | 担当 | 進捗 | 開始 | 終了 |" in md_content

    def test_task_worktree_column_hidden_when_git_disabled(
        self, dashboard_manager, temp_dir, monkeypatch
    ):
        """MCP_ENABLE_GIT=false のとき worktree 列を表示しないことをテスト。"""
        monkeypatch.setenv("MCP_ENABLE_GIT", "false")
        monkeypatch.setenv("MCP_ENABLE_WORKTREE", "true")
        dashboard_manager.create_task(
            title="No Git Task",
            worktree_path=str(temp_dir / "worktrees" / "feature-worker-1"),
        )

        md_content = dashboard_manager.generate_markdown_dashboard()
        assert "| ID | タイトル | 状態 | 担当 | 進捗 | 開始 | 終了 | worktree |" not in md_content
        assert "| ID | タイトル | 状態 | 担当 | 進捗 | 開始 | 終了 |" in md_content

    def test_task_table_renders_start_and_end_times_in_hhmmss(
        self, dashboard_manager, monkeypatch
    ):
        """タスク表で開始/終了時刻を HH:mm:ss 形式で表示することをテスト。"""
        monkeypatch.setenv("MCP_ENABLE_WORKTREE", "false")

        timed_task = dashboard_manager.create_task(title="Timed Task")
        pending_task = dashboard_manager.create_task(title="Pending Task")
        dashboard = dashboard_manager.get_dashboard()
        timed = dashboard.get_task(timed_task.id)
        pending = dashboard.get_task(pending_task.id)
        assert timed is not None
        assert pending is not None

        timed.started_at = datetime(2026, 2, 10, 9, 8, 7)
        timed.completed_at = datetime(2026, 2, 10, 10, 11, 12)
        dashboard_manager._write_dashboard(dashboard)

        md_content = dashboard_manager.generate_markdown_dashboard()
        assert "| ID | タイトル | 状態 | 担当 | 進捗 | 開始 | 終了 |" in md_content
        timed_pattern = r"\| `[^`]+` \| Timed Task \| .* \| 0% \| 09:08:07 \| 10:11:12 \|"
        assert re.search(timed_pattern, md_content)
        assert re.search(r"\| `[^`]+` \| Pending Task \| .* \| 0% \| - \| - \|", md_content)

    def test_task_assignee_is_rendered_as_agent_label(self, dashboard_manager, temp_dir):
        """タスク担当が agent_id ではなく表示名で描画されることをテスト。"""
        dashboard = dashboard_manager.get_dashboard()
        dashboard.agents.append(
            AgentSummary(
                agent_id="worker-001",
                role="worker",
                status="busy",
                current_task_id=None,
                worktree_path=str(temp_dir / "worktrees" / "feature-worker-1"),
                branch=None,
                last_activity=datetime.now(),
            )
        )
        dashboard_manager._write_dashboard(dashboard)

        dashboard_manager.create_task(
            title="Assigned Task",
            assigned_agent_id="worker-001",
        )
        md_content = dashboard_manager.generate_markdown_dashboard()
        assert "`worker1`" in md_content

    def test_task_details_hidden_when_only_progress_exists(self, dashboard_manager):
        """補足情報なし（進捗のみ）のタスクでは詳細セクションを表示しないことをテスト。"""
        task = dashboard_manager.create_task(title="In Progress Task")
        dashboard_manager.update_task_status(task.id, TaskStatus.IN_PROGRESS, progress=70)

        md_content = dashboard_manager.generate_markdown_dashboard()
        assert "## タスク詳細" not in md_content

    def test_task_details_shows_failed_with_error_message(self, dashboard_manager):
        """failed かつ補足情報ありのタスクを詳細表示することをテスト。"""
        task = dashboard_manager.create_task(title="Failed Task")
        dashboard_manager.update_task_status(
            task.id,
            TaskStatus.FAILED,
            progress=100,
            error_message="ネットワークエラー",
        )

        md_content = dashboard_manager.generate_markdown_dashboard()
        assert "## タスク詳細" in md_content
        assert "### Failed Task" in md_content
        assert "**状態**: `失敗`" in md_content
        assert "**エラー**: ネットワークエラー" in md_content

    def test_task_details_hides_failed_without_supplement(self, dashboard_manager):
        """failed でも補足情報なしのタスクは詳細表示しないことをテスト。"""
        task = dashboard_manager.create_task(title="Failed No Detail")
        dashboard_manager.update_task_status(task.id, TaskStatus.FAILED, progress=100)

        md_content = dashboard_manager.generate_markdown_dashboard()
        assert "## タスク詳細" not in md_content

    def test_task_details_mixes_in_progress_and_failed(self, dashboard_manager):
        """in_progress / failed が同一セクションに表示されることをテスト。"""
        in_progress_task = dashboard_manager.create_task(title="Doing Task")
        dashboard_manager.update_task_status(
            in_progress_task.id, TaskStatus.IN_PROGRESS, progress=55
        )
        dashboard_manager.update_task_checklist(
            in_progress_task.id,
            [{"text": "実装", "completed": False}],
            "進捗更新",
        )

        failed_task = dashboard_manager.create_task(title="Broken Task")
        dashboard_manager.update_task_status(
            failed_task.id,
            TaskStatus.FAILED,
            progress=80,
            error_message="テスト失敗",
        )

        md_content = dashboard_manager.generate_markdown_dashboard()
        assert "## タスク詳細" in md_content
        assert "### Doing Task" in md_content
        assert "### Broken Task" in md_content
        assert "**状態**: `進行中`" in md_content
        assert "**状態**: `失敗`" in md_content

    def test_message_history_written_to_messages_md(self, dashboard_manager):
        """メッセージ履歴が messages.md に分離保存されることをテスト。"""
        session_dir = dashboard_manager.dashboard_dir.parent
        agents_file = session_dir / "agents.json"
        agents_file.write_text(
            json.dumps(
                {
                    "admin-001": {
                        "id": "admin-001",
                        "role": "admin",
                        "status": "busy",
                        "current_task": None,
                        "worktree_path": None,
                        "last_activity": datetime.now().isoformat(),
                    },
                    "worker-001": {
                        "id": "worker-001",
                        "role": "worker",
                        "status": "busy",
                        "current_task": None,
                        "worktree_path": "/tmp/repo-worktrees/feature-worker-1",
                        "last_activity": datetime.now().isoformat(),
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        ipc_dir = session_dir / "ipc" / "admin-001"
        ipc_dir.mkdir(parents=True, exist_ok=True)
        msg_file = ipc_dir / "20260206_170000_000000_test.md"
        msg_file.write_text(
            (
                "---\n"
                "id: test-msg-id\n"
                "sender_id: worker-001\n"
                "receiver_id: admin-001\n"
                "message_type: request\n"
                "priority: high\n"
                "subject: 補足依頼\n"
                "created_at: '2026-02-06T17:00:00'\n"
                "read_at: null\n"
                "---\n\n"
                "詳細本文のテストメッセージです。\n"
            ),
            encoding="utf-8",
        )

        project_root = session_dir / "project"
        project_root.mkdir(exist_ok=True)
        md_path = dashboard_manager.save_markdown_dashboard(project_root, "test-session")
        md_content = md_path.read_text(encoding="utf-8")
        assert "## メッセージ履歴" not in md_content

        messages_path = md_path.parent / "messages.md"
        assert messages_path.exists()
        messages_content = messages_path.read_text(encoding="utf-8")
        assert "## メッセージ履歴" in messages_content
        assert "## メッセージ本文" not in messages_content
        assert "| 時刻 | 種類 | 送信元 | 宛先 | 件名 |" not in messages_content
        assert "<summary>" in messages_content
        assert "<details open>" in messages_content
        assert "詳細本文のテストメッセージです。" in messages_content

    def test_add_message_appends_to_messages_md_without_overwrite(self, dashboard_manager):
        """add_message が messages.md 履歴を追記保持することをテスト。"""
        dashboard_manager.add_message(
            sender_id="system",
            receiver_id=None,
            message_type="task_progress",
            subject="first",
            content="message-1",
        )
        dashboard_manager.add_message(
            sender_id="system",
            receiver_id=None,
            message_type="task_complete",
            subject="second",
            content="message-2",
        )

        messages_path = dashboard_manager.dashboard_dir / "messages.md"
        content = messages_path.read_text(encoding="utf-8")
        assert "message-1" in content
        assert "message-2" in content

    def test_system_actor_is_rendered_without_unknown_prefix(self, dashboard_manager):
        """system 送信者が unknown(system) にならないことをテスト。"""
        dashboard = dashboard_manager.get_dashboard()
        dashboard.messages.append(
            MessageSummary(
                sender_id="system",
                receiver_id=None,
                message_type="system",
                subject="",
                content="system message",
                created_at=datetime.now(),
            )
        )

        messages_md = dashboard_manager._generate_messages_markdown(dashboard)
        assert "unknown(system)" not in messages_md
        assert "system → broadcast" in messages_md

    def test_cost_section_includes_role_and_agent_breakdown(self, dashboard_manager):
        """コスト情報に role/agent 内訳が表示されることをテスト。"""
        dashboard = dashboard_manager.get_dashboard()
        dashboard.agents.extend(
            [
                AgentSummary(
                    agent_id="admin-001",
                    role="admin",
                    status="busy",
                    current_task_id=None,
                    worktree_path=None,
                    branch=None,
                    last_activity=datetime.now(),
                ),
                AgentSummary(
                    agent_id="worker-001",
                    role="worker",
                    status="busy",
                    current_task_id=None,
                    worktree_path="/tmp/repo-worktrees/feature-worker-1",
                    branch=None,
                    last_activity=datetime.now(),
                ),
            ]
        )
        dashboard_manager._write_dashboard(dashboard)

        dashboard_manager.record_api_call(
            ai_cli="codex", estimated_tokens=1000, agent_id="admin-001"
        )
        dashboard_manager.record_api_call(
            ai_cli="codex", estimated_tokens=2000, agent_id="worker-001"
        )

        md_content = dashboard_manager.generate_markdown_dashboard()
        assert "**役割別内訳**" in md_content
        assert "`admin`: 1 calls / 1,000 tokens" in md_content
        assert "`worker`: 1 calls / 2,000 tokens" in md_content
        assert "**エージェント別呼び出し**" in md_content
        assert "`admin`" in md_content
        assert "`worker1`" in md_content

    def test_parse_ipc_message_keeps_full_content(self, dashboard_manager, temp_dir):
        """IPC 本文が省略されずに保持されることをテスト。"""
        msg_file = temp_dir / "message.md"
        full_text = "A" * 180
        msg_file.write_text(
            (
                "---\n"
                "id: test-id\n"
                "sender_id: worker-001\n"
                "receiver_id: admin-001\n"
                "message_type: request\n"
                "subject: long body\n"
                "created_at: '2026-02-06T17:00:00'\n"
                "---\n\n"
                f"{full_text}\n"
            ),
            encoding="utf-8",
        )

        msg = dashboard_manager._parse_ipc_message(msg_file)
        assert msg is not None
        assert msg.content == full_text

    def test_markdown_stats_excludes_session_and_includes_process_counts(self, dashboard_manager):
        """統計セクションでセッション時刻を除外し、process 回数を表示することをテスト。"""
        task = dashboard_manager.create_task(title="Stats Task")
        dashboard_manager.update_task_status(task.id, TaskStatus.IN_PROGRESS)
        dashboard_manager.increment_process_crash_count()
        dashboard_manager.increment_process_recovery_count()

        md_content = dashboard_manager.generate_markdown_dashboard()
        assert "**開始時刻**" in md_content
        assert "**終了時刻**" in md_content
        assert "- **セッション開始**" not in md_content
        assert "- **セッション終了**" not in md_content
        assert "プロセスクラッシュ回数" in md_content
        assert "プロセス復旧回数" in md_content


class TestDashboardCost:
    """ダッシュボードコスト管理メソッドのテスト。"""

    def test_record_api_call(self, dashboard_manager):
        """API 呼び出し記録後にコスト統計が更新されることをテスト。"""
        dashboard_manager.record_api_call(ai_cli="claude", estimated_tokens=1000)
        estimate = dashboard_manager.get_cost_estimate()
        assert estimate["total_api_calls"] == 1
        assert estimate["estimated_tokens"] == 1000
        assert estimate["claude_calls"] == 1

    def test_record_multiple_cli_calls(self, dashboard_manager):
        """複数 CLI の呼び出しが正しくカウントされることをテスト。"""
        dashboard_manager.record_api_call(ai_cli="claude", estimated_tokens=500)
        dashboard_manager.record_api_call(ai_cli="codex", estimated_tokens=300)
        dashboard_manager.record_api_call(ai_cli="gemini", estimated_tokens=200)
        estimate = dashboard_manager.get_cost_estimate()
        assert estimate["total_api_calls"] == 3
        assert estimate["estimated_tokens"] == 1000
        assert estimate["claude_calls"] == 1
        assert estimate["codex_calls"] == 1
        assert estimate["gemini_calls"] == 1

    def test_cost_summary_with_warning(self, dashboard_manager):
        """閾値超過時に警告メッセージが含まれることをテスト。"""
        dashboard_manager.set_cost_warning_threshold(0.001)
        dashboard_manager.record_api_call(ai_cli="claude", estimated_tokens=10000)
        summary = dashboard_manager.get_cost_summary()
        assert summary["warning_message"] is not None
        assert "警告" in summary["warning_message"]

    def test_check_cost_warning_below_threshold(self, dashboard_manager):
        """閾値未満で None を返すことをテスト。"""
        result = dashboard_manager.check_cost_warning()
        assert result is None

    def test_check_cost_warning_above_threshold(self, dashboard_manager):
        """閾値以上で警告文字列を返すことをテスト。"""
        dashboard_manager.set_cost_warning_threshold(0.0)
        dashboard_manager.record_api_call(ai_cli="claude", estimated_tokens=1000)
        result = dashboard_manager.check_cost_warning()
        assert result is not None
        assert "警告" in result

    def test_set_cost_warning_threshold(self, dashboard_manager):
        """閾値変更が永続化されることをテスト。"""
        dashboard_manager.set_cost_warning_threshold(25.0)
        summary = dashboard_manager.get_cost_summary()
        assert summary["warning_threshold_usd"] == 25.0

    def test_reset_cost_counter(self, dashboard_manager):
        """リセット後に全カウントがゼロであることをテスト。"""
        dashboard_manager.record_api_call(ai_cli="claude", estimated_tokens=1000)
        dashboard_manager.record_api_call(ai_cli="codex", estimated_tokens=500)
        dashboard_manager.reset_cost_counter()
        estimate = dashboard_manager.get_cost_estimate()
        assert estimate["total_api_calls"] == 0
        assert estimate["estimated_tokens"] == 0
        assert estimate["estimated_cost_usd"] == 0.0

    def test_record_api_call_with_agent_and_task(self, dashboard_manager):
        """エージェントID とタスクID 付きの API 呼び出し記録をテスト。"""
        dashboard_manager.record_api_call(
            ai_cli="claude",
            estimated_tokens=1000,
            agent_id="agent-001",
            task_id="task-001",
        )
        estimate = dashboard_manager.get_cost_estimate()
        assert estimate["total_api_calls"] == 1

    def test_estimated_cost_calculation(self, dashboard_manager):
        """コスト計算が正しいことをテスト。"""
        dashboard_manager.record_api_call(ai_cli="claude", estimated_tokens=1000)
        estimate = dashboard_manager.get_cost_estimate()
        assert estimate["estimated_cost_usd"] > 0
