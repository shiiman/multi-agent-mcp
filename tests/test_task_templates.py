"""タスクテンプレート生成のテスト。"""


from src.config.settings import Settings
from src.tools.task_templates import generate_7section_task, generate_admin_task


class TestGenerateAdminTask:
    """generate_admin_task 関数のテスト。"""

    def test_includes_session_id(self):
        """セッションIDがタイトルに含まれることをテスト。"""
        result = generate_admin_task(
            session_id="TEST-123",
            agent_id="admin-001",
            plan_content="テスト計画",
            branch_name="feature/test",
            worker_count=3,
            memory_context="",
            project_name="test-project",
        )
        assert "TEST-123" in result
        assert "Admin タスク" in result

    def test_includes_plan_content(self):
        """計画書が含まれることをテスト。"""
        plan = "## 実装内容\n\n- 機能Aを追加\n- 機能Bを修正"
        result = generate_admin_task(
            session_id="123",
            agent_id="admin-001",
            plan_content=plan,
            branch_name="feature/test",
            worker_count=3,
            memory_context="",
            project_name="test-project",
        )
        assert "## 実装内容" in result
        assert "機能Aを追加" in result

    def test_includes_branch_name(self):
        """ブランチ名が含まれることをテスト。"""
        result = generate_admin_task(
            session_id="123",
            agent_id="admin-001",
            plan_content="テスト",
            branch_name="feature/my-feature",
            worker_count=3,
            memory_context="",
            project_name="test-project",
        )
        assert "feature/my-feature" in result
        assert ("**作業ブランチ**:" in result) or ("**作業ラベル**:" in result)

    def test_includes_worker_count(self):
        """Worker数が含まれることをテスト。"""
        result = generate_admin_task(
            session_id="123",
            agent_id="admin-001",
            plan_content="テスト",
            branch_name="feature/test",
            worker_count=5,
            memory_context="",
            project_name="test-project",
        )
        assert "**Worker 数**: 5" in result

    def test_includes_memory_context(self):
        """メモリコンテキストが含まれることをテスト。"""
        memory = "**プロジェクトメモリ:**\n- 設定ファイルは config.yaml"
        result = generate_admin_task(
            session_id="123",
            agent_id="admin-001",
            plan_content="テスト",
            branch_name="feature/test",
            worker_count=3,
            memory_context=memory,
            project_name="test-project",
        )
        assert "プロジェクトメモリ" in result
        assert "config.yaml" in result

    def test_no_memory_context(self):
        """メモリコンテキストなしの場合のテスト。"""
        result = generate_admin_task(
            session_id="123",
            agent_id="admin-001",
            plan_content="テスト",
            branch_name="feature/test",
            worker_count=3,
            memory_context="",
            project_name="test-project",
        )
        assert "（関連情報なし）" in result

    def test_includes_project_name(self):
        """プロジェクト名が含まれることをテスト。"""
        result = generate_admin_task(
            session_id="123",
            agent_id="admin-001",
            plan_content="テスト",
            branch_name="feature/test",
            worker_count=3,
            memory_context="",
            project_name="my-awesome-project",
        )
        assert "**プロジェクト**: my-awesome-project" in result

    def test_includes_mcp_tool_prefix(self):
        """MCPツールプレフィックスが含まれることをテスト。"""
        result = generate_admin_task(
            session_id="123",
            agent_id="admin-001",
            plan_content="テスト",
            branch_name="feature/test",
            worker_count=3,
            memory_context="",
            project_name="test-project",
            mcp_tool_prefix="mcp__custom-server__",
        )
        assert "mcp__custom-server__create_task" in result
        assert "mcp__custom-server__send_task" in result

    def test_uses_default_mcp_tool_prefix(self):
        """デフォルトのMCPツールプレフィックスが使用されることをテスト。"""
        result = generate_admin_task(
            session_id="123",
            agent_id="admin-001",
            plan_content="テスト",
            branch_name="feature/test",
            worker_count=3,
            memory_context="",
            project_name="test-project",
        )
        assert "mcp__multi-agent-mcp__create_task" in result

    def test_includes_quality_check_settings(self):
        """品質チェック設定が含まれることをテスト。"""
        settings = Settings()
        result = generate_admin_task(
            session_id="123",
            agent_id="admin-001",
            plan_content="テスト",
            branch_name="feature/test",
            worker_count=3,
            memory_context="",
            project_name="test-project",
            settings=settings,
        )
        # デフォルト値
        assert f"イテレーション < {settings.quality_check_max_iterations}" in result
        assert f"が{settings.quality_check_same_issue_limit}回以上繰り返される" in result

    def test_includes_self_check_info(self):
        """Self-Check情報が含まれることをテスト。"""
        result = generate_admin_task(
            session_id="ISSUE-456",
            agent_id="admin-xyz",
            plan_content="テスト",
            branch_name="feature/test",
            worker_count=3,
            memory_context="",
            project_name="test-project",
        )
        assert "**セッションID**: ISSUE-456" in result
        assert "**Admin ID**: admin-xyz" in result
        assert 'retrieve_from_memory "ISSUE-456"' in result

    def test_mentions_role_template(self):
        """Admin タスクが役割テンプレート参照前提の文言を含むことをテスト。"""
        result = generate_admin_task(
            session_id="123",
            agent_id="admin-001",
            plan_content="テスト",
            branch_name="feature/test",
            worker_count=3,
            memory_context="",
            project_name="test-project",
        )
        assert "役割テンプレートで確認済みの前提" in result
        assert "F001-F005" in result or "F001" in result
        # 品質イテレーションセクションでは F001 への言及が残っている
        assert "F001 違反" in result

    def test_uses_no_git_admin_template_when_git_disabled(self):
        """enable_git=false 時は admin_task_no_git を使用することをテスト。"""
        settings = Settings()
        settings.enable_git = False
        settings.enable_worktree = True

        result = generate_admin_task(
            session_id="123",
            agent_id="admin-001",
            plan_content="テスト",
            branch_name="feature/test",
            worker_count=2,
            memory_context="",
            project_name="test-project",
            working_dir="/tmp/project",
            settings=settings,
        )

        assert "No Git モード" in result
        assert "create_worktree" in result


