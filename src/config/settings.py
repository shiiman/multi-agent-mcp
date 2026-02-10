"""設定管理モジュール。"""

import json
import os
from enum import Enum
from pathlib import Path
from typing import ClassVar

from pydantic import ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings


def resolve_project_env_file(project_root: str | os.PathLike[str] | None) -> str | None:
    """指定した project_root から .env ファイルを解決する。

    Args:
        project_root: プロジェクトルートパス

    Returns:
        .env ファイルのパス（存在する場合）、または None
    """
    if not project_root:
        return None

    env_file = Path(project_root) / ".multi-agent-mcp" / ".env"
    if env_file.exists():
        return str(env_file)
    return None


def get_project_env_file() -> str | None:
    """プロジェクト別 .env ファイルのパスを取得。

    MCP_PROJECT_ROOT 環境変数が設定されている場合、
    {project_root}/.multi-agent-mcp/.env を返す。

    Returns:
        .env ファイルのパス（存在する場合）、または None
    """
    return resolve_project_env_file(os.getenv("MCP_PROJECT_ROOT"))


class AICli(str, Enum):
    """サポートするAI CLIツール。"""

    CLAUDE = "claude"
    """Claude Code CLI"""

    CODEX = "codex"
    """OpenAI Codex CLI"""

    GEMINI = "gemini"
    """Google Gemini CLI"""


class TerminalApp(str, Enum):
    """サポートするターミナルアプリ。"""

    AUTO = "auto"
    """自動検出（ghostty → iTerm2 → Terminal.app）"""

    GHOSTTY = "ghostty"
    """Ghostty"""

    ITERM2 = "iterm2"
    """iTerm2"""

    TERMINAL = "terminal"
    """macOS Terminal.app"""


class ModelProfile(str, Enum):
    """モデルプロファイル。

    タスクの重要度に応じてモデルやリソースを切り替える。
    """

    STANDARD = "standard"
    """標準プロファイル - コスト重視、Sonnet"""

    PERFORMANCE = "performance"
    """高性能プロファイル - 性能重視、Opus"""


