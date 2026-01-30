"""tmuxセッション管理モジュール。"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config.settings import Settings

from src.config.settings import TerminalApp

logger = logging.getLogger(__name__)

# セッション名定数（単一セッション方式）
# 注意: MAIN_SESSION は後方互換性のために残していますが、
# 実際のセッション名はプロジェクト名を含む動的な名前になります
MAIN_SESSION = "main"


def get_project_name(working_dir: str) -> str:
    """作業ディレクトリからプロジェクト名を取得する。

    Args:
        working_dir: 作業ディレクトリのパス

    Returns:
        プロジェクト名（ディレクトリ名）
    """
    from pathlib import Path

    return Path(working_dir).name

# メインウィンドウのペイン配置
# Owner は tmux ペインに配置しない（実行AIエージェントが担う）
# 左 40%: Admin (0)
# 右 60%: Worker 1-6 (1-6)
MAIN_WINDOW_PANE_ADMIN = 0
MAIN_WINDOW_WORKER_PANES = [1, 2, 3, 4, 5, 6]  # Worker 1-6


class TmuxManager:
    """tmuxセッションを管理するクラス。"""

    def __init__(self, settings: "Settings") -> None:
        """TmuxManagerを初期化する。

        Args:
            settings: アプリケーション設定
        """
        self.prefix = settings.tmux_prefix
        self.default_terminal = settings.default_terminal

    async def _run(self, *args: str) -> tuple[int, str, str]:
        """tmuxコマンドを実行する。

        Args:
            *args: tmuxコマンドの引数

        Returns:
            (リターンコード, stdout, stderr) のタプル
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "tmux",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return proc.returncode or 0, stdout.decode(), stderr.decode()
        except FileNotFoundError:
            logger.error("tmux がインストールされていません")
            return 1, "", "tmux not found"
        except Exception as e:
            logger.error(f"tmux コマンド実行エラー: {e}")
            return 1, "", str(e)

    def _session_name(self, name: str) -> str:
        """セッション名にプレフィックスを付与する。

        Args:
            name: 元のセッション名

        Returns:
            プレフィックス付きセッション名
        """
        return f"{self.prefix}-{name}"

    def _get_window_name(self, window_index: int) -> str:
        """ウィンドウインデックスからウィンドウ名を取得する。

        base-index 設定に依存せず、ウィンドウ名で指定することで
        異なる環境でも一貫した動作を保証する。

        Args:
            window_index: ウィンドウインデックス（0 = メイン、1+ = 追加）

        Returns:
            ウィンドウ名（"main" または "workers-N"）
        """
        if window_index == 0:
            return "main"
        return f"workers-{window_index}"

    async def create_session(self, name: str, working_dir: str) -> bool:
        """新しいtmuxセッションを作成する。

        Args:
            name: セッション名（プレフィックスなし）
            working_dir: 作業ディレクトリのパス

        Returns:
            成功した場合True
        """
        session_name = self._session_name(name)
        code, _, stderr = await self._run(
            "new-session", "-d", "-s", session_name, "-c", working_dir
        )
        if code != 0:
            logger.error(f"セッション作成エラー: {stderr}")
        return code == 0

    async def send_keys(self, session: str, command: str, literal: bool = True) -> bool:
        """セッションにキー入力を送信する。

        Args:
            session: セッション名（プレフィックスなし）
            command: 実行するコマンド
            literal: Trueの場合、特殊文字をリテラルとして送信（デフォルト: True）

        Returns:
            成功した場合True
        """
        session_name = self._session_name(session)

        # コマンド送信（リテラルモードで特殊文字をエスケープ）
        # multi-agent-shogun の知見: メッセージと Enter は別々に送信する必要がある
        if literal:
            code, _, stderr = await self._run(
                "send-keys", "-t", session_name, "-l", command
            )
        else:
            code, _, stderr = await self._run(
                "send-keys", "-t", session_name, command
            )

        if code != 0:
            logger.error(f"キー送信エラー: {stderr}")
            return False

        # Enter キーを別途送信（重要：multi-agent-shogun の知見）
        code, _, stderr = await self._run("send-keys", "-t", session_name, "Enter")
        if code != 0:
            logger.error(f"Enterキー送信エラー: {stderr}")
        return code == 0

    async def capture_pane(self, session: str, lines: int = 100) -> str:
        """セッションの出力をキャプチャする。

        Args:
            session: セッション名（プレフィックスなし）
            lines: 取得する行数

        Returns:
            キャプチャした出力テキスト
        """
        session_name = self._session_name(session)
        code, stdout, stderr = await self._run(
            "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"
        )
        if code != 0:
            logger.error(f"ペインキャプチャエラー: {stderr}")
            return ""
        return stdout

    async def kill_session(self, session: str) -> bool:
        """セッションを終了する。

        Args:
            session: セッション名（プレフィックスなし）

        Returns:
            成功した場合True
        """
        session_name = self._session_name(session)
        code, _, stderr = await self._run("kill-session", "-t", session_name)
        if code != 0:
            logger.warning(f"セッション終了エラー（既に終了している可能性）: {stderr}")
        return code == 0

    async def list_sessions(self) -> list[str]:
        """管理対象のセッション一覧を取得する。

        Returns:
            セッション名のリスト（プレフィックス付き）
        """
        code, stdout, _ = await self._run("list-sessions", "-F", "#{session_name}")
        if code != 0:
            return []
        sessions = [s.strip() for s in stdout.strip().split("\n") if s.strip()]
        return [s for s in sessions if s.startswith(self.prefix)]

    async def session_exists(self, session: str) -> bool:
        """セッションが存在するか確認する。

        Args:
            session: セッション名（プレフィックスなし）

        Returns:
            存在する場合True
        """
        session_name = self._session_name(session)
        code, _, _ = await self._run("has-session", "-t", session_name)
        return code == 0

    async def cleanup_all_sessions(self) -> int:
        """管理対象の全セッションを終了する。

        Returns:
            終了したセッション数
        """
        sessions = await self.list_sessions()
        count = 0
        for session in sessions:
            # プレフィックスを除去して kill_session を呼び出す
            name = session.replace(f"{self.prefix}-", "", 1)
            if await self.kill_session(name):
                count += 1
        return count

    async def _run_shell(self, command: str) -> tuple[int, str, str]:
        """シェルコマンドを実行する。

        Args:
            command: 実行するシェルコマンド

        Returns:
            (リターンコード, stdout, stderr) のタプル
        """
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return proc.returncode or 0, stdout.decode(), stderr.decode()
        except Exception as e:
            logger.error(f"シェルコマンド実行エラー: {e}")
            return 1, "", str(e)

    async def open_session_in_terminal(self, session: str) -> bool:
        """tmuxセッションをターミナルアプリで開く。

        環境変数 MCP_DEFAULT_TERMINAL で指定されたターミナルを使用。
        auto の場合は優先順位: ghostty → iTerm2 → Terminal.app

        Args:
            session: セッション名（プレフィックスなし）

        Returns:
            成功した場合True
        """
        session_name = self._session_name(session)
        attach_cmd = f"tmux attach -t {session_name}"

        # 指定されたターミナルを使用
        if self.default_terminal == TerminalApp.GHOSTTY:
            return await self._open_in_ghostty(attach_cmd)
        elif self.default_terminal == TerminalApp.ITERM2:
            return await self._open_in_iterm2(attach_cmd)
        elif self.default_terminal == TerminalApp.TERMINAL:
            return await self._open_in_terminal_app(attach_cmd)

        # auto: 優先順位で試行
        if await self._open_in_ghostty(attach_cmd):
            return True
        if await self._open_in_iterm2(attach_cmd):
            return True
        return await self._open_in_terminal_app(attach_cmd)

    async def _open_in_ghostty(self, attach_cmd: str) -> bool:
        """Ghostty でセッションを開く。"""
        import shutil
        from pathlib import Path

        ghostty_path = shutil.which("ghostty")
        if not ghostty_path:
            macos_ghostty = Path("/Applications/Ghostty.app/Contents/MacOS/ghostty")
            if macos_ghostty.exists():
                ghostty_path = str(macos_ghostty)

        if ghostty_path:
            code, _, _ = await self._run_shell(f'"{ghostty_path}" -e "{attach_cmd}"')
            return code == 0
        return False

    async def _open_in_iterm2(self, attach_cmd: str) -> bool:
        """iTerm2 でセッションを開く。"""
        iterm_check = await self._run_shell(
            "osascript -e 'application \"iTerm\" exists'"
        )
        if iterm_check[0] == 0:
            applescript = f'''
            tell application "iTerm"
                activate
                create window with default profile
                tell current session of current window
                    write text "{attach_cmd}"
                end tell
            end tell
            '''
            code, _, _ = await self._run_shell(f"osascript -e '{applescript}'")
            return code == 0
        return False

    async def _open_in_terminal_app(self, attach_cmd: str) -> bool:
        """macOS Terminal.app でセッションを開く。"""
        applescript = f'''
        tell application "Terminal"
            activate
            do script "{attach_cmd}"
        end tell
        '''
        code, _, _ = await self._run_shell(f"osascript -e '{applescript}'")
        return code == 0

    # ========== グリッドレイアウト関連メソッド ==========

    async def create_main_session(self, working_dir: str) -> bool:
        """メインセッション（左40:右60分離レイアウト）を作成する。

        Owner は tmux ペインに配置しない（実行AIエージェントが担う）。

        レイアウト:
        ┌─────────────────┬─────────────────────────────┐
        │                 │    W1    │    W2    │  W3   │
        │     Admin       │  pane 1  │  pane 2  │pane 3 │
        │     pane 0      ├──────────┼──────────┼───────┤
        │      40%        │    W4    │    W5    │  W6   │
        │                 │  pane 4  │  pane 5  │pane 6 │
        └─────────────────┴─────────────────────────────┘
               40%                    60%

        Args:
            working_dir: 作業ディレクトリのパス

        Returns:
            成功した場合True
        """
        # プロジェクト名を含むセッション名を生成
        project_name = get_project_name(working_dir)
        session_name = self._session_name(project_name)

        # セッションが既に存在する場合はスキップ
        if await self.session_exists(project_name):
            logger.info(f"メインセッション {session_name} は既に存在します")
            return True

        # 1. セッション作成（ウィンドウ名: main）
        code, _, stderr = await self._run(
            "new-session", "-d", "-s", session_name, "-c", working_dir, "-n", "main"
        )
        if code != 0:
            logger.error(f"メインセッション作成エラー: {stderr}")
            return False

        # セッション固有のオプション設定（base-index に依存しないようにする）
        await self._run("set-option", "-t", session_name, "base-index", "0")
        await self._run("set-option", "-t", session_name, "pane-base-index", "0")

        # ウィンドウ名 "main" を使用
        target = f"{session_name}:main"

        # 分割順序: 右側を先に完成させる
        # これにより、分割中のペイン番号のシフトを回避

        # 2. 左右40:60に分割（右側60%を作成）
        code, _, stderr = await self._run(
            "split-window", "-h", "-t", target, "-p", "60"
        )
        if code != 0:
            logger.error(f"左右分割エラー: {stderr}")
            return False

        # 3. 右側（pane 1）を3列に分割
        # 現在のペイン配置: 0(左40%), 1(右60%)
        # 最初の分割: 67% (2/3) を残す → pane 2 ができる
        code, _, stderr = await self._run(
            "split-window", "-h", "-t", f"{target}.1", "-p", "67"
        )
        if code != 0:
            logger.error(f"右側列分割エラー(1): {stderr}")
            return False

        # 2回目の分割: 残りの50% → pane 3 ができる
        # 現在のペイン配置: 0(左40%), 1(W列1), 2(W列2+3)
        code, _, stderr = await self._run(
            "split-window", "-h", "-t", f"{target}.2", "-p", "50"
        )
        if code != 0:
            logger.error(f"右側列分割エラー(2): {stderr}")
            return False

        # 4. 各Worker列を上下に分割（3列 → 6ペイン）
        # 現在のペイン配置: 0(左40%), 1(W列1), 2(W列2), 3(W列3)
        # 重要: 逆順（.3 → .2 → .1）で分割することで、
        # 分割時のペイン番号シフトを回避
        for pane_idx in [3, 2, 1]:
            code, _, stderr = await self._run(
                "split-window", "-v", "-t", f"{target}.{pane_idx}"
            )
            if code != 0:
                logger.error(f"右側行分割エラー(pane {pane_idx}): {stderr}")
                return False

        # 最終的なペイン配置: 0(Admin), 1-6(Workers)
        # Owner の分割は不要（実行AIエージェントが Owner の役割を担う）

        logger.info(f"メインセッション作成完了: {session_name}")
        return True

    async def _split_into_grid(
        self, session: str, window: int, rows: int = 2, cols: int = 3
    ) -> bool:
        """指定ウィンドウをグリッドに分割する。

        Args:
            session: セッション名（プレフィックス付き）
            window: ウィンドウ番号
            rows: 行数
            cols: 列数

        Returns:
            成功した場合True
        """
        target = f"{session}:{window}"

        # 1. 水平分割で cols 列作成
        for _ in range(cols - 1):
            code, _, stderr = await self._run("split-window", "-h", "-t", target)
            if code != 0:
                logger.error(f"水平分割エラー: {stderr}")
                return False

        # 2. 列幅を均等化（これにより各列が十分な幅を持つ）
        code, _, _ = await self._run("select-layout", "-t", target, "even-horizontal")
        if code != 0:
            logger.warning("列幅均等化に失敗、続行します")

        # 3. 各列を垂直分割で rows 行に
        # 重要: 逆順（cols-1 → 0）で分割することで、
        # 分割時のペイン番号シフトを回避
        for col in range(cols - 1, -1, -1):
            pane_target = f"{target}.{col}"
            for _ in range(rows - 1):
                code, _, stderr = await self._run(
                    "split-window", "-v", "-t", pane_target
                )
                if code != 0:
                    logger.error(f"垂直分割エラー: {stderr}")
                    return False

        logger.debug(f"グリッド分割完了: {target} ({rows}×{cols})")
        return True

    async def add_window(
        self, session: str, window_name: str, rows: int = 2, cols: int = 3
    ) -> int | None:
        """セッションに新しいウィンドウを追加しグリッドを作成する。

        Args:
            session: セッション名（プレフィックスなし）
            window_name: ウィンドウ名
            rows: 行数
            cols: 列数

        Returns:
            新しいウィンドウ番号、失敗した場合None
        """
        session_name = self._session_name(session)

        # 新しいウィンドウを追加
        code, _, stderr = await self._run(
            "new-window", "-t", session_name, "-n", window_name
        )
        if code != 0:
            logger.error(f"ウィンドウ追加エラー: {stderr}")
            return None

        # ウィンドウ番号を取得
        windows = await self.list_windows(session)
        if not windows:
            return None

        # 最後のウィンドウ番号
        window_index = len(windows) - 1

        # グリッドに分割
        success = await self._split_into_grid(session_name, window_index, rows, cols)
        if not success:
            return None

        logger.info(f"ウィンドウ追加完了: {session_name}:{window_name} ({window_index})")
        return window_index

    async def add_extra_worker_window(
        self,
        project_name: str,
        window_index: int,
        rows: int = 2,
        cols: int = 6,
    ) -> bool:
        """追加Workerウィンドウ（6×2グリッド）を作成する。

        Args:
            project_name: プロジェクト名（セッション名の一部）
            window_index: ウィンドウインデックス（1, 2, ...）
            rows: 行数
            cols: 列数

        Returns:
            成功した場合True
        """
        session_name = self._session_name(project_name)
        window_name = f"workers-{window_index + 1}"

        # ウィンドウが既に存在するか確認
        windows = await self.list_windows(project_name)
        existing_indices = {w["index"] for w in windows}
        if window_index in existing_indices:
            logger.info(f"ウィンドウ {window_index} は既に存在します")
            return True

        # 新しいウィンドウを追加
        code, _, stderr = await self._run(
            "new-window", "-t", session_name, "-n", window_name
        )
        if code != 0:
            logger.error(f"追加Workerウィンドウ作成エラー: {stderr}")
            return False

        # ウィンドウに pane-base-index を設定（ユーザーのグローバル設定に依存しない）
        window_target = f"{session_name}:{window_name}"
        await self._run("set-window-option", "-t", window_target, "pane-base-index", "0")

        # グリッドに分割（6×2 = 12ペイン）
        success = await self._split_into_grid(session_name, window_index, rows, cols)
        if not success:
            return False

        logger.info(f"追加Workerウィンドウ作成完了: {session_name}:{window_name}")
        return True

    def get_pane_for_role(
        self, role: str, worker_index: int = 0, settings: "Settings | None" = None
    ) -> tuple[str, int, int] | None:
        """ロールに対応するペイン位置を取得する。

        Owner は tmux ペインに配置しないため、None を返す。

        Args:
            role: エージェントの役割（"owner", "admin", "worker"）
            worker_index: Worker番号（0始まり、roleがworkerの場合のみ使用）
            settings: 設定オブジェクト（Worker 7以上の場合に必要）

        Returns:
            (session_name, window_index, pane_index) のタプル、または None（ownerの場合）
        """
        if role == "owner":
            # Owner は tmux ペインに配置しない（実行AIエージェントが担う）
            return None
        elif role == "admin":
            return MAIN_SESSION, 0, MAIN_WINDOW_PANE_ADMIN
        elif role == "worker":
            # Worker 1-6 はメインウィンドウ
            if worker_index < 6:
                # ペイン番号: 1, 2, 3, 4, 5, 6
                pane_index = MAIN_WINDOW_WORKER_PANES[worker_index]
                return MAIN_SESSION, 0, pane_index
            else:
                # Worker 7以降は追加ウィンドウ
                # 追加ウィンドウは12ペイン/ウィンドウ
                extra_worker_index = worker_index - 6
                workers_per_extra = 12  # デフォルト
                if settings:
                    workers_per_extra = settings.workers_per_extra_window

                window_index = 1 + (extra_worker_index // workers_per_extra)
                pane_index = extra_worker_index % workers_per_extra
                return MAIN_SESSION, window_index, pane_index
        else:
            raise ValueError(f"不明なロール: {role}")

    async def send_keys_to_pane(
        self,
        session: str,
        window: int,
        pane: int,
        command: str,
        literal: bool = True,
    ) -> bool:
        """指定したウィンドウ・ペインにキー入力を送信する。

        Args:
            session: セッション名（プレフィックスなし）
            window: ウィンドウ番号（0 = メイン、1+ = 追加）
            pane: ペインインデックス
            command: 実行するコマンド
            literal: Trueの場合、特殊文字をリテラルとして送信

        Returns:
            成功した場合True
        """
        session_name = self._session_name(session)
        window_name = self._get_window_name(window)
        target = f"{session_name}:{window_name}.{pane}"

        # コマンド送信
        if literal:
            code, _, stderr = await self._run("send-keys", "-t", target, "-l", command)
        else:
            code, _, stderr = await self._run("send-keys", "-t", target, command)

        if code != 0:
            logger.error(f"ペインへのキー送信エラー: {stderr}")
            return False

        # Enter キーを別途送信
        code, _, stderr = await self._run("send-keys", "-t", target, "Enter")
        if code != 0:
            logger.error(f"Enterキー送信エラー: {stderr}")
        return code == 0

    async def capture_pane_by_index(
        self, session: str, window: int, pane: int, lines: int = 100
    ) -> str:
        """指定したウィンドウ・ペインの出力をキャプチャする。

        Args:
            session: セッション名（プレフィックスなし）
            window: ウィンドウ番号（0 = メイン、1+ = 追加）
            pane: ペインインデックス
            lines: 取得する行数

        Returns:
            キャプチャした出力テキスト
        """
        session_name = self._session_name(session)
        window_name = self._get_window_name(window)
        target = f"{session_name}:{window_name}.{pane}"

        code, stdout, stderr = await self._run(
            "capture-pane", "-t", target, "-p", "-S", f"-{lines}"
        )
        if code != 0:
            logger.error(f"ペインキャプチャエラー: {stderr}")
            return ""
        return stdout

    async def set_pane_title(
        self, session: str, window: int, pane: int, title: str
    ) -> bool:
        """ペインにタイトルを設定する。

        Args:
            session: セッション名（プレフィックスなし）
            window: ウィンドウ番号（0 = メイン、1+ = 追加）
            pane: ペインインデックス
            title: タイトル

        Returns:
            成功した場合True
        """
        session_name = self._session_name(session)
        window_name = self._get_window_name(window)
        target = f"{session_name}:{window_name}.{pane}"

        # ペインタイトルを設定
        code, _, stderr = await self._run(
            "select-pane", "-t", target, "-T", title
        )
        if code != 0:
            logger.warning(f"ペインタイトル設定警告: {stderr}")
        return code == 0

    async def list_windows(self, session: str) -> list[dict]:
        """セッション内のウィンドウ一覧を取得する。

        Args:
            session: セッション名（プレフィックスなし）

        Returns:
            ウィンドウ情報のリスト
        """
        session_name = self._session_name(session)

        code, stdout, _ = await self._run(
            "list-windows",
            "-t",
            session_name,
            "-F",
            "#{window_index}:#{window_name}:#{window_panes}",
        )
        if code != 0:
            return []

        windows = []
        for line in stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split(":")
            if len(parts) >= 3:
                windows.append(
                    {
                        "index": int(parts[0]),
                        "name": parts[1],
                        "panes": int(parts[2]),
                    }
                )
        return windows

    async def get_pane_count(self, session: str, window: int) -> int:
        """指定ウィンドウのペイン数を取得する。

        Args:
            session: セッション名（プレフィックスなし）
            window: ウィンドウ番号

        Returns:
            ペイン数
        """
        windows = await self.list_windows(session)
        for w in windows:
            if w["index"] == window:
                return w["panes"]
        return 0

    # ========== ターミナル先行起動関連メソッド ==========

    def _generate_workspace_script(self, session_name: str, working_dir: str) -> str:
        """ワークスペース構築用のシェルスクリプトを生成する。

        セッション作成・ペイン分割・attachを一度に行うスクリプトを生成。
        Owner は tmux ペインに配置しない（実行AIエージェントが担う）。

        Args:
            session_name: tmuxセッション名（プレフィックス付き）
            working_dir: 作業ディレクトリのパス

        Returns:
            シェルスクリプト文字列
        """
        # シェル変数でエスケープ問題を回避
        # 注意: ウィンドウ名 "main" を使用（base-index 設定に依存しないため）
        script = f'''#!/bin/bash
set -e

SESSION="{session_name}"
WD="{working_dir}"

# セッションが存在しない場合のみ作成
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Creating new tmux session: $SESSION"

    # 1. セッション作成（ウィンドウ名: main）
    tmux new-session -d -s "$SESSION" -c "$WD" -n main

    # セッション固有のオプション設定（base-index に依存しないようにする）
    tmux set-option -t "$SESSION" base-index 0
    tmux set-option -t "$SESSION" pane-base-index 0

    # 分割順序: 右側を先に完成させる
    # これにより pane 0 が途中で番号変更されるのを防ぐ

    # 2. 左右40:60に分割（左40% Admin, 右60% Workers）
    # pane 0 = 左40%, pane 1 = 右60%
    tmux split-window -h -t "$SESSION:main" -p 60

    # 3. 右側（pane 1）を3列に分割
    tmux split-window -h -t "$SESSION:main.1" -p 67
    tmux split-window -h -t "$SESSION:main.2" -p 50
    # pane 0 = Admin, pane 1 = W列1, pane 2 = W列2, pane 3 = W列3

    # 4. 各Worker列を上下に分割（6ペイン）
    # 重要: 逆順（.3 → .2 → .1）で分割することで、
    # 分割時のペイン番号シフトを回避
    tmux split-window -v -t "$SESSION:main.3"
    tmux split-window -v -t "$SESSION:main.2"
    tmux split-window -v -t "$SESSION:main.1"
    # pane 0 = Admin, pane 1-6 = Workers

    # Owner の分割は不要（VSCode Claude が Owner の役割を担う）

    echo "Workspace layout created"
else
    echo "Session $SESSION already exists"
fi

# セッションにattach
exec tmux attach -t "$SESSION"
'''
        return script

    async def launch_workspace_in_terminal(
        self,
        working_dir: str,
        terminal: TerminalApp | None = None,
    ) -> tuple[bool, str]:
        """ターミナルを開いてtmuxワークスペース（グリッドレイアウト）を構築する。

        ターミナルを先に開き、その中でtmuxセッション作成・ペイン分割を行う。
        セッションが既に存在する場合はattachのみ行う。

        Args:
            working_dir: 作業ディレクトリのパス
            terminal: 使用するターミナルアプリ（Noneでデフォルト設定を使用）

        Returns:
            (成功したかどうか, メッセージ) のタプル
        """
        import os
        import shutil
        import tempfile

        from .terminal import GhosttyExecutor, ITerm2Executor, TerminalAppExecutor

        # 作業ディレクトリの検証
        if not os.path.isdir(working_dir):
            return False, f"作業ディレクトリが存在しません: {working_dir}"

        # tmuxの利用可能性確認
        if shutil.which("tmux") is None:
            return False, "tmux がインストールされていません"

        # ターミナル設定
        terminal = terminal or self.default_terminal

        # プロジェクト名を含むセッション名を生成
        project_name = get_project_name(working_dir)
        session_name = self._session_name(project_name)

        # スクリプト生成
        script = self._generate_workspace_script(session_name, working_dir)

        # スクリプトを一時ファイルに書き出す
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".sh",
            prefix="mcp-workspace-",
            delete=False,
        ) as f:
            f.write(script)
            script_path = f.name
        os.chmod(script_path, 0o755)

        # ターミナル実行クラスの選択
        executors = {
            TerminalApp.GHOSTTY: GhosttyExecutor(),
            TerminalApp.ITERM2: ITerm2Executor(),
            TerminalApp.TERMINAL: TerminalAppExecutor(),
        }

        # 指定されたターミナルを使用
        if terminal in executors:
            executor = executors[terminal]
            if await executor.is_available():
                return await executor.execute_script(working_dir, script, script_path)

        # auto: 優先順位で試行
        for app in [TerminalApp.GHOSTTY, TerminalApp.ITERM2, TerminalApp.TERMINAL]:
            executor = executors[app]
            if await executor.is_available():
                success, msg = await executor.execute_script(
                    working_dir, script, script_path
                )
                if success:
                    return True, msg

        return False, "利用可能なターミナルアプリが見つかりません"
