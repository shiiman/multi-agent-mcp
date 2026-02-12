"""エージェント永続化ヘルパー関数。"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.config.settings import get_mcp_dir
from src.context import AppContext
from src.tools.helpers_git import resolve_main_repo_root
from src.tools.helpers_registry import (
    ensure_session_id,
    get_project_root_from_config,
)

if TYPE_CHECKING:
    from src.models.agent import Agent

logger = logging.getLogger(__name__)

# sync_agents_from_file のキャッシュ TTL（秒）
_SYNC_CACHE_TTL_SECONDS = 5.0
# scope（session/path）ごとの最終同期時刻を保持する
_last_sync_times: dict[str, float] = {}


def _normalize_project_root_for_persistence(
    project_root: str | None,
    enable_git: bool,
) -> str | None:
    """永続化用の project_root を正規化する。"""
    if not project_root:
        return None
    resolved_root = str(Path(project_root).expanduser().resolve())
    if not enable_git:
        return resolved_root
    return resolve_main_repo_root(resolved_root)


def reset_sync_cache() -> None:
    """sync_agents_from_file のキャッシュをリセットする（テスト用）。"""
    _last_sync_times.clear()


def _get_agents_file_path(project_root: str | None, session_id: str | None = None) -> Path | None:
    """エージェント情報ファイルのパスを取得する。

    Args:
        project_root: プロジェクトルートパス
        session_id: セッションID（タスクディレクトリ名、必須）

    Returns:
        agents.json のパス、project_root または session_id が None の場合は None
    """
    if not project_root:
        return None
    if not session_id:
        logger.warning("session_id が指定されていません。agents.json のパスを取得できません。")
        return None
    # タスクディレクトリ配下に配置（session_id 必須）
    return Path(project_root) / get_mcp_dir() / session_id / "agents.json"


def _resolve_agents_file_path(
    app_ctx: AppContext,
    *,
    working_dir_fallback: str | None = None,
) -> Path | None:
    """AppContext から agents.json の実体パスを解決する。"""
    project_root = app_ctx.project_root
    if not project_root:
        project_root = get_project_root_from_config()
    if not project_root and working_dir_fallback:
        project_root = working_dir_fallback

    project_root = _normalize_project_root_for_persistence(
        project_root, app_ctx.settings.enable_git
    )
    session_id = ensure_session_id(app_ctx)
    return _get_agents_file_path(project_root, session_id)


def _get_sync_cache_key(agents_file: Path | None) -> str:
    """同期キャッシュのキーを返す（agents.json パス単位）。"""
    if agents_file is None:
        return "none"
    try:
        return str(agents_file.expanduser().resolve())
    except OSError:
        return str(agents_file.expanduser())


def _get_agents_lock_path(agents_file: Path) -> Path:
    """agents.json 用の排他ロックファイルパスを返す。"""
    return agents_file.with_name(f"{agents_file.stem}.lock")


@contextmanager
def _agents_file_lock(agents_file: Path) -> Iterator[None]:
    """agents.json の更新時に排他ロックを取得する。"""
    lock_path = _get_agents_lock_path(agents_file)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(file_path: Path, payload: dict[str, Any]) -> None:
    """JSON payload をアトミックに書き込む。"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    fd, tmp_path = tempfile.mkstemp(dir=str(file_path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(file_path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_agent_to_file(app_ctx: AppContext, agent: Agent) -> bool:
    """エージェント情報をファイルに保存する。

    worktree 内で実行されている場合でも、メインリポジトリの agents.json に保存する。
    これにより、全エージェント（Owner/Admin/Workers）が同じファイルに記録される。

    Args:
        app_ctx: アプリケーションコンテキスト
        agent: 保存するエージェント

    Returns:
        成功した場合 True
    """

    agents_file = _resolve_agents_file_path(app_ctx, working_dir_fallback=agent.working_dir)

    if not agents_file:
        logger.debug("project_root が設定されていないため、エージェント情報を保存できません")
        return False

    try:
        with _agents_file_lock(agents_file):
            # 既存のエージェント情報を読み込み
            agents_data: dict[str, Any] = {}
            if agents_file.exists():
                with open(agents_file, encoding="utf-8") as f:
                    agents_data = json.load(f)

            # エージェント情報を追加/更新
            agents_data[agent.id] = agent.model_dump(mode="json")

            # アトミック書き込み（tmpfile + os.replace）
            _atomic_write_json(agents_file, agents_data)

        logger.debug(f"エージェント {agent.id} を {agents_file} に保存しました")
        return True

    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning(f"エージェント情報の保存に失敗: {e}")
        return False


