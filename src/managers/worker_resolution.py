"""Worker 解決ロジックの共通モジュール。

healthcheck_manager と agent_helpers に重複していた以下の解決処理を統合する:

- ``resolve_worker_number_from_slot``: tmux slot から Worker 番号を算出する。
- ``resolve_agent_cli_name``: Agent の実行 CLI 名を文字列で解決する。
- ``resolve_worker_model_for_cli``: Worker の実行 CLI に整合するモデル名を解決する。

統合方針:

- 例外型は ``(ValueError, TypeError)`` の狭い型へ統一する。
- role 比較は Enum / 文字列双方を許容する。
- ``resolve_worker_model_for_cli`` は window/pane 未確定時に None を返す
  (healthcheck 版の None ガードを採用)。

``src.managers`` 配下へ集約することで、managers → tools の逆依存を解消する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.config.settings import normalize_cli_name, resolve_model_for_cli

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.context import AppContext
    from src.models.agent import Agent

logger = logging.getLogger(__name__)


def resolve_worker_number_from_slot(
    settings: Settings,
    window_index: int,
    pane_index: int,
) -> int:
    """tmux slot から Worker 番号（1..16）を計算する。

    Args:
        settings: 設定。``workers_per_extra_window`` を参照する。
        window_index: tmux ウィンドウ番号（0 = メイン）。
        pane_index: ウィンドウ内のペインインデックス。

    Returns:
        算出した Worker 番号。
    """
    if window_index == 0:
        return pane_index
    workers_per_extra = settings.workers_per_extra_window
    return 6 + ((window_index - 1) * workers_per_extra) + pane_index + 1


def resolve_agent_cli_name(agent: Agent, app_ctx: AppContext) -> str:
    """Agent の CLI 名を文字列で返す。

    Worker の場合は pin 状態・tmux slot から CLI を再解決し、
    解決できない場合は ``agent.ai_cli``、最終的にデフォルト CLI へフォールバックする。

    Args:
        agent: 対象エージェント。
        app_ctx: アプリケーションコンテキスト。

    Returns:
        正規化済みの CLI 名。
    """
    from src.models.agent import AgentRole

    # Agent は use_enum_values=True のため role は文字列の場合がある。
    # Enum / 文字列双方を許容して Worker 判定する。
    if agent.role == AgentRole.WORKER or agent.role == AgentRole.WORKER.value:
        # preferred_cli / 明示指定で pin された Worker は agent 側設定を優先する。
        if getattr(agent, "ai_cli_pinned", False) and agent.ai_cli:
            return normalize_cli_name(agent.ai_cli)

        if agent.window_index is not None and agent.pane_index is not None:
            try:
                worker_no = resolve_worker_number_from_slot(
                    app_ctx.settings,
                    agent.window_index,
                    agent.pane_index,
                )
                return app_ctx.settings.get_worker_cli(worker_no).value
            except (ValueError, TypeError) as e:
                logger.debug("Worker CLI の再解決に失敗したため agent.ai_cli を使用: %s", e)

    if agent.ai_cli:
        return normalize_cli_name(agent.ai_cli)
    return normalize_cli_name(app_ctx.ai_cli.get_default_cli())


def resolve_worker_model_for_cli(
    app_ctx: AppContext,
    agent: Agent,
    profile_settings: dict[str, Any],
    agent_cli_name: str | None = None,
) -> str | None:
    """Worker の実行 CLI に整合するモデル名を解決する。

    Args:
        app_ctx: アプリケーションコンテキスト。
        agent: 対象 Worker エージェント。
        profile_settings: アクティブプロファイル設定（``worker_model`` を参照）。
        agent_cli_name: 事前解決済みの CLI 名。None の場合は内部で解決する。

    Returns:
        解決されたモデル名。window/pane が未確定の場合は None を返す。
    """
    if agent.window_index is None or agent.pane_index is None:
        return None
    cli_name = (agent_cli_name or resolve_agent_cli_name(agent, app_ctx)).lower()
    worker_no = resolve_worker_number_from_slot(
        app_ctx.settings,
        agent.window_index,
        agent.pane_index,
    )
    configured_model = app_ctx.settings.get_worker_model(
        worker_no,
        profile_settings.get("worker_model"),
    )
    return resolve_model_for_cli(
        cli_name,
        configured_model,
        role="worker",
        cli_defaults=app_ctx.settings.get_cli_default_models(),
    )
