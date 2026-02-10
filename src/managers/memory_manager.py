"""メモリ管理モジュール。

プロジェクトレベル / グローバルレベルの永続的な学習・知識を管理する。

保存先:
- Layer 2 (グローバル): ~/{mcp_dir}/memory/
- Layer 3 (プロジェクト): {project_root}/{mcp_dir}/{session_id}/memory/

形式: YAML Front Matter + Markdown（各エントリは個別の .md ファイル）

アーカイブ:
- prune 時に削除ではなくアーカイブディレクトリに移動
- 必要時にアーカイブから検索・復元可能
- アーカイブディレクトリ: archive/
"""

import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from src.config.settings import Settings, get_mcp_dir

logger = logging.getLogger(__name__)


def _get_default_max_entries() -> int:
    """Settings からデフォルトの最大エントリ数を取得する。"""
    return Settings().memory_max_entries


def _get_default_ttl_days() -> int:
    """Settings からデフォルトの TTL（日数）を取得する。"""
    return Settings().memory_ttl_days


def _sanitize_filename(key: str) -> str:
    """キーをファイル名として安全な形式に変換する。"""
    # 危険な文字を置換
    safe = re.sub(r'[<>:"/\\|?*]', "_", key)
    # 先頭・末尾の空白とドットを除去
    safe = safe.strip(" .")
    # 空の場合はデフォルト名
    return safe or "entry"


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

    プロジェクトレベル / グローバルレベルでの知識・学習内容を
    YAML Front Matter + Markdown ファイルで永続化する。
    自動クリーンアップ機能付き。
    """

    def __init__(
        self,
        storage_dir: str | Path | None = None,
        max_entries: int | None = None,
        ttl_days: int | None = None,
        auto_prune: bool = True,
    ) -> None:
        """MemoryManagerを初期化する。

        Args:
            storage_dir: メモリストレージのディレクトリ（オプション）
            max_entries: 最大エントリ数（デフォルト: Settings から取得）
            ttl_days: エントリの有効期限（日数、デフォルト: Settings から取得）
            auto_prune: 保存時に自動でクリーンアップするか（デフォルト: True）
        """
        self.storage_dir = Path(storage_dir) if storage_dir else None
        self.max_entries = max_entries if max_entries is not None else _get_default_max_entries()
        self.ttl_days = ttl_days if ttl_days is not None else _get_default_ttl_days()
        self.auto_prune = auto_prune
        self.entries: dict[str, MemoryEntry] = {}

        if self.storage_dir:
            self._load_from_dir()

    @property
    def archive_dir(self) -> Path | None:
        """アーカイブディレクトリのパスを取得する。"""
        if self.storage_dir is None:
            return None
        return self.storage_dir / "archive"

    @classmethod
    def from_project_root(
        cls,
        project_root: str | Path,
        session_id: str | None = None,
        max_entries: int | None = None,
        ttl_days: int | None = None,
    ) -> "MemoryManager":
        """プロジェクトルートからMemoryManagerを作成する (Layer 3)。

        Args:
            project_root: プロジェクトのルートディレクトリ
            session_id: セッションID（オプション）
            max_entries: 最大エントリ数（デフォルト: Settings から取得）
            ttl_days: エントリの有効期限（日数、デフォルト: Settings から取得）

        Returns:
            MemoryManager インスタンス
        """
        if session_id:
            storage_dir = Path(project_root) / get_mcp_dir() / session_id / "memory"
        else:
            storage_dir = Path(project_root) / get_mcp_dir() / "memory"
        return cls(storage_dir, max_entries=max_entries, ttl_days=ttl_days)

    @classmethod
    def from_global(
        cls,
        max_entries: int | None = None,
        ttl_days: int | None = None,
    ) -> "MemoryManager":
        """グローバルMemoryManagerを作成する (Layer 2)。

        保存先: ~/{mcp_dir}/memory/

        Args:
            max_entries: 最大エントリ数（デフォルト: Settings から取得）
            ttl_days: エントリの有効期限（日数、デフォルト: Settings から取得）

        Returns:
            MemoryManager インスタンス
        """
        home_dir = Path(os.path.expanduser("~"))
        storage_dir = home_dir / get_mcp_dir() / "memory"
        return cls(storage_dir, max_entries=max_entries, ttl_days=ttl_days)

    def _get_entry_path(self, key: str) -> Path:
        """エントリのファイルパスを取得する。"""
        if not self.storage_dir:
            raise ValueError("storage_dir が設定されていません")
        filename = _sanitize_filename(key) + ".md"
        return self.storage_dir / filename

    def _parse_markdown_entry(self, file_path: Path) -> MemoryEntry | None:
        """Markdown ファイルからメモリエントリを読み込む。"""
        try:
            content = file_path.read_text(encoding="utf-8")

            # YAML Front Matter を抽出
            if not content.startswith("---"):
                return None

            parts = content.split("---", 2)
            if len(parts) < 3:
                return None

            # YAML パース
            front_matter = yaml.safe_load(parts[1])
            if not front_matter or "key" not in front_matter:
                return None

            # Markdown 本文
            body = parts[2].strip()

            return MemoryEntry(
                key=front_matter["key"],
                content=body,
                tags=front_matter.get("tags", []),
                created_at=datetime.fromisoformat(front_matter["created_at"])
                if "created_at" in front_matter
                else datetime.now(),
                updated_at=datetime.fromisoformat(front_matter["updated_at"])
                if "updated_at" in front_matter
                else datetime.now(),
                metadata=front_matter.get("metadata", {}),
            )
        except (OSError, yaml.YAMLError, KeyError, ValueError) as e:
            logger.warning(f"エントリの読み込みに失敗 ({file_path}): {e}")
            return None

    def _write_markdown_entry(self, entry: MemoryEntry, file_path: Path) -> None:
        """メモリエントリを Markdown ファイルとして保存する。"""
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # YAML Front Matter を構築
            front_matter = {
                "key": entry.key,
                "tags": entry.tags,
                "created_at": entry.created_at.isoformat(),
                "updated_at": entry.updated_at.isoformat(),
            }
            if entry.metadata:
                front_matter["metadata"] = entry.metadata

            # YAML + Markdown を結合
            yaml_str = yaml.dump(
                front_matter,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
            content = f"---\n{yaml_str}---\n\n{entry.content}\n"

            file_path.write_text(content, encoding="utf-8")
        except (OSError, yaml.YAMLError) as e:
            logger.error(f"エントリの保存に失敗 ({file_path}): {e}")
            raise

    def _get_load_limit(self) -> int | None:
        """起動時ロード件数の上限を取得する。"""
        if self.max_entries <= 0:
            return None
        return self.max_entries

    def _collect_entry_files(self) -> list[Path]:
        """読み込み対象のエントリファイル一覧を更新日時順で取得する。"""
        if not self.storage_dir:
            return []

        files = [
            file_path
            for file_path in self.storage_dir.glob("*.md")
            if file_path.name != "README.md"
        ]

        try:
            files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        except OSError as e:
            logger.warning(f"エントリファイルのソートに失敗: {e}")

        return files

    def _archive_overflow_files(self, overflow_files: list[Path]) -> int:
        """上限超過したエントリファイルをアーカイブに移動する。"""
        if not overflow_files or not self.archive_dir:
            return 0

        moved_count = 0
        try:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            for file_path in overflow_files:
                archive_path = self.archive_dir / file_path.name
                if archive_path.exists():
                    archive_path = self.archive_dir / (
                        f"{file_path.stem}_{int(datetime.now().timestamp())}.md"
                    )
                shutil.move(str(file_path), str(archive_path))
                moved_count += 1
        except OSError as e:
            logger.warning(f"上限超過ファイルのアーカイブに失敗: {e}")

        return moved_count

    def _load_from_dir(self) -> None:
        """ディレクトリからメモリエントリを上限付きで読み込む。"""
        if not self.storage_dir or not self.storage_dir.exists():
            return

        try:
            all_files = self._collect_entry_files()
            load_limit = self._get_load_limit()
            files_to_load = all_files
            overflow_files: list[Path] = []

            if load_limit is not None and len(all_files) > load_limit:
                files_to_load = all_files[:load_limit]
                overflow_files = all_files[load_limit:]

                if self.auto_prune:
                    archived_files = self._archive_overflow_files(overflow_files)
                    if archived_files > 0:
                        logger.info(
                            "起動時ロード件数超過をアーカイブ: %s ファイル (上限=%s)",
                            archived_files,
                            load_limit,
                        )
                else:
                    logger.info(
                        "起動時ロード件数を制限: %s/%s ファイルを読み込み (上限=%s)",
                        len(files_to_load),
                        len(all_files),
                        load_limit,
                    )

            for file_path in files_to_load:
                entry = self._parse_markdown_entry(file_path)
                if entry:
                    self.entries[entry.key] = entry

            logger.info(f"メモリを読み込みました: {len(self.entries)} エントリ")

            # 読み込み時にもクリーンアップ
            if self.auto_prune:
                self.prune()
        except (OSError, yaml.YAMLError, KeyError, ValueError) as e:
            logger.warning(f"メモリの読み込みに失敗: {e}")

    def _save_entry(self, entry: MemoryEntry) -> None:
        """単一エントリを保存する。"""
        if not self.storage_dir:
            return

        file_path = self._get_entry_path(entry.key)
        self._write_markdown_entry(entry, file_path)

    def _delete_entry_file(self, key: str) -> None:
        """エントリのファイルを削除する。"""
        if not self.storage_dir:
            return

        file_path = self._get_entry_path(key)
        if file_path.exists():
            file_path.unlink()

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
            key for key, entry in self.entries.items() if entry.updated_at < cutoff_date
        ]
        for key in expired_keys:
            entries_to_archive.append(self.entries[key])
            del self.entries[key]
            self._delete_entry_file(key)
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
                self._delete_entry_file(key)
                archived_count += 1
                logger.debug(f"エントリ数超過によりアーカイブ: {key}")

        if archived_count > 0:
            # アーカイブに追加
            self._move_to_archive(entries_to_archive)
            logger.info(f"クリーンアップ: {archived_count} エントリをアーカイブ")

        return archived_count

    def _move_to_archive(self, entries: list[MemoryEntry]) -> None:
        """エントリをアーカイブディレクトリに移動する。"""
        if not self.archive_dir or not entries:
            return

        try:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            archive_time = datetime.now().isoformat()

            for entry in entries:
                # メタデータにアーカイブ日時を追加
                entry.metadata["archived_at"] = archive_time
                file_path = self.archive_dir / (_sanitize_filename(entry.key) + ".md")
                self._write_markdown_entry(entry, file_path)

            logger.info(f"アーカイブに追加: {len(entries)} エントリ")
        except (OSError, yaml.YAMLError) as e:
            logger.error(f"アーカイブへの追加に失敗: {e}")

    def _load_archive(self) -> dict[str, MemoryEntry]:
        """アーカイブディレクトリからエントリを読み込む。"""
        archive_entries: dict[str, MemoryEntry] = {}

        if not self.archive_dir or not self.archive_dir.exists():
            return archive_entries

        try:
            for file_path in self.archive_dir.glob("*.md"):
                entry = self._parse_markdown_entry(file_path)
                if entry:
                    archive_entries[entry.key] = entry

            logger.debug(f"アーカイブを読み込み: {len(archive_entries)} エントリ")
        except (OSError, yaml.YAMLError, KeyError, ValueError) as e:
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
        if not self.archive_dir or not self.archive_dir.exists():
            return None

        try:
            archive_file = self.archive_dir / (_sanitize_filename(key) + ".md")
            if not archive_file.exists():
                return None

            entry = self._parse_markdown_entry(archive_file)
            if not entry:
                return None

            # 更新日時を現在に
            entry.updated_at = datetime.now()
            # アーカイブ日時をメタデータから削除
            entry.metadata.pop("archived_at", None)

            # メインメモリに追加
            self.entries[key] = entry
            self._save_entry(entry)

            # アーカイブから削除
            archive_file.unlink()

            logger.info(f"アーカイブから復元: {key}")
            return entry

        except (OSError, yaml.YAMLError, KeyError, ValueError) as e:
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
            "archive_dir": str(self.archive_dir) if self.archive_dir else None,
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
            if tags is not None:
                entry.tags = tags
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

        self._save_entry(entry)
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
        return [entry for entry in self.entries.values() if any(tag in entry.tags for tag in tags)]

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
            self._delete_entry_file(key)
            logger.info(f"メモリを削除: {key}")
            return True
        return False

    def clear(self) -> None:
        """すべてのメモリエントリを削除する。"""
        for key in list(self.entries.keys()):
            self._delete_entry_file(key)
        self.entries.clear()
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
            "storage_dir": str(self.storage_dir) if self.storage_dir else None,
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
