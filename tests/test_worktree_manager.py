"""WorktreeManagerのテスト。"""

from unittest.mock import AsyncMock, patch

import pytest


class TestWorktreeManager:
    """WorktreeManagerのテスト。"""

    @pytest.mark.asyncio
    async def test_is_git_repo(self, worktree_manager):
        """gitリポジトリかどうかを確認できることをテスト。"""
        result = await worktree_manager.is_git_repo()
        assert result is True

    @pytest.mark.asyncio
    async def test_is_git_repo_invalid(self, temp_dir):
        """無効なパスでFalseを返すことをテスト。"""
        from src.managers.worktree_manager import WorktreeManager

        manager = WorktreeManager(str(temp_dir / "nonexistent"))
        result = await manager.is_git_repo()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_gtr_available(self, worktree_manager):
        """gtrの利用可能性を確認できることをテスト。"""
        result = await worktree_manager._check_gtr_available()
        # gtr がインストールされているかどうかに依存
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_list_worktrees(self, worktree_manager):
        """worktree一覧を取得できることをテスト。"""
        worktrees = await worktree_manager.list_worktrees()
        assert isinstance(worktrees, list)
        # メインのworktreeが含まれているはず
        assert len(worktrees) >= 1

    @pytest.mark.asyncio
    async def test_get_current_branch(self, worktree_manager):
        """現在のブランチを取得できることをテスト。"""
        branch = await worktree_manager.get_current_branch()
        # 初期状態では master または main
        assert branch in ["master", "main"]


class TestWorktreeManagerCreateWorktree:
    """create_worktreeのテスト。"""

    @pytest.mark.asyncio
    async def test_create_worktree_native_returns_actual_path(
        self, worktree_manager, temp_dir
    ):
        """native worktree作成で実際のパスを返すことをテスト。"""
        # gtr を無効化
        worktree_manager._force_gtr = False
        worktree_manager._gtr_available = False

        worktree_path = str(temp_dir / "test-worktree")
        branch = "test-branch"

        success, message, actual_path = await worktree_manager.create_worktree(
            worktree_path, branch
        )

        assert success is True
        assert actual_path == worktree_path
        assert "作成しました" in message

        # クリーンアップ
        await worktree_manager.remove_worktree(worktree_path)

    @pytest.mark.asyncio
    async def test_create_worktree_native_existing_path(
        self, worktree_manager, temp_dir
    ):
        """既存パスでエラーを返すことをテスト。"""
        worktree_manager._force_gtr = False
        worktree_manager._gtr_available = False

        # 既存のパスを指定
        existing_path = str(temp_dir)

        success, message, actual_path = await worktree_manager.create_worktree(
            existing_path, "test-branch"
        )

        assert success is False
        assert actual_path is None
        assert "既に存在" in message

    @pytest.mark.asyncio
    async def test_create_worktree_gtr_returns_actual_path(self, worktree_manager):
        """gtr worktree作成で実際のパスを返すことをテスト（モック）。"""
        worktree_manager._force_gtr = True
        worktree_manager._gtr_available = True

        with patch.object(
            worktree_manager, "_run_command", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = (0, "Created worktree", "")

            with patch.object(
                worktree_manager,
                "get_worktree_path_for_branch",
                new_callable=AsyncMock,
            ) as mock_get_path:
                mock_get_path.return_value = "/actual/gtr/path"

                success, message, actual_path = await worktree_manager.create_worktree(
                    "/ignored/path", "feature/test"
                )

                assert success is True
                assert actual_path == "/actual/gtr/path"
                assert "gtr" in message

    @pytest.mark.asyncio
    async def test_create_worktree_gtr_failure(self, worktree_manager):
        """gtr worktree作成失敗時にNoneを返すことをテスト。"""
        worktree_manager._force_gtr = True
        worktree_manager._gtr_available = True

        with patch.object(
            worktree_manager, "_run_command", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = (1, "", "error message")

            success, message, actual_path = await worktree_manager.create_worktree(
                "/ignored/path", "feature/test"
            )

            assert success is False
            assert actual_path is None
            assert "失敗" in message


class TestWorktreeManagerRemoveWorktree:
    """remove_worktreeのテスト。"""

    @pytest.mark.asyncio
    async def test_remove_worktree_native(self, worktree_manager, temp_dir):
        """native worktree削除をテスト。"""
        worktree_manager._force_gtr = False
        worktree_manager._gtr_available = False

        # 先にworktreeを作成
        worktree_path = str(temp_dir / "to-remove")
        await worktree_manager.create_worktree(worktree_path, "branch-to-remove")

        # 削除
        success, message = await worktree_manager.remove_worktree(worktree_path)
        assert success is True
        assert "削除" in message

    @pytest.mark.asyncio
    async def test_remove_worktree_gtr(self, worktree_manager):
        """gtr worktree削除をテスト（モック）。"""
        worktree_manager._force_gtr = True
        worktree_manager._gtr_available = True

        with patch.object(
            worktree_manager, "_run_command", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = (0, "", "")

            success, message = await worktree_manager.remove_worktree("feature/test")
            assert success is True
            assert "gtr" in message


class TestWorktreeManagerGetWorktreePath:
    """get_worktree_path_for_branchのテスト。"""

    @pytest.mark.asyncio
    async def test_get_worktree_path_for_branch_found(
        self, worktree_manager, temp_dir
    ):
        """ブランチからworktreeパスを取得できることをテスト。"""
        import os

        worktree_manager._force_gtr = False
        worktree_manager._gtr_available = False

        # worktreeを作成
        worktree_path = str(temp_dir / "path-test")
        await worktree_manager.create_worktree(worktree_path, "path-test-branch")

        # パスを取得
        found_path = await worktree_manager.get_worktree_path_for_branch(
            "path-test-branch"
        )
        # macOS では /var が /private/var のシンボリックリンクなので realpath で比較
        assert os.path.realpath(found_path) == os.path.realpath(worktree_path)

        # クリーンアップ
        await worktree_manager.remove_worktree(worktree_path)

    @pytest.mark.asyncio
    async def test_get_worktree_path_for_branch_not_found(self, worktree_manager):
        """存在しないブランチでNoneを返すことをテスト。"""
        found_path = await worktree_manager.get_worktree_path_for_branch(
            "nonexistent-branch"
        )
        assert found_path is None
