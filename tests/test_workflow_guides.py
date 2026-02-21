"""workflow_guides のテスト。"""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.config.workflow_guides import (
    get_role_guide,
    get_role_template_path,
    get_role_template_path_for_workspace,
    list_role_guides,
)


class TestWorkflowGuides:
    """ロールガイド解決のテスト。"""

    def test_get_role_template_path_uses_no_git_variant(self):
        """enable_git=false の場合は *_no_git テンプレートを返す。"""
        path = get_role_template_path("admin", enable_git=False)
        assert path.name == "admin_no_git.md"

    def test_get_role_guide_uses_no_git_variant(self):
        """enable_git=false の場合は no_git ガイド内容を返す。"""
        guide = get_role_guide("worker", enable_git=False)
        assert guide is not None
        assert "No Git" in guide.content

    def test_list_role_guides_hides_variant_suffix(self):
        """list_role_guides は *_no_git サフィックスを公開しない。"""
        roles = list_role_guides()
        assert "owner" in roles
        assert "admin" in roles
        assert "worker" in roles
        assert "owner_no_git" not in roles

    def test_get_role_template_path_for_workspace_copies_outside_template(self, tmp_path: Path):
        """ワークスペース外テンプレートは runtime 配下にミラーされる。"""
        source_dir = tmp_path / "source_templates"
        workspace_dir = tmp_path / "workspace"
        source_dir.mkdir()
        workspace_dir.mkdir()

        source_template = source_dir / "worker_no_git.md"
        source_template.write_text("# Worker No Git\n", encoding="utf-8")

        with patch(
            "src.config.workflow_guides.get_role_template_path",
            return_value=source_template,
        ):
            resolved = get_role_template_path_for_workspace(
                "worker",
                workspace_dir,
                enable_git=False,
            )

        expected = workspace_dir / ".multi-agent-mcp" / "runtime" / "roles" / "worker_no_git.md"
        assert resolved == expected
        assert resolved.read_text(encoding="utf-8") == "# Worker No Git\n"

    def test_get_role_template_path_for_workspace_keeps_inside_template(self, tmp_path: Path):
        """ワークスペース配下テンプレートはそのまま返す。"""
        workspace_dir = tmp_path / "workspace"
        template_path = workspace_dir / "templates" / "roles" / "admin.md"
        template_path.parent.mkdir(parents=True)
        template_path.write_text("# Admin\n", encoding="utf-8")

        with patch(
            "src.config.workflow_guides.get_role_template_path",
            return_value=template_path,
        ):
            resolved = get_role_template_path_for_workspace("admin", workspace_dir, enable_git=True)

        assert resolved == template_path

    def test_get_role_guide_rejects_invalid_role(self):
        """許可値以外の role は取得不可であることをテスト。"""
        guide = get_role_guide("../owner", enable_git=True)
        assert guide is None

    def test_get_role_template_path_rejects_invalid_role(self):
        """許可値以外の role でパス解決すると例外になることをテスト。"""
        with (
            patch("src.config.workflow_guides._get_templates_dir", return_value=Path(".")),
            pytest.raises(ValueError, match="無効なロール"),
        ):
            get_role_template_path("../owner", enable_git=True)
