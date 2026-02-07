"""TmuxManagerのテスト。

注意: このテストにはtmuxがインストールされている必要があります。
tmuxがインストールされていない環境ではスキップされます。
"""

import shutil
import uuid

import pytest

from src.managers.tmux_manager import TmuxManager, get_project_name

# tmuxが利用可能かチェック
HAS_TMUX = shutil.which("tmux") is not None


class TestGetProjectName:
    """get_project_name 関数のテスト。"""

    def test_raises_value_error_for_non_git_directory(self, temp_dir):
        """git リポジトリでないディレクトリで ValueError を発生させることをテスト。"""
        with pytest.raises(ValueError) as exc_info:
            get_project_name(str(temp_dir))

        assert "git リポジトリではありません" in str(exc_info.value)

    def test_returns_project_name_for_git_repo(self, git_repo):
        """git リポジトリでプロジェクト名を返すことをテスト。"""
        result = get_project_name(str(git_repo))
        # git_repo フィクスチャは temp_dir/repo を作成
        assert result == "repo"


class TestTmuxWorkspaceMixinUnit:
    """TmuxWorkspaceMixin の単体テスト。"""

    @pytest.mark.asyncio
    async def test_get_pane_current_command_success(self, settings):
        """pane_current_command を取得できることをテスト。"""
        manager = TmuxManager(settings)

        async def mock_run(*_args):
            return (0, "zsh\n", "")

        manager._run = mock_run  # type: ignore[assignment]

        command = await manager.get_pane_current_command("session", 0, 1)
        assert command == "zsh"

    @pytest.mark.asyncio
    async def test_get_pane_current_command_failure(self, settings):
        """取得失敗時に None を返すことをテスト。"""
        manager = TmuxManager(settings)

        async def mock_run(*_args):
            return (1, "", "error")

        manager._run = mock_run  # type: ignore[assignment]

        command = await manager.get_pane_current_command("session", 0, 1)
        assert command is None


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
    async def test_create_main_session_normalizes_existing_window_index(
        self, tmux_manager, git_repo
    ):
        """既存セッションでも main ウィンドウが 0 番になることをテスト。"""
        session_name = "repo"  # git_repo fixture の project_name と一致

        # グローバルの index 設定を退避
        _, base_stdout, _ = await tmux_manager._run("show", "-g", "base-index")
        _, pane_stdout, _ = await tmux_manager._run("show", "-g", "pane-base-index")
        base_parts = base_stdout.strip().split()
        pane_parts = pane_stdout.strip().split()
        base_index = base_parts[-1] if base_parts else "0"
        pane_base_index = pane_parts[-1] if pane_parts else "0"

        # base-index=1 の環境を再現
        await tmux_manager._run("set", "-g", "base-index", "1")
        await tmux_manager._run("set", "-g", "pane-base-index", "1")
        await tmux_manager._run("new-session", "-d", "-s", session_name, "-n", "main")

        try:
            # 既存セッション経路（早期 return）で正規化されることを確認
            success = await tmux_manager.create_main_session(str(git_repo))
            assert success is True

            code, stdout, _ = await tmux_manager._run(
                "list-windows", "-t", session_name, "-F", "#{window_index}:#{window_name}"
            )
            assert code == 0
            assert "0:main" in stdout
        finally:
            await tmux_manager.kill_session(session_name)
            await tmux_manager._run("set", "-g", "base-index", base_index)
            await tmux_manager._run("set", "-g", "pane-base-index", pane_base_index)

    @pytest.mark.asyncio
    async def test_create_main_session_normalizes_new_session_window_index(
        self, tmux_manager, git_repo
    ):
        """新規セッションでも main ウィンドウが 0 番になることをテスト。"""
        session_name = "repo"  # git_repo fixture の project_name と一致

        # グローバルの index 設定を退避
        _, base_stdout, _ = await tmux_manager._run("show", "-g", "base-index")
        _, pane_stdout, _ = await tmux_manager._run("show", "-g", "pane-base-index")
        base_parts = base_stdout.strip().split()
        pane_parts = pane_stdout.strip().split()
        base_index = base_parts[-1] if base_parts else "0"
        pane_base_index = pane_parts[-1] if pane_parts else "0"

        # base-index=1 の環境を再現
        await tmux_manager._run("set", "-g", "base-index", "1")
        await tmux_manager._run("set", "-g", "pane-base-index", "1")

        try:
            # 新規セッション経路でも正規化されることを確認
            success = await tmux_manager.create_main_session(str(git_repo))
            assert success is True

            code, stdout, _ = await tmux_manager._run(
                "list-windows", "-t", session_name, "-F", "#{window_index}:#{window_name}"
            )
            assert code == 0
            assert "0:main" in stdout
        finally:
            await tmux_manager.kill_session(session_name)
            await tmux_manager._run("set", "-g", "base-index", base_index)
            await tmux_manager._run("set", "-g", "pane-base-index", pane_base_index)

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
            assert session_name in sessions
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
    async def test_cleanup_sessions_only_targets(self, tmux_manager, temp_dir):
        """指定セッションのみクリーンアップできることをテスト。"""
        session_a = f"test-scoped-{uuid.uuid4().hex[:8]}-a"
        session_b = f"test-scoped-{uuid.uuid4().hex[:8]}-b"

        await tmux_manager.create_session(session_a, str(temp_dir))
        await tmux_manager.create_session(session_b, str(temp_dir))

        try:
            count = await tmux_manager.cleanup_sessions([session_a])
            assert count >= 1

            exists_a = await tmux_manager.session_exists(session_a)
            exists_b = await tmux_manager.session_exists(session_b)
            assert exists_a is False
            assert exists_b is True
        finally:
            await tmux_manager.kill_session(session_a)
            await tmux_manager.kill_session(session_b)

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

        import src.managers.tmux_manager as tmux_module

        # get_project_name をモック（git リポジトリでなくても動作させる）
        monkeypatch.setattr(tmux_module, "get_project_name", lambda x: "test-project")

        # shutil.which をモックして ghostty が存在するようにする
        monkeypatch.setattr(shutil, "which", lambda x: "/usr/local/bin/ghostty")

        # asyncio.create_subprocess_exec をモックしてプロセス起動をシミュレート
        # returncode = None はプロセスがまだ実行中であることを示す
        class MockProcess:
            returncode = None

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
        import src.managers.tmux_manager as tmux_module
        from src.managers.terminal import GhosttyExecutor, ITerm2Executor

        # get_project_name をモック（git リポジトリでなくても動作させる）
        monkeypatch.setattr(tmux_module, "get_project_name", lambda x: "test-project")

        # Ghostty を利用不可にする
        async def mock_ghostty_unavailable(self):
            return False

        monkeypatch.setattr(GhosttyExecutor, "is_available", mock_ghostty_unavailable)

        # iTerm2 を利用可能にして成功させる
        async def mock_iterm2_available(self):
            return True

        async def mock_iterm2_execute(self, working_dir, script, script_path):
            return (True, "iTerm2 でワークスペースを開きました")

        monkeypatch.setattr(ITerm2Executor, "is_available", mock_iterm2_available)
        monkeypatch.setattr(ITerm2Executor, "execute_script", mock_iterm2_execute)

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
        import src.managers.tmux_manager as tmux_module
        from src.managers.terminal import (
            GhosttyExecutor,
            ITerm2Executor,
            TerminalAppExecutor,
        )

        # get_project_name をモック（git リポジトリでなくても動作させる）
        monkeypatch.setattr(tmux_module, "get_project_name", lambda x: "test-project")

        # Ghostty を利用不可にする
        async def mock_ghostty_unavailable(self):
            return False

        monkeypatch.setattr(GhosttyExecutor, "is_available", mock_ghostty_unavailable)

        # iTerm2 を利用不可にする
        async def mock_iterm2_unavailable(self):
            return False

        monkeypatch.setattr(ITerm2Executor, "is_available", mock_iterm2_unavailable)

        # Terminal.app を利用可能にして成功させる
        async def mock_terminal_available(self):
            return True

        async def mock_terminal_execute(self, working_dir, script, script_path):
            return (True, "Terminal.app でワークスペースを開きました")

        monkeypatch.setattr(TerminalAppExecutor, "is_available", mock_terminal_available)
        monkeypatch.setattr(TerminalAppExecutor, "execute_script", mock_terminal_execute)

        success, message = await tmux_manager.launch_workspace_in_terminal(
            str(temp_dir)
        )

        assert success is True
        assert "Terminal.app" in message

    @pytest.mark.asyncio
    async def test_create_main_session_runs_expected_split_sequence(
        self, tmux_manager, monkeypatch
    ):
        """create_main_session の分割順序をテスト。"""
        import src.managers.tmux_manager as tmux_module

        monkeypatch.setattr(tmux_module, "get_project_name", lambda _wd: "test-project")

        calls: list[tuple[str, ...]] = []

        async def mock_run(*args):
            calls.append(tuple(args))
            return (0, "", "")

        tmux_manager._run = mock_run
        tmux_manager.session_exists = lambda _session: False  # type: ignore[assignment]

        async def mock_session_exists(_session):
            return False

        tmux_manager.session_exists = mock_session_exists  # type: ignore[assignment]

        success = await tmux_manager.create_main_session("/tmp/workspace")
        assert success is True

        split_calls = [c for c in calls if c and c[0] == "split-window"]
        assert split_calls[0][1:] == ("-h", "-t", "test-project:main", "-p", "60")
        assert split_calls[1][1:] == ("-h", "-t", "test-project:main.1", "-p", "67")
        assert split_calls[2][1:] == ("-h", "-t", "test-project:main.2", "-p", "50")

    def test_get_pane_for_role_boundary_workers(self, tmux_manager):
        """Worker 6/7 の境界でウィンドウが切り替わることをテスト。"""
        main_slot = tmux_manager.get_pane_for_role("worker", worker_index=5)
        extra_slot = tmux_manager.get_pane_for_role("worker", worker_index=6)

        assert main_slot == ("main", 0, 6)
        assert extra_slot is not None
        assert extra_slot[1] == 1

    @pytest.mark.asyncio
    async def test_add_extra_worker_window_returns_true_when_window_exists(
        self, tmux_manager, monkeypatch
    ):
        """既存ウィンドウがある場合は作成せず True を返すことをテスト。"""
        async def mock_list_windows(_session):
            return [{"index": 1, "name": "workers-2", "panes": 12}]

        tmux_manager.list_windows = mock_list_windows  # type: ignore[assignment]

        called = {"run": 0}

        async def mock_run(*_args):
            called["run"] += 1
            return (0, "", "")

        tmux_manager._run = mock_run  # type: ignore[assignment]

        success = await tmux_manager.add_extra_worker_window("repo", 1)
        assert success is True
        assert called["run"] == 0
