"""PersonaManager のテスト。"""

import pytest

from src.managers.persona_manager import PersonaManager, TaskType


class TestPersonaManager:
    """PersonaManager クラスのテスト。"""

    @pytest.fixture
    def manager(self) -> PersonaManager:
        """PersonaManager のフィクスチャ。"""
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
            assert persona.system_prompt_addition != ""

    def test_get_optimal_persona(self, manager: PersonaManager) -> None:
        """最適ペルソナ取得テスト。"""
        persona = manager.get_optimal_persona("ユーザー認証を実装")
        assert persona.name == "シニアソフトウェアエンジニア"

        persona = manager.get_optimal_persona("ユニットテストを書く")
        assert persona.name == "QAエンジニア"

    def test_get_persona_prompt(self, manager: PersonaManager) -> None:
        """ペルソナプロンプト取得テスト。"""
        prompt = manager.get_persona_prompt("バグを修正")
        assert "デバッグスペシャリスト" in prompt

    def test_list_personas(self, manager: PersonaManager) -> None:
        """ペルソナ一覧取得テスト。"""
        personas = manager.list_personas()
        assert len(personas) == len(TaskType)

        for persona in personas:
            assert "task_type" in persona
            assert "name" in persona
            assert "description" in persona
