"""tmux_shared ユーティリティのテスト。"""

import re

import pytest

from src.managers.tmux_shared import get_legacy_project_name, get_project_name


class TestGetProjectName:
    """セッション名生成のテスト。"""

    def test_git_project_name_always_has_suffix(self, git_repo):
        """git リポジトリでも base-hash 形式になる。"""
        result = get_project_name(str(git_repo), enable_git=True)
        assert re.fullmatch(rf"{re.escape(git_repo.name)}-[0-9a-f]{{6}}", result)

    def test_non_git_project_name_has_suffix(self, temp_dir):
        """non-git でも base-hash 形式になる。"""
        result = get_project_name(str(temp_dir), enable_git=False)
        assert re.fullmatch(rf"{re.escape(temp_dir.name)}-[0-9a-f]{{6}}", result)

    def test_legacy_project_name_returns_git_basename(self, git_repo):
        """旧命名は git basename を返す。"""
        assert get_legacy_project_name(str(git_repo), enable_git=True) == git_repo.name

    def test_legacy_project_name_is_none_for_non_git_mode(self, temp_dir):
        """no-git モードには legacy 名がない。"""
        assert get_legacy_project_name(str(temp_dir), enable_git=False) is None

    def test_git_project_name_raises_for_non_git_dir(self, temp_dir):
        """enable_git=True で non-git を指定した場合は例外。"""
        with pytest.raises(ValueError):
            get_project_name(str(temp_dir), enable_git=True)
