"""レジストリ・設定 JSON ヘルパー関数。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from src.config.settings import get_mcp_dir
from src.tools.helpers_git import resolve_main_repo_root

if TYPE_CHECKING:
    from src.context import AppContext

logger = logging.getLogger(__name__)


# ========== グローバルレジストリ ==========


class InvalidConfigError(ValueError):
    """config.json が破損していることを示す例外。"""


def _get_global_mcp_dir() -> Path:
    """グローバルな MCP ディレクトリを取得する。"""
    return Path.home() / ".multi-agent-mcp"


def _get_agent_registry_dir() -> Path:
    """エージェントレジストリディレクトリを取得する。"""
    return _get_global_mcp_dir() / "agents"


def save_agent_to_registry(
    agent_id: str,
    owner_id: str,
    project_root: str,
    session_id: str | None = None,
) -> None:
    """エージェント情報をグローバルレジストリに保存する。

    Args:
        agent_id: エージェントID
        owner_id: オーナーエージェントID（自分自身の場合は同じID）
        project_root: プロジェクトルートパス
        session_id: セッションID（タスクディレクトリ名）
    """
    registry_dir = _get_agent_registry_dir()
    registry_dir.mkdir(parents=True, exist_ok=True)
    agent_file = registry_dir / f"{agent_id}.json"
    data = {
        "agent_id": agent_id,
        "owner_id": owner_id,
        "project_root": project_root,
    }
    if session_id:
        data["session_id"] = session_id
    with open(agent_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.debug(
        f"エージェントをレジストリに保存: {agent_id} -> {project_root}"
        f" (session: {session_id})"
    )


def get_project_root_from_registry(agent_id: str) -> str | None:
    """レジストリからエージェントの project_root を取得する。

    Args:
        agent_id: エージェントID

    Returns:
        project_root のパス、見つからない場合は None
    """
    agent_file = _get_agent_registry_dir() / f"{agent_id}.json"
    if not agent_file.exists():
        return None
    try:
        with open(agent_file, encoding="utf-8") as f:
            data = json.load(f)
        project_root = data.get("project_root")
        if project_root:
            logger.debug(f"レジストリから project_root を取得: {agent_id} -> {project_root}")
        return project_root
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"レジストリファイルの読み込みに失敗: {agent_file}: {e}")
        return None


def get_session_id_from_registry(agent_id: str) -> str | None:
    """レジストリからエージェントの session_id を取得する。

    Args:
        agent_id: エージェントID

    Returns:
        session_id、見つからない場合は None
    """
    agent_file = _get_agent_registry_dir() / f"{agent_id}.json"
    if not agent_file.exists():
        return None
    try:
        with open(agent_file, encoding="utf-8") as f:
            data = json.load(f)
        session_id = data.get("session_id")
        if session_id:
            logger.debug(f"レジストリから session_id を取得: {agent_id} -> {session_id}")
        return session_id
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"レジストリファイルの読み込みに失敗: {agent_file}: {e}")
        return None


def remove_agent_from_registry(agent_id: str) -> bool:
    """レジストリからエージェント情報を削除する。

    Args:
        agent_id: エージェントID

    Returns:
        削除成功時 True
    """
    agent_file = _get_agent_registry_dir() / f"{agent_id}.json"
    if agent_file.exists():
        agent_file.unlink()
        logger.debug(f"エージェントをレジストリから削除: {agent_id}")
        return True
    return False


def remove_agents_by_owner(owner_id: str) -> int:
    """オーナーに紐づく全エージェントをレジストリから削除する。

    Args:
        owner_id: オーナーエージェントID

    Returns:
        削除したエージェント数
    """
    registry_dir = _get_agent_registry_dir()
    if not registry_dir.exists():
        return 0

    removed_count = 0
    for agent_file in registry_dir.glob("*.json"):
        try:
            with open(agent_file, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("owner_id") == owner_id:
                agent_file.unlink()
                logger.debug(f"エージェントをレジストリから削除: {agent_file.stem}")
                removed_count += 1
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"レジストリファイルの処理に失敗: {agent_file}: {e}")

    return removed_count


def get_project_root_from_config(
    caller_agent_id: str | None = None,
) -> str | None:
    """project_root をグローバルレジストリから取得する。

    Args:
        caller_agent_id: 呼び出し元エージェントID（オプション）

    Returns:
        project_root のパス、見つからない場合は None
    """
    if caller_agent_id:
        return get_project_root_from_registry(caller_agent_id)
    return None


# ========== config.json ヘルパー ==========


def _get_from_config(
    key: str,
    working_dir: str | None = None,
    strict: bool = False,
) -> object | None:
    """config.json から指定キーの値を取得する。

    working_dir → worktree のメインリポジトリの順で探索する。

    Args:
        key: 取得するキー名
        working_dir: 探索開始ディレクトリ（オプション）
        strict: True の場合、config.json 破損時に例外を送出する

    Returns:
        値が見つかった場合はその値、見つからない場合は None
    """
    search_dirs: list[Path] = []

    if working_dir:
        resolved_working_dir = Path(working_dir).expanduser().resolve()
        search_dirs.append(resolved_working_dir)
        try:
            main_repo = resolve_main_repo_root(working_dir)
            resolved_main_repo = Path(main_repo).expanduser().resolve()
            if resolved_main_repo != resolved_working_dir:
                search_dirs.append(resolved_main_repo)
        except ValueError:
            # 非gitディレクトリの場合は working_dir のみ探索する
            pass

    for base_dir in search_dirs:
        config_file = base_dir / get_mcp_dir() / "config.json"
        if config_file.exists():
            try:
                with open(config_file, encoding="utf-8") as f:
                    config = json.load(f)
                value = config.get(key)
                if value is not None:
                    logger.debug(f"config.json から {key} を取得: {value}")
                    return value
            except (OSError, json.JSONDecodeError) as e:
                if strict:
                    raise InvalidConfigError(
                        f"invalid_config: {config_file} の読み込みに失敗しました: {e}"
                    ) from e
                logger.warning(f"config.json の読み込みに失敗: {e}")

    return None


def get_mcp_tool_prefix_from_config(
    working_dir: str | None = None,
    strict: bool = False,
) -> str:
    """config.json から mcp_tool_prefix を取得する。

    Args:
        working_dir: 探索開始ディレクトリ（オプション）
        strict: True の場合、config.json 破損時に例外を送出する

    Returns:
        MCP ツールの完全名プレフィックス
    """
    value = _get_from_config("mcp_tool_prefix", working_dir, strict=strict)
    if isinstance(value, str) and value:
        return value
    return "mcp__multi-agent-mcp__"


def get_session_id_from_config(
    working_dir: str | None = None,
    strict: bool = False,
) -> str | None:
    """config.json から session_id を取得する。

    Args:
        working_dir: 探索開始ディレクトリ（オプション）
        strict: True の場合、config.json 破損時に例外を送出する

    Returns:
        セッションID、見つからない場合は None
    """
    value = _get_from_config("session_id", working_dir, strict=strict)
    if isinstance(value, str) and value:
        return value
    return None


def get_enable_git_from_config(
    working_dir: str | None = None,
    strict: bool = False,
) -> bool | None:
    """config.json から enable_git を取得する。

    Args:
        working_dir: 探索開始ディレクトリ（オプション）
        strict: True の場合、config.json 破損時に例外を送出する

    Returns:
        enable_git の真偽値、未設定時は None
    """
    value = _get_from_config("enable_git", working_dir, strict=strict)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return None


def ensure_session_id(app_ctx: AppContext) -> str | None:
    """セッションID を確保する。

    app_ctx.session_id が設定されていなければ config.json から読み取る。

    Args:
        app_ctx: アプリケーションコンテキスト

    Returns:
        セッションID、見つからない場合は None
    """
    if app_ctx.session_id:
        return app_ctx.session_id

    # config.json から取得
    working_dir = app_ctx.project_root or get_project_root_from_config()
    session_id = get_session_id_from_config(working_dir)

    if session_id:
        app_ctx.session_id = session_id
        logger.debug(f"config.json から session_id を設定: {session_id}")

    return session_id
