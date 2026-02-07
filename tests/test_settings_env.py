"""プロジェクト別 .env ファイル読み込みのテスト。"""



import src.config.settings as settings_module
from src.config.settings import (
    AICli,
    ModelDefaults,
    WorkerCliMode,
    get_mcp_dir,
    get_project_env_file,
    load_settings_for_project,
)
from src.tools.session import generate_env_template


class TestGetMcpDir:
    """get_mcp_dir 関数のテスト。"""

    def test_returns_default_mcp_dir(self, monkeypatch):
        """デフォルト値 .multi-agent-mcp を返すことをテスト。"""
        # シングルトンキャッシュをリセット
        monkeypatch.setattr(settings_module, "_settings_instance", None)
        monkeypatch.delenv("MCP_MCP_DIR", raising=False)

        result = get_mcp_dir()
        assert result == ".multi-agent-mcp"

    def test_returns_custom_mcp_dir_from_env(self, monkeypatch):
        """環境変数でカスタム値を設定できることをテスト。"""
        # シングルトンキャッシュをリセット
        monkeypatch.setattr(settings_module, "_settings_instance", None)
        monkeypatch.setenv("MCP_MCP_DIR", ".custom-mcp-dir")

        result = get_mcp_dir()
        assert result == ".custom-mcp-dir"

    def test_caches_settings_instance(self, monkeypatch):
        """Settings インスタンスがキャッシュされることをテスト。"""
        # シングルトンキャッシュをリセット
        monkeypatch.setattr(settings_module, "_settings_instance", None)
        monkeypatch.delenv("MCP_MCP_DIR", raising=False)

        # 最初の呼び出し
        get_mcp_dir()

        # キャッシュが設定されていることを確認
        assert settings_module._settings_instance is not None

        # 2回目の呼び出しで同じインスタンスを使用
        cached_instance = settings_module._settings_instance
        get_mcp_dir()
        assert settings_module._settings_instance is cached_instance


class TestGetProjectEnvFile:
    """get_project_env_file 関数のテスト。"""

    def test_returns_none_when_no_project_root(self, temp_dir, monkeypatch):
        """MCP_PROJECT_ROOT 未設定時に None を返すことをテスト。"""
        monkeypatch.delenv("MCP_PROJECT_ROOT", raising=False)
        result = get_project_env_file()
        assert result is None

    def test_returns_none_when_env_file_not_exists(self, temp_dir, monkeypatch):
        """.env ファイルが存在しない場合に None を返すことをテスト。"""
        monkeypatch.setenv("MCP_PROJECT_ROOT", str(temp_dir))

        # .multi-agent-mcp ディレクトリは作成するが .env は作成しない
        mcp_dir = temp_dir / ".multi-agent-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)

        result = get_project_env_file()
        assert result is None

    def test_returns_path_when_env_file_exists(self, temp_dir, monkeypatch):
        """.env ファイルが存在する場合にパスを返すことをテスト。"""
        monkeypatch.setenv("MCP_PROJECT_ROOT", str(temp_dir))

        # .env ファイルを作成
        mcp_dir = temp_dir / ".multi-agent-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)
        env_file = mcp_dir / ".env"
        env_file.write_text("MCP_MAX_WORKERS=10")

        result = get_project_env_file()
        assert result == str(env_file)


