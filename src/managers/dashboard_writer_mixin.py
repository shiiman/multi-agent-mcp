"""Dashboard の書き込み責務 Mixin。

Dashboard のファイル書き込みおよびトランザクション処理を提供する。
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import yaml

from src.managers.atomic_io import atomic_write_text as _atomic_write_text_impl
from src.models.dashboard import Dashboard

logger = logging.getLogger(__name__)

_TransactionResult = TypeVar("_TransactionResult")


class DashboardWriterMixin:
    """Dashboard 書き込み機能を提供する Mixin クラス。

    DashboardManager と組み合わせて使用する。
    _dashboard_file_lock(), _get_dashboard_path() は DashboardManager で定義される。
    _generate_markdown_body() は DashboardMarkdownMixin で定義される。
    _read_dashboard_unlocked() は DashboardReaderMixin で定義される。
    """

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

    async def run_dashboard_transaction_async(
        self,
        mutate: Callable[[Dashboard], _TransactionResult],
        *,
        write_back: bool = True,
    ) -> _TransactionResult:
        """Dashboard を非同期ロック下で更新するトランザクションを実行する。

        _dashboard_file_lock_async() を使用し、イベントループをブロックしない。
        """
        async with self._dashboard_file_lock_async():
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
            self._atomic_write_text(dashboard_path, content)
            # 書き込み成功時にキャッシュを無効化
            self._read_cache = None
            self._read_cache_mtime = 0
        except OSError as e:
            logger.error(f"ダッシュボード保存エラー: {e}")
            raise

    def _atomic_write_text(self, file_path: Path, content: str) -> None:
        """テキストを原子的に書き込む。"""
        _atomic_write_text_impl(file_path, content)
