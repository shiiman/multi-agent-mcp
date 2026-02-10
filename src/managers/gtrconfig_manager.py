""".gtrconfig管理マネージャー。

プロジェクトの.gtrconfigファイルの検出・生成・管理を行う。
"""

import logging
from pathlib import Path

import tomli
import tomli_w

logger = logging.getLogger(__name__)


class GtrconfigManager:
    """Gtrconfigの検出・生成・管理を行うマネージャー。"""

    GTRCONFIG_FILENAME = ".gtrconfig"

    def __init__(self, project_root: str) -> None:
        """GtrconfigManagerを初期化する。

        Args:
            project_root: プロジェクトのルートディレクトリ
        """
        self.project_root = Path(project_root)

    def exists(self) -> bool:
        """Gtrconfigが存在するか確認する。

        Returns:
            存在する場合True
        """
        return (self.project_root / self.GTRCONFIG_FILENAME).exists()

    def read(self) -> dict | None:
        """Gtrconfigを読み込む。

        Returns:
            設定の辞書、存在しない場合None
        """
        config_path = self.project_root / self.GTRCONFIG_FILENAME
        if not config_path.exists():
            return None

        try:
            with open(config_path, "rb") as f:
                return tomli.load(f)
        except (OSError, tomli.TOMLDecodeError) as e:
            logger.error(f".gtrconfig読み込みエラー: {e}")
            return None

    def write(self, config: dict) -> bool:
        """Gtrconfigを書き込む。

        Args:
            config: 設定の辞書

        Returns:
            成功した場合True
        """
        config_path = self.project_root / self.GTRCONFIG_FILENAME
        try:
            with open(config_path, "wb") as f:
                tomli_w.dump(config, f)
            return True
        except OSError as e:
            logger.error(f".gtrconfig書き込みエラー: {e}")
            return False

    def _detect_package_manager(self) -> list[str]:
        """パッケージマネージャーを検出してフックコマンドを返す。

        Returns:
            postCreateフックのコマンドリスト
        """
        hooks = []

        # Node.js プロジェクト
        if (self.project_root / "package.json").exists():
            if (self.project_root / "pnpm-lock.yaml").exists():
                hooks.append("pnpm install")
            elif (self.project_root / "yarn.lock").exists():
                hooks.append("yarn install")
            elif (self.project_root / "bun.lockb").exists():
                hooks.append("bun install")
            else:
                hooks.append("npm install")

        # Python プロジェクト
        if (self.project_root / "pyproject.toml").exists():
            if (self.project_root / "uv.lock").exists():
                hooks.append("uv sync")
            elif (self.project_root / "poetry.lock").exists():
                hooks.append("poetry install")
            elif (self.project_root / "Pipfile.lock").exists():
                hooks.append("pipenv install")
            else:
                hooks.append("pip install -e .")
        elif (self.project_root / "requirements.txt").exists():
            hooks.append("pip install -r requirements.txt")

        # Go プロジェクト
        if (self.project_root / "go.mod").exists():
            hooks.append("go mod download")

        # Ruby プロジェクト
        if (self.project_root / "Gemfile").exists():
            hooks.append("bundle install")

        # Rust プロジェクト
        if (self.project_root / "Cargo.toml").exists():
            hooks.append("cargo fetch")

        # PHP プロジェクト
        if (self.project_root / "composer.json").exists():
            hooks.append("composer install")

        return hooks

    def _detect_env_files(self) -> tuple[list[str], list[str]]:
        """環境ファイルを検出してinclude/excludeパターンを返す。

        Returns:
            (includeパターン, excludeパターン) のタプル
        """
        include = []
        exclude = []

        # .env.example / .env.sample をinclude
        for pattern in ["**/.env.example", "**/.env.sample", "**/.env.template"]:
            for env_file in self.project_root.glob(pattern):
                rel_path = env_file.relative_to(self.project_root)
                include.append(str(rel_path))

        # 実際の.envファイルはexclude
        exclude.extend(
            [
                "**/.env",
                "**/.env.local",
                "**/.env.*.local",
            ]
        )

        return include, exclude

    def analyze_project(self) -> dict:
        """プロジェクト構造を解析して推奨設定を生成する。

        Returns:
            推奨設定の辞書
        """
        config: dict = {
            "copy": {"include": [], "exclude": []},
            "hooks": {"postCreate": []},
        }

        # パッケージマネージャー検出
        config["hooks"]["postCreate"] = self._detect_package_manager()

        # 環境ファイル検出
        env_include, env_exclude = self._detect_env_files()
        config["copy"]["include"].extend(env_include)
        config["copy"]["exclude"].extend(env_exclude)

        # 標準の除外パターン
        config["copy"]["exclude"].extend(
            [
                "**/node_modules/**",
                "**/__pycache__/**",
                "**/.git/**",
                "**/target/**",
                "**/vendor/**",
                "**/.venv/**",
                "**/venv/**",
            ]
        )

        # ドキュメントファイル
        if list(self.project_root.glob("*.md")):
            config["copy"]["include"].append("*.md")

        # AI CLI の設定ファイルがあれば include に追加
        for cli_file in ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "CODEX.md", ".cursorrules"]:
            if (self.project_root / cli_file).exists() and cli_file not in config["copy"][
                "include"
            ]:
                config["copy"]["include"].append(cli_file)

        # 重複を除去
        config["copy"]["include"] = list(set(config["copy"]["include"]))
        config["copy"]["exclude"] = list(set(config["copy"]["exclude"]))

        return config

    def generate(self, overwrite: bool = False) -> tuple[bool, dict | str]:
        """プロジェクト解析に基づいてGtrconfigを自動生成する。

        Args:
            overwrite: 既存ファイルを上書きするか

        Returns:
            (成功したか, 設定またはエラーメッセージ) のタプル
        """
        if self.exists() and not overwrite:
            return False, f"{self.GTRCONFIG_FILENAME} は既に存在します"

        config = self.analyze_project()
        if self.write(config):
            logger.info(f".gtrconfig を生成しました: {self.project_root}")
            return True, config
        else:
            return False, ".gtrconfig の書き込みに失敗しました"

    def update_section(
        self,
        section: str,
        key: str,
        value: str | list[str],
    ) -> tuple[bool, str]:
        """Gtrconfigの特定セクションを更新する。

        Args:
            section: セクション名（copy/hooks/defaults）
            key: キー名
            value: 値

        Returns:
            (成功したか, メッセージ) のタプル
        """
        config = self.read()
        if config is None:
            config = {}

        if section not in config:
            config[section] = {}

        config[section][key] = value

        if self.write(config):
            return True, f".gtrconfig の [{section}].{key} を更新しました"
        else:
            return False, ".gtrconfig の更新に失敗しました"

    def get_status(self) -> dict:
        """Gtrconfigの状態を取得する。

        Returns:
            状態情報の辞書
        """
        config = self.read()
        return {
            "exists": self.exists(),
            "config": config,
            "project_root": str(self.project_root),
        }
