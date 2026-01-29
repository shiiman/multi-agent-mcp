"""ペルソナ管理モジュール。

タスクの種類に応じて最適なペルソナを自動設定する機能を提供する。
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """タスクの種類。"""

    CODE = "code"
    """コード実装"""

    TEST = "test"
    """テスト作成"""

    DOCS = "docs"
    """ドキュメント作成"""

    REVIEW = "review"
    """コードレビュー"""

    DEBUG = "debug"
    """デバッグ・バグ修正"""

    DESIGN = "design"
    """設計・アーキテクチャ"""

    REFACTOR = "refactor"
    """リファクタリング"""

    UNKNOWN = "unknown"
    """不明"""


@dataclass
class Persona:
    """ペルソナ情報。"""

    name: str
    """ペルソナ名"""

    description: str
    """ペルソナの説明"""

    system_prompt_addition: str
    """システムプロンプトに追加するテキスト"""


# タスクタイプとペルソナのマッピング
TASK_PERSONAS: dict[TaskType, Persona] = {
    TaskType.CODE: Persona(
        name="シニアソフトウェアエンジニア",
        description="効率的で保守性の高いコードを書くエキスパート",
        system_prompt_addition=(
            "あなたはシニアソフトウェアエンジニアとして作業しています。\n"
            "- クリーンで読みやすいコードを心がける\n"
            "- 適切なエラーハンドリングを実装する\n"
            "- パフォーマンスとセキュリティを考慮する\n"
            "- 必要に応じてコメントを追加する"
        ),
    ),
    TaskType.TEST: Persona(
        name="QAエンジニア",
        description="品質保証とテスト設計のエキスパート",
        system_prompt_addition=(
            "あなたはQAエンジニアとして作業しています。\n"
            "- 網羅的なテストケースを設計する\n"
            "- エッジケースを考慮する\n"
            "- テストの可読性と保守性を重視する\n"
            "- カバレッジを意識したテストを書く"
        ),
    ),
    TaskType.DOCS: Persona(
        name="テクニカルライター",
        description="明確で分かりやすいドキュメントを書くエキスパート",
        system_prompt_addition=(
            "あなたはテクニカルライターとして作業しています。\n"
            "- 読者の視点で分かりやすく説明する\n"
            "- 適切な構成と見出しを使用する\n"
            "- コード例を含める場合は動作確認済みのものを使う\n"
            "- 専門用語には説明を添える"
        ),
    ),
    TaskType.REVIEW: Persona(
        name="コードレビュワー",
        description="コード品質とベストプラクティスを確認するエキスパート",
        system_prompt_addition=(
            "あなたはコードレビュワーとして作業しています。\n"
            "- コードの可読性と保守性を確認する\n"
            "- バグやセキュリティの問題を見つける\n"
            "- ベストプラクティスからの逸脱を指摘する\n"
            "- 建設的なフィードバックを提供する"
        ),
    ),
    TaskType.DEBUG: Persona(
        name="デバッグスペシャリスト",
        description="問題の根本原因を特定し解決するエキスパート",
        system_prompt_addition=(
            "あなたはデバッグスペシャリストとして作業しています。\n"
            "- 問題を再現可能な形で特定する\n"
            "- 根本原因を分析する\n"
            "- 影響範囲を確認する\n"
            "- 修正による副作用を考慮する"
        ),
    ),
    TaskType.DESIGN: Persona(
        name="ソフトウェアアーキテクト",
        description="システム設計とアーキテクチャのエキスパート",
        system_prompt_addition=(
            "あなたはソフトウェアアーキテクトとして作業しています。\n"
            "- スケーラビリティと保守性を考慮する\n"
            "- 適切なデザインパターンを選択する\n"
            "- 依存関係を最小限に抑える\n"
            "- 将来の拡張性を考慮する"
        ),
    ),
    TaskType.REFACTOR: Persona(
        name="リファクタリングエキスパート",
        description="コード改善と技術的負債解消のエキスパート",
        system_prompt_addition=(
            "あなたはリファクタリングエキスパートとして作業しています。\n"
            "- 動作を変えずにコードを改善する\n"
            "- 段階的に変更を加える\n"
            "- テストで動作を保証する\n"
            "- 読みやすさと保守性を向上させる"
        ),
    ),
    TaskType.UNKNOWN: Persona(
        name="汎用エンジニア",
        description="様々なタスクに対応可能なエンジニア",
        system_prompt_addition=(
            "あなたは経験豊富なソフトウェアエンジニアとして作業しています。\n"
            "- タスクの要件を正確に理解する\n"
            "- 適切な品質でアウトプットを出す\n"
            "- 不明点があれば確認する"
        ),
    ),
}


# タスクタイプ検出用のキーワードパターン
TASK_TYPE_PATTERNS: dict[TaskType, list[str]] = {
    TaskType.CODE: [
        r"実装",
        r"implement",
        r"作成",
        r"create",
        r"追加",
        r"add",
        r"機能",
        r"feature",
        r"開発",
        r"develop",
    ],
    TaskType.TEST: [
        r"テスト",
        r"test",
        r"ユニットテスト",
        r"unit\s*test",
        r"結合テスト",
        r"integration",
        r"e2e",
        r"カバレッジ",
        r"coverage",
    ],
    TaskType.DOCS: [
        r"ドキュメント",
        r"document",
        r"README",
        r"説明",
        r"マニュアル",
        r"manual",
        r"コメント",
        r"comment",
        r"docstring",
    ],
    TaskType.REVIEW: [
        r"レビュー",
        r"review",
        r"確認",
        r"check",
        r"チェック",
        r"検証",
        r"verify",
    ],
    TaskType.DEBUG: [
        r"デバッグ",
        r"debug",
        r"バグ",
        r"bug",
        r"修正",
        r"fix",
        r"エラー",
        r"error",
        r"問題",
        r"issue",
        r"不具合",
    ],
    TaskType.DESIGN: [
        r"設計",
        r"design",
        r"アーキテクチャ",
        r"architecture",
        r"構造",
        r"structure",
        r"プラン",
        r"plan",
        r"企画",
    ],
    TaskType.REFACTOR: [
        r"リファクタ",
        r"refactor",
        r"改善",
        r"improve",
        r"最適化",
        r"optimize",
        r"整理",
        r"clean",
        r"技術的負債",
    ],
}


class PersonaManager:
    """ペルソナ管理クラス。

    タスクの内容に基づいて最適なペルソナを自動的に選択する。
    """

    def __init__(self) -> None:
        """PersonaManagerを初期化する。"""
        self.personas = TASK_PERSONAS
        self.patterns = TASK_TYPE_PATTERNS

    def detect_task_type(self, task_description: str) -> TaskType:
        """タスクの説明からタスクタイプを検出する。

        Args:
            task_description: タスクの説明文

        Returns:
            検出されたタスクタイプ
        """
        if not task_description:
            return TaskType.UNKNOWN

        description_lower = task_description.lower()
        scores: dict[TaskType, int] = {}

        for task_type, patterns in self.patterns.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, description_lower, re.IGNORECASE):
                    score += 1
            if score > 0:
                scores[task_type] = score

        if not scores:
            return TaskType.UNKNOWN

        # 最も高いスコアのタスクタイプを返す
        best_type = max(scores, key=lambda x: scores[x])
        logger.info(f"タスクタイプを検出: {best_type.value} (スコア: {scores})")
        return best_type

    def get_persona(self, task_type: TaskType) -> Persona:
        """タスクタイプに対応するペルソナを取得する。

        Args:
            task_type: タスクタイプ

        Returns:
            ペルソナ情報
        """
        return self.personas.get(task_type, self.personas[TaskType.UNKNOWN])

    def get_optimal_persona(self, task_description: str) -> Persona:
        """タスクの説明から最適なペルソナを取得する。

        Args:
            task_description: タスクの説明文

        Returns:
            最適なペルソナ情報
        """
        task_type = self.detect_task_type(task_description)
        return self.get_persona(task_type)

    def get_persona_prompt(self, task_description: str) -> str:
        """タスクの説明から最適なペルソナのプロンプトを取得する。

        Args:
            task_description: タスクの説明文

        Returns:
            ペルソナのシステムプロンプト追加文
        """
        persona = self.get_optimal_persona(task_description)
        return persona.system_prompt_addition

    def list_personas(self) -> list[dict]:
        """利用可能なペルソナの一覧を取得する。

        Returns:
            ペルソナ情報のリスト
        """
        return [
            {
                "task_type": task_type.value,
                "name": persona.name,
                "description": persona.description,
            }
            for task_type, persona in self.personas.items()
        ]