class TestGenerate7SectionTask:
    """generate_7section_task 関数のテスト。"""

    def test_includes_task_id(self):
        """タスクIDがタイトルに含まれることをテスト。"""
        result = generate_7section_task(
            task_id="TASK-001",
            agent_id="worker-001",
            task_description="テストタスク",
            persona_name="Backend Engineer",
            persona_prompt="バックエンド開発者として...",
            memory_context="",
            project_name="test-project",
        )
        assert "# タスク: TASK-001" in result

    def test_uses_no_git_worker_template_when_git_disabled(self):
        """enable_git=false 時は worker_task_no_git を使用することをテスト。"""
        result = generate_7section_task(
            task_id="TASK-NG-001",
            agent_id="worker-001",
            task_description="テストタスク",
            persona_name="Backend Engineer",
            persona_prompt="バックエンド開発者として...",
            memory_context="",
            project_name="test-project",
            enable_git=False,
        )
        assert "No Git モード" in result
        assert "git 操作は行わない" in result

    def test_includes_what_section(self):
        """Whatセクションにタスク説明が含まれることをテスト。"""
        result = generate_7section_task(
            task_id="001",
            agent_id="worker-001",
            task_description="認証機能を実装する",
            persona_name="Backend Engineer",
            persona_prompt="...",
            memory_context="",
            project_name="test-project",
        )
        assert "## What（何をするか）" in result
        assert "認証機能を実装する" in result

    def test_includes_why_section(self):
        """Whyセクションにプロジェクト名が含まれることをテスト。"""
        result = generate_7section_task(
            task_id="001",
            agent_id="worker-001",
            task_description="テスト",
            persona_name="Backend Engineer",
            persona_prompt="...",
            memory_context="",
            project_name="my-project",
        )
        assert "## Why（なぜやるか）" in result
        assert "my-project" in result

    def test_includes_who_section(self):
        """Whoセクションにペルソナ情報が含まれることをテスト。"""
        result = generate_7section_task(
            task_id="001",
            agent_id="worker-001",
            task_description="テスト",
            persona_name="Frontend Specialist",
            persona_prompt="フロントエンドの専門家として振る舞う",
            memory_context="",
            project_name="test-project",
        )
        assert "## Who（誰がやるか）" in result
        assert "**Frontend Specialist**" in result
        assert "フロントエンドの専門家として振る舞う" in result

    def test_includes_constraints_section(self):
        """Constraintsセクションが含まれることをテスト。"""
        result = generate_7section_task(
            task_id="001",
            agent_id="worker-001",
            task_description="テスト",
            persona_name="Engineer",
            persona_prompt="...",
            memory_context="",
            project_name="test-project",
        )
        assert "## Constraints（制約）" in result
        assert "セキュリティ脆弱性を作らない" in result

    def test_includes_current_state_section(self):
        """Current Stateセクションが含まれることをテスト。"""
        result = generate_7section_task(
            task_id="001",
            agent_id="worker-001",
            task_description="テスト",
            persona_name="Engineer",
            persona_prompt="...",
            memory_context="",
            project_name="test-project",
        )
        assert "## Current State（現状）" in result

    def test_includes_memory_context(self):
        """メモリコンテキストが含まれることをテスト。"""
        memory = "関連ドキュメント: docs/api.md"
        result = generate_7section_task(
            task_id="001",
            agent_id="worker-001",
            task_description="テスト",
            persona_name="Engineer",
            persona_prompt="...",
            memory_context=memory,
            project_name="test-project",
        )
        assert "関連ドキュメント: docs/api.md" in result

    def test_no_memory_context(self):
        """メモリコンテキストなしの場合のテスト。"""
        result = generate_7section_task(
            task_id="001",
            agent_id="worker-001",
            task_description="テスト",
            persona_name="Engineer",
            persona_prompt="...",
            memory_context="",
            project_name="test-project",
        )
        assert "（関連情報なし）" in result

    def test_includes_worktree_path(self):
        """worktree_pathが含まれることをテスト。"""
        result = generate_7section_task(
            task_id="001",
            agent_id="worker-001",
            task_description="テスト",
            persona_name="Engineer",
            persona_prompt="...",
            memory_context="",
            project_name="test-project",
            worktree_path="/tmp/worktree/feature-1",
        )
        assert "**作業ディレクトリ**: `/tmp/worktree/feature-1`" in result

    def test_includes_branch_name(self):
        """branch_nameが含まれることをテスト。"""
        result = generate_7section_task(
            task_id="001",
            agent_id="worker-001",
            task_description="テスト",
            persona_name="Engineer",
            persona_prompt="...",
            memory_context="",
            project_name="test-project",
            branch_name="feature/my-branch",
        )
        assert "**作業ブランチ**: `feature/my-branch`" in result

    def test_no_worktree_info(self):
        """worktree情報なしの場合のテスト。"""
        result = generate_7section_task(
            task_id="001",
            agent_id="worker-001",
            task_description="テスト",
            persona_name="Engineer",
            persona_prompt="...",
            memory_context="",
            project_name="test-project",
        )
        assert "（メインリポジトリで作業）" in result

    def test_includes_self_check_info(self):
        """Self-Check情報が含まれることをテスト。"""
        result = generate_7section_task(
            task_id="TASK-999",
            agent_id="worker-abc",
            task_description="テスト",
            persona_name="Engineer",
            persona_prompt="...",
            memory_context="",
            project_name="test-project",
        )
        assert "**タスクID**: TASK-999" in result
        assert "**担当エージェント**: worker-abc" in result
        assert 'retrieve_from_memory "TASK-999"' in result

    def test_includes_decisions_section(self):
        """Decisionsセクションが含まれることをテスト。"""
        result = generate_7section_task(
            task_id="001",
            agent_id="worker-001",
            task_description="テスト",
            persona_name="Engineer",
            persona_prompt="...",
            memory_context="",
            project_name="test-project",
        )
        assert "## Decisions（決定事項）" in result

    def test_includes_notes_section(self):
        """Notesセクションが含まれることをテスト。"""
        result = generate_7section_task(
            task_id="001",
            agent_id="worker-001",
            task_description="テスト",
            persona_name="Engineer",
            persona_prompt="...",
            memory_context="",
            project_name="test-project",
        )
        assert "## Notes（メモ）" in result
        assert "report_task_completion" in result

    def test_includes_custom_mcp_tool_prefix(self):
        """カスタムMCPツールプレフィックスが反映されることをテスト。"""
        result = generate_7section_task(
            task_id="001",
            agent_id="worker-001",
            task_description="テスト",
            persona_name="Engineer",
            persona_prompt="...",
            memory_context="",
            project_name="test-project",
            mcp_tool_prefix="mcp__custom-server__",
        )
        assert "mcp__custom-server__report_task_completion" in result
        # デフォルトのプレフィックスが含まれないことを確認
        assert "mcp__multi-agent-mcp__report_task_completion" not in result

    def test_uses_default_mcp_tool_prefix(self):
        """デフォルトのMCPツールプレフィックスが使用されることをテスト。"""
        result = generate_7section_task(
            task_id="001",
            agent_id="worker-001",
            task_description="テスト",
            persona_name="Engineer",
            persona_prompt="...",
            memory_context="",
            project_name="test-project",
        )
        assert "mcp__multi-agent-mcp__report_task_completion" in result
