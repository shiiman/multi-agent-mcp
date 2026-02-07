"""DashboardManagerのテスト。"""

import json
from datetime import datetime

from src.managers.dashboard_manager import DashboardManager
from src.models.dashboard import AgentSummary, TaskStatus


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
        assert "更新時刻" in md_content

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
        assert "| ID | タイトル | 状態 | 担当 | 進捗 | worktree |" in md_content
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
        assert "| ID | タイトル | 状態 | 担当 | 進捗 | worktree |" not in md_content
        assert "| ID | タイトル | 状態 | 担当 | 進捗 |" in md_content

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
