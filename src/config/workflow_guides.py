"""ロール別テンプレートガイド。

エージェントの役割に応じた振る舞いガイドを templates/ から読み込む。
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class RoleGuide:
    """ロール別操作ガイド。"""

    role: str
    """ロール名"""

    description: str
    """ガイドの説明"""

    content: str
    """ガイド本文（Markdown形式）"""

    def to_dict(self) -> dict:
        """ガイドを辞書に変換する。"""
        return {
            "role": self.role,
            "description": self.description,
            "content": self.content,
        }


def _get_templates_dir() -> Path:
    """templates ディレクトリのパスを取得する。"""
    # このファイルは src/config/workflow_guides.py にある
    # templates/ は プロジェクトルート/templates/
    return Path(__file__).parent.parent.parent / "templates"


def _load_template(role: str) -> str | None:
    """テンプレートファイルを読み込む。

    Args:
        role: ロール名（owner, admin, worker）

    Returns:
        テンプレート内容、ファイルが存在しない場合 None
    """
    template_path = _get_templates_dir() / "roles" / f"{role}.md"
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    return None


# ロール説明
ROLE_DESCRIPTIONS = {
    "owner": "マルチエージェントワークフローにおける Owner の役割と振る舞い",
    "admin": "マルチエージェントワークフローにおける Admin の役割と振る舞い",
    "worker": "マルチエージェントワークフローにおける Worker の役割と振る舞い",
}


def get_role_guide(role: str) -> RoleGuide | None:
    """ロールガイドを名前で取得する。

    templates/roles/{role}.md からテンプレートを読み込む。

    Args:
        role: ロール名（owner, admin, worker）

    Returns:
        ロールガイド、見つからない場合 None
    """
    content = _load_template(role)
    if content is None:
        return None

    description = ROLE_DESCRIPTIONS.get(role, f"{role} の役割と振る舞い")

    return RoleGuide(
        role=role,
        description=description,
        content=content,
    )


def list_role_guides() -> list[str]:
    """利用可能なロールガイド名の一覧を取得する。

    templates/roles/ ディレクトリ内の .md ファイルを検索する。

    Returns:
        ロール名のリスト
    """
    roles_dir = _get_templates_dir() / "roles"
    if not roles_dir.exists():
        return []

    return [f.stem for f in roles_dir.glob("*.md")]
