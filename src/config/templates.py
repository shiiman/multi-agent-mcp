"""ワークスペース設定テンプレート。

用途別の構成テンプレートを定義する。
"""

from dataclasses import dataclass


@dataclass
class WorkspaceTemplate:
    """ワークスペース設定テンプレート。"""

    name: str
    """テンプレート名"""

    description: str
    """テンプレートの説明"""

    owner_count: int = 1
    """Ownerエージェントの数"""

    admin_count: int = 1
    """Adminエージェントの数"""

    worker_count: int = 3
    """Workerエージェントの数"""

    ai_cli: str = "claude"
    """使用するAI CLI"""

    auto_assign: bool = True
    """タスクの自動割り当てを有効にするか"""

    healthcheck_enabled: bool = True
    """ヘルスチェックを有効にするか"""

    healthcheck_interval_sec: int = 300
    """ヘルスチェックの間隔（秒）"""

    def to_dict(self) -> dict:
        """テンプレートを辞書に変換する。

        Returns:
            テンプレートの辞書表現
        """
        return {
            "name": self.name,
            "description": self.description,
            "owner_count": self.owner_count,
            "admin_count": self.admin_count,
            "worker_count": self.worker_count,
            "ai_cli": self.ai_cli,
            "auto_assign": self.auto_assign,
            "healthcheck_enabled": self.healthcheck_enabled,
            "healthcheck_interval_sec": self.healthcheck_interval_sec,
        }


# 定義済みテンプレート
TEMPLATES: dict[str, WorkspaceTemplate] = {
    "development": WorkspaceTemplate(
        name="development",
        description="標準的な開発ワークフロー",
        worker_count=3,
        auto_assign=True,
    ),
    "large-feature": WorkspaceTemplate(
        name="large-feature",
        description="大規模機能開発（Worker最大数）",
        worker_count=5,
        auto_assign=True,
    ),
    "testing": WorkspaceTemplate(
        name="testing",
        description="テスト実行専用",
        worker_count=2,
        auto_assign=False,
    ),
    "review": WorkspaceTemplate(
        name="review",
        description="コードレビュー専用",
        owner_count=1,
        admin_count=0,
        worker_count=1,
        auto_assign=False,
    ),
    "solo": WorkspaceTemplate(
        name="solo",
        description="単一Worker（シンプルなタスク向け）",
        admin_count=0,
        worker_count=1,
        auto_assign=False,
        healthcheck_enabled=False,
    ),
    "pair": WorkspaceTemplate(
        name="pair",
        description="ペアプログラミング向け（2 Worker）",
        admin_count=0,
        worker_count=2,
        auto_assign=True,
        healthcheck_enabled=True,
    ),
}


def get_template(name: str) -> WorkspaceTemplate | None:
    """テンプレートを名前で取得する。

    Args:
        name: テンプレート名

    Returns:
        テンプレート、見つからない場合None
    """
    return TEMPLATES.get(name)


def list_templates() -> list[WorkspaceTemplate]:
    """全テンプレートを取得する。

    Returns:
        テンプレートのリスト
    """
    return list(TEMPLATES.values())


def get_template_names() -> list[str]:
    """テンプレート名の一覧を取得する。

    Returns:
        テンプレート名のリスト
    """
    return list(TEMPLATES.keys())