class TestGenerateEnvTemplate:
    """generate_env_template 関数のテスト。"""

    def test_template_contains_max_workers(self):
        """テンプレートに MCP_MAX_WORKERS が含まれることをテスト。"""
        template = generate_env_template()
        assert "MCP_MAX_WORKERS" in template

    def test_template_contains_model_profile_settings(self):
        """テンプレートにモデルプロファイル設定が含まれることをテスト。"""
        template = generate_env_template()
        assert "MCP_MODEL_PROFILE_ACTIVE" in template
        assert "MCP_MODEL_PROFILE_STANDARD_CLI" in template
        assert "MCP_MODEL_PROFILE_STANDARD_ADMIN_MODEL" in template
        assert "MCP_MODEL_PROFILE_STANDARD_WORKER_MODEL" in template
        assert "MCP_MODEL_PROFILE_STANDARD_MAX_WORKERS" in template
        assert "MCP_MODEL_PROFILE_PERFORMANCE_CLI" in template
        assert "MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_MODEL" in template
        assert "MCP_MODEL_PROFILE_PERFORMANCE_WORKER_MODEL" in template
        assert "MCP_MODEL_PROFILE_PERFORMANCE_MAX_WORKERS" in template

    def test_template_contains_cli_default_models(self):
        """テンプレートに CLI 別デフォルトモデル設定が含まれることをテスト。"""
        template = generate_env_template()
        assert "MCP_CLI_DEFAULT_CLAUDE_ADMIN_MODEL" in template
        assert "MCP_CLI_DEFAULT_CLAUDE_WORKER_MODEL" in template
        assert "MCP_CLI_DEFAULT_CODEX_ADMIN_MODEL" in template
        assert "MCP_CLI_DEFAULT_CODEX_WORKER_MODEL" in template
        assert "MCP_CLI_DEFAULT_GEMINI_ADMIN_MODEL" in template
        assert "MCP_CLI_DEFAULT_GEMINI_WORKER_MODEL" in template
        assert ModelDefaults.OPUS in template
        assert ModelDefaults.SONNET in template
        assert ModelDefaults.CODEX_DEFAULT in template
        assert ModelDefaults.GEMINI_DEFAULT in template
        assert ModelDefaults.GEMINI_LIGHT in template

    def test_template_contains_thinking_tokens(self):
        """テンプレートにプロファイル別 Thinking Tokens 設定が含まれることをテスト。"""
        template = generate_env_template()
        assert "MCP_MODEL_PROFILE_STANDARD_ADMIN_THINKING_TOKENS" in template
        assert "MCP_MODEL_PROFILE_STANDARD_WORKER_THINKING_TOKENS" in template
        assert "MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_THINKING_TOKENS" in template
        assert "MCP_MODEL_PROFILE_PERFORMANCE_WORKER_THINKING_TOKENS" in template
        assert "MCP_MODEL_PROFILE_STANDARD_ADMIN_REASONING_EFFORT" in template
        assert "MCP_MODEL_PROFILE_STANDARD_WORKER_REASONING_EFFORT" in template
        assert "MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_REASONING_EFFORT" in template
        assert "MCP_MODEL_PROFILE_PERFORMANCE_WORKER_REASONING_EFFORT" in template

    def test_template_contains_cost_settings(self):
        """テンプレートにコスト設定が含まれることをテスト。"""
        template = generate_env_template()
        assert "MCP_COST_WARNING_THRESHOLD_USD" in template
        assert "MCP_MODEL_COST_TABLE_JSON" in template
        assert "MCP_MODEL_COST_DEFAULT_PER_1K" in template
        assert "MCP_COST_PER_1K_TOKENS_" not in template

    def test_template_contains_worker_cli_mode(self):
        """テンプレートに Worker CLI モード設定が含まれることをテスト。"""
        template = generate_env_template()
        assert "MCP_WORKER_CLI_MODE" in template
        assert "MCP_WORKER_CLI_1" in template
        assert "MCP_WORKER_CLI_16" in template
        assert "MCP_WORKER_CLI_1=claude" in template

    def test_template_contains_worker_model_mode(self):
        """テンプレートに Worker モデル設定が含まれることをテスト。"""
        template = generate_env_template()
        assert "MCP_WORKER_MODEL_1" in template
        assert "MCP_WORKER_MODEL_16" in template

    def test_template_contains_healthcheck_settings(self):
        """テンプレートにヘルスチェック設定が含まれることをテスト。"""
        template = generate_env_template()
        assert "MCP_HEALTHCHECK_INTERVAL_SECONDS" in template
        assert "MCP_HEALTHCHECK_STALL_TIMEOUT_SECONDS" in template
        assert "MCP_HEALTHCHECK_IN_PROGRESS_NO_IPC_TIMEOUT_SECONDS" in template
        assert "MCP_HEALTHCHECK_MAX_RECOVERY_ATTEMPTS" in template
        assert "MCP_HEALTHCHECK_IDLE_STOP_CONSECUTIVE" in template

    def test_template_has_comments(self):
        """テンプレートにコメントが含まれることをテスト。"""
        template = generate_env_template()
        assert "# Multi-Agent MCP" in template
        assert "# ========" in template  # セクション区切り

    def test_template_default_values(self):
        """テンプレートのデフォルト値が正しいことをテスト。"""
        template = generate_env_template()

        # デフォルト値の確認
        assert "MCP_MAX_WORKERS=6" in template
        assert "MCP_MODEL_PROFILE_ACTIVE=standard" in template
        assert ModelDefaults.SONNET in template
        assert ModelDefaults.OPUS in template


