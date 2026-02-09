"""配布設定の回帰を防ぐテスト。"""

from pathlib import Path

import tomli


class TestPyprojectPackagingConfig:
    """pyproject.toml の配布設定を検証する。"""

    def test_wheel_force_includes_templates(self) -> None:
        """wheel に templates ディレクトリが同梱されることを確認する。"""
        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        data = tomli.loads(pyproject_path.read_text(encoding="utf-8"))

        wheel_target = data["tool"]["hatch"]["build"]["targets"]["wheel"]
        force_include = wheel_target.get("force-include", {})

        assert force_include.get("templates") == "templates"
