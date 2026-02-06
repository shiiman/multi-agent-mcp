"""エージェント永続化ヘルパー関数。"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config.settings import get_mcp_dir
from src.context import AppContext
from src.tools.helpers_git import resolve_main_repo_root
from src.tools.helpers_registry import (
    ensure_session_id,
    get_project_root_from_config,
)

logger = logging.getLogger(__name__)


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


def save_agent_to_file(app_ctx: AppContext, agent: "Agent") -> bool:
    """エージェント情報をファイルに保存する。

    worktree 内で実行されている場合でも、メインリポジトリの agents.json に保存する。
    これにより、全エージェント（Owner/Admin/Workers）が同じファイルに記録される。

    Args:
        app_ctx: アプリケーションコンテキスト
        agent: 保存するエージェント

    Returns:
        成功した場合 True
    """
    from src.models.agent import Agent  # 循環インポート回避

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

        # ファイルに保存
        with open(agents_file, "w", encoding="utf-8") as f:
            json.dump(agents_data, f, ensure_ascii=False, indent=2, default=str)

        logger.debug(f"エージェント {agent.id} を {agents_file} に保存しました")
        return True

    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning(f"エージェント情報の保存に失敗: {e}")
        return False


def load_agents_from_file(app_ctx: AppContext) -> dict[str, "Agent"]:
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


def sync_agents_from_file(app_ctx: AppContext) -> int:
    """ファイルからエージェント情報をメモリに同期する。

    既存のエージェント情報は保持し、ファイルにのみ存在するエージェントを追加する。

    Args:
        app_ctx: アプリケーションコンテキスト

    Returns:
        追加されたエージェント数
    """
    file_agents = load_agents_from_file(app_ctx)
    added = 0

    for agent_id, agent in file_agents.items():
        if agent_id not in app_ctx.agents:
            app_ctx.agents[agent_id] = agent
            added += 1

    if added > 0:
        logger.info(f"ファイルから {added} 件のエージェント情報を同期しました")

    return added


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

            with open(agents_file, "w", encoding="utf-8") as f:
                json.dump(agents_data, f, ensure_ascii=False, indent=2, default=str)

            logger.debug(f"エージェント {agent_id} を {agents_file} から削除しました")
            return True

        return False

    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"エージェント情報の削除に失敗: {e}")
        return False
