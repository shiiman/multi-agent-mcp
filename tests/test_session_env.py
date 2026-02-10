"""session_env.py のユニットテスト。"""

import json
from enum import Enum
from unittest.mock import patch

import pytest

from src.tools.session_env import (
    _format_env_value,
    _setup_mcp_directories,
    generate_env_template,
    set_env_value,
)


class TestFormatEnvValue:
    """_format_env_value のテスト。"""

    def test_bool_true(self):
        """True を 'true' に変換する。"""
        assert _format_env_value(True) == "true"

    def test_bool_false(self):
        """False を 'false' に変換する。"""
        assert _format_env_value(False) == "false"

    def test_enum_value(self):
        """Enum の value を文字列として返す。"""

        class Color(Enum):
            RED = "red"

        assert _format_env_value(Color.RED) == "red"

    def test_list_value(self):
        """リストを JSON 文字列に変換する。"""
        result = _format_env_value([".png", ".jpg"])
        assert result == '[".png", ".jpg"]'

    def test_integer_value(self):
        """整数を文字列に変換する。"""
        assert _format_env_value(42) == "42"

    def test_string_value(self):
        """文字列はそのまま返す。"""
        assert _format_env_value("hello") == "hello"

    def test_float_value(self):
        """浮動小数点を文字列に変換する。"""
        assert _format_env_value(3.14) == "3.14"


class TestGenerateEnvTemplate:
    """generate_env_template のテスト。"""

    def test_generates_template_with_settings(self, settings):
        """Settings を渡すとテンプレートが生成される。"""
        result = generate_env_template(settings=settings)
        assert "MCP_MCP_DIR=" in result
        assert "MCP_ENABLE_GIT=" in result
        assert "MCP_MAX_WORKERS=" in result
        assert "MCP_ENABLE_WORKTREE=" in result

    def test_template_contains_all_sections(self, settings):
        """テンプレートが全てのセクションを含む。"""
        result = generate_env_template(settings=settings)
        assert "基本設定" in result
        assert "エージェント設定" in result
        assert "Worktree 設定" in result
        assert "tmux 設定" in result
        assert "モデルプロファイル" in result
        assert "コスト設定" in result
        assert "ヘルスチェック設定" in result
        assert "メモリ設定" in result

    def test_template_values_match_settings(self, settings):
        """テンプレートの値が Settings と一致する。"""
        result = generate_env_template(settings=settings)
        assert f"MCP_MAX_WORKERS={settings.max_workers}" in result

    def test_template_contains_send_cooldown_default(self, settings):
        """テンプレートに send cooldown の既定値が含まれることをテスト。"""
        result = generate_env_template(settings=settings)
        assert "MCP_SEND_COOLDOWN_SECONDS=2.0" in result


