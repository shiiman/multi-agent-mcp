"""TmuxManager のワークスペース構築ロジック mixin。"""

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING

from src.config.settings import TerminalApp
from src.config.template_loader import get_template_loader
from src.managers.tmux_shared import (
    MAIN_SESSION,
    MAIN_WINDOW_PANE_ADMIN,
    MAIN_WINDOW_WORKER_PANES,
)

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = logging.getLogger(__name__)


class TmuxWorkspaceMixin:
    """tmux ワークスペース構築・ペイン操作機能を提供する mixin。"""

    @staticmethod
    def _pane_target(session: str, window: int, pane: int) -> str:
        """tmux target 文字列を構築する。"""
        return f"{session}:{window}.{pane}"

    async def _send_enter_key(self, target: str) -> bool:
        """Enter キーを送信する（C-m 優先、失敗時は Enter をフォールバック）。"""
        code, _, stderr = await self._run("send-keys", "-t", target, "C-m")
        if code == 0:
            return True

        logger.warning(f"C-m 送信に失敗、Enter へフォールバックします: {stderr}")
        code, _, stderr = await self._run("send-keys", "-t", target, "Enter")
        if code != 0:
            logger.error(f"Enterキー送信エラー: {stderr}")
            return False
        return True

    async def create_main_session(self, working_dir: str) -> bool:
        """メインセッション（左40:右60分離レイアウト）を作成する。

        Owner は tmux ペインに配置しない（実行AIエージェントが担う）。

        レイアウト:
        ┌─────────────────┬────────────────────────────────┐
        │                 │    W1    │    W2    │    W3    │
        │     Admin       │  pane 1  │  pane 2  │  pane 3  │
        │     pane 0      ├──────────┼──────────┼──────────┤
        │      40%        │    W4    │    W5    │    W6    │
        │                 │  pane 4  │  pane 5  │  pane 6  │
        └─────────────────┴────────────────────────────────┘
               40%                    60%

        Args:
            working_dir: 作業ディレクトリのパス

        Returns:
            成功した場合True
        """
        # プロジェクト名を含むセッション名を生成
        project_name = self._get_project_name(working_dir)
        session_name = project_name

        # セッションが既に存在する場合も、インデックスを正規化して続行する
        if await self.session_exists(project_name):
            await self._configure_session_options(session_name)
            await self._normalize_window_indices(session_name)
            logger.info(
                "メインセッション %s は既に存在します（インデックス正規化済み）",
                session_name,
            )
            return True

        if not await self._create_main_session_window(session_name, working_dir):
            return False
        if not await self._configure_session_options(session_name):
            return False
        # 新規セッションでも、ユーザーの global base-index 設定に影響される可能性があるため
        # ウィンドウ番号を必ず再採番して main=0 を保証する。
        if not await self._normalize_window_indices(session_name):
            return False
        if not await self._split_main_window_layout(session_name):
            return False

        # 最終的なペイン配置: 0(Admin), 1-6(Workers)
        # Owner の分割は不要（実行AIエージェントが Owner の役割を担う）

        logger.info(f"メインセッション作成完了: {session_name}")
        return True

    async def _create_main_session_window(self, session_name: str, working_dir: str) -> bool:
        """メインウィンドウを持つセッションを作成する。"""
        code, _, stderr = await self._run(
            "new-session",
            "-d",
            "-s",
            session_name,
            "-c",
            working_dir,
            "-n",
            self.settings.window_name_main,
        )
        if code != 0:
            logger.error(f"メインセッション作成エラー: {stderr}")
            return False
        return True

    async def _configure_session_options(self, session_name: str) -> bool:
        """base-index 系オプションを session に設定する。"""
        await self._run("set-option", "-t", session_name, "base-index", "0")
        await self._run("set-option", "-t", session_name, "pane-base-index", "0")
        # main ウィンドウにも pane-base-index を明示設定しておく
        await self._run(
            "set-window-option",
            "-t",
            f"{session_name}:{self.settings.window_name_main}",
            "pane-base-index",
            "0",
        )
        return True

    async def _normalize_window_indices(self, session_name: str) -> bool:
        """既存セッションのウィンドウ番号を base-index に合わせて再採番する。"""
        code, _, stderr = await self._run("move-window", "-r", "-t", session_name)
        if code != 0:
            logger.warning(f"ウィンドウ再採番に失敗: {stderr}")
        return True

    async def _split_main_window_layout(self, session_name: str) -> bool:
        """main ウィンドウを Admin + Worker 1-6 配置へ分割する。"""
        target = f"{session_name}:{self.settings.window_name_main}"
        split_steps = [
            ("左右分割エラー", "split-window", "-h", "-t", target, "-p", "60"),
            ("右側列分割エラー(1)", "split-window", "-h", "-t", f"{target}.1", "-p", "67"),
            ("右側列分割エラー(2)", "split-window", "-h", "-t", f"{target}.2", "-p", "50"),
        ]
        for error_prefix, *command in split_steps:
            code, _, stderr = await self._run(*command)
            if code != 0:
                logger.error(f"{error_prefix}: {stderr}")
                return False

        for pane_idx in [3, 2, 1]:
            code, _, stderr = await self._run(
                "split-window",
                "-v",
                "-t",
                f"{target}.{pane_idx}",
            )
            if code != 0:
                logger.error(f"右側行分割エラー(pane {pane_idx}): {stderr}")
                return False
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
        if not await self._create_named_window(session, window_name, "ウィンドウ追加エラー"):
            return None

        # ウィンドウ番号を取得
        windows = await self.list_windows(session)
        if not windows:
            return None

        # 最後のウィンドウ番号
        window_index = len(windows) - 1

        # グリッドに分割
        success = await self._split_into_grid(session, window_index, rows, cols)
        if not success:
            return None

        logger.info(f"ウィンドウ追加完了: {session}:{window_name} ({window_index})")
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
        window_name = f"{self.settings.window_name_worker_prefix}{window_index + 1}"

        # ウィンドウが既に存在するか確認
        windows = await self.list_windows(project_name)
        existing_indices = {w["index"] for w in windows}
        if window_index in existing_indices:
            logger.info(f"ウィンドウ {window_index} は既に存在します")
            return True

        # 新しいウィンドウを追加
        if not await self._create_named_window(
            project_name, window_name, "追加Workerウィンドウ作成エラー"
        ):
            return False

        # ウィンドウに pane-base-index を設定（ユーザーのグローバル設定に依存しない）
        window_target = f"{project_name}:{window_name}"
        await self._run("set-window-option", "-t", window_target, "pane-base-index", "0")

        # グリッドに分割（6×2 = 12ペイン）
        success = await self._split_into_grid(project_name, window_index, rows, cols)
        if not success:
            return False

        logger.info(f"追加Workerウィンドウ作成完了: {project_name}:{window_name}")
        return True

    async def _create_named_window(self, session: str, window_name: str, error_prefix: str) -> bool:
        """指定セッションに名前付きウィンドウを作成する。"""
        code, _, stderr = await self._run("new-window", "-t", session, "-n", window_name)
        if code != 0:
            logger.error(f"{error_prefix}: {stderr}")
            return False
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
                # 追加ウィンドウは settings.workers_per_extra_window ペイン/ウィンドウ
                extra_worker_index = worker_index - 6
                workers_per_extra = self.settings.workers_per_extra_window

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
        clear_input: bool = True,
    ) -> bool:
        """指定したウィンドウ・ペインにキー入力を送信する。

        Args:
            session: セッション名（プレフィックスなし）
            window: ウィンドウ番号（0 = メイン、1+ = 追加）
            pane: ペインインデックス
            command: 実行するコマンド
            literal: Trueの場合、特殊文字をリテラルとして送信
            clear_input: Trueの場合、送信前に C-c/C-u で入力バッファをクリア。
                         通知送信時は False にすること（Claude Code の処理を中断させないため）

        Returns:
            成功した場合True
        """
        target = self._pane_target(session, window, pane)

        # 入力バッファをクリア（残存文字による @export 問題を防止）
        # C-c はシェル再描画（先頭 '%' 表示や重複表示）を誘発しやすいため送らない。
        # 通知送信時は clear_input=False でスキップ（Claude Code の処理を中断させない）
        if clear_input:
            await self._run("send-keys", "-t", target, "C-u")

        # コマンド送信
        if literal:
            code, _, stderr = await self._run("send-keys", "-t", target, "-l", command)
        else:
            code, _, stderr = await self._run("send-keys", "-t", target, command)

        if code != 0:
            logger.error(f"ペインへのキー送信エラー: {stderr}")
            return False

        # Enter キーを別途送信
        return await self._send_enter_key(target)

    @staticmethod
    def _is_pending_codex_prompt(output: str, command: str) -> bool:
        """Codex プロンプトに未確定入力が残っているか判定する。"""
        expected = command.strip()
        if not expected:
            return False

        def _normalize(text: str) -> str:
            return re.sub(r"\s+", " ", text.strip().lower())

        def _tokenize(text: str) -> set[str]:
            return {
                token
                for token in re.findall(r"[a-zA-Z0-9_./:-]+", text.lower())
                if len(token) >= 2
            }

        # 直近の Codex 入力プロンプト（› ...）を優先して判定する。
        pending_line = ""
        for raw in reversed(output.splitlines()[-120:]):
            stripped = raw.strip()
            if stripped.startswith("›"):
                pending_line = stripped[1:].strip()
                break

        if not pending_line:
            return False

        expected_norm = _normalize(expected)
        pending_norm = _normalize(pending_line)
        if pending_norm == expected_norm:
            return True

        # 折り返し・切り詰めに対する緩和判定
        if expected_norm.startswith(pending_norm) or pending_norm.startswith(expected_norm):
            return True

        # 文言一致が崩れてもトークン重複率で未確定を判定する
        expected_tokens = _tokenize(expected_norm)
        pending_tokens = _tokenize(pending_norm)
        if expected_tokens and pending_tokens:
            overlap = len(expected_tokens & pending_tokens) / len(expected_tokens)
            if overlap >= 0.4:
                return True

        # Codex 固有の入力ヒントが出ており、入力行が残っていれば未確定
        if "tab to queue message" in output.lower():
            return True
        return False

    async def send_and_confirm_to_pane(
        self,
        session: str,
        window: int,
        pane: int,
        command: str,
        *,
        literal: bool = True,
        clear_input: bool = True,
        confirm_codex_prompt: bool = False,
    ) -> bool:
        """ペイン送信後に必要なら Enter 再送で確定を保証する。"""
        sent = await self.send_keys_to_pane(
            session=session,
            window=window,
            pane=pane,
            command=command,
            literal=literal,
            clear_input=clear_input,
        )
        if not sent or not confirm_codex_prompt:
            return sent

        retries = max(0, int(getattr(self.settings, "codex_enter_retry_max", 3)))
        interval_ms = max(0, int(getattr(self.settings, "codex_enter_retry_interval_ms", 250)))
        target = self._pane_target(session, window, pane)

        for _ in range(retries):
            # Codex の画面出力は行数が増えやすいため広めに取得する
            output = await self.capture_pane_by_index(session, window, pane, lines=120)
            if not self._is_pending_codex_prompt(output, command):
                return True
            if not await self._send_enter_key(target):
                logger.error("Codex Enter再送エラー")
                return False
            if interval_ms:
                await asyncio.sleep(interval_ms / 1000)

        output = await self.capture_pane_by_index(session, window, pane, lines=120)
        return not self._is_pending_codex_prompt(output, command)

    async def send_with_rate_limit_to_pane(
        self,
        session: str,
        window: int,
        pane: int,
        command: str,
        *,
        literal: bool = True,
        clear_input: bool = True,
        confirm_codex_prompt: bool = False,
    ) -> bool:
        """共通レート制御付きでペインに送信する。"""
        lock = getattr(self, "_send_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._send_lock = lock

        async with lock:
            cooldown = float(getattr(self.settings, "send_cooldown_seconds", 2.0))
            last_sent = getattr(self, "_last_send_at", None)
            now = time.monotonic()
            if isinstance(last_sent, (float, int)) and cooldown > 0:
                wait_for = cooldown - (now - float(last_sent))
                if wait_for > 0:
                    await asyncio.sleep(wait_for)

            success = await self.send_and_confirm_to_pane(
                session=session,
                window=window,
                pane=pane,
                command=command,
                literal=literal,
                clear_input=clear_input,
                confirm_codex_prompt=confirm_codex_prompt,
            )
            self._last_send_at = time.monotonic()
            return success

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
        target = self._pane_target(session, window, pane)

        code, stdout, stderr = await self._run(
            "capture-pane", "-t", target, "-p", "-S", f"-{lines}"
        )
        if code != 0:
            logger.error(f"ペインキャプチャエラー: {stderr}")
            return ""
        return stdout

    async def get_pane_current_command(
        self, session: str, window: int, pane: int
    ) -> str | None:
        """指定ペインで現在実行中のコマンド名を取得する。

        Args:
            session: セッション名（プレフィックスなし）
            window: ウィンドウ番号
            pane: ペインインデックス

        Returns:
            コマンド名（取得失敗時は None）
        """
        target = self._pane_target(session, window, pane)
        code, stdout, stderr = await self._run(
            "display-message",
            "-p",
            "-t",
            target,
            "#{pane_current_command}",
        )
        if code != 0:
            logger.warning(f"pane_current_command 取得エラー: {stderr}")
            return None
        command = stdout.strip()
        return command or None

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
        target = self._pane_target(session, window, pane)

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
        session_name = session

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
        loader = get_template_loader()
        return loader.render(
            "scripts/bash",
            "workspace_setup",
            session_name=session_name,
            working_dir=working_dir,
        )

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
        terminal = terminal or self.settings.default_terminal

        # プロジェクト名を含むセッション名を生成
        project_name = self._get_project_name(working_dir)
        session_name = project_name

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
