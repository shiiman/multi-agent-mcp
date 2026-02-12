"""テンプレートローダーモジュール。

テンプレートファイルを読み込み、変数を置換する。
"""

from pathlib import Path
from typing import Any


class TemplateLoader:
    """テンプレートを読み込むクラス。"""

    def __init__(self, base_dir: Path | None = None) -> None:
        """TemplateLoader を初期化する。

        Args:
            base_dir: テンプレートのベースディレクトリ（デフォルト: templates/）
        """
        if base_dir is None:
            # src/config/template_loader.py からの相対パス
            base_dir = Path(__file__).parent.parent.parent / "templates"
        self._base_dir = base_dir
        self._cache: dict[str, str] = {}

    def load(self, category: str, name: str) -> str:
        """テンプレートを読み込む。

        Args:
            category: カテゴリ（roles, tasks, scripts/bash, scripts/applescript）
            name: テンプレート名（拡張子なし）

        Returns:
            テンプレート内容

        Raises:
            FileNotFoundError: テンプレートが見つからない場合
        """
        cache_key = f"{category}/{name}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        ext = self._get_extension(category)
        path = (self._base_dir / category / f"{name}{ext}").resolve()

        # パストラバーサル防止: base_dir 配下であることを検証
        try:
            path.relative_to(self._base_dir.resolve())
        except ValueError as e:
            raise FileNotFoundError(
                f"テンプレートディレクトリ外へのアクセスは許可されていません: {category}/{name}"
            ) from e

        if not path.exists():
            raise FileNotFoundError(f"テンプレートが見つかりません: {path}")

        content = path.read_text(encoding="utf-8")
        self._cache[cache_key] = content
        return content

    def render(self, category: str, name: str, **kwargs: Any) -> str:
        """テンプレートを読み込んで変数を置換する。

        Args:
            category: カテゴリ
            name: テンプレート名
            **kwargs: 置換する変数

        Returns:
            置換後の文字列
        """
        template = self.load(category, name)
        return template.format(**kwargs)

    def _get_extension(self, category: str) -> str:
        """カテゴリから拡張子を推定する。"""
        if category.startswith("scripts/bash"):
            return ".sh"
        elif category.startswith("scripts/applescript"):
            return ".scpt"
        return ".md"

    def clear_cache(self) -> None:
        """キャッシュをクリアする。"""
        self._cache.clear()


# グローバルインスタンス
_loader: TemplateLoader | None = None


def get_template_loader() -> TemplateLoader:
    """TemplateLoader のシングルトンを取得する。"""
    global _loader
    if _loader is None:
        _loader = TemplateLoader()
    return _loader
