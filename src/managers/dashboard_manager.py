"""ダッシュボード管理モジュール。

複数プロセス対応: インメモリキャッシュを使わず、毎回ファイルから読み書きする。
YAML Front Matter 付き Markdown で統一管理。
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from src.managers.dashboard_cost import DashboardCostMixin
from src.managers.dashboard_rendering_mixin import DashboardRenderingMixin
from src.models.dashboard import Dashboard

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = logging.getLogger(__name__)


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

    def initialize(self) -> None:
        """ダッシュボード環境を初期化する。"""
        self.dashboard_dir.mkdir(parents=True, exist_ok=True)
        dashboard_path = self._get_dashboard_path()
        if not dashboard_path.exists():
            dashboard = Dashboard(
                workspace_id=self.workspace_id,
                workspace_path=self.workspace_path,
            )
            self._write_dashboard(dashboard)
        logger.info(f"ダッシュボード環境を初期化しました: {self.dashboard_dir}")

    def cleanup(self) -> None:
        """ダッシュボード環境をクリーンアップする。"""
        for path in (self._get_dashboard_path(), self._get_messages_path()):
            if path.exists():
                try:
                    path.unlink()
                except OSError as e:
                    logger.warning(f"ダッシュボードファイル削除エラー: {e}")
        logger.info("ダッシュボード環境をクリーンアップしました")

    def _get_dashboard_path(self) -> Path:
        return self.dashboard_dir / "dashboard.md"

    def _get_messages_path(self) -> Path:
        return self.dashboard_dir / "messages.md"

    def _write_dashboard(self, dashboard: Dashboard) -> None:
        """ダッシュボードをファイルに保存する（YAML Front Matter + Markdown）。"""
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
            with open(dashboard_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            logger.error(f"ダッシュボード保存エラー: {e}")

    def _read_dashboard(self) -> Dashboard:
        """ダッシュボードをファイルから読み込む。"""
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
                            raise ValueError(
                                "invalid_legacy_dashboard_format: description body is no longer supported"
                            )
                        if description and task_file_path and description != task_file_path:
                            raise ValueError(
                                "invalid_legacy_dashboard_format: description and task_file_path mismatch"
                            )
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
