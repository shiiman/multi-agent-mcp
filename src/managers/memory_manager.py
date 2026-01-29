"""メモリ管理モジュール。

プロジェクトレベル / グローバルレベルの永続的な学習・知識を管理する。

保存先:
- Layer 2 (グローバル): ~/.multi-agent-mcp/memory/memory.json
- Layer 3 (プロジェクト): {project_root}/.multi-agent-mcp/memory/memory.json

アーカイブ:
- prune 時に削除ではなくアーカイブファイルに移動
- 必要時にアーカイブから検索・復元可能
- アーカイブファイル: memory_archive.json
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# デフォルト設定
DEFAULT_MAX_ENTRIES = 1000
DEFAULT_TTL_DAYS = 90


@dataclass
class MemoryEntry:
    """メモリエントリ。"""

    key: str
    """エントリのキー"""

    content: str
    """保存されたコンテンツ"""

    tags: list[str] = field(default_factory=list)
    """タグのリスト"""

    created_at: datetime = field(default_factory=datetime.now)
    """作成日時"""

    updated_at: datetime = field(default_factory=datetime.now)
    """更新日時"""

    metadata: dict = field(default_factory=dict)
    """追加のメタデータ"""


class MemoryManager:
    """メモリ管理クラス。

    プロジェクトレベル / グローバルレベルでの知識・学習内容を JSON ファイルで永続化する。
    自動クリーンアップ機能付き。
    """

    def __init__(
        self,
        storage_path: str | Path | None = None,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_days: int = DEFAULT_TTL_DAYS,
        auto_prune: bool = True,
    ) -> None:
        """MemoryManagerを初期化する。

        Args:
            storage_path: メモリストレージのパス（オプション）
            max_entries: 最大エントリ数（デフォルト: 1000）
            ttl_days: エントリの有効期限（日数、デフォルト: 90）
            auto_prune: 保存時に自動でクリーンアップするか（デフォルト: True）
        """
        self.storage_path = Path(storage_path) if storage_path else None
        self.max_entries = max_entries
        self.ttl_days = ttl_days
        self.auto_prune = auto_prune
        self.entries: dict[str, MemoryEntry] = {}

        if self.storage_path:
            self._load_from_file()

    @property
    def archive_path(self) -> Path | None:
        """アーカイブファイルのパスを取得する。"""
        if self.storage_path is None:
            return None
        return self.storage_path.parent / "memory_archive.json"

    @classmethod
    def from_project_root(
        cls,
        project_root: str | Path,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_days: int = DEFAULT_TTL_DAYS,
    ) -> "MemoryManager":
        """プロジェクトルートからMemoryManagerを作成する (Layer 3)。

        Args:
            project_root: プロジェクトのルートディレクトリ
            max_entries: 最大エントリ数
            ttl_days: エントリの有効期限（日数）

        Returns:
            MemoryManager インスタンス
        """
        storage_path = Path(project_root) / ".multi-agent-mcp" / "memory" / "memory.json"
        return cls(storage_path, max_entries=max_entries, ttl_days=ttl_days)

    @classmethod
    def from_global(
        cls,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_days: int = DEFAULT_TTL_DAYS,
    ) -> "MemoryManager":
        """グローバルMemoryManagerを作成する (Layer 2)。

        保存先: ~/.multi-agent-mcp/memory/memory.json

        Args:
            max_entries: 最大エントリ数
            ttl_days: エントリの有効期限（日数）

        Returns:
            MemoryManager インスタンス
        """
        home_dir = Path(os.path.expanduser("~"))
        storage_path = home_dir / ".multi-agent-mcp" / "memory" / "memory.json"
        return cls(storage_path, max_entries=max_entries, ttl_days=ttl_days)

    def _load_from_file(self) -> None:
        """ファイルからメモリエントリを読み込む。"""
        if not self.storage_path or not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, encoding="utf-8") as f:
                data = json.load(f)

            for key, entry_data in data.items():
                self.entries[key] = MemoryEntry(
                    key=key,
                    content=entry_data["content"],
                    tags=entry_data.get("tags", []),
                    created_at=datetime.fromisoformat(entry_data["created_at"]),
                    updated_at=datetime.fromisoformat(entry_data["updated_at"]),
                    metadata=entry_data.get("metadata", {}),
                )

            logger.info(f"メモリを読み込みました: {len(self.entries)} エントリ")

            # 読み込み時にもクリーンアップ
            if self.auto_prune:
                self.prune()
        except Exception as e:
            logger.warning(f"メモリの読み込みに失敗: {e}")

    def _save_to_file(self) -> None:
        """メモリエントリをファイルに保存する。"""
        if not self.storage_path:
            return

        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)

            data = {}
            for key, entry in self.entries.items():
                data[key] = {
                    "content": entry.content,
                    "tags": entry.tags,
                    "created_at": entry.created_at.isoformat(),
                    "updated_at": entry.updated_at.isoformat(),
                    "metadata": entry.metadata,
                }

            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(f"メモリを保存しました: {len(self.entries)} エントリ")
        except Exception as e:
            logger.error(f"メモリの保存に失敗: {e}")

    def prune(self) -> int:
        """古いエントリと超過エントリをアーカイブに移動する。

        1. TTL を超えたエントリをアーカイブに移動
        2. max_entries を超えている場合、古いものからアーカイブに移動

        Returns:
            アーカイブに移動したエントリ数
        """
        archived_count = 0
        now = datetime.now()
        cutoff_date = now - timedelta(days=self.ttl_days)
        entries_to_archive: list[MemoryEntry] = []

        # 1. TTL を超えたエントリを収集
        expired_keys = [
            key
            for key, entry in self.entries.items()
            if entry.updated_at < cutoff_date
        ]
        for key in expired_keys:
            entries_to_archive.append(self.entries[key])
            del self.entries[key]
            archived_count += 1
            logger.debug(f"TTL 超過によりアーカイブ: {key}")

        # 2. max_entries を超えている場合、古いものを収集
        if len(self.entries) > self.max_entries:
            # 更新日時でソート（古い順）
            sorted_entries = sorted(
                self.entries.items(),
                key=lambda x: x[1].updated_at,
            )
            # 超過分をアーカイブに移動
            excess_count = len(self.entries) - self.max_entries
            for key, entry in sorted_entries[:excess_count]:
                entries_to_archive.append(entry)
                del self.entries[key]
                archived_count += 1
                logger.debug(f"エントリ数超過によりアーカイブ: {key}")

        if archived_count > 0:
            # アーカイブに追加
            self._append_to_archive(entries_to_archive)
            logger.info(f"クリーンアップ: {archived_count} エントリをアーカイブ")
            self._save_to_file()

        return archived_count

    def _append_to_archive(self, entries: list[MemoryEntry]) -> None:
        """エントリをアーカイブファイルに追加する。"""
        if not self.archive_path or not entries:
            return

        try:
            # 既存のアーカイブを読み込み
            archive_data = {}
            if self.archive_path.exists():
                with open(self.archive_path, encoding="utf-8") as f:
                    archive_data = json.load(f)

            # 新しいエントリを追加（アーカイブ日時を記録）
            archive_time = datetime.now().isoformat()
            for entry in entries:
                archive_data[entry.key] = {
                    "content": entry.content,
                    "tags": entry.tags,
                    "created_at": entry.created_at.isoformat(),
                    "updated_at": entry.updated_at.isoformat(),
                    "metadata": entry.metadata,
                    "archived_at": archive_time,
                }

            # 保存
            self.archive_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.archive_path, "w", encoding="utf-8") as f:
                json.dump(archive_data, f, ensure_ascii=False, indent=2)

            logger.info(f"アーカイブに追加: {len(entries)} エントリ")
        except Exception as e:
            logger.error(f"アーカイブへの追加に失敗: {e}")

    def _load_archive(self) -> dict[str, MemoryEntry]:
        """アーカイブファイルからエントリを読み込む。"""
        archive_entries: dict[str, MemoryEntry] = {}

        if not self.archive_path or not self.archive_path.exists():
            return archive_entries

        try:
            with open(self.archive_path, encoding="utf-8") as f:
                data = json.load(f)

            for key, entry_data in data.items():
                archive_entries[key] = MemoryEntry(
                    key=key,
                    content=entry_data["content"],
                    tags=entry_data.get("tags", []),
                    created_at=datetime.fromisoformat(entry_data["created_at"]),
                    updated_at=datetime.fromisoformat(entry_data["updated_at"]),
                    metadata=entry_data.get("metadata", {}),
                )

            logger.debug(f"アーカイブを読み込み: {len(archive_entries)} エントリ")
        except Exception as e:
            logger.warning(f"アーカイブの読み込みに失敗: {e}")

        return archive_entries

    def search_archive(
        self,
        query: str,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """アーカイブを検索する。

        Args:
            query: 検索クエリ
            tags: フィルタリングするタグ（オプション）
            limit: 最大結果数

        Returns:
            マッチしたメモリエントリのリスト
        """
        archive_entries = self._load_archive()
        results = []
        query_lower = query.lower()

        for entry in archive_entries.values():
            # タグフィルタ
            if tags and not any(tag in entry.tags for tag in tags):
                continue

            # コンテンツ検索
            if query_lower in entry.content.lower() or query_lower in entry.key.lower():
                results.append(entry)

            if len(results) >= limit:
                break

        # 更新日時でソート（新しい順）
        results.sort(key=lambda x: x.updated_at, reverse=True)
        return results[:limit]

    def list_archive(self, limit: int | None = None) -> list[MemoryEntry]:
        """アーカイブのエントリ一覧を取得する。

        Args:
            limit: 最大結果数（Noneで無制限）

        Returns:
            アーカイブされたメモリエントリのリスト
        """
        archive_entries = self._load_archive()
        entries = list(archive_entries.values())

        # 更新日時でソート（新しい順）
        entries.sort(key=lambda x: x.updated_at, reverse=True)

        if limit:
            return entries[:limit]
        return entries

    def restore_from_archive(self, key: str) -> MemoryEntry | None:
        """アーカイブからエントリを復元する。

        Args:
            key: 復元するエントリのキー

        Returns:
            復元されたメモリエントリ、見つからない場合はNone
        """
        if not self.archive_path or not self.archive_path.exists():
            return None

        try:
            with open(self.archive_path, encoding="utf-8") as f:
                archive_data = json.load(f)

            if key not in archive_data:
                return None

            entry_data = archive_data[key]

            # エントリを作成
            entry = MemoryEntry(
                key=key,
                content=entry_data["content"],
                tags=entry_data.get("tags", []),
                created_at=datetime.fromisoformat(entry_data["created_at"]),
                updated_at=datetime.now(),  # 復元時に更新
                metadata=entry_data.get("metadata", {}),
            )

            # メインメモリに追加
            self.entries[key] = entry
            self._save_to_file()

            # アーカイブから削除
            del archive_data[key]
            with open(self.archive_path, "w", encoding="utf-8") as f:
                json.dump(archive_data, f, ensure_ascii=False, indent=2)

            logger.info(f"アーカイブから復元: {key}")
            return entry

        except Exception as e:
            logger.error(f"アーカイブからの復元に失敗: {e}")
            return None

    def get_archive_summary(self) -> dict:
        """アーカイブのサマリー情報を取得する。

        Returns:
            サマリー情報の辞書
        """
        archive_entries = self._load_archive()

        all_tags: set[str] = set()
        oldest_entry: datetime | None = None
        newest_entry: datetime | None = None

        for entry in archive_entries.values():
            all_tags.update(entry.tags)
            if oldest_entry is None or entry.updated_at < oldest_entry:
                oldest_entry = entry.updated_at
            if newest_entry is None or entry.updated_at > newest_entry:
                newest_entry = entry.updated_at

        return {
            "total_entries": len(archive_entries),
            "unique_tags": list(all_tags),
            "tag_count": len(all_tags),
            "archive_path": str(self.archive_path) if self.archive_path else None,
            "oldest_entry": oldest_entry.isoformat() if oldest_entry else None,
            "newest_entry": newest_entry.isoformat() if newest_entry else None,
        }

    def save(
        self,
        key: str,
        content: str,
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ) -> MemoryEntry:
        """メモリにコンテンツを保存する。

        Args:
            key: エントリのキー
            content: 保存するコンテンツ
            tags: タグのリスト（オプション）
            metadata: 追加のメタデータ（オプション）

        Returns:
            作成または更新されたメモリエントリ
        """
        now = datetime.now()

        if key in self.entries:
            # 既存エントリの更新
            entry = self.entries[key]
            entry.content = content
            entry.tags = tags or entry.tags
            entry.updated_at = now
            if metadata:
                entry.metadata.update(metadata)
            logger.info(f"メモリを更新: {key}")
        else:
            # 新規エントリの作成
            entry = MemoryEntry(
                key=key,
                content=content,
                tags=tags or [],
                created_at=now,
                updated_at=now,
                metadata=metadata or {},
            )
            self.entries[key] = entry
            logger.info(f"メモリを保存: {key}")

        # 自動クリーンアップ
        if self.auto_prune:
            self.prune()

        self._save_to_file()
        return entry

    def get(self, key: str) -> MemoryEntry | None:
        """キーでメモリエントリを取得する。

        Args:
            key: エントリのキー

        Returns:
            メモリエントリ、見つからない場合はNone
        """
        return self.entries.get(key)

    def search(
        self,
        query: str,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """メモリを検索する。

        Args:
            query: 検索クエリ
            tags: フィルタリングするタグ（オプション）
            limit: 最大結果数

        Returns:
            マッチしたメモリエントリのリスト
        """
        results = []
        query_lower = query.lower()

        for entry in self.entries.values():
            # タグフィルタ
            if tags and not any(tag in entry.tags for tag in tags):
                continue

            # コンテンツ検索
            if query_lower in entry.content.lower() or query_lower in entry.key.lower():
                results.append(entry)

            if len(results) >= limit:
                break

        # 更新日時でソート（新しい順）
        results.sort(key=lambda x: x.updated_at, reverse=True)
        return results[:limit]

    def list_by_tags(self, tags: list[str]) -> list[MemoryEntry]:
        """タグでメモリエントリをフィルタリングする。

        Args:
            tags: フィルタリングするタグのリスト

        Returns:
            マッチしたメモリエントリのリスト
        """
        return [
            entry
            for entry in self.entries.values()
            if any(tag in entry.tags for tag in tags)
        ]

    def list_all(self) -> list[MemoryEntry]:
        """すべてのメモリエントリを取得する。

        Returns:
            すべてのメモリエントリのリスト
        """
        return list(self.entries.values())

    def delete(self, key: str) -> bool:
        """メモリエントリを削除する。

        Args:
            key: 削除するエントリのキー

        Returns:
            削除に成功した場合はTrue
        """
        if key in self.entries:
            del self.entries[key]
            self._save_to_file()
            logger.info(f"メモリを削除: {key}")
            return True
        return False

    def clear(self) -> None:
        """すべてのメモリエントリを削除する。"""
        self.entries.clear()
        self._save_to_file()
        logger.info("メモリをクリアしました")

    def get_summary(self) -> dict:
        """メモリのサマリー情報を取得する。

        Returns:
            サマリー情報の辞書
        """
        all_tags: set[str] = set()
        oldest_entry: datetime | None = None
        newest_entry: datetime | None = None

        for entry in self.entries.values():
            all_tags.update(entry.tags)
            if oldest_entry is None or entry.updated_at < oldest_entry:
                oldest_entry = entry.updated_at
            if newest_entry is None or entry.updated_at > newest_entry:
                newest_entry = entry.updated_at

        return {
            "total_entries": len(self.entries),
            "unique_tags": list(all_tags),
            "tag_count": len(all_tags),
            "storage_path": str(self.storage_path) if self.storage_path else None,
            "max_entries": self.max_entries,
            "ttl_days": self.ttl_days,
            "oldest_entry": oldest_entry.isoformat() if oldest_entry else None,
            "newest_entry": newest_entry.isoformat() if newest_entry else None,
        }

    def to_dict(self, entry: MemoryEntry) -> dict:
        """メモリエントリを辞書に変換する。

        Args:
            entry: メモリエントリ

        Returns:
            辞書形式のエントリ
        """
        return {
            "key": entry.key,
            "content": entry.content,
            "tags": entry.tags,
            "created_at": entry.created_at.isoformat(),
            "updated_at": entry.updated_at.isoformat(),
            "metadata": entry.metadata,
        }
