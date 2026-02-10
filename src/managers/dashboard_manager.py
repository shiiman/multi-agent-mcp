"""ダッシュボード管理モジュール。

複数プロセス対応: インメモリキャッシュを使わず、毎回ファイルから読み書きする。
YAML Front Matter 付き Markdown で統一管理。
"""

import logging
import os
import tempfile
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

import yaml

from src.managers.dashboard_cost import DashboardCostMixin
from src.managers.dashboard_rendering_mixin import DashboardRenderingMixin
from src.models.dashboard import Dashboard

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = logging.getLogger(__name__)

_TransactionResult = TypeVar("_TransactionResult")


class DashboardManager(DashboardRenderingMixin, DashboardCostMixin):
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
        logger.info(
            "ダッシュボード環境をクリーンアップしました（dashboard/messages は保持）"
        )

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

        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as e:
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

    def run_dashboard_transaction(
        self,
        mutate: Callable[[Dashboard], _TransactionResult],
        *,
        write_back: bool = True,
    ) -> _TransactionResult:
        """Dashboard をロック下で更新するトランザクションを実行する。"""
        with self._dashboard_file_lock():
            dashboard = self._read_dashboard_unlocked()
            result = mutate(dashboard)
            if write_back:
                self._write_dashboard_unlocked(dashboard)
            return result

    def _write_dashboard(self, dashboard: Dashboard) -> None:
        """ダッシュボードをファイルに保存する（YAML Front Matter + Markdown）。"""
        with self._dashboard_file_lock():
            self._write_dashboard_unlocked(dashboard)

    def _write_dashboard_unlocked(self, dashboard: Dashboard) -> None:
        """ロック取得済み前提でダッシュボードを書き込む。"""
        dashboard_path = self._get_dashboard_path()
        try:
            front_matter_data = dashboard.model_dump(mode="json", exclude={"messages"})
            md_content = self._generate_markdown_body(dashboard)
            yaml_str = yaml.dump(
                front_matter_data,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
            content = f"---\n{yaml_str}---\n\n{md_content}"
            dashboard_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(dashboard_path.parent), suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(tmp_path, str(dashboard_path))
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as e:
            logger.error(f"ダッシュボード保存エラー: {e}")
            raise

    def _read_dashboard(self) -> Dashboard:
        """ダッシュボードをファイルから読み込む。"""
        with self._dashboard_file_lock():
            return self._read_dashboard_unlocked()

    def _read_dashboard_unlocked(self) -> Dashboard:
        """ロック取得済み前提でダッシュボードを読み込む。"""
        dashboard_path = self._get_dashboard_path()
        if dashboard_path.exists():
            try:
                content = dashboard_path.read_text(encoding="utf-8")
                data = self._parse_yaml_front_matter(content)
                if data:
                    tasks = data.get("tasks") or []
                    for task in tasks:
                        description = task.get("description") or ""
                        task_file_path = task.get("task_file_path")
                        if description and not task_file_path:
                            msg = "invalid_legacy_dashboard_format: "
                            raise ValueError(msg + "description body unsupported")
                        if description and task_file_path and description != task_file_path:
                            msg = "invalid_legacy_dashboard_format: "
                            raise ValueError(msg + "description/task_file_path mismatch")
                    return Dashboard(**data)
            except ValueError as e:
                if "invalid_legacy_dashboard_format" in str(e):
                    raise
                logger.warning(f"ダッシュボード読み込みエラー: {e}")
            except (yaml.YAMLError, OSError) as e:
                logger.warning(f"ダッシュボード読み込みエラー: {e}")

        return Dashboard(
            workspace_id=self.workspace_id,
            workspace_path=self.workspace_path,
        )
