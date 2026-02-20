"""ペルソナ管理モジュール。

タスクの種類に応じて最適なペルソナを自動設定する機能を提供する。
ペルソナ定義は templates/personas/*.md からロードする。
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

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

    task_type: str
    """タスクタイプ"""

    file_path: Path
    """ペルソナテンプレートファイルのパス"""


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
    ペルソナ定義は templates/personas/*.md からロードする。
    """

    def __init__(self, personas_dir: Path | None = None) -> None:
        """PersonaManagerを初期化する。

        Args:
            personas_dir: ペルソナテンプレートディレクトリ。
                省略時は templates/personas/ を使用。
        """
        if personas_dir is None:
            personas_dir = Path(__file__).parent.parent.parent / "templates" / "personas"
        self._personas_dir = personas_dir
        self.patterns = TASK_TYPE_PATTERNS
        self._personas_cache: dict[str, Persona] | None = None

    def _load_personas(self) -> dict[str, Persona]:
        """ペルソナテンプレートファイルをロードしてキャッシュする。

        Returns:
            タスクタイプ → Persona のマッピング
        """
        if self._personas_cache is not None:
            return self._personas_cache

        personas: dict[str, Persona] = {}
        if not self._personas_dir.exists():
            logger.warning(
                "ペルソナテンプレートディレクトリが見つかりません: %s",
                self._personas_dir,
            )
            return personas

        for md_file in sorted(self._personas_dir.glob("*.md")):
            persona = self._parse_persona_file(md_file)
            if persona:
                personas[persona.task_type] = persona

        self._personas_cache = personas
        return personas

    def _parse_persona_file(self, file_path: Path) -> Persona | None:
        """ペルソナテンプレートファイルをパースする。

        Args:
            file_path: ペルソナテンプレートファイルのパス

        Returns:
            Persona オブジェクト。パース失敗時は None
        """
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("ペルソナファイルの読み込みに失敗: %s - %s", file_path, e)
            return None

        metadata = self._parse_front_matter(content)
        if not metadata:
            logger.warning(
                "ペルソナファイルの Front Matter が見つかりません: %s", file_path
            )
            return None

        # task_type のバリデーション: TaskType Enum に存在する値のみ許可
        raw_task_type = metadata.get("task_type", file_path.stem)
        valid_values = {t.value for t in TaskType}
        if raw_task_type not in valid_values:
            logger.warning(
                "不正な task_type '%s' です（%s）。有効な値: %s",
                raw_task_type,
                file_path,
                valid_values,
            )
            return None

        return Persona(
            name=metadata.get("name", file_path.stem),
            description=metadata.get("description", ""),
            task_type=raw_task_type,
            file_path=file_path.resolve(),
        )

    @staticmethod
    def _parse_front_matter(content: str) -> dict | None:
        """YAML Front Matter をパースする。

        Args:
            content: Markdown コンテンツ（YAML Front Matter 付き）

        Returns:
            パースされた辞書。失敗時は None
        """
        if not content.startswith("---"):
            return None
        parts = content.split("---", 2)
        if len(parts) < 3:
            return None
        try:
            return yaml.safe_load(parts[1])
        except yaml.YAMLError:
            return None

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
        personas = self._load_personas()
        persona = personas.get(task_type.value)
        if persona is None:
            persona = personas.get(TaskType.UNKNOWN.value)
        if persona is None:
            raise ValueError(
                f"ペルソナが見つかりません（ディレクトリ: {self._personas_dir}）"
            )
        return persona

    def get_optimal_persona(self, task_description: str) -> Persona:
        """タスクの説明から最適なペルソナを取得する。

        Args:
            task_description: タスクの説明文

        Returns:
            最適なペルソナ情報
        """
        task_type = self.detect_task_type(task_description)
        return self.get_persona(task_type)

    def list_personas(self) -> list[dict]:
        """利用可能なペルソナの一覧を取得する。

        Returns:
            ペルソナ情報のリスト
        """
        personas = self._load_personas()
        return [
            {
                "task_type": persona.task_type,
                "name": persona.name,
                "description": persona.description,
                "file_path": str(persona.file_path),
            }
            for persona in personas.values()
        ]