class TestSetupMcpDirectories:
    """_setup_mcp_directories のテスト。"""

    def test_creates_directories_and_files(self, temp_dir, settings):
        """初回実行で memory, screenshot ディレクトリと .env, config.json を作成する。"""
        with patch("src.tools.session_env.resolve_main_repo_root", return_value=str(temp_dir)):
            result = _setup_mcp_directories(str(temp_dir), settings=settings, session_id="test-001")

        assert "memory" in result["created_dirs"]
        assert "screenshot" in result["created_dirs"]
        assert result["env_created"] is True
        assert result["config_created"] is True
        assert result["project_root"] == str(temp_dir)

        # ファイルが実際に存在するか確認
        mcp_dir = temp_dir / settings.mcp_dir
        assert (mcp_dir / "memory").is_dir()
        assert (mcp_dir / "screenshot").is_dir()
        assert (mcp_dir / ".env").is_file()
        assert (mcp_dir / "config.json").is_file()

    def test_does_not_overwrite_existing_env(self, temp_dir, settings):
        """既存の .env ファイルを上書きしない。"""
        mcp_dir = temp_dir / settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        env_file = mcp_dir / ".env"
        env_file.write_text("EXISTING=true")

        with patch("src.tools.session_env.resolve_main_repo_root", return_value=str(temp_dir)):
            result = _setup_mcp_directories(str(temp_dir), settings=settings)

        assert result["env_created"] is False
        assert env_file.read_text() == "EXISTING=true"

    def test_updates_existing_config_json(self, temp_dir, settings):
        """既存の config.json の mcp_tool_prefix を更新する。"""
        mcp_dir = temp_dir / settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        config_file = mcp_dir / "config.json"
        config_file.write_text(json.dumps({"mcp_tool_prefix": "old_prefix__"}))

        with patch("src.tools.session_env.resolve_main_repo_root", return_value=str(temp_dir)):
            result = _setup_mcp_directories(
                str(temp_dir), settings=settings, session_id="test-002"
            )

        assert result["config_created"] is False
        with open(config_file) as f:
            config = json.load(f)
        assert config["mcp_tool_prefix"] == "mcp__multi-agent-mcp__"
        assert config["session_id"] == "test-002"

    def test_persists_enable_git_override_to_config(self, temp_dir, settings):
        """enable_git_override の値が config.json に保存される。"""
        with patch("src.tools.session_env.resolve_main_repo_root", return_value=str(temp_dir)):
            _setup_mcp_directories(
                str(temp_dir),
                settings=settings,
                session_id="test-003",
                enable_git_override=False,
            )

        config_file = temp_dir / settings.mcp_dir / "config.json"
        with open(config_file, encoding="utf-8") as f:
            config = json.load(f)
        assert config["enable_git"] is False

    def test_keeps_existing_enable_git_when_override_is_none(self, temp_dir, settings):
        """enable_git_override=None のとき既存 config の値を維持する。"""
        mcp_dir = temp_dir / settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        config_file = mcp_dir / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcp_tool_prefix": "mcp__multi-agent-mcp__",
                    "enable_git": False,
                }
            ),
            encoding="utf-8",
        )

        with patch("src.tools.session_env.resolve_main_repo_root", return_value=str(temp_dir)):
            _setup_mcp_directories(
                str(temp_dir),
                settings=settings,
                session_id="test-004",
                enable_git_override=None,
            )

        with open(config_file, encoding="utf-8") as f:
            config = json.load(f)
        assert config["enable_git"] is False

    def test_removes_legacy_project_root_from_config(self, temp_dir, settings):
        """config.json に project_root があれば削除する。"""
        mcp_dir = temp_dir / settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        config_file = mcp_dir / "config.json"
        config_file.write_text(
            json.dumps({
                "mcp_tool_prefix": "mcp__multi-agent-mcp__",
                "project_root": "/old/path",
            })
        )

        with patch("src.tools.session_env.resolve_main_repo_root", return_value=str(temp_dir)):
            _setup_mcp_directories(str(temp_dir), settings=settings)

        with open(config_file) as f:
            config = json.load(f)
        assert "project_root" not in config

    def test_second_run_does_not_recreate_dirs(self, temp_dir, settings):
        """2回目の実行ではディレクトリを再作成しない。"""
        with patch("src.tools.session_env.resolve_main_repo_root", return_value=str(temp_dir)):
            _setup_mcp_directories(str(temp_dir), settings=settings)
            result = _setup_mcp_directories(str(temp_dir), settings=settings)

        assert result["created_dirs"] == []
        assert result["env_created"] is False

    def test_fallback_to_working_dir_when_not_git(self, temp_dir, settings):
        """git リポジトリでない場合は working_dir にフォールバックする。"""
        with patch(
            "src.tools.session_env.resolve_main_repo_root",
            side_effect=ValueError("not a git repo"),
        ):
            result = _setup_mcp_directories(str(temp_dir), settings=settings)

        assert result["project_root"] == str(temp_dir)

    def test_raises_on_invalid_existing_config(self, temp_dir, settings):
        """既存 config.json が破損している場合は invalid_config エラーを送出する。"""
        mcp_dir = temp_dir / settings.mcp_dir
        mcp_dir.mkdir(parents=True, exist_ok=True)
        (mcp_dir / "config.json").write_text("{invalid", encoding="utf-8")

        with (
            patch("src.tools.session_env.resolve_main_repo_root", return_value=str(temp_dir)),
            pytest.raises(ValueError) as exc_info,
        ):
            _setup_mcp_directories(str(temp_dir), settings=settings)
        assert "invalid_config" in str(exc_info.value)


class TestSetEnvValue:
    """set_env_value のテスト。"""

    def test_updates_existing_key(self, temp_dir):
        """既存キーを上書きできる。"""
        env_file = temp_dir / ".multi-agent-mcp" / ".env"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text("MCP_MODEL_PROFILE_ACTIVE=standard\n", encoding="utf-8")

        set_env_value(env_file, "MCP_MODEL_PROFILE_ACTIVE", "performance")

        assert env_file.read_text(encoding="utf-8") == "MCP_MODEL_PROFILE_ACTIVE=performance\n"

    def test_appends_new_key(self, temp_dir):
        """存在しないキーは末尾に追加する。"""
        env_file = temp_dir / ".multi-agent-mcp" / ".env"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text("MCP_ENABLE_GIT=true\n", encoding="utf-8")

        set_env_value(env_file, "MCP_MODEL_PROFILE_ACTIVE", "performance")

        assert env_file.read_text(encoding="utf-8").endswith(
            "MCP_MODEL_PROFILE_ACTIVE=performance\n"
        )
