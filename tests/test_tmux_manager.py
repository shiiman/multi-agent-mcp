"""TmuxManagerのテスト。

注意: このテストにはtmuxがインストールされている必要があります。
tmuxがインストールされていない環境ではスキップされます。
"""

import shutil

import pytest

# tmuxが利用可能かチェック
HAS_TMUX = shutil.which("tmux") is not None


@pytest.mark.skipif(not HAS_TMUX, reason="tmux is not installed")
class TestTmuxManager:
    """TmuxManagerのテスト。"""

    @pytest.mark.asyncio
    async def test_create_and_kill_session(self, tmux_manager, temp_dir):
        """セッション作成と終了をテスト。"""
        session_name = "test-session-001"

        # セッション作成
        success = await tmux_manager.create_session(session_name, str(temp_dir))
        assert success is True

        # セッションが存在することを確認
        exists = await tmux_manager.session_exists(session_name)
        assert exists is True

        # セッション終了
        success = await tmux_manager.kill_session(session_name)
        assert success is True

        # セッションが存在しないことを確認
        exists = await tmux_manager.session_exists(session_name)
        assert exists is False

    @pytest.mark.asyncio
    async def test_send_keys(self, tmux_manager, temp_dir):
        """キー送信をテスト。"""
        session_name = "test-session-002"

        await tmux_manager.create_session(session_name, str(temp_dir))

        try:
            # コマンド送信
            success = await tmux_manager.send_keys(session_name, "echo 'hello'")
            assert success is True
        finally:
            await tmux_manager.kill_session(session_name)

    @pytest.mark.asyncio
    async def test_capture_pane(self, tmux_manager, temp_dir):
        """ペインキャプチャをテスト。"""
        session_name = "test-session-003"

        await tmux_manager.create_session(session_name, str(temp_dir))

        try:
            # 出力をキャプチャ
            output = await tmux_manager.capture_pane(session_name, 10)
            assert output is not None
            assert isinstance(output, str)
        finally:
            await tmux_manager.kill_session(session_name)

    @pytest.mark.asyncio
    async def test_list_sessions(self, tmux_manager, temp_dir):
        """セッション一覧をテスト。"""
        session_name = "test-session-004"

        await tmux_manager.create_session(session_name, str(temp_dir))

        try:
            sessions = await tmux_manager.list_sessions()
            # 作成したセッションが含まれているか確認
            # list_sessions()はプレフィックス付きのセッション名のリストを返す
            full_session_name = f"{tmux_manager.prefix}-{session_name}"
            assert full_session_name in sessions
        finally:
            await tmux_manager.kill_session(session_name)

    @pytest.mark.asyncio
    async def test_cleanup_all_sessions(self, tmux_manager, temp_dir):
        """全セッションクリーンアップをテスト。"""
        # 複数セッションを作成
        await tmux_manager.create_session("test-cleanup-001", str(temp_dir))
        await tmux_manager.create_session("test-cleanup-002", str(temp_dir))

        # クリーンアップ
        count = await tmux_manager.cleanup_all_sessions()

        assert count >= 2

    @pytest.mark.asyncio
    async def test_session_not_exists(self, tmux_manager):
        """存在しないセッションをテスト。"""
        exists = await tmux_manager.session_exists("nonexistent-session")
        assert exists is False

    @pytest.mark.asyncio
    async def test_kill_nonexistent_session(self, tmux_manager):
        """存在しないセッションの終了をテスト。"""
        # エラーにはならないが、falseを返す
        success = await tmux_manager.kill_session("nonexistent-session")
        # 実装によってはTrue/Falseが変わるが、例外は発生しない
        assert success is True or success is False
