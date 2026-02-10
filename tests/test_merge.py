"""merge.py のユニットテスト。"""

import subprocess
from unittest.mock import patch

import pytest
from mcp.server.fastmcp import FastMCP

from src.models.dashboard import TaskStatus
from src.tools.merge import _is_branch_merged, _run_git, register_tools


class TestRunGit:
    """_run_git のテスト。"""

    def test_run_git_success(self, git_repo):
        """正常な git コマンドが成功を返す。"""
        ok, output = _run_git(str(git_repo), ["status"])
        assert ok is True

    def test_run_git_failure_returns_stderr(self, git_repo):
        """存在しないブランチへの checkout は失敗を返す。"""
        ok, output = _run_git(str(git_repo), ["checkout", "nonexistent-branch"])
        assert ok is False
        assert output != ""

    def test_run_git_invalid_repo_path(self, temp_dir):
        """存在しないリポジトリパスでも例外にならない。"""
        ok, output = _run_git(str(temp_dir / "no-repo"), ["status"])
        assert ok is False

    def test_run_git_exception_handling(self):
        """subprocess.run が例外を投げた場合に (False, message) を返す。"""
        with patch("src.tools.merge.subprocess.run", side_effect=OSError("command not found")):
            ok, output = _run_git("/tmp", ["status"])
        assert ok is False
        assert "command not found" in output


class TestIsBranchMerged:
    """_is_branch_merged のテスト。"""

    def test_branch_is_ancestor(self, git_repo):
        """同一ブランチは ancestor として True を返す。"""
        # HEAD は自分自身の ancestor
        result = _is_branch_merged(str(git_repo), "HEAD", "HEAD")
        assert result is True

    def test_branch_not_merged(self, git_repo):
        """マージされていないブランチは False を返す。"""
        # 新しいブランチを作成してコミットを追加
        subprocess.run(
            ["git", "-C", str(git_repo), "checkout", "-b", "feature-test"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(git_repo), "commit", "--allow-empty", "-m", "feature commit"],
            capture_output=True,
            check=True,
        )
        # feature-test は main より先にいるので main は feature-test の ancestor ではない
        result = _is_branch_merged(str(git_repo), "feature-test", "main")
        assert result is False


