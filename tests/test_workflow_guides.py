"""workflow_guides のテスト。"""

from src.config.workflow_guides import (
    get_role_guide,
    get_role_template_path,
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
