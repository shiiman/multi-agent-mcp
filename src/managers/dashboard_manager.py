"""ダッシュボード管理モジュール。

複数プロセス対応: 読み取り専用操作には mtime ベースの短命キャッシュを使用し、
書き込み操作は毎回ファイルから読み書きする。
YAML Front Matter 付き Markdown で統一管理。
"""

import asyncio
import logging
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.managers.dashboard_cost import DashboardCostMixin
from src.managers.dashboard_reader_mixin import DashboardReaderMixin
from src.managers.dashboard_rendering_mixin import DashboardRenderingMixin
from src.managers.dashboard_writer_mixin import DashboardWriterMixin
from src.models.dashboard import Dashboard

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = logging.getLogger(__name__)


class DashboardManager(
    DashboardReaderMixin,
    DashboardWriterMixin,
    DashboardRenderingMixin,
    DashboardCostMixin,
):
    """ダッシュボードを管理するクラス。"""

    def __init__(
        self,
        workspace_id: str,
        workspace_path: str,
        dashboard_dir: str,
        settings: "Settings | None" = None,
    ) -> None:
        from src.config.settings import load_settings_for_project

        self.workspace_id = workspace_id
        self.workspace_path = workspace_path
        self.dashboard_dir = Path(dashboard_dir)
        self.settings = settings or load_settings_for_project(workspace_path)
        self._dashboard_lock_timeout_seconds = 1.0
        # 読み取り専用操作用の mtime ベースキャッシュ
        self._read_cache: Dashboard | None = None
        self._read_cache_mtime: float = 0.0

    @staticmethod
    def _is_event_loop_running() -> bool:
        """現在スレッドで event loop が実行中か判定する。"""
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    def initialize(self) -> None:
        """ダッシュボード環境を初期化する。"""
        self.dashboard_dir.mkdir(parents=True, exist_ok=True)
        dashboard_path = self._get_dashboard_path()
        if not dashboard_path.exists():
            dashboard = Dashboard(
                workspace_id=self.workspace_id,
                workspace_path=self.workspace_path,
                session_started_at=datetime.now(),
            )
            self._write_dashboard(dashboard)
        logger.info(f"ダッシュボード環境を初期化しました: {self.dashboard_dir}")

    def cleanup(self) -> None:
        """ダッシュボード環境をクリーンアップする。

        dashboard.md / messages.md はセッション履歴として永続保持するため削除しない。
        """
        logger.info("ダッシュボード環境をクリーンアップしました（dashboard/messages は保持）")

    def _get_dashboard_path(self) -> Path:
        return self.dashboard_dir / "dashboard.md"

    def _get_messages_path(self) -> Path:
        return self.dashboard_dir / "messages.md"

    def _get_dashboard_lock_path(self) -> Path:
        return self.dashboard_dir / "dashboard.lock"

    @contextmanager
    def _dashboard_file_lock(self) -> None:
        """Dashboard 読み書き用の排他ロックを取得する。"""
        import fcntl

        lock_path = self._get_dashboard_lock_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        started_at = time.monotonic()
        running_in_event_loop = self._is_event_loop_running()

        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as e:
                    if running_in_event_loop:
                        msg = f"dashboard lock busy in event loop context: {lock_path}"
                        raise TimeoutError(msg) from e
                    elapsed = time.monotonic() - started_at
                    if elapsed >= self._dashboard_lock_timeout_seconds:
                        msg = (
                            "dashboard lock timeout "
                            f"({self._dashboard_lock_timeout_seconds:.2f}s): {lock_path}"
                        )
                        raise TimeoutError(msg) from e
                    time.sleep(0.01)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