class ReasoningEffort(str, Enum):
    """推論強度設定。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    NONE = "none"


class WorkerCliMode(str, Enum):
    """Worker CLI 設定モード。"""

    UNIFORM = "uniform"
    PER_WORKER = "per-worker"


class WorkerModelMode(str, Enum):
    """Worker モデル設定モード。"""

    UNIFORM = "uniform"
    PER_WORKER = "per-worker"


# モデル定数（重複を避けるため一元管理）
class ModelDefaults:
    """デフォルトモデル名の定数。"""

    # Claude CLI
    OPUS = "opus"
    """Claude Opus モデル（Claude CLI が最新バージョンに自動解決）"""

    SONNET = "sonnet"
    """Claude Sonnet モデル（Claude CLI が最新バージョンに自動解決）"""

    # Codex CLI
    CODEX_DEFAULT = "gpt-5.3-codex"
    """Codex デフォルトモデル"""

    # Gemini CLI
    GEMINI_DEFAULT = "gemini-3-pro"
    """Gemini デフォルトモデル"""

    GEMINI_LIGHT = "gemini-3-flash"
    """Gemini 軽量モデル"""

    # CLI 別デフォルトモデルマッピング
    CLI_DEFAULTS: ClassVar[dict[str, dict[str, str]]] = {
        "claude": {"admin": OPUS, "worker": SONNET},
        "codex": {"admin": CODEX_DEFAULT, "worker": CODEX_DEFAULT},
        "gemini": {"admin": GEMINI_DEFAULT, "worker": GEMINI_LIGHT},
    }

    # Claude 固有のモデル名（非 Claude CLI で使用された場合、CLI デフォルトに置換）
    CLAUDE_ALIASES: ClassVar[set[str]] = {"opus", "sonnet", "haiku", "default"}


def resolve_model_for_cli(
    cli: str,
    model: str | None,
    role: str = "worker",
    cli_defaults: dict[str, dict[str, str]] | None = None,
) -> str | None:
    """CLI に応じてモデル名を解決する。

    CLI とモデル名の組み合わせを検証し、不一致の場合は
    その CLI のデフォルトモデルへフォールバックする。

    Args:
        cli: AI CLI 名（"claude", "codex", "gemini"）
        model: 設定されたモデル名
        role: ロール（"admin" or "worker"）
        cli_defaults: CLI 別デフォルトモデルマッピング（Settings から構築）。
            None の場合は ModelDefaults.CLI_DEFAULTS を使用。

    Returns:
        解決されたモデル名（None の場合は None を返す）
    """
    defaults_map = cli_defaults if cli_defaults is not None else ModelDefaults.CLI_DEFAULTS
    defaults = defaults_map.get(cli, {})

    if model is None:
        return defaults.get(role)

    def _is_model_compatible(target_cli: str, model_name: str) -> bool:
        value = model_name.strip().lower()
        if target_cli == "claude":
            return value in ModelDefaults.CLAUDE_ALIASES or value.startswith("claude")
        if target_cli == "codex":
            return "codex" in value or value.startswith("gpt-")
        if target_cli == "gemini":
            return value.startswith("gemini")
        return True

    if not _is_model_compatible(cli, model):
        return defaults.get(role, model)

    return model


# AI CLI のデフォルトコマンドマッピング
DEFAULT_AI_CLI_COMMANDS: dict[str, str] = {
    AICli.CLAUDE: "claude",
    AICli.CODEX: "codex",
    AICli.GEMINI: "gemini",
}


class Settings(BaseSettings):
    """MCP サーバーの設定。

    環境変数で上書き可能。プレフィックスは MCP_。
    例: MCP_MAX_WORKERS=10

    優先順位:
    1. 環境変数（最優先）
    2. プロジェクト別 .env ファイル（{project}/.multi-agent-mcp/.env）
    3. デフォルト値
    """

    model_config = ConfigDict(
        env_prefix="MCP_",
        env_file=get_project_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MCP ディレクトリ設定
    mcp_dir: str = ".multi-agent-mcp"
    """MCP 設定ディレクトリ名（デフォルト: .multi-agent-mcp）"""

    # Worktree 設定
    enable_git: bool = True
    """git 前提機能を有効にするか（デフォルト: True）。
    False の場合、git/worktree/gtr 前提の機能は無効化される。"""

    enable_worktree: bool = True
    """git worktree を使用するか（デフォルト: True）。
    False にすると Worker は全て同一ディレクトリで作業する。"""

    # エージェント設定
    max_workers: int = 6
    """Workerエージェントの最大数（デフォルト: メインウィンドウに収まる6）"""

    # tmux設定
    window_name_main: str = "main"
    """メインウィンドウ名（Admin + Worker 1-6）"""

    window_name_worker_prefix: str = "workers-"
    """追加 Worker ウィンドウ名のプレフィックス（workers-2, workers-3, ...）"""

    # tmux グリッド設定（追加ウィンドウ: Worker 7以降）
    extra_worker_rows: int = 2
    """追加ウィンドウの行数"""

    extra_worker_cols: int = 5
    """追加ウィンドウの列数"""

    workers_per_extra_window: int = 10
    """追加ウィンドウのWorker数（extra_worker_rows × extra_worker_cols）"""

    # コスト設定
    cost_warning_threshold_usd: float = 10.0
    """コスト警告の閾値（USD）"""

    # ヘルスチェック設定
    healthcheck_interval_seconds: int = 60
    """ヘルスチェックの実行間隔（秒）。"""

    healthcheck_stall_timeout_seconds: int = 600
    """無応答判定の閾値（秒）。
    last_activity 超過かつ tmux 出力が変化しない場合に異常と判定する。"""

    healthcheck_in_progress_no_ipc_timeout_seconds: int = 120
    """in_progress タスクの無通信判定閾値（秒）。
    進捗更新（IPC）や task 更新が一定時間ない場合に異常候補として扱う。"""

    healthcheck_max_recovery_attempts: int = 3
    """同一 worker/task に対する復旧試行の上限回数。"""

    healthcheck_idle_stop_consecutive: int = 3
    """実作業なし状態を連続検出した際に daemon を停止する閾値。"""

    codex_enter_retry_max: int = 3
    """Codex ペイン送信時に Enter 再送する最大回数。"""

    codex_enter_retry_interval_ms: int = 250
    """Codex ペイン送信時の Enter 再送間隔（ミリ秒）。"""

    send_cooldown_seconds: float = 2.0
    """tmux への連続送信時に挟む最小待機秒数（全CLI共通）。"""

    # ターミナル設定
    default_terminal: TerminalApp = Field(
        default=TerminalApp.AUTO, description="デフォルトのターミナルアプリ"
    )
    """デフォルトで使用するターミナルアプリ"""

    # モデルプロファイル設定
    model_profile_active: ModelProfile = Field(
        default=ModelProfile.STANDARD,
        description="現在のモデルプロファイル",
    )
    """現在アクティブなモデルプロファイル"""

    # standard プロファイル設定
    model_profile_standard_cli: AICli = Field(
        default=AICli.CLAUDE,
        description="standard プロファイルで使用する AI CLI",
    )
    model_profile_standard_admin_model: str = Field(
        default=ModelDefaults.OPUS,
        description="standard プロファイルで Admin が使用するモデル",
    )
    model_profile_standard_worker_model: str = Field(
        default=ModelDefaults.SONNET,
        description="standard プロファイルで Worker が使用するモデル",
    )
    model_profile_standard_max_workers: int = Field(
        default=6,
        description="standard プロファイルの Worker 数上限",
    )
    model_profile_standard_admin_thinking_tokens: int = Field(
        default=4000,
        description="standard プロファイルの Admin 思考トークン数",
    )
    model_profile_standard_worker_thinking_tokens: int = Field(
        default=4000,
        description="standard プロファイルの Worker 思考トークン数",
    )
    model_profile_standard_admin_reasoning_effort: ReasoningEffort = Field(
        default=ReasoningEffort.MEDIUM,
        description="standard プロファイルの Admin reasoning effort",
    )
    model_profile_standard_worker_reasoning_effort: ReasoningEffort = Field(
        default=ReasoningEffort.MEDIUM,
        description="standard プロファイルの Worker reasoning effort",
    )

    # performance プロファイル設定
    model_profile_performance_cli: AICli = Field(
        default=AICli.CLAUDE,
        description="performance プロファイルで使用する AI CLI",
    )
    model_profile_performance_admin_model: str = Field(
        default=ModelDefaults.OPUS,
        description="performance プロファイルで Admin が使用するモデル",
    )
    model_profile_performance_worker_model: str = Field(
        default=ModelDefaults.OPUS,
        description="performance プロファイルで Worker が使用するモデル",
    )
    model_profile_performance_max_workers: int = Field(
        default=16,
        description="performance プロファイルの Worker 数上限",
    )
    model_profile_performance_admin_thinking_tokens: int = Field(
        default=30000,
        description="performance プロファイルの Admin 思考トークン数",
    )
    model_profile_performance_worker_thinking_tokens: int = Field(
        default=4000,
        description="performance プロファイルの Worker 思考トークン数",
    )
    model_profile_performance_admin_reasoning_effort: ReasoningEffort = Field(
        default=ReasoningEffort.HIGH,
        description="performance プロファイルの Admin reasoning effort",
    )
    model_profile_performance_worker_reasoning_effort: ReasoningEffort = Field(
        default=ReasoningEffort.HIGH,
        description="performance プロファイルの Worker reasoning effort",
    )

    cli_default_claude_admin_model: str = Field(
        default=ModelDefaults.OPUS,
        description="Claude CLI の Admin デフォルトモデル",
    )
    cli_default_claude_worker_model: str = Field(
        default=ModelDefaults.SONNET,
        description="Claude CLI の Worker デフォルトモデル",
    )

    # CLI 別デフォルトモデル設定（Claude 固有名が非 Claude CLI で使われた場合のフォールバック）
    cli_default_codex_admin_model: str = Field(
        default=ModelDefaults.CODEX_DEFAULT,
        description="Codex CLI の Admin デフォルトモデル",
    )
    """Codex CLI で Admin に使用するデフォルトモデル"""

    cli_default_codex_worker_model: str = Field(
        default=ModelDefaults.CODEX_DEFAULT,
        description="Codex CLI の Worker デフォルトモデル",
    )
    """Codex CLI で Worker に使用するデフォルトモデル"""

    cli_default_gemini_admin_model: str = Field(
        default=ModelDefaults.GEMINI_DEFAULT,
        description="Gemini CLI の Admin デフォルトモデル",
    )
    """Gemini CLI で Admin に使用するデフォルトモデル"""

    cli_default_gemini_worker_model: str = Field(
        default=ModelDefaults.GEMINI_LIGHT,
        description="Gemini CLI の Worker デフォルトモデル",
    )
    """Gemini CLI で Worker に使用するデフォルトモデル"""

    worker_cli_mode: WorkerCliMode = Field(
        default=WorkerCliMode.UNIFORM,
        description="Worker CLI 設定モード（uniform/per-worker）",
    )
    worker_cli_1: str | None = Field(default=None, description="Worker 1 の CLI")
    worker_cli_2: str | None = Field(default=None, description="Worker 2 の CLI")
    worker_cli_3: str | None = Field(default=None, description="Worker 3 の CLI")
    worker_cli_4: str | None = Field(default=None, description="Worker 4 の CLI")
    worker_cli_5: str | None = Field(default=None, description="Worker 5 の CLI")
    worker_cli_6: str | None = Field(default=None, description="Worker 6 の CLI")
    worker_cli_7: str | None = Field(default=None, description="Worker 7 の CLI")
    worker_cli_8: str | None = Field(default=None, description="Worker 8 の CLI")
    worker_cli_9: str | None = Field(default=None, description="Worker 9 の CLI")
    worker_cli_10: str | None = Field(default=None, description="Worker 10 の CLI")
    worker_cli_11: str | None = Field(default=None, description="Worker 11 の CLI")
    worker_cli_12: str | None = Field(default=None, description="Worker 12 の CLI")
    worker_cli_13: str | None = Field(default=None, description="Worker 13 の CLI")
    worker_cli_14: str | None = Field(default=None, description="Worker 14 の CLI")
    worker_cli_15: str | None = Field(default=None, description="Worker 15 の CLI")
    worker_cli_16: str | None = Field(default=None, description="Worker 16 の CLI")

    worker_model_mode: WorkerModelMode = Field(
        default=WorkerModelMode.UNIFORM,
        description="Worker モデル設定モード（uniform/per-worker）",
    )
    worker_model_uniform: str | None = Field(
        default=None,
        description="uniform モード時の Worker モデル（未設定なら profile の worker_model）",
    )
    worker_model_1: str | None = Field(default=None, description="Worker 1 のモデル")
    worker_model_2: str | None = Field(default=None, description="Worker 2 のモデル")
    worker_model_3: str | None = Field(default=None, description="Worker 3 のモデル")
    worker_model_4: str | None = Field(default=None, description="Worker 4 のモデル")
    worker_model_5: str | None = Field(default=None, description="Worker 5 のモデル")
    worker_model_6: str | None = Field(default=None, description="Worker 6 のモデル")
    worker_model_7: str | None = Field(default=None, description="Worker 7 のモデル")
    worker_model_8: str | None = Field(default=None, description="Worker 8 のモデル")
    worker_model_9: str | None = Field(default=None, description="Worker 9 のモデル")
    worker_model_10: str | None = Field(default=None, description="Worker 10 のモデル")
    worker_model_11: str | None = Field(default=None, description="Worker 11 のモデル")
    worker_model_12: str | None = Field(default=None, description="Worker 12 のモデル")
    worker_model_13: str | None = Field(default=None, description="Worker 13 のモデル")
    worker_model_14: str | None = Field(default=None, description="Worker 14 のモデル")
    worker_model_15: str | None = Field(default=None, description="Worker 15 のモデル")
    worker_model_16: str | None = Field(default=None, description="Worker 16 のモデル")

    # スクリーンショット設定
    screenshot_extensions: list[str] = Field(
        default=[".png", ".jpg", ".jpeg", ".gif", ".webp"],
        description="スクリーンショットとして認識する拡張子",
    )
    """対象とする画像拡張子"""

    # 品質チェック・イテレーション設定
    quality_check_max_iterations: int = Field(
        default=5,
        description="品質チェックの最大イテレーション回数",
    )
    """品質チェックの最大イテレーション回数（デフォルト: 5）"""

    quality_check_same_issue_limit: int = Field(
        default=3,
        description="同一問題の繰り返し上限（超えたら Owner に相談）",
    )
    """同一問題の繰り返し上限（デフォルト: 3）"""

    quality_gate_strict: bool = Field(
        default=True,
        description="品質ゲートを厳格に適用するか（false で緩和）",
    )
    """品質ゲートの厳格モード（デフォルト: true）"""

    # メモリ設定
    memory_max_entries: int = Field(
        default=1000,
        description="メモリの最大エントリ数",
    )
    """メモリの最大エントリ数（デフォルト: 1000）"""

    memory_ttl_days: int = Field(
        default=90,
        description="メモリエントリの保持期間（日）",
    )
    """メモリエントリの保持期間（デフォルト: 90日）"""

    # コスト推定設定
    estimated_tokens_per_call: int = Field(
        default=2000,
        description="1回のAPI呼び出しあたりの推定トークン数",
    )
    """1回のAPI呼び出しあたりの推定トークン数（デフォルト: 2000）"""

    model_cost_table_json: str = Field(
        default='{"claude:opus":0.03,"claude:sonnet":0.015,'
        '"codex:gpt-5.3-codex":0.01,"gemini:gemini-3-pro":0.005,'
        '"gemini:gemini-3-flash":0.0025}',
        description="モデル別 1K トークン単価テーブル（JSON）",
    )
    model_cost_default_per_1k: float = Field(
        default=0.01,
        description="未定義モデル向け汎用単価（USD/1K tokens）",
    )

    @field_validator("mcp_dir")
    @classmethod
    def validate_mcp_dir(cls, value: str) -> str:
        """MCP ディレクトリ名を安全な相対単一ディレクトリ名に制限する。"""
        candidate = value.strip()
        base_error = (
            "MCP_MCP_DIR は相対の単一ディレクトリ名を指定してください（例: .multi-agent-mcp）"
        )

        if not candidate:
            raise ValueError(f"{base_error}: 空文字は許可されません")
        if os.path.isabs(candidate):
            raise ValueError(f"{base_error}: 絶対パスは許可されません")
        if "/" in candidate or "\\" in candidate:
            raise ValueError(f"{base_error}: 区切り文字を含むパスは許可されません")
        if ".." in candidate:
            raise ValueError(f"{base_error}: '..' を含む値は許可されません")
        if candidate in {".", ".."}:
            raise ValueError(f"{base_error}: '.' や '..' は許可されません")
        if ":" in candidate:
            raise ValueError(f"{base_error}: ':' を含む値は許可されません")

        return candidate

    def get_cli_default_models(self) -> dict[str, dict[str, str]]:
        """CLI別のデフォルトモデルマッピングを返す。"""
        return {
            "claude": {
                "admin": self.cli_default_claude_admin_model,
                "worker": self.cli_default_claude_worker_model,
            },
            "codex": {
                "admin": self.cli_default_codex_admin_model,
                "worker": self.cli_default_codex_worker_model,
            },
            "gemini": {
                "admin": self.cli_default_gemini_admin_model,
                "worker": self.cli_default_gemini_worker_model,
            },
        }

    def get_model_cost_table(self) -> dict[str, float]:
        """モデル別コストテーブル（JSON）を辞書へ変換する。"""
        try:
            loaded = json.loads(self.model_cost_table_json)
        except json.JSONDecodeError:
            return {}
        return {str(k): float(v) for k, v in loaded.items()}

    def get_active_profile_cli(self) -> AICli:
        """現在アクティブなモデルプロファイルの CLI を返す。"""
        if self.model_profile_active == ModelProfile.STANDARD:
            return self.model_profile_standard_cli
        return self.model_profile_performance_cli

    def get_worker_cli(self, worker_index: int) -> AICli:
        """Worker index(1..16) に対する CLI を取得する。"""

        def _to_cli(value: str | AICli | None) -> AICli | None:
            if value is None:
                return None
            if isinstance(value, AICli):
                return value
            return AICli(str(value).strip())

        profile_cli = self.get_active_profile_cli()
        if self.worker_cli_mode == WorkerCliMode.UNIFORM:
            return profile_cli
        if not (1 <= worker_index <= 16):
            raise ValueError(f"worker_index は 1..16 で指定してください: {worker_index}")
        per_worker = getattr(self, f"worker_cli_{worker_index}")
        parsed = _to_cli(per_worker)
        return parsed or profile_cli

    def get_worker_model(self, worker_index: int, profile_worker_model: str) -> str:
        """Worker index(1..16) に対するモデルを取得する。"""
        if self.worker_model_mode == WorkerModelMode.UNIFORM:
            return self.worker_model_uniform or profile_worker_model
        if not (1 <= worker_index <= 16):
            raise ValueError(f"worker_index は 1..16 で指定してください: {worker_index}")
        per_worker = getattr(self, f"worker_model_{worker_index}")
        return per_worker or profile_worker_model

    def is_worktree_enabled(self) -> bool:
        """worktree の実効有効状態を返す。"""
        return bool(self.enable_git and self.enable_worktree)


def get_mcp_dir() -> str:
    """MCP ディレクトリ名を取得する。

    実行時点の環境変数と .env を常に反映する。

    Returns:
        MCP ディレクトリ名（デフォルト: .multi-agent-mcp）
    """
    return Settings().mcp_dir


def load_settings_for_project(project_root: str | os.PathLike[str] | None) -> Settings:
    """指定 project_root の .env を優先して Settings を生成する。

    優先順位:
    1. プロセス環境変数 MCP_*
    2. {project_root}/.multi-agent-mcp/.env
    3. デフォルト値

    Args:
        project_root: プロジェクトルートパス

    Returns:
        読み込み済み Settings インスタンス
    """
    env_file = resolve_project_env_file(project_root)
    if env_file:
        return Settings(_env_file=env_file)
    # model_config 側の env_file を使わず、環境変数 + デフォルトのみで構築
    return Settings(_env_file=None)


def load_effective_settings_for_project(
    project_root: str | os.PathLike[str] | None,
    strict_config: bool = False,
) -> Settings:
    """指定 project_root の有効設定を読み込む。

    .env の設定に加えて、config.json の runtime override（enable_git）を適用する。

    モデルプロファイル関連（model_profile_active など）の正準保存先は
    `.multi-agent-mcp/.env` とし、config.json からは読み込まない。

    Args:
        project_root: プロジェクトルートパス
        strict_config: True の場合、config.json 破損時に例外を送出する

    Returns:
        runtime override 適用済み Settings
    """
    settings = load_settings_for_project(project_root)
    if not project_root:
        return settings

    config_file = Path(project_root) / settings.mcp_dir / "config.json"
    if not config_file.exists():
        return settings

    try:
        with open(config_file, encoding="utf-8") as f:
            config = json.load(f)
        # config.json の runtime override は enable_git のみを許可する。
        # モデルプロファイル関連キーは意図的に無視し、.env を正準とする。
        enable_git = config.get("enable_git")
        if isinstance(enable_git, bool):
            settings.enable_git = enable_git
    except (OSError, ValueError, json.JSONDecodeError) as e:
        if strict_config:
            raise ValueError(f"invalid_config: {config_file} の読み込みに失敗しました: {e}") from e
        # 設定ファイル破損時は .env 設定を優先して継続
        pass

    return settings
