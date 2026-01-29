"""GtrconfigManagerのテスト。"""

import tempfile
from pathlib import Path

from src.managers.gtrconfig_manager import GtrconfigManager


class TestGtrconfigManager:
    """GtrconfigManagerのテスト。"""

    def test_exists_false(self):
        """存在しないディレクトリでFalseを返すことをテスト。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = GtrconfigManager(tmpdir)
            assert manager.exists() is False

    def test_exists_true(self):
        """.gtrconfigがある場合Trueを返すことをテスト。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            gtrconfig_path = Path(tmpdir) / ".gtrconfig"
            gtrconfig_path.write_text("[core]\ncommand = test\n")
            manager = GtrconfigManager(tmpdir)
            assert manager.exists() is True

    def test_read_existing_config(self):
        """既存の.gtrconfigを読み込めることをテスト。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            gtrconfig_path = Path(tmpdir) / ".gtrconfig"
            gtrconfig_path.write_text(
                '[core]\ncommand = "pytest"\n\n[env]\nNODE_ENV = "test"\n'
            )
            manager = GtrconfigManager(tmpdir)
            config = manager.read()
            assert config is not None
            assert "core" in config
            assert config["core"]["command"] == "pytest"

    def test_read_nonexistent_config(self):
        """存在しない.gtrconfigでNoneを返すことをテスト。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = GtrconfigManager(tmpdir)
            config = manager.read()
            assert config is None

    def test_analyze_project_empty(self):
        """空のプロジェクトを分析できることをテスト。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = GtrconfigManager(tmpdir)
            analysis = manager.analyze_project()
            assert "copy" in analysis
            assert "hooks" in analysis
            assert "include" in analysis["copy"]
            assert "exclude" in analysis["copy"]

    def test_analyze_project_with_package_json(self):
        """package.jsonがあるプロジェクトを分析できることをテスト。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            package_json = Path(tmpdir) / "package.json"
            package_json.write_text('{"name": "test", "scripts": {"test": "jest"}}')
            manager = GtrconfigManager(tmpdir)
            analysis = manager.analyze_project()
            # postCreateにnpm installが含まれている
            assert "npm install" in analysis["hooks"]["postCreate"]

    def test_analyze_project_with_pyproject(self):
        """pyproject.tomlがあるプロジェクトを分析できることをテスト。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject = Path(tmpdir) / "pyproject.toml"
            pyproject.write_text('[project]\nname = "test"\n')
            manager = GtrconfigManager(tmpdir)
            analysis = manager.analyze_project()
            # Python関連のフックが含まれている
            assert any("pip" in cmd or "uv" in cmd or "poetry" in cmd
                       for cmd in analysis["hooks"]["postCreate"])

    def test_generate_config(self):
        """設定を生成できることをテスト。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = GtrconfigManager(tmpdir)
            success, result = manager.generate()
            assert success is True
            assert isinstance(result, dict)
            assert "copy" in result

    def test_generate_existing_no_overwrite(self):
        """既存の.gtrconfigがある場合に上書きしないことをテスト。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            gtrconfig_path = Path(tmpdir) / ".gtrconfig"
            gtrconfig_path.write_text("[existing]\nkey = value\n")
            manager = GtrconfigManager(tmpdir)
            success, result = manager.generate(overwrite=False)
            assert success is False
            assert "既に存在" in str(result)

    def test_generate_with_overwrite(self):
        """既存の.gtrconfigを上書きできることをテスト。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            gtrconfig_path = Path(tmpdir) / ".gtrconfig"
            gtrconfig_path.write_text("[existing]\nkey = value\n")
            manager = GtrconfigManager(tmpdir)
            success, result = manager.generate(overwrite=True)
            assert success is True
            assert isinstance(result, dict)

    def test_write_config(self):
        """設定を書き込めることをテスト。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = GtrconfigManager(tmpdir)
            config = {"core": {"command": "test"}}
            success = manager.write(config)
            assert success is True
            # 読み込んで確認
            loaded = manager.read()
            assert loaded["core"]["command"] == "test"

    def test_get_status(self):
        """ステータスを取得できることをテスト。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = GtrconfigManager(tmpdir)
            status = manager.get_status()
            assert "exists" in status
            assert "config" in status
            assert "project_root" in status
