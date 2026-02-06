"""DashboardManager 用 mixin 集約。"""

from src.managers.dashboard_markdown_mixin import DashboardMarkdownMixin
from src.managers.dashboard_sync_mixin import DashboardSyncMixin
from src.managers.dashboard_tasks_mixin import DashboardTasksMixin


class DashboardRenderingMixin(
    DashboardMarkdownMixin,
    DashboardTasksMixin,
    DashboardSyncMixin,
):
    """Dashboard の描画・更新・同期機能を集約する mixin。"""