def load_agents_from_file(app_ctx: AppContext, agents_file: Path | None = None) -> dict[str, Agent]:
    """ファイルからエージェント情報を読み込む。

    Args:
        app_ctx: アプリケーションコンテキスト

    Returns:
        エージェント ID -> Agent の辞書
    """
    from src.models.agent import Agent  # 循環インポート回避

    resolved_agents_file = agents_file or _resolve_agents_file_path(app_ctx)

    if not resolved_agents_file or not resolved_agents_file.exists():
        return {}

    try:
        with open(resolved_agents_file, encoding="utf-8") as f:
            agents_data = json.load(f)

        agents: dict[str, Agent] = {}
        for agent_id, data in agents_data.items():
            try:
                # datetime 文字列を datetime オブジェクトに変換
                if isinstance(data.get("created_at"), str):
                    data["created_at"] = datetime.fromisoformat(data["created_at"])
                if isinstance(data.get("last_activity"), str):
                    data["last_activity"] = datetime.fromisoformat(data["last_activity"])
                agents[agent_id] = Agent(**data)
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(f"エージェント {agent_id} のパースに失敗: {e}")

        logger.debug(
            f"{len(agents)} 件のエージェント情報を {resolved_agents_file} から読み込みました"
        )
        return agents

    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"エージェント情報の読み込みに失敗: {e}")
        return {}


def sync_agents_from_file(app_ctx: AppContext, force: bool = False) -> int:
    """ファイルからエージェント情報をメモリに同期する。

    キャッシュTTL（5秒）以内の再呼び出しはスキップする。
    force=True で強制同期。

    Args:
        app_ctx: アプリケーションコンテキスト
        force: TTL を無視して強制同期するか

    Returns:
        追加または更新されたエージェント数
    """
    agents_file = _resolve_agents_file_path(app_ctx)
    cache_key = _get_sync_cache_key(agents_file)

    if not force:
        now = time.monotonic()
        last_sync_time = _last_sync_times.get(cache_key, 0.0)
        if (now - last_sync_time) < _SYNC_CACHE_TTL_SECONDS:
            return 0

    file_agents = load_agents_from_file(app_ctx, agents_file=agents_file)
    synced = 0

    for agent_id, agent in file_agents.items():
        current = app_ctx.agents.get(agent_id)
        if current is None:
            app_ctx.agents[agent_id] = agent
            synced += 1
            continue
        if current.model_dump(mode="json") != agent.model_dump(mode="json"):
            app_ctx.agents[agent_id] = agent
            synced += 1

    _last_sync_times[cache_key] = time.monotonic()

    if synced > 0:
        logger.info(f"ファイルから {synced} 件のエージェント情報を同期しました")

    return synced


def delete_agents_file(app_ctx: AppContext) -> bool:
    """agents.json ファイルを削除する。

    セッション終了時に呼び出され、古いエージェント情報の残存を防ぐ。

    Args:
        app_ctx: アプリケーションコンテキスト

    Returns:
        削除成功時 True、ファイル未存在や失敗時 False
    """
    project_root = app_ctx.project_root
    if not project_root:
        project_root = get_project_root_from_config()
    project_root = _normalize_project_root_for_persistence(
        project_root, app_ctx.settings.enable_git
    )
    session_id = ensure_session_id(app_ctx)
    agents_file = _get_agents_file_path(project_root, session_id)
    if agents_file and agents_file.exists():
        try:
            agents_file.unlink()
            logger.info(f"agents.json を削除しました: {agents_file}")
            return True
        except OSError as e:
            logger.warning(f"agents.json 削除に失敗: {e}")
    return False


def remove_agent_from_file(app_ctx: AppContext, agent_id: str) -> bool:
    """ファイルからエージェント情報を削除する。

    Args:
        app_ctx: アプリケーションコンテキスト
        agent_id: 削除するエージェントID

    Returns:
        成功した場合 True
    """
    agents_file = _resolve_agents_file_path(app_ctx)

    if not agents_file or not agents_file.exists():
        return False

    try:
        with _agents_file_lock(agents_file):
            with open(agents_file, encoding="utf-8") as f:
                agents_data = json.load(f)

            if agent_id in agents_data:
                del agents_data[agent_id]
                _atomic_write_json(agents_file, agents_data)

                logger.debug(f"エージェント {agent_id} を {agents_file} から削除しました")
                return True

        return False

    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"エージェント情報の削除に失敗: {e}")
        return False
