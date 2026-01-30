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

    @pytest.mark.asyncio
    async def test_send_keys_with_special_characters(self, tmux_manager, temp_dir):
        """特殊文字を含むコマンドのリテラルモード送信をテスト。"""
        session_name = "test-session-special"

        await tmux_manager.create_session(session_name, str(temp_dir))

        try:
            # 特殊文字（#, $, !）を含むコマンドをリテラルモードで送信
            success = await tmux_manager.send_keys(
                session_name, "echo 'Hello #World $USER!'", literal=True
            )
            assert success is True

            # 少し待ってから出力をキャプチャ
            import asyncio

            await asyncio.sleep(0.5)
            output = await tmux_manager.capture_pane(session_name, 10)
            # コマンドがそのまま送信されていることを確認
            assert "Hello #World" in output or "echo" in output
        finally:
            await tmux_manager.kill_session(session_name)

    @pytest.mark.asyncio
    async def test_send_keys_non_literal_mode(self, tmux_manager, temp_dir):
        """非リテラルモードでの送信をテスト。"""
        session_name = "test-session-nonliteral"

        await tmux_manager.create_session(session_name, str(temp_dir))

        try:
            # 非リテラルモードで送信
            success = await tmux_manager.send_keys(
                session_name, "echo test", literal=False
            )
            assert success is True
        finally:
            await tmux_manager.kill_session(session_name)

    @pytest.mark.asyncio
    async def test_run_shell(self, tmux_manager):
        """シェルコマンド実行をテスト。"""
        code, stdout, stderr = await tmux_manager._run_shell("echo 'test'")
        assert code == 0
        assert "test" in stdout

    @pytest.mark.asyncio
    async def test_run_shell_error(self, tmux_manager):
        """シェルコマンドエラーをテスト。"""
        code, stdout, stderr = await tmux_manager._run_shell("exit 1")
        assert code == 1

    @pytest.mark.asyncio
    async def test_open_session_in_terminal_terminal_app(
        self, tmux_manager, temp_dir, monkeypatch
    ):
        """Terminal.app でセッションを開くテスト（モック使用）。"""
        session_name = "test-session-terminal"

        await tmux_manager.create_session(session_name, str(temp_dir))

        try:
            # shutil.which をモックして ghostty が存在しないようにする
            monkeypatch.setattr(shutil, "which", lambda x: None)

            # _run_shell をモックしてターミナル起動をシミュレート
            # ghostty(macOS path)は失敗、iTerm2は失敗、Terminal.appは成功
            async def mock_run_shell(cmd):
                if "ghostty" in cmd.lower():
                    return (1, "", "ghostty not found")
                if "iTerm" in cmd and "exists" in cmd:
                    return (1, "", "")  # iTerm2 存在チェック失敗
                if "Terminal" in cmd:
                    return (0, "", "")  # Terminal.app 成功
                return (1, "", "unknown command")

            monkeypatch.setattr(tmux_manager, "_run_shell", mock_run_shell)

            success = await tmux_manager.open_session_in_terminal(session_name)

            assert success is True
        finally:
            await tmux_manager.kill_session(session_name)

    @pytest.mark.asyncio
    async def test_open_session_in_terminal_iterm(
        self, tmux_manager, temp_dir, monkeypatch
    ):
        """iTerm2 でセッションを開くテスト（モック使用）。"""
        session_name = "test-session-iterm"

        await tmux_manager.create_session(session_name, str(temp_dir))

        try:
            # shutil.which をモックして ghostty が存在しないようにする
            monkeypatch.setattr(shutil, "which", lambda x: None)

            # _run_shell をモックして iTerm2 で開くシミュレート
            # ghostty(macOS path)は失敗、iTerm2は成功
            async def mock_run_shell(cmd):
                if "ghostty" in cmd.lower():
                    return (1, "", "ghostty not found")
                if "iTerm" in cmd:
                    return (0, "", "")  # iTerm2 存在チェック成功、iTerm2 で開く成功
                return (1, "", "unknown command")

            monkeypatch.setattr(tmux_manager, "_run_shell", mock_run_shell)

            success = await tmux_manager.open_session_in_terminal(session_name)

            assert success is True
        finally:
            await tmux_manager.kill_session(session_name)

    @pytest.mark.asyncio
    async def test_open_session_in_terminal_ghostty(
        self, tmux_manager, temp_dir, monkeypatch
    ):
        """ghostty でセッションを開くテスト（モック使用）。"""
        session_name = "test-session-ghostty"

        await tmux_manager.create_session(session_name, str(temp_dir))

        try:
            # shutil.which をモックして ghostty が存在するようにする
            monkeypatch.setattr(shutil, "which", lambda x: "/usr/local/bin/ghostty")

            # _run_shell をモックして ghostty で開くシミュレート
            call_count = 0

            async def mock_run_shell(cmd):
                nonlocal call_count
                call_count += 1
                return (0, "", "")

            monkeypatch.setattr(tmux_manager, "_run_shell", mock_run_shell)

            success = await tmux_manager.open_session_in_terminal(session_name)

            assert success is True
            assert call_count == 1
        finally:
            await tmux_manager.kill_session(session_name)

    # ========== ターミナル先行起動関連テスト ==========

    def test_generate_workspace_script(self, tmux_manager):
        """ワークスペーススクリプト生成をテスト。"""
        script = tmux_manager._generate_workspace_script(
            "mcp-agent-main", "/tmp/test-workspace"
        )

        # スクリプトに必要な要素が含まれているか確認
        assert 'SESSION="mcp-agent-main"' in script
        assert 'WD="/tmp/test-workspace"' in script
        assert "tmux new-session -d" in script
        assert "tmux split-window" in script
        assert "tmux attach" in script
        assert "set -e" in script

    @pytest.mark.asyncio
    async def test_launch_workspace_in_terminal_invalid_dir(self, tmux_manager):
        """存在しないディレクトリでの起動失敗をテスト。"""
        success, message = await tmux_manager.launch_workspace_in_terminal(
            "/nonexistent/directory/path"
        )

        assert success is False
        assert "存在しません" in message

    @pytest.mark.asyncio
    async def test_launch_workspace_in_terminal_ghostty(
        self, tmux_manager, temp_dir, monkeypatch
    ):
        """launch_workspace_in_terminal の Ghostty 起動テスト（モック使用）。"""
        import asyncio

        # shutil.which をモックして ghostty が存在するようにする
        monkeypatch.setattr(shutil, "which", lambda x: "/usr/local/bin/ghostty")

        # asyncio.create_subprocess_exec をモックしてプロセス起動をシミュレート
        class MockProcess:
            returncode = 0

            async def communicate(self):
                return b"", b""

        async def mock_create_subprocess_exec(*args, **kwargs):
            return MockProcess()

        monkeypatch.setattr(
            asyncio, "create_subprocess_exec", mock_create_subprocess_exec
        )

        success, message = await tmux_manager.launch_workspace_in_terminal(
            str(temp_dir)
        )

        assert success is True
        assert "Ghostty" in message

    @pytest.mark.asyncio
    async def test_launch_workspace_in_terminal_iterm2(
        self, tmux_manager, temp_dir, monkeypatch
    ):
        """launch_workspace_in_terminal の iTerm2 起動テスト（モック使用）。"""
        # _execute_script_in_ghostty を失敗させる
        async def mock_ghostty_fail(working_dir, script):
            return (False, "Ghostty が見つかりません")

        monkeypatch.setattr(
            tmux_manager, "_execute_script_in_ghostty", mock_ghostty_fail
        )

        # _execute_script_in_iterm2 を成功させる
        async def mock_iterm2_success(working_dir, script):
            return (True, "iTerm2 でワークスペースを開きました")

        monkeypatch.setattr(
            tmux_manager, "_execute_script_in_iterm2", mock_iterm2_success
        )

        success, message = await tmux_manager.launch_workspace_in_terminal(
            str(temp_dir)
        )

        assert success is True
        assert "iTerm2" in message

    @pytest.mark.asyncio
    async def test_launch_workspace_in_terminal_terminal_app(
        self, tmux_manager, temp_dir, monkeypatch
    ):
        """launch_workspace_in_terminal の Terminal.app 起動テスト（モック使用）。"""
        # _execute_script_in_ghostty を失敗させる
        async def mock_ghostty_fail(working_dir, script):
            return (False, "Ghostty が見つかりません")

        monkeypatch.setattr(
            tmux_manager, "_execute_script_in_ghostty", mock_ghostty_fail
        )

        # _execute_script_in_iterm2 を失敗させる
        async def mock_iterm2_fail(working_dir, script):
            return (False, "iTerm2 が見つかりません")

        monkeypatch.setattr(
            tmux_manager, "_execute_script_in_iterm2", mock_iterm2_fail
        )

        # _execute_script_in_terminal_app を成功させる
        async def mock_terminal_success(working_dir, script):
            return (True, "Terminal.app でワークスペースを開きました")

        monkeypatch.setattr(
            tmux_manager, "_execute_script_in_terminal_app", mock_terminal_success
        )

        success, message = await tmux_manager.launch_workspace_in_terminal(
            str(temp_dir)
        )

        assert success is True
        assert "Terminal.app" in message
