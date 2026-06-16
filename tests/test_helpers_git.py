"""helpers_git のテスト。"""

from unittest.mock import MagicMock, patch

from src.tools import helpers_git


def test_resolve_main_repo_root_caches_result():
    """同一パスの解決結果はキャッシュされ、git は1回しか実行されないこと。"""
    helpers_git.clear_main_repo_root_cache()

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        if "--show-toplevel" in cmd:
            result.stdout = "/repo\n"
        else:  # --git-common-dir
            result.stdout = "/repo/.git\n"
        return result

    with patch("src.managers.git_utils.subprocess.run", side_effect=fake_run) as mock_run:
        first = helpers_git.resolve_main_repo_root("/repo/sub")
        second = helpers_git.resolve_main_repo_root("/repo/sub")

    assert first == "/repo"
    assert second == "/repo"
    # 1回目で2回（show-toplevel + git-common-dir）、2回目はキャッシュヒットで0回
    assert mock_run.call_count == 2


def test_clear_main_repo_root_cache_forces_recompute():
    """キャッシュクリア後は再計算されること。"""
    helpers_git.clear_main_repo_root_cache()

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.stdout = "/repo\n" if "--show-toplevel" in cmd else "/repo/.git\n"
        return result

    with patch("src.managers.git_utils.subprocess.run", side_effect=fake_run) as mock_run:
        helpers_git.resolve_main_repo_root("/repo/sub")
        helpers_git.clear_main_repo_root_cache()
        helpers_git.resolve_main_repo_root("/repo/sub")

    assert mock_run.call_count == 4  # クリアで再計算され 2回 + 2回