class TestLoadSettingsForProject:
    """load_settings_for_project 関数のテスト。"""

    def test_loads_env_file_without_mcp_project_root(self, temp_dir, monkeypatch):
        """MCP_PROJECT_ROOT 未設定でも project_root 指定で .env を読み込める。"""
        monkeypatch.delenv("MCP_PROJECT_ROOT", raising=False)
        monkeypatch.delenv("MCP_MODEL_PROFILE_STANDARD_CLI", raising=False)
        monkeypatch.delenv("MCP_MODEL_PROFILE_STANDARD_ADMIN_MODEL", raising=False)

        mcp_dir = temp_dir / ".multi-agent-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)
        env_file = mcp_dir / ".env"
        env_file.write_text(
            "MCP_MODEL_PROFILE_STANDARD_CLI=codex\n"
            "MCP_MODEL_PROFILE_STANDARD_ADMIN_MODEL=gpt-5.3-codex\n",
            encoding="utf-8",
        )

        settings = load_settings_for_project(str(temp_dir))

        assert settings.model_profile_standard_cli == AICli.CODEX
        assert settings.model_profile_standard_admin_model == "gpt-5.3-codex"

    def test_falls_back_to_default_when_env_file_not_exists(self, temp_dir, monkeypatch):
        """.env がない場合はデフォルト設定を使用する。"""
        monkeypatch.delenv("MCP_PROJECT_ROOT", raising=False)
        monkeypatch.delenv("MCP_MODEL_PROFILE_STANDARD_CLI", raising=False)
        monkeypatch.delenv("MCP_MODEL_PROFILE_STANDARD_ADMIN_MODEL", raising=False)

        settings = load_settings_for_project(str(temp_dir))

        assert settings.model_profile_standard_cli == AICli.CLAUDE
        assert settings.model_profile_standard_admin_model == ModelDefaults.OPUS


class TestWorkerCliAndModelResolution:
    """Worker CLI / モデル解決ロジックのテスト。"""

    def test_get_worker_cli_uniform(self):
        settings = load_settings_for_project(None)
        settings.worker_cli_mode = WorkerCliMode.UNIFORM
        settings.worker_cli_uniform = AICli.CODEX
        assert settings.get_worker_cli(1) == AICli.CODEX
        assert settings.get_worker_cli(16) == AICli.CODEX

    def test_get_worker_cli_per_worker(self):
        settings = load_settings_for_project(None)
        settings.worker_cli_mode = WorkerCliMode.PER_WORKER
        settings.worker_cli_uniform = AICli.CLAUDE
        settings.worker_cli_2 = "gemini"
        assert settings.get_worker_cli(1) == AICli.CLAUDE
        assert settings.get_worker_cli(2) == AICli.GEMINI

    def test_get_worker_model_depends_on_worker_cli_mode(self):
        settings = load_settings_for_project(None)
        settings.worker_cli_mode = WorkerCliMode.UNIFORM
        settings.worker_model_1 = "gpt-5.3-codex"
        assert settings.get_worker_model(1, "opus") == "opus"

        settings.worker_cli_mode = WorkerCliMode.PER_WORKER
        settings.worker_model_3 = "gemini-3-pro"
        assert settings.get_worker_model(3, "opus") == "gemini-3-pro"
        assert settings.get_worker_model(4, "opus") == "opus"


class TestSetupMcpDirectories:
    """_setup_mcp_directories 関数のテスト。"""

    def test_creates_memory_directory(self, temp_dir):
        """memory ディレクトリが作成されることをテスト。"""
        from src.tools.session import _setup_mcp_directories

        result = _setup_mcp_directories(str(temp_dir))

        memory_dir = temp_dir / ".multi-agent-mcp" / "memory"
        assert memory_dir.exists()
        assert "memory" in result["created_dirs"]

    def test_creates_screenshot_directory(self, temp_dir):
        """screenshot ディレクトリが作成されることをテスト。"""
        from src.tools.session import _setup_mcp_directories

        result = _setup_mcp_directories(str(temp_dir))

        screenshot_dir = temp_dir / ".multi-agent-mcp" / "screenshot"
        assert screenshot_dir.exists()
        assert "screenshot" in result["created_dirs"]

    def test_creates_env_file(self, temp_dir):
        """.env ファイルが作成されることをテスト。"""
        from src.tools.session import _setup_mcp_directories

        result = _setup_mcp_directories(str(temp_dir))

        env_file = temp_dir / ".multi-agent-mcp" / ".env"
        assert env_file.exists()
        assert result["env_created"] is True
        assert result["env_path"] == str(env_file)

    def test_does_not_overwrite_existing_env_file(self, temp_dir):
        """既存の .env ファイルを上書きしないことをテスト。"""
        from src.tools.session import _setup_mcp_directories

        # 事前に .env ファイルを作成
        mcp_dir = temp_dir / ".multi-agent-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)
        env_file = mcp_dir / ".env"
        env_file.write_text("CUSTOM_SETTING=value")

        result = _setup_mcp_directories(str(temp_dir))

        # 上書きされていないことを確認
        assert env_file.read_text() == "CUSTOM_SETTING=value"
        assert result["env_created"] is False

    def test_does_not_recreate_existing_directories(self, temp_dir):
        """既存のディレクトリを再作成しないことをテスト。"""
        from src.tools.session import _setup_mcp_directories

        # 事前にディレクトリを作成
        mcp_dir = temp_dir / ".multi-agent-mcp"
        (mcp_dir / "memory").mkdir(parents=True, exist_ok=True)
        (mcp_dir / "screenshot").mkdir(parents=True, exist_ok=True)
        (mcp_dir / ".env").write_text("test")

        result = _setup_mcp_directories(str(temp_dir))

        assert result["created_dirs"] == []
        assert result["env_created"] is False