class TestMergeCompletedTasks:
    """merge_completed_tasks ツールのテスト。"""

    @staticmethod
    def _get_merge_tool():
        """merge_completed_tasks ツール関数を取得する。"""
        mcp = FastMCP("test")
        register_tools(mcp)
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "merge_completed_tasks":
                return tool.fn
        raise RuntimeError("merge_completed_tasks ツールが見つかりません")

    @pytest.mark.asyncio
    async def test_invalid_strategy_returns_error(self, mock_mcp_context, git_repo):
        """無効な strategy が指定された場合にエラーを返す。"""
        merge_completed_tasks = self._get_merge_tool()
        app_ctx = mock_mcp_context.request_context.lifespan_context
        app_ctx.project_root = str(git_repo)
        result = await merge_completed_tasks(
            session_id="issue-1",
            repo_path=str(git_repo),
            base_branch="main",
            strategy="invalid",
            caller_agent_id="agent-001",
            ctx=mock_mcp_context,
        )
        assert result["success"] is False
        assert "strategy は merge / squash / rebase" in result["error"]

    @pytest.mark.asyncio
    async def test_returns_error_when_git_disabled(self, mock_mcp_context, git_repo):
        """enable_git=false のとき merge_completed_tasks がエラーになることをテスト。"""
        merge_completed_tasks = self._get_merge_tool()
        app_ctx = mock_mcp_context.request_context.lifespan_context
        app_ctx.project_root = str(git_repo)
        app_ctx.settings.enable_git = False

        result = await merge_completed_tasks(
            session_id="issue-no-git",
            repo_path=str(git_repo),
            base_branch="main",
            strategy="merge",
            caller_agent_id="agent-001",
            ctx=mock_mcp_context,
        )

        assert result["success"] is False
        assert "MCP_ENABLE_GIT=false" in result["error"]

    @pytest.mark.asyncio
    async def test_applies_preview_diff_without_commit(
        self, mock_mcp_context, git_repo
    ):
        """統合差分を commit なしで展開し、履歴は変わらないことをテスト。"""
        merge_completed_tasks = self._get_merge_tool()

        base_branch = subprocess.check_output(
            ["git", "-C", str(git_repo), "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
        ).strip()
        feature_branch = "feature-merge-report"
        feature_file = git_repo / "preview_diff.txt"

        feature_file.write_text("base line\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(git_repo), "add", "preview_diff.txt"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(git_repo), "commit", "-m", "add base file"],
            capture_output=True,
            check=True,
        )

        subprocess.run(
            ["git", "-C", str(git_repo), "checkout", "-b", feature_branch],
            capture_output=True,
            check=True,
        )
        feature_file.write_text("preview diff content\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(git_repo), "commit", "-am", "feature commit"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(git_repo), "checkout", base_branch],
            capture_output=True,
            check=True,
        )

        app_ctx = mock_mcp_context.request_context.lifespan_context
        app_ctx.project_root = str(git_repo)
        task = app_ctx.dashboard_manager.create_task(title="merge target", branch=feature_branch)
        app_ctx.dashboard_manager.update_task_status(task.id, TaskStatus.COMPLETED)

        head_before = subprocess.check_output(
            ["git", "-C", str(git_repo), "rev-parse", "HEAD"],
            text=True,
        ).strip()

        with patch(
            "src.tools.merge.ensure_dashboard_manager",
            return_value=app_ctx.dashboard_manager,
        ):
            result = await merge_completed_tasks(
                session_id="issue-2",
                repo_path=str(git_repo),
                base_branch=base_branch,
                strategy="merge",
                caller_agent_id="agent-001",
                ctx=mock_mcp_context,
            )

        head_after = subprocess.check_output(
            ["git", "-C", str(git_repo), "rev-parse", "HEAD"],
            text=True,
        ).strip()

        assert result["success"] is True
        assert result["preview_merge"] is True
        assert result["working_tree_updated"] is True
        assert result["merged"] == [feature_branch]
        assert head_before == head_after
        unstaged = subprocess.check_output(
            ["git", "-C", str(git_repo), "diff", "--name-only"],
            text=True,
        ).splitlines()
        staged = subprocess.check_output(
            ["git", "-C", str(git_repo), "diff", "--cached", "--name-only"],
            text=True,
        ).splitlines()
        assert "preview_diff.txt" in unstaged
        assert staged == []
        assert _is_branch_merged(str(git_repo), feature_branch, base_branch) is False

    @pytest.mark.asyncio
    async def test_marks_missing_branch_as_failed(self, mock_mcp_context, git_repo):
        """存在しない branch は failed に記録されることをテスト。"""
        merge_completed_tasks = self._get_merge_tool()
        base_branch = subprocess.check_output(
            ["git", "-C", str(git_repo), "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
        ).strip()

        app_ctx = mock_mcp_context.request_context.lifespan_context
        app_ctx.project_root = str(git_repo)
        task = app_ctx.dashboard_manager.create_task(
            title="missing branch task",
            branch="feature/missing-branch",
        )
        app_ctx.dashboard_manager.update_task_status(task.id, TaskStatus.COMPLETED)

        with patch(
            "src.tools.merge.ensure_dashboard_manager",
            return_value=app_ctx.dashboard_manager,
        ):
            result = await merge_completed_tasks(
                session_id="issue-3",
                repo_path=str(git_repo),
                base_branch=base_branch,
                strategy="rebase",
                caller_agent_id="agent-001",
                ctx=mock_mcp_context,
            )
        assert result["success"] is False
        assert result["failed"] == [
            {"branch": "feature/missing-branch", "error": "branch_not_found"}
        ]

    def test_run_git_returns_stdout_on_success(self, git_repo):
        """_run_git が成功時に stdout を返す。"""
        ok, output = _run_git(str(git_repo), ["rev-parse", "--git-dir"])
        assert ok is True
        assert ".git" in output
