"""Dashboard の読み取り責務 Mixin。

mtime ベースキャッシュ付きの Dashboard 読み込みロジックを提供する。
"""

import logging

import yaml

from src.models.dashboard import Dashboard

logger = logging.getLogger(__name__)


class DashboardReaderMixin:
    """Dashboard 読み取り機能を提供する Mixin クラス。

    DashboardManager と組み合わせて使用する。
    _dashboard_file_lock(), _get_dashboard_path() は DashboardManager で定義される。
    _parse_yaml_front_matter() は DashboardMarkdownMixin で定義される。
    """

    def _read_dashboard(self) -> Dashboard:
        """ダッシュボードをファイルから読み込む（mtime_ns ベースキャッシュ付き）。"""
        dashboard_path = self._get_dashboard_path()
        try:
            current_mtime_ns = dashboard_path.stat().st_mtime_ns
        except OSError:
            current_mtime_ns = 0
        if self._read_cache is not None and current_mtime_ns == self._read_cache_mtime:
            return self._read_cache
        with self._dashboard_file_lock():
            dashboard = self._read_dashboard_unlocked()
        self._read_cache = dashboard
        self._read_cache_mtime = current_mtime_ns
        return dashboard

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
