"""PersonaManager のテスト。"""

from pathlib import Path

import pytest

from src.managers.persona_manager import PersonaManager, TaskType


class TestPersonaManager:
    """PersonaManager クラスのテスト。"""

    @pytest.fixture
    def manager(self) -> PersonaManager:
        """PersonaManager のフィクスチャ（実テンプレートを使用）。"""
        return PersonaManager()

    def test_detect_task_type_code(self, manager: PersonaManager) -> None:
        """コード実装タスクの検出テスト。"""
        descriptions = [
            "ユーザー認証機能を実装してください",
            "新しいAPIエンドポイントを追加",
            "機能を開発する",
            "implement user login",
        ]

        for desc in descriptions:
            task_type = manager.detect_task_type(desc)
            assert task_type == TaskType.CODE, f"Failed for: {desc}"

    def test_detect_task_type_test(self, manager: PersonaManager) -> None:
        """テストタスクの検出テスト。"""
        descriptions = [
            "ユニットテストを書いてください",
            "unit test for the module",
            "カバレッジを上げる",
            "結合テストを書く",
        ]

        for desc in descriptions:
            task_type = manager.detect_task_type(desc)
            assert task_type == TaskType.TEST, f"Failed for: {desc}"

    def test_detect_task_type_docs(self, manager: PersonaManager) -> None:
        """ドキュメントタスクの検出テスト。"""
        descriptions = [
            "READMEを更新してください",
            "ドキュメントを書いてください",
            "マニュアルを書く",
            "docstring を書く",
        ]

        for desc in descriptions:
            task_type = manager.detect_task_type(desc)
            assert task_type == TaskType.DOCS, f"Failed for: {desc}"

    def test_detect_task_type_debug(self, manager: PersonaManager) -> None:
        """デバッグタスクの検出テスト。"""
        descriptions = [
            "バグを修正する",
            "エラーを解決",
            "デバッグする",
            "不具合を直す",
        ]

        for desc in descriptions:
            task_type = manager.detect_task_type(desc)
            assert task_type == TaskType.DEBUG, f"Failed for: {desc}"

    def test_detect_task_type_design(self, manager: PersonaManager) -> None:
        """設計タスクの検出テスト。"""
        descriptions = [
            "システム設計を行う",
            "アーキテクチャを検討",
            "構造を設計する",
        ]

        for desc in descriptions:
            task_type = manager.detect_task_type(desc)
            assert task_type == TaskType.DESIGN, f"Failed for: {desc}"

    def test_detect_task_type_refactor(self, manager: PersonaManager) -> None:
        """リファクタリングタスクの検出テスト。"""
        descriptions = [
            "コードをリファクタリング",
            "最適化する",
            "コードを改善",
        ]

        for desc in descriptions:
            task_type = manager.detect_task_type(desc)
            assert task_type == TaskType.REFACTOR, f"Failed for: {desc}"

    def test_detect_task_type_unknown(self, manager: PersonaManager) -> None:
        """不明なタスクの検出テスト。"""
        descriptions = [
            "",
            "あいうえお",
            "xyzabc123",
        ]

        for desc in descriptions:
            task_type = manager.detect_task_type(desc)
            assert task_type == TaskType.UNKNOWN, f"Failed for: {desc}"

    def test_get_persona(self, manager: PersonaManager) -> None:
        """ペルソナ取得テスト。"""
        for task_type in TaskType:
            persona = manager.get_persona(task_type)
            assert persona is not None
            assert persona.name != ""
            assert persona.description != ""
            assert persona.file_path.exists()

    def test_get_optimal_persona(self, manager: PersonaManager) -> None:
        """最適ペルソナ取得テスト。"""
        persona = manager.get_optimal_persona("ユーザー認証を実装")
        assert persona.name == "シニアソフトウェアエンジニア"

        persona = manager.get_optimal_persona("ユニットテストを書く")
        assert persona.name == "QAエンジニア"

    def test_list_personas(self, manager: PersonaManager) -> None:
        """ペルソナ一覧取得テスト。"""
        personas = manager.list_personas()
        assert len(personas) == len(TaskType)

        for persona in personas:
            assert "task_type" in persona
            assert "name" in persona
            assert "description" in persona
            assert "file_path" in persona

    def test_load_all_persona_files(self, manager: PersonaManager) -> None:
        """全ペルソナファイルがロードされることを確認。"""
        personas = manager._load_personas()
        assert len(personas) == len(TaskType)
        for task_type in TaskType:
            assert task_type.value in personas, (
                f"タスクタイプ '{task_type.value}' のペルソナが見つかりません"
            )

    def test_parse_front_matter_valid(self) -> None:
        """YAML Front Matter の正常パースをテスト。"""
        content = "---\nname: テスト\ndescription: 説明\ntask_type: code\n---\n# 本文"
        result = PersonaManager._parse_front_matter(content)
        assert result is not None
        assert result["name"] == "テスト"
        assert result["description"] == "説明"
        assert result["task_type"] == "code"

    def test_parse_front_matter_no_front_matter(self) -> None:
        """Front Matter がないコンテンツで None を返すことをテスト。"""
        content = "# タイトル\n\n本文"
        result = PersonaManager._parse_front_matter(content)
        assert result is None

    def test_parse_front_matter_invalid_yaml(self) -> None:
        """不正な YAML で None を返すことをテスト。"""
        content = "---\n: invalid: yaml: [\n---\n# 本文"
        result = PersonaManager._parse_front_matter(content)
        assert result is None

    def test_parse_front_matter_non_mapping_yaml(self) -> None:
        """YAML が mapping 以外なら None を返す。"""
        content = "---\n- item1\n- item2\n---\n# 本文"
        result = PersonaManager._parse_front_matter(content)
        assert result is None

    def test_fallback_to_unknown(self, manager: PersonaManager) -> None:
        """存在しない TaskType で unknown にフォールバックすることをテスト。"""
        persona = manager.get_persona(TaskType.UNKNOWN)
        assert persona.name == "汎用エンジニア"
        assert persona.task_type == "unknown"

    def test_custom_personas_dir(self, tmp_path: Path) -> None:
        """カスタムディレクトリでの初期化をテスト。"""
        personas_dir = tmp_path / "personas"
        personas_dir.mkdir()
        (personas_dir / "unknown.md").write_text(
            "---\nname: カスタム\ndescription: テスト\ntask_type: unknown\n---\n# カスタム\n",
            encoding="utf-8",
        )
        manager = PersonaManager(personas_dir=personas_dir)
        persona = manager.get_persona(TaskType.UNKNOWN)
        assert persona.name == "カスタム"

    def test_personas_dir_not_found(self, tmp_path: Path) -> None:
        """存在しないディレクトリで空のペルソナを返すことをテスト。"""
        manager = PersonaManager(personas_dir=tmp_path / "nonexistent")
        personas = manager._load_personas()
        assert len(personas) == 0

    def test_get_persona_raises_value_error_when_no_personas(
        self, tmp_path: Path
    ) -> None:
        """unknown.md も含めペルソナが存在しない場合 ValueError を送出する。"""
        empty_dir = tmp_path / "empty_personas"
        empty_dir.mkdir()
        manager = PersonaManager(personas_dir=empty_dir)
        with pytest.raises(ValueError, match="ペルソナが見つかりません"):
            manager.get_persona(TaskType.CODE)

    def test_parse_persona_file_invalid_task_type(self, tmp_path: Path) -> None:
        """不正な task_type のペルソナファイルは None を返す。"""
        personas_dir = tmp_path / "personas"
        personas_dir.mkdir()
        bad_file = personas_dir / "bad.md"
        bad_file.write_text(
            "---\nname: テスト\ndescription: 説明\ntask_type: nonexistent\n---\n# 本文\n",
            encoding="utf-8",
        )
        manager = PersonaManager(personas_dir=personas_dir)
        result = manager._parse_persona_file(bad_file)
        assert result is None

    def test_parse_persona_file_non_mapping_front_matter(self, tmp_path: Path) -> None:
        """Front Matter が mapping 以外なら None を返す。"""
        personas_dir = tmp_path / "personas"
        personas_dir.mkdir()
        bad_file = personas_dir / "bad.md"
        bad_file.write_text(
            "---\n- item1\n- item2\n---\n# 本文\n",
            encoding="utf-8",
        )
        manager = PersonaManager(personas_dir=personas_dir)
        result = manager._parse_persona_file(bad_file)
        assert result is None

    def test_parse_front_matter_single_delimiter(self) -> None:
        """閉じ --- がない場合 None を返す。"""
        content = "---\nname: テスト\n"
        result = PersonaManager._parse_front_matter(content)
        assert result is None

    def test_parse_persona_file_missing_keys_uses_defaults(
        self, tmp_path: Path
    ) -> None:
        """name/description が省略された場合、ファイル名・空文字のデフォルトを使用する。"""
        personas_dir = tmp_path / "personas"
        personas_dir.mkdir()
        minimal = personas_dir / "code.md"
        minimal.write_text(
            "---\ntask_type: code\n---\n# 本文\n",
            encoding="utf-8",
        )
        manager = PersonaManager(personas_dir=personas_dir)
        persona = manager._parse_persona_file(minimal)
        assert persona is not None
        assert persona.name == "code"  # ファイル名がデフォルト
        assert persona.description == ""  # 空文字がデフォルト
        assert persona.task_type == "code"

    def test_parse_persona_file_os_error(self, tmp_path: Path) -> None:
        """読み込み不能ファイルで None を返す。"""
        personas_dir = tmp_path / "personas"
        personas_dir.mkdir()
        bad_path = personas_dir / "missing.md"
        manager = PersonaManager(personas_dir=personas_dir)
        result = manager._parse_persona_file(bad_path)
        assert result is None

    def test_load_personas_skips_non_mapping_front_matter_file(
        self, tmp_path: Path
    ) -> None:
        """破損した persona ファイルがあっても有効なファイルだけをロードする。"""
        personas_dir = tmp_path / "personas"
        personas_dir.mkdir()
        (personas_dir / "bad.md").write_text(
            "---\n- item1\n- item2\n---\n# 本文\n",
            encoding="utf-8",
        )
        (personas_dir / "unknown.md").write_text(
            "---\nname: 汎用\ndescription: fallback\ntask_type: unknown\n---\n# 本文\n",
            encoding="utf-8",
        )
        manager = PersonaManager(personas_dir=personas_dir)

        personas = manager._load_personas()

        assert list(personas) == ["unknown"]
