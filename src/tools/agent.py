"""エージェント管理ツール。"""

import logging
import uuid
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.settings import Settings
from src.context import AppContext
from src.managers.tmux_manager import (
    MAIN_WINDOW_PANE_ADMIN,
    MAIN_WINDOW_WORKER_PANES,
    get_project_name,
)
from src.models.agent import Agent, AgentRole, AgentStatus

logger = logging.getLogger(__name__)


def _get_next_worker_slot(
    agents: dict[str, Agent], settings: Settings, session_name: str
) -> tuple[int, int] | None:
    """次に利用可能なWorkerスロット（ウィンドウ, ペイン）を取得する。

    単一セッション方式（40:60 レイアウト）:
    - メインウィンドウ（window 0）: Admin はペイン 0、Worker 1-6 はペイン 1-6
    - 追加ウィンドウ（window 1+）: 10ペイン/ウィンドウ（2×5）

    Args:
        agents: エージェント辞書
        settings: 設定オブジェクト
        session_name: 対象のセッション名（プロジェクト名）

    Returns:
        (window_index, pane_index) のタプル、空きがない場合はNone
    """
    # 最大Worker数チェック
    total_workers = len(
        [a for a in agents.values() if a.role == AgentRole.WORKER]
    )
    if total_workers >= settings.max_workers:
        return None

    # 現在のWorkerペイン割り当て状況を取得
    used_slots: set[tuple[int, int]] = set()
    for agent in agents.values():
        if (
            agent.role == AgentRole.WORKER
            and agent.session_name == session_name
            and agent.window_index is not None
            and agent.pane_index is not None
        ):
            used_slots.add((agent.window_index, agent.pane_index))

    # メインウィンドウ（Worker 1-6: pane 1-6）の空きを探す
    for pane_index in MAIN_WINDOW_WORKER_PANES:
        if (0, pane_index) not in used_slots:
            return (0, pane_index)

    # 追加ウィンドウの空きを探す
    panes_per_extra = settings.workers_per_extra_window
    extra_worker_index = 0
    while total_workers + extra_worker_index < settings.max_workers:
        window_index = 1 + (extra_worker_index // panes_per_extra)
        pane_index = extra_worker_index % panes_per_extra
        if (window_index, pane_index) not in used_slots:
            return (window_index, pane_index)
        extra_worker_index += 1

    return None


def register_tools(mcp: FastMCP) -> None:
    """エージェント管理ツールを登録する。"""

    @mcp.tool()
    async def create_agent(role: str, working_dir: str, ctx: Context) -> dict[str, Any]:
        """新しいエージェントを作成する。

        単一セッション方式: 左右40:60分離レイアウト
        - Owner: tmux ペインに配置しない（実行AIエージェントが担う）
        - 左 40%: Admin (pane 0)
        - 右 60%: Worker 1-6 (pane 1-6)
        - Worker 7以降は追加ウィンドウ（2×5=10ペイン/ウィンドウ）

        Args:
            role: エージェントの役割（owner/admin/worker）
            working_dir: 作業ディレクトリのパス

        Returns:
            作成結果（success, agent, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        settings = app_ctx.settings
        tmux = app_ctx.tmux
        agents = app_ctx.agents

        # 役割の検証
        try:
            agent_role = AgentRole(role)
        except ValueError:
            return {
                "success": False,
                "error": f"無効な役割です: {role}（有効: owner, admin, worker）",
            }

        # Worker数の上限チェック
        if agent_role == AgentRole.WORKER:
            worker_count = sum(1 for a in agents.values() if a.role == AgentRole.WORKER)
            if worker_count >= settings.max_workers:
                return {
                    "success": False,
                    "error": f"Worker数が上限（{settings.max_workers}）に達しています",
                }

        # Owner/Adminの重複チェック
        if agent_role in (AgentRole.OWNER, AgentRole.ADMIN):
            existing = [a for a in agents.values() if a.role == agent_role]
            if existing:
                return {
                    "success": False,
                    "error": f"{agent_role.value}は既に存在します（ID: {existing[0].id}）",
                }

        # エージェントIDを生成
        agent_id = str(uuid.uuid4())[:8]

        # ロールに応じてペイン位置を決定（プロジェクト固有のセッション内）
        project_name = get_project_name(working_dir)
        if agent_role == AgentRole.OWNER:
            # Owner は tmux ペインに配置しない（実行AIエージェントが担う）
            session_name: str | None = None
            window_index: int | None = None
            pane_index: int | None = None
        elif agent_role == AgentRole.ADMIN:
            # メインセッションを確保（単一セッション方式）
            if not await tmux.create_main_session(working_dir):
                return {
                    "success": False,
                    "error": "メインセッションの作成に失敗しました",
                }
            session_name = project_name
            window_index = 0
            pane_index = MAIN_WINDOW_PANE_ADMIN
        else:  # WORKER
            # メインセッションを確保（単一セッション方式）
            if not await tmux.create_main_session(working_dir):
                return {
                    "success": False,
                    "error": "メインセッションの作成に失敗しました",
                }
            session_name = project_name

            # 次の空きスロットを探す
            slot = _get_next_worker_slot(agents, settings, project_name)
            if slot is None:
                return {
                    "success": False,
                    "error": "利用可能なWorkerスロットがありません",
                }
            window_index, pane_index = slot

            # 追加ウィンドウが必要な場合は作成
            if window_index > 0:
                success = await tmux.add_extra_worker_window(
                    project_name=project_name,
                    window_index=window_index,
                    rows=settings.extra_worker_rows,
                    cols=settings.extra_worker_cols,
                )
                if not success:
                    return {
                        "success": False,
                        "error": f"追加Workerウィンドウ {window_index} の作成に失敗しました",
                    }

        # ペインにタイトルを設定（tmux ペインがある場合のみ）
        if session_name is not None and window_index is not None and pane_index is not None:
            await tmux.set_pane_title(
                session_name, window_index, pane_index, f"{agent_role.value}-{agent_id}"
            )
            tmux_session = f"{session_name}:{window_index}.{pane_index}"
            log_location = tmux_session
        else:
            tmux_session = None
            log_location = "tmux なし（VSCode Claude）"

        # エージェント情報を登録
        now = datetime.now()
        agent = Agent(
            id=agent_id,
            role=agent_role,
            status=AgentStatus.IDLE,
            tmux_session=tmux_session,
            session_name=session_name,
            window_index=window_index,
            pane_index=pane_index,
            created_at=now,
            last_activity=now,
        )
        agents[agent_id] = agent

        logger.info(
            f"エージェント {agent_id}（{role}）を作成しました: {log_location}"
        )

        return {
            "success": True,
            "agent": agent.model_dump(mode="json"),
            "message": f"エージェント {agent_id}（{role}）を作成しました",
        }

    @mcp.tool()
    async def list_agents(ctx: Context) -> dict[str, Any]:
        """全エージェントの一覧を取得する。

        Returns:
            エージェント一覧（success, agents, count）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        agents = app_ctx.agents

        agent_list = [a.model_dump(mode="json") for a in agents.values()]

        return {
            "success": True,
            "agents": agent_list,
            "count": len(agent_list),
        }

    @mcp.tool()
    async def get_agent_status(agent_id: str, ctx: Context) -> dict[str, Any]:
        """指定エージェントの詳細ステータスを取得する。

        Args:
            agent_id: エージェントID

        Returns:
            エージェント詳細（success, agent, session_active または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        tmux = app_ctx.tmux
        agents = app_ctx.agents

        agent = agents.get(agent_id)
        if not agent:
            return {
                "success": False,
                "error": f"エージェント {agent_id} が見つかりません",
            }

        session_exists = await tmux.session_exists(agent.tmux_session)

        return {
            "success": True,
            "agent": agent.model_dump(mode="json"),
            "session_active": session_exists,
        }

    @mcp.tool()
    async def terminate_agent(agent_id: str, ctx: Context) -> dict[str, Any]:
        """エージェントを終了する。

        グリッドレイアウトではペインは維持され、再利用可能になる。

        Args:
            agent_id: 終了するエージェントID

        Returns:
            終了結果（success, agent_id, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        tmux = app_ctx.tmux
        agents = app_ctx.agents

        agent = agents.get(agent_id)
        if not agent:
            return {
                "success": False,
                "error": f"エージェント {agent_id} が見つかりません",
            }

        # グリッドレイアウトの場合はペインをクリアするだけ（セッションは維持）
        if (
            agent.session_name is not None
            and agent.window_index is not None
            and agent.pane_index is not None
        ):
            # ペインに Ctrl+C を送信してプロセスを停止
            await tmux.send_keys_to_pane(
                agent.session_name, agent.window_index, agent.pane_index, "", literal=False
            )
            session_name = tmux._session_name(agent.session_name)
            window_name = tmux._get_window_name(agent.window_index)
            target = f"{session_name}:{window_name}.{agent.pane_index}"
            await tmux._run("send-keys", "-t", target, "C-c")
            # ペインタイトルをクリア
            await tmux.set_pane_title(
                agent.session_name, agent.window_index, agent.pane_index, "(empty)"
            )
        else:
            # フォールバック: 従来のセッション方式（個別セッションを終了）
            await tmux.kill_session(agent.tmux_session)

        del agents[agent_id]

        logger.info(f"エージェント {agent_id} を終了しました")

        return {
            "success": True,
            "agent_id": agent_id,
            "message": f"エージェント {agent_id} を終了しました",
        }
