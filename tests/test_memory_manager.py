"""MemoryManager のテスト。"""

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.managers.memory_manager import MemoryManager


class TestMemoryManager:
    """MemoryManager クラスのテスト。"""

    @pytest.fixture
    def temp_storage(self) -> Path:
        """一時ストレージパスのフィクスチャ。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "memory.json"

    @pytest.fixture
    def manager(self, temp_storage: Path) -> MemoryManager:
        """MemoryManager のフィクスチャ。"""
        return MemoryManager(temp_storage)

    @pytest.fixture
    def manager_no_storage(self) -> MemoryManager:
        """ストレージなしの MemoryManager フィクスチャ。"""
        return MemoryManager()

    def test_save_and_get(self, manager: MemoryManager) -> None:
        """保存と取得のテスト。"""
        entry = manager.save("test_key", "test content", tags=["tag1", "tag2"])

        assert entry.key == "test_key"
        assert entry.content == "test content"
        assert "tag1" in entry.tags

        retrieved = manager.get("test_key")
        assert retrieved is not None
        assert retrieved.content == "test content"

    def test_save_update_existing(self, manager: MemoryManager) -> None:
        """既存エントリの更新テスト。"""
        manager.save("key1", "content1")
        entry = manager.save("key1", "content2")

        assert entry.content == "content2"

        retrieved = manager.get("key1")
        assert retrieved.content == "content2"

    def test_save_update_existing_with_empty_tags_clears_tags(
        self, manager: MemoryManager
    ) -> None:
        """既存エントリ更新時に tags=[] でタグをクリアできることをテスト。"""
        manager.save("key1", "content1", tags=["tag1", "tag2"])

        updated = manager.save("key1", "content2", tags=[])

        assert updated.tags == []
        assert manager.get("key1").tags == []

    def test_save_update_existing_without_tags_preserves_tags(
        self, manager: MemoryManager
    ) -> None:
        """既存エントリ更新時に tags 未指定なら既存タグを維持することをテスト。"""
        manager.save("key1", "content1", tags=["tag1"])

        updated = manager.save("key1", "content2")

        assert updated.tags == ["tag1"]

    def test_get_nonexistent(self, manager: MemoryManager) -> None:
        """存在しないキーの取得テスト。"""
        entry = manager.get("nonexistent")
        assert entry is None

    def test_search(self, manager: MemoryManager) -> None:
        """検索テスト。"""
        manager.save("key1", "Python programming")
        manager.save("key2", "JavaScript development")
        manager.save("key3", "Python testing")

        results = manager.search("Python")
        assert len(results) == 2

        results = manager.search("JavaScript")
        assert len(results) == 1

    def test_search_with_tags(self, manager: MemoryManager) -> None:
        """タグ付き検索テスト。"""
        manager.save("key1", "content1", tags=["python"])
        manager.save("key2", "content2", tags=["javascript"])
        manager.save("key3", "content3", tags=["python", "testing"])

        results = manager.search("content", tags=["python"])
        assert len(results) == 2

    def test_search_limit(self, manager: MemoryManager) -> None:
        """検索結果数制限テスト。"""
        for i in range(10):
            manager.save(f"key{i}", "same content")

        results = manager.search("content", limit=3)
        assert len(results) == 3

    def test_search_limit_prefers_newest_entries(self, manager: MemoryManager) -> None:
        """検索の件数制限時に更新日時の新しい順で返すことをテスト。"""
        manager.save("old_key", "match content")
        manager.save("new_key", "match content")

        now = datetime.now()
        manager.entries["old_key"].updated_at = now - timedelta(hours=2)
        manager.entries["new_key"].updated_at = now - timedelta(hours=1)

        results = manager.search("match", limit=1)

        assert len(results) == 1
        assert results[0].key == "new_key"

    def test_list_by_tags(self, manager: MemoryManager) -> None:
        """タグによるフィルタリングテスト。"""
        manager.save("key1", "content1", tags=["python"])
        manager.save("key2", "content2", tags=["javascript"])
        manager.save("key3", "content3", tags=["python", "testing"])

        results = manager.list_by_tags(["python"])
        assert len(results) == 2

        results = manager.list_by_tags(["testing"])
        assert len(results) == 1

    def test_list_all(self, manager: MemoryManager) -> None:
        """全エントリ取得テスト。"""
        manager.save("key1", "content1")
        manager.save("key2", "content2")
        manager.save("key3", "content3")

        results = manager.list_all()
        assert len(results) == 3

    def test_delete(self, manager: MemoryManager) -> None:
        """削除テスト。"""
        manager.save("key1", "content1")

        assert manager.delete("key1") is True
        assert manager.get("key1") is None

    def test_delete_nonexistent(self, manager: MemoryManager) -> None:
        """存在しないエントリの削除テスト。"""
        assert manager.delete("nonexistent") is False

    def test_clear(self, manager: MemoryManager) -> None:
        """クリアテスト。"""
        manager.save("key1", "content1")
        manager.save("key2", "content2")

        manager.clear()

        assert len(manager.list_all()) == 0

    def test_get_summary(self, manager: MemoryManager) -> None:
        """サマリー取得テスト。"""
        manager.save("key1", "content1", tags=["tag1"])
        manager.save("key2", "content2", tags=["tag2"])
        manager.save("key3", "content3", tags=["tag1", "tag2"])

        summary = manager.get_summary()

        assert summary["total_entries"] == 3
        assert summary["tag_count"] == 2
        assert "tag1" in summary["unique_tags"]
        assert "tag2" in summary["unique_tags"]

    def test_persistence(self, temp_storage: Path) -> None:
        """永続化テスト。"""
        # 最初のマネージャーでデータを保存
        manager1 = MemoryManager(temp_storage)
        manager1.save("key1", "content1", tags=["tag1"])

        # 新しいマネージャーでデータを読み込み
        manager2 = MemoryManager(temp_storage)
        entry = manager2.get("key1")

        assert entry is not None
        assert entry.content == "content1"
        assert "tag1" in entry.tags

    def test_to_dict(self, manager: MemoryManager) -> None:
        """辞書変換テスト。"""
        entry = manager.save("key1", "content1", tags=["tag1"])

        entry_dict = manager.to_dict(entry)

        assert entry_dict["key"] == "key1"
        assert entry_dict["content"] == "content1"
        assert "tag1" in entry_dict["tags"]
        assert "created_at" in entry_dict
        assert "updated_at" in entry_dict

    def test_no_storage_manager(self, manager_no_storage: MemoryManager) -> None:
        """ストレージなしマネージャーのテスト。"""
        entry = manager_no_storage.save("key1", "content1")
        assert entry is not None

        retrieved = manager_no_storage.get("key1")
        assert retrieved is not None

    def test_from_project_root(self) -> None:
        """from_project_root クラスメソッドのテスト。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager.from_project_root(tmpdir)

            # 保存先ディレクトリが正しいことを確認
            expected_dir = Path(tmpdir) / ".multi-agent-mcp" / "memory"
            assert manager.storage_dir == expected_dir

            # 保存・読み込みが動作することを確認
            manager.save("test_key", "test_content")
            assert manager.get("test_key").content == "test_content"

            # ディレクトリが作成されていることを確認
            assert expected_dir.exists()

    def test_from_global(self) -> None:
        """from_global クラスメソッドのテスト。"""
        manager = MemoryManager.from_global()

        # 保存先ディレクトリが正しいことを確認
        home_dir = Path.home()
        expected_dir = home_dir / ".multi-agent-mcp" / "memory"
        assert manager.storage_dir == expected_dir

        # デフォルト値が設定されていることを確認
        assert manager.max_entries == 1000
        assert manager.ttl_days == 90

    def test_prune_ttl(self, temp_storage: Path) -> None:
        """TTL超過エントリの削除テスト。"""
        from datetime import datetime, timedelta

        manager = MemoryManager(temp_storage, ttl_days=1, auto_prune=False)

        # 古いエントリを直接作成
        from src.managers.memory_manager import MemoryEntry

        old_date = datetime.now() - timedelta(days=2)
        old_entry = MemoryEntry(
            key="old_key",
            content="old content",
            created_at=old_date,
            updated_at=old_date,
        )
        manager.entries["old_key"] = old_entry

        # 新しいエントリを追加
        manager.save("new_key", "new content")

        # prune を実行
        deleted_count = manager.prune()

        # 古いエントリが削除されていることを確認
        assert deleted_count == 1
        assert manager.get("old_key") is None
        assert manager.get("new_key") is not None

    def test_prune_max_entries(self, temp_storage: Path) -> None:
        """最大エントリ数超過時の削除テスト。"""
        manager = MemoryManager(temp_storage, max_entries=3, auto_prune=False)

        # 5つのエントリを追加
        for i in range(5):
            manager.save(f"key{i}", f"content{i}")

        # prune を実行
        deleted_count = manager.prune()

        # 2つのエントリが削除されていることを確認
        assert deleted_count == 2
        assert len(manager.list_all()) == 3

    def test_auto_prune_on_save(self, temp_storage: Path) -> None:
        """保存時の自動クリーンアップテスト。"""
        manager = MemoryManager(temp_storage, max_entries=3, auto_prune=True)

        # 5つのエントリを追加（自動クリーンアップが発動）
        for i in range(5):
            manager.save(f"key{i}", f"content{i}")

        # 最大3つのエントリのみ残っていることを確認
        assert len(manager.list_all()) == 3

    def test_custom_max_entries_and_ttl(self, temp_storage: Path) -> None:
        """カスタムmax_entriesとttl_daysのテスト。"""
        manager = MemoryManager(
            temp_storage,
            max_entries=100,
            ttl_days=30,
        )

        assert manager.max_entries == 100
        assert manager.ttl_days == 30

    def test_archive_path(self, temp_storage: Path) -> None:
        """アーカイブパスのテスト。"""
        manager = MemoryManager(temp_storage)

        expected_archive_dir = temp_storage / "archive"
        assert manager.archive_dir == expected_archive_dir

    def test_prune_archives_entries(self, temp_storage: Path) -> None:
        """prune がエントリをアーカイブに移動することをテスト。"""
        manager = MemoryManager(temp_storage, max_entries=2, auto_prune=False)

        # 3つのエントリを追加
        manager.save("key1", "content1")
        manager.save("key2", "content2")
        manager.save("key3", "content3")

        # prune を実行
        archived_count = manager.prune()

        # 1つのエントリがアーカイブに移動
        assert archived_count == 1
        assert len(manager.list_all()) == 2

        # アーカイブディレクトリが作成されていることを確認
        assert manager.archive_dir.exists()

        # アーカイブからエントリを検索できることを確認
        archive_entries = manager.list_archive()
        assert len(archive_entries) == 1

    def test_search_archive(self, temp_storage: Path) -> None:
        """アーカイブ検索のテスト。"""
        manager = MemoryManager(temp_storage, max_entries=1, auto_prune=False)

        # 2つのエントリを追加してアーカイブさせる
        manager.save("python_key", "Python programming")
        manager.save("java_key", "Java development")
        manager.prune()  # python_key がアーカイブに移動

        # アーカイブを検索
        results = manager.search_archive("Python")
        assert len(results) == 1
        assert results[0].key == "python_key"

    def test_search_archive_limit_prefers_newest_entries(self, temp_storage: Path) -> None:
        """アーカイブ検索の件数制限時に更新日時の新しい順で返すことをテスト。"""
        manager = MemoryManager(temp_storage, max_entries=1, auto_prune=False)

        manager.save("old_key", "Python old")
        manager.save("mid_key", "Python mid")
        manager.save("new_key", "Python new")

        now = datetime.now()
        manager.entries["old_key"].updated_at = now - timedelta(hours=3)
        manager.entries["mid_key"].updated_at = now - timedelta(hours=2)
        manager.entries["new_key"].updated_at = now - timedelta(hours=1)

        manager.prune()  # old_key, mid_key をアーカイブ

        results = manager.search_archive("Python", limit=1)

        assert len(results) == 1
        assert results[0].key == "mid_key"

    def test_restore_from_archive(self, temp_storage: Path) -> None:
        """アーカイブからの復元テスト。"""
        manager = MemoryManager(temp_storage, max_entries=1, auto_prune=False)

        # エントリを追加してアーカイブ
        manager.save("old_key", "old content", tags=["tag1"])
        manager.save("new_key", "new content")
        manager.prune()

        # old_key がアーカイブに移動していることを確認
        assert manager.get("old_key") is None
        archive_entries = manager.list_archive()
        assert any(e.key == "old_key" for e in archive_entries)

        # アーカイブから復元
        restored = manager.restore_from_archive("old_key")
        assert restored is not None
        assert restored.key == "old_key"
        assert restored.content == "old content"
        assert "tag1" in restored.tags

        # メインメモリに復元されていることを確認
        assert manager.get("old_key") is not None

        # アーカイブから削除されていることを確認
        archive_entries = manager.list_archive()
        assert not any(e.key == "old_key" for e in archive_entries)

    def test_get_archive_summary(self, temp_storage: Path) -> None:
        """アーカイブサマリーのテスト。"""
        manager = MemoryManager(temp_storage, max_entries=1, auto_prune=False)

        # エントリを追加してアーカイブ
        manager.save("key1", "content1", tags=["tag1"])
        manager.save("key2", "content2")
        manager.prune()

        summary = manager.get_archive_summary()
        assert summary["total_entries"] == 1
        assert "tag1" in summary["unique_tags"]
        assert summary["archive_dir"] is not None

    def test_list_archive_with_limit(self, temp_storage: Path) -> None:
        """アーカイブ一覧の件数制限テスト。"""
        manager = MemoryManager(temp_storage, max_entries=1, auto_prune=False)

        # 5つのエントリを追加してアーカイブ
        for i in range(5):
            manager.save(f"key{i}", f"content{i}")
        manager.prune()  # 4つがアーカイブに移動

        # 件数制限ありで取得
        entries = manager.list_archive(limit=2)
        assert len(entries) == 2

        # 全件取得
        all_entries = manager.list_archive()
        assert len(all_entries) == 4

    def test_load_from_dir_limits_entries_by_max_entries(self, temp_storage: Path) -> None:
        """起動時読み込みが max_entries 件に制限されることをテスト。"""
        seed_manager = MemoryManager(temp_storage, max_entries=10, auto_prune=False)
        for i in range(5):
            seed_manager.save(f"key{i}", f"content{i}")

        base_ts = datetime.now().timestamp() - 1000
        for i in range(5):
            file_path = temp_storage / f"key{i}.md"
            mtime = base_ts + i
            os.utime(file_path, (mtime, mtime))

        manager = MemoryManager(temp_storage, max_entries=3, auto_prune=False)
        loaded_keys = {entry.key for entry in manager.list_all()}

        assert loaded_keys == {"key2", "key3", "key4"}

    def test_load_from_dir_archives_overflow_files_when_auto_prune_enabled(
        self, temp_storage: Path
    ) -> None:
        """起動時に上限超過ファイルがアーカイブへ移動されることをテスト。"""
        seed_manager = MemoryManager(temp_storage, max_entries=10, auto_prune=False)
        for i in range(4):
            seed_manager.save(f"key{i}", f"content{i}")

        base_ts = datetime.now().timestamp() - 1000
        for i in range(4):
            file_path = temp_storage / f"key{i}.md"
            mtime = base_ts + i
            os.utime(file_path, (mtime, mtime))

        manager = MemoryManager(temp_storage, max_entries=2, auto_prune=True)

        loaded_keys = {entry.key for entry in manager.list_all()}
        assert loaded_keys == {"key2", "key3"}

        remaining_files = {path.name for path in temp_storage.glob("*.md")}
        assert remaining_files == {"key2.md", "key3.md"}

        assert manager.archive_dir is not None
        archived_files = {path.name for path in manager.archive_dir.glob("*.md")}
        assert archived_files == {"key0.md", "key1.md"}
