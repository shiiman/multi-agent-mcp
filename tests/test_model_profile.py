"""モデルプロファイルのテスト。"""

import pytest

from src.config.settings import ModelDefaults, ModelProfile, Settings


class TestModelProfile:
    """ModelProfile のテスト。"""

    def test_model_profile_enum_values(self):
        """ModelProfile が正しい値を持つことをテスト。"""
        assert ModelProfile.STANDARD.value == "standard"
        assert ModelProfile.PERFORMANCE.value == "performance"

    def test_model_profile_from_string(self):
        """文字列から ModelProfile を生成できることをテスト。"""
        assert ModelProfile("standard") == ModelProfile.STANDARD
        assert ModelProfile("performance") == ModelProfile.PERFORMANCE

    def test_model_profile_invalid_string(self):
        """無効な文字列で ValueError が発生することをテスト。"""
        with pytest.raises(ValueError):
            ModelProfile("invalid")


class TestSettingsModelProfile:
    """Settings のモデルプロファイル関連テスト。"""

    def test_default_profile_is_standard(self, settings):
        """デフォルトプロファイルが standard であることをテスト。"""
        assert settings.model_profile_active == ModelProfile.STANDARD

    def test_standard_profile_settings_defaults(self, settings):
        """standard プロファイルのデフォルト値をテスト。"""
        assert settings.model_profile_standard_admin_model == ModelDefaults.OPUS
        assert settings.model_profile_standard_worker_model == ModelDefaults.SONNET
        assert settings.model_profile_standard_max_workers == 6
        assert settings.model_profile_standard_thinking_multiplier == 1.0

    def test_performance_profile_settings_defaults(self, settings):
        """performance プロファイルのデフォルト値をテスト。"""
        assert settings.model_profile_performance_admin_model == ModelDefaults.OPUS
        assert settings.model_profile_performance_worker_model == ModelDefaults.OPUS
        assert settings.model_profile_performance_max_workers == 16
        assert settings.model_profile_performance_thinking_multiplier == 2.0

    def test_switch_profile(self, settings):
        """プロファイルを切り替えられることをテスト。"""
        settings.model_profile_active = ModelProfile.PERFORMANCE
        assert settings.model_profile_active == ModelProfile.PERFORMANCE

        settings.model_profile_active = ModelProfile.STANDARD
        assert settings.model_profile_active == ModelProfile.STANDARD
