"""エージェント永続化ヘルパー関数。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
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
_SYNC_CACHE_TTL_SECONDS = 2.0
# 最終同期時刻を保持するグローバル変数
_last_sync_time: float = 0.0


def reset_sync_cache() -> None:
    """sync_agents_from_file のキャッシュをリセットする（テスト用）。"""
    global _last_sync_time
    _last_sync_time = 0.0


def _get_agents_file_path(
    project_root: str | None, session_id: str | None = None
) -> Path | None:
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

    # project_root を決定（複数のソースから取得を試みる）
    project_root = app_ctx.project_root

    # config.json から取得（init_tmux_workspace で設定される）
    if not project_root:
        project_root = get_project_root_from_config()

    # エージェントの working_dir から取得
    if not project_root and agent.working_dir:
        project_root = agent.working_dir

    # worktree の場合はメインリポジトリのパスを使用
    if project_root:
        project_root = resolve_main_repo_root(project_root)

    # session_id を確保（config.json から読み取り）
    session_id = ensure_session_id(app_ctx)
    agents_file = _get_agents_file_path(project_root, session_id)

    if not agents_file:
        logger.debug("project_root が設定されていないため、エージェント情報を保存できません")
        return False

    try:
        # 既存のエージェント情報を読み込み
        agents_data: dict[str, Any] = {}
        if agents_file.exists():
            with open(agents_file, encoding="utf-8") as f:
                agents_data = json.load(f)

        # エージェント情報を追加/更新
        agents_data[agent.id] = agent.model_dump(mode="json")

        # ディレクトリ作成
        agents_file.parent.mkdir(parents=True, exist_ok=True)

        # アトミック書き込み（tmpfile + os.replace）
        content = json.dumps(agents_data, ensure_ascii=False, indent=2, default=str)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(agents_file.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, str(agents_file))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.debug(f"エージェント {agent.id} を {agents_file} に保存しました")
        return True

    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning(f"エージェント情報の保存に失敗: {e}")
        return False


def load_agents_from_file(app_ctx: AppContext) -> dict[str, Agent]:
    """ファイルからエージェント情報を読み込む。

    Args:
        app_ctx: アプリケーションコンテキスト

    Returns:
        エージェント ID -> Agent の辞書
    """
    from src.models.agent import Agent  # 循環インポート回避

    # project_root を決定（app_ctx → config.json の順）
    project_root = app_ctx.project_root
    if not project_root:
        project_root = get_project_root_from_config()

    # worktree の場合はメインリポジトリのパスを使用
    if project_root:
        project_root = resolve_main_repo_root(project_root)

    # session_id を確保（config.json から読み取り）
    session_id = ensure_session_id(app_ctx)
    agents_file = _get_agents_file_path(project_root, session_id)

    if not agents_file or not agents_file.exists():
        return {}

    try:
        with open(agents_file, encoding="utf-8") as f:
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

        logger.debug(f"{len(agents)} 件のエージェント情報を {agents_file} から読み込みました")
        return agents

    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"エージェント情報の読み込みに失敗: {e}")
        return {}


def sync_agents_from_file(app_ctx: AppContext, force: bool = False) -> int:
    """ファイルからエージェント情報をメモリに同期する。

    キャッシュTTL（2秒）以内の再呼び出しはスキップする。
    force=True で強制同期。

    Args:
        app_ctx: アプリケーションコンテキスト
        force: TTL を無視して強制同期するか

    Returns:
        追加されたエージェント数
    """
    global _last_sync_time

    if not force:
        now = time.monotonic()
        if (now - _last_sync_time) < _SYNC_CACHE_TTL_SECONDS:
            return 0

    file_agents = load_agents_from_file(app_ctx)
    added = 0

    for agent_id, agent in file_agents.items():
        if agent_id not in app_ctx.agents:
            app_ctx.agents[agent_id] = agent
            added += 1

    _last_sync_time = time.monotonic()

    if added > 0:
        logger.info(f"ファイルから {added} 件のエージェント情報を同期しました")

    return added


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
    if project_root:
        project_root = resolve_main_repo_root(project_root)
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
    # project_root を決定（複数のソースから取得を試みる）
    project_root = app_ctx.project_root

    # config.json から取得（init_tmux_workspace で設定される）
    if not project_root:
        project_root = get_project_root_from_config()

    # worktree の場合はメインリポジトリのパスを使用
    if project_root:
        project_root = resolve_main_repo_root(project_root)

    # session_id を確保（config.json から読み取り）
    session_id = ensure_session_id(app_ctx)
    agents_file = _get_agents_file_path(project_root, session_id)

    if not agents_file or not agents_file.exists():
        return False

    try:
        with open(agents_file, encoding="utf-8") as f:
            agents_data = json.load(f)

        if agent_id in agents_data:
            del agents_data[agent_id]

            content = json.dumps(
                agents_data, ensure_ascii=False, indent=2, default=str
            )
            fd, tmp_path = tempfile.mkstemp(
                dir=str(agents_file.parent), suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(tmp_path, str(agents_file))
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            logger.debug(f"エージェント {agent_id} を {agents_file} から削除しました")
            return True

        return False

    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"エージェント情報の削除に失敗: {e}")
        return False
