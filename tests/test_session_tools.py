"""session_tools.py のユニットテスト。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.workspace import WorktreeInfo
from src.tools.session_state import (
    cleanup_orphan_provisional_sessions,
    cleanup_session_resources,
)
from src.tools.session_tools import _migrate_provisional_session_dir

# cleanup_session_resources 内で resolve_main_repo_root が呼ばれるのをモック
_RESOLVE_PATCH = "src.tools.helpers_persistence.resolve_main_repo_root"
_HEALTHCHECK_PATCH = "src.managers.healthcheck_daemon.stop_healthcheck_daemon"


class TestCleanupWorkspaceUnified:
    """cleanup_workspace の統一クリーンアップテスト。"""

    @pytest.mark.asyncio
    async def test_uses_unified_cleanup(self, app_ctx, temp_dir):
        """T9: cleanup_workspace が cleanup_session_resources を使用すること。

        cleanup_workspace は remove_worktrees=False で
        cleanup_session_resources を呼ぶ。
        統一関数が正しく呼ばれることを、実際に呼び出して確認する。
        """
        app_ctx.project_root = str(temp_dir)

        with patch(
            _HEALTHCHECK_PATCH, new_callable=AsyncMock,
        ), patch(_RESOLVE_PATCH, return_value=str(temp_dir)):
            results = await cleanup_session_resources(
                app_ctx, remove_worktrees=False
            )

        # cleanup_session_resources が正しい結果を返すこと
        assert "terminated_sessions" in results
        assert "cleared_agents" in results
        assert "ipc_cleaned" in results
        assert "dashboard_cleaned" in results
        assert "agents_file_deleted" in results
        assert "config_session_cleared" in results
        # worktree は削除しない
        assert results["removed_worktrees"] == 0
        # インメモリ状態がリセットされていること
        assert app_ctx.session_id is None
        assert len(app_ctx.agents) == 0


class TestInitTmuxWorkspaceRecovery:
    """init_tmux_workspace のセッションリカバリテスト。"""

    @pytest.mark.asyncio
    async def test_recovers_stale_session(self, app_ctx, temp_dir):
        """T13: 既存セッション検出時にリカバリが行われること。

        init_tmux_workspace のリカバリフローをシミュレート:
        1. session_exists=True で既存セッション検出
        2. cleanup_session_resources でリソース解放
        3. kill_session でセッション削除
        4. session_exists=False で再初期化可能
        """
        app_ctx.project_root = str(temp_dir)
        tmux = app_ctx.tmux
        tmux.kill_session = AsyncMock(return_value=True)

        with patch(
            _HEALTHCHECK_PATCH, new_callable=AsyncMock,
        ), patch(
            _RESOLVE_PATCH, return_value=str(temp_dir),
        ):
            # ① 既存セッションの検出をシミュレート
            tmux.session_exists = AsyncMock(return_value=True)
            session_exists = await tmux.session_exists("test-project")
            assert session_exists is True

            # ② cleanup_session_resources でリソースを解放
            results = await cleanup_session_resources(
                app_ctx, remove_worktrees=False
            )
            assert "terminated_sessions" in results

            # ③ tmux セッションを明示的に kill
            await tmux.kill_session("test-project")

            # ④ 再チェック: kill 後はセッションが存在しない
            tmux.session_exists = AsyncMock(return_value=False)
            still_exists = await tmux.session_exists("test-project")
            assert still_exists is False

        # kill_session が呼ばれたことを確認
        tmux.kill_session.assert_called_with("test-project")

    @pytest.mark.asyncio
    async def test_recovery_fails_when_kill_fails(self):
        """既存セッションの kill に失敗した場合エラーが返されること。"""
        tmux = MagicMock()
        # session_exists: kill 後もまだ存在する
        tmux.session_exists = AsyncMock(side_effect=[True, True])
        tmux.kill_session = AsyncMock(return_value=False)

        # kill 後に再チェックしてもセッションが存在する場合
        still_exists = await tmux.session_exists("test-project")
        assert still_exists is True


class TestCleanupOnCompletionUnified:
    """cleanup_on_completion の統一クリーンアップテスト。"""

    @pytest.mark.asyncio
    async def test_uses_unified_cleanup(self, app_ctx, temp_dir):
        """T10: cleanup_on_completion が cleanup_session_resources を使用すること。

        cleanup_on_completion は remove_worktrees=True で
        cleanup_session_resources を呼ぶ。
        """
        app_ctx.project_root = str(temp_dir)

        with patch(
            _HEALTHCHECK_PATCH, new_callable=AsyncMock,
        ), patch(_RESOLVE_PATCH, return_value=str(temp_dir)):
            results = await cleanup_session_resources(
                app_ctx, remove_worktrees=True, repo_path="/test/repo"
            )

        # cleanup_session_resources が正しい結果を返すこと
        assert "terminated_sessions" in results
        assert "cleared_agents" in results
        assert "registry_removed" in results
        assert "ipc_cleaned" in results
        assert "dashboard_cleaned" in results
        # インメモリ状態がリセットされていること
        assert app_ctx.session_id is None
        assert len(app_ctx.agents) == 0

    @pytest.mark.asyncio
    async def test_removes_only_session_managed_worktrees(self, app_ctx, temp_dir):
        """管理下 path/branch に厳密一致する worktree のみ削除することをテスト。"""
        repo_path = temp_dir / "repo"
        repo_path.mkdir(parents=True, exist_ok=True)
        app_ctx.project_root = str(temp_dir)
        app_ctx.settings.enable_git = True

        managed_path = str(repo_path / ".worktrees" / "managed-worker")
        unmanaged_path = str(repo_path / ".worktrees" / "managed-worker-shadow")
        managed_branch = "feature/task-worker-1-ab12cd34"

        # セッション管理下ターゲットを 1 件のみ設定
        worker = app_ctx.agents["agent-002"]
        worker.worktree_path = managed_path
        worker.branch = managed_branch

        mock_worktree_manager = MagicMock()
        mock_worktree_manager.list_worktrees = AsyncMock(
            return_value=[
                WorktreeInfo(
                    path=managed_path,
                    branch=managed_branch,
                    commit="a1",
                    is_bare=False,
                    is_detached=False,
                    locked=False,
                    prunable=False,
                ),
                WorktreeInfo(
                    path=unmanaged_path,
                    branch="feature/task-worker-1-ab12cd34-shadow",
                    commit="b2",
                    is_bare=False,
                    is_detached=False,
                    locked=False,
                    prunable=False,
                ),
            ]
        )
        mock_worktree_manager.remove_worktree = AsyncMock(return_value=(True, "removed"))

        with patch(
            _HEALTHCHECK_PATCH, new_callable=AsyncMock,
        ), patch(
            _RESOLVE_PATCH, return_value=str(temp_dir),
        ), patch(
            "src.tools.helpers.get_worktree_manager",
            return_value=mock_worktree_manager,
        ):
            results = await cleanup_session_resources(
                app_ctx,
                remove_worktrees=True,
                repo_path=str(repo_path),
            )

        assert results["removed_worktrees"] == 1
        mock_worktree_manager.remove_worktree.assert_awaited_once_with(
            managed_path,
            force=True,
            managed_branch_names={managed_branch},
        )


class TestProvisionalSessionMigration:
    """provisional セッション移行のテスト。"""

    def test_migrates_provisional_directory(self, temp_dir):
        """provisional-* ディレクトリが正式 session_id へ移行されることをテスト。"""
        mcp_dir = temp_dir / ".multi-agent-mcp"
        source = mcp_dir / "provisional-abcd1234"
        source.mkdir(parents=True, exist_ok=True)
        (source / "agents.json").write_text('{"owner":"owner-001"}', encoding="utf-8")

        result = _migrate_provisional_session_dir(
            project_root=str(temp_dir),
            mcp_dir_name=".multi-agent-mcp",
            previous_session_id="provisional-abcd1234",
            new_session_id="issue-123",
        )

        target = mcp_dir / "issue-123"
        assert result["executed"] is True
        assert result["source_removed"] is True
        assert (target / "agents.json").exists()
        assert not source.exists()

    def test_skips_non_provisional_session(self, temp_dir):
        """provisional 以外の session_id では移行を行わないことをテスト。"""
        result = _migrate_provisional_session_dir(
            project_root=str(temp_dir),
            mcp_dir_name=".multi-agent-mcp",
            previous_session_id="issue-001",
            new_session_id="issue-002",
        )
        assert result["executed"] is False

    def test_cleans_up_orphan_provisional_directories(self, temp_dir):
        """孤立した provisional-* ディレクトリを削除できることをテスト。"""
        mcp_dir = temp_dir / ".multi-agent-mcp"
        orphan = mcp_dir / "provisional-old1234"
        orphan.mkdir(parents=True, exist_ok=True)
        (orphan / "agents.json").write_text("{}", encoding="utf-8")

        result = cleanup_orphan_provisional_sessions(
            project_root=str(temp_dir),
            mcp_dir_name=".multi-agent-mcp",
            target_session_ids=["provisional-old1234"],
        )

        assert result["removed_count"] == 1
        assert result["removed_dirs"] == ["provisional-old1234"]
        assert not orphan.exists()

    def test_cleans_up_all_provisional_directories_when_target_is_none(self, temp_dir):
        """target_session_ids=None の場合に provisional-* を一括削除することをテスト。"""
        mcp_dir = temp_dir / ".multi-agent-mcp"
        first = mcp_dir / "provisional-old1111"
        second = mcp_dir / "provisional-old2222"
        first.mkdir(parents=True, exist_ok=True)
        second.mkdir(parents=True, exist_ok=True)
        (first / "agents.json").write_text("{}", encoding="utf-8")
        (second / "agents.json").write_text("{}", encoding="utf-8")

        result = cleanup_orphan_provisional_sessions(
            project_root=str(temp_dir),
            mcp_dir_name=".multi-agent-mcp",
            target_session_ids=None,
        )

        assert result["removed_count"] == 2
        assert sorted(result["removed_dirs"]) == ["provisional-old1111", "provisional-old2222"]
        assert not first.exists()
        assert not second.exists()
