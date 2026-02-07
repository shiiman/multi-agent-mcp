"""ヘルスチェックマネージャー。

エージェントの死活監視を行い、異常を検出したら通知・復旧する。
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.managers.tmux_manager import TmuxManager
    from src.models.agent import Agent

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """エージェントのヘルス状態。"""

    agent_id: str
    """エージェントID"""

    is_healthy: bool
    """健全かどうか"""

    tmux_session_alive: bool
    """tmuxセッションが生きているか"""

    error_message: str | None = None
    """エラーメッセージ"""

    def to_dict(self) -> dict:
        """辞書に変換する。"""
        return {
            "agent_id": self.agent_id,
            "is_healthy": self.is_healthy,
            "tmux_session_alive": self.tmux_session_alive,
            "error_message": self.error_message,
        }


class HealthcheckManager:
    """エージェントのヘルスチェックを管理する。"""

    def __init__(
        self,
        tmux_manager: "TmuxManager",
        agents: dict[str, "Agent"],
        healthcheck_interval_seconds: int = 60,
        stall_timeout_seconds: int = 600,
        max_recovery_attempts: int = 3,
    ) -> None:
        """HealthcheckManagerを初期化する。"""
        self.tmux_manager = tmux_manager
        self.agents = agents
        self.healthcheck_interval_seconds = healthcheck_interval_seconds
        self.stall_timeout_seconds = stall_timeout_seconds
        self.max_recovery_attempts = max_recovery_attempts
        self.last_monitor_at: datetime | None = None

        # 二段階判定用の状態
        self._pane_hash: dict[str, str] = {}
        self._pane_last_changed_at: dict[str, datetime] = {}

        # 同一 worker/task ごとの復旧試行回数
        self._recovery_failures: dict[str, int] = {}

    @staticmethod
    def _resolve_session_name(agent: "Agent") -> str | None:
        """Agent から tmux のセッション名を解決する。"""
        if getattr(agent, "session_name", None):
            return agent.session_name

        tmux_session = getattr(agent, "tmux_session", None)
        if tmux_session:
            return str(tmux_session).split(":", 1)[0]
        return None

    @staticmethod
    def _recovery_key(agent_id: str, task_id: str | None) -> str:
        normalized_task = task_id or "-"
        return f"{agent_id}:{normalized_task}"

    def _prune_state(self) -> None:
        """削除済み/無関係エージェントの監視状態を掃除する。"""
        active_ids = set(self.agents.keys())
        self._pane_hash = {k: v for k, v in self._pane_hash.items() if k in active_ids}
        self._pane_last_changed_at = {
            k: v for k, v in self._pane_last_changed_at.items() if k in active_ids
        }

        def _is_key_alive(key: str) -> bool:
            agent_id = key.split(":", 1)[0]
            return agent_id in active_ids

        self._recovery_failures = {
            k: v for k, v in self._recovery_failures.items() if _is_key_alive(k)
        }

    async def _capture_pane_hash(self, agent: "Agent") -> str | None:
        """Worker pane の出力ハッシュを取得する。"""
        session_name = self._resolve_session_name(agent)
        if (
            not session_name
            or agent.window_index is None
            or agent.pane_index is None
        ):
            return None

        try:
            output = await self.tmux_manager.capture_pane_by_index(
                session_name,
                agent.window_index,
                agent.pane_index,
                lines=120,
            )
        except Exception:
            return None

        compact = "\n".join(output.strip().splitlines()[-40:])
        return hashlib.sha1(compact.encode("utf-8")).hexdigest()

    async def _is_worker_stalled(
        self,
        agent_id: str,
        agent: "Agent",
        now: datetime,
    ) -> bool:
        """Worker が無応答状態かを二段階判定で判定する。"""
        if not agent.current_task or not agent.last_activity:
            return False

        inactive_for = now - agent.last_activity
        if inactive_for < timedelta(seconds=self.stall_timeout_seconds):
            return False

        pane_hash = await self._capture_pane_hash(agent)
        if pane_hash is None:
            # pane 情報が取得できない場合は inactive 判定のみで扱う
            return True

        previous_hash = self._pane_hash.get(agent_id)
        self._pane_hash[agent_id] = pane_hash

        if previous_hash != pane_hash:
            self._pane_last_changed_at[agent_id] = now
            return False

        if agent_id not in self._pane_last_changed_at:
            self._pane_last_changed_at[agent_id] = now
            return False

        unchanged_for = now - self._pane_last_changed_at[agent_id]
        return unchanged_for >= timedelta(seconds=self.stall_timeout_seconds)

    async def check_agent(self, agent_id: str) -> HealthStatus:
        """単一エージェントのヘルスチェックを行う。"""
        agent = self.agents.get(agent_id)
        if not agent:
            return HealthStatus(
                agent_id=agent_id,
                is_healthy=False,
                tmux_session_alive=False,
                error_message="エージェントが見つかりません",
            )

        session_name = self._resolve_session_name(agent)
        if not session_name:
            return HealthStatus(
                agent_id=agent_id,
                is_healthy=False,
                tmux_session_alive=False,
                error_message="tmux セッション情報が未設定です",
            )

        tmux_alive = await self.tmux_manager.session_exists(session_name)
        return HealthStatus(
            agent_id=agent_id,
            is_healthy=tmux_alive,
            tmux_session_alive=tmux_alive,
            error_message=None if tmux_alive else "tmux セッションが見つかりません",
        )

    async def check_all_agents(self) -> list[HealthStatus]:
        """全エージェントのヘルスチェックを行う。"""
        statuses = []
        for agent_id in self.agents:
            statuses.append(await self.check_agent(agent_id))
        return statuses

    async def get_unhealthy_agents(self) -> list[HealthStatus]:
        """異常なエージェント一覧を取得する。"""
        all_status = await self.check_all_agents()
        return [s for s in all_status if not s.is_healthy]

    async def get_healthy_agents(self) -> list[HealthStatus]:
        """健全なエージェント一覧を取得する。"""
        all_status = await self.check_all_agents()
        return [s for s in all_status if s.is_healthy]

    async def attempt_recovery(self, agent_id: str, force: bool = False) -> tuple[bool, str]:
        """エージェントの復旧を試みる。"""
        status = await self.check_agent(agent_id)

        if status.is_healthy and not force:
            return True, f"エージェント {agent_id} は既に健全です"

        agent = self.agents.get(agent_id)
        if not agent:
            return False, f"エージェント {agent_id} が見つかりません"

        session_name = self._resolve_session_name(agent)
        if not session_name:
            return False, f"エージェント {agent_id} の tmux セッション情報がありません"

        if force and agent.window_index is not None and agent.pane_index is not None:
            try:
                window_name = self.tmux_manager._get_window_name(agent.window_index)
                target = f"{session_name}:{window_name}.{agent.pane_index}"
                code, _, stderr = await self.tmux_manager._run(
                    "send-keys", "-t", target, "C-c"
                )
                if code != 0:
                    return False, f"強制復旧に失敗しました: {stderr}"
                await self.tmux_manager._run("send-keys", "-t", target, "clear", "Enter")
                return True, f"エージェント {agent_id} に割り込みを送信しました"
            except Exception as e:
                return False, f"強制復旧に失敗しました: {e}"

        logger.info(f"エージェント {agent_id} の tmux セッションを再作成します")
        working_dir = agent.worktree_path or agent.working_dir or "."
        success = await self.tmux_manager.create_session(session_name, working_dir)
        if success:
            return True, f"エージェント {agent_id} の tmux セッションを再作成しました"
        return False, f"エージェント {agent_id} の tmux セッション再作成に失敗しました"

    async def attempt_recovery_all(self) -> list[tuple[str, bool, str]]:
        """全ての異常なエージェントの復旧を試みる。"""
        unhealthy = await self.get_unhealthy_agents()
        results = []
        for status in unhealthy:
            success, message = await self.attempt_recovery(status.agent_id)
            results.append((status.agent_id, success, message))
        return results

    async def _run_full_recovery(self, app_ctx: Any, agent_id: str) -> tuple[bool, str]:
        """段階復旧の 2 段目として full_recovery を実行する。"""
        try:
            from src.tools.healthcheck import execute_full_recovery

            result = await execute_full_recovery(app_ctx, agent_id)
            if result.get("success"):
                return True, result.get("message", "full_recovery succeeded")
            return False, result.get("error", result.get("message", "full_recovery failed"))
        except Exception as e:
            return False, str(e)

    async def _finalize_failed_task(
        self,
        app_ctx: Any,
        agent_id: str,
        agent: "Agent",
        reason: str,
    ) -> dict[str, str]:
        """復旧失敗上限を超えたタスクを failed 化し、Admin に通知する。"""
        from src.models.agent import AgentStatus

        task_id = agent.current_task
        detail = {
            "agent_id": agent_id,
            "task_id": task_id or "",
            "reason": reason,
        }

        if app_ctx is not None and task_id:
            try:
                from pathlib import Path

                from src.models.dashboard import TaskStatus
                from src.models.message import MessagePriority, MessageType
                from src.tools.helpers_managers import (
                    ensure_dashboard_manager,
                    ensure_ipc_manager,
                )

                dashboard = app_ctx.dashboard_manager
                if dashboard is None:
                    dashboard = ensure_dashboard_manager(app_ctx)
                dashboard.update_task_status(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error_message=f"healthcheck_recovery_failed: {reason}",
                )
                if app_ctx.project_root and app_ctx.session_id:
                    dashboard.save_markdown_dashboard(
                        Path(app_ctx.project_root),
                        app_ctx.session_id,
                    )

                ipc = ensure_ipc_manager(app_ctx)
                admin_ids = [
                    worker_id
                    for worker_id, worker in self.agents.items()
                    if worker.role == "admin"
                ]
                for admin_id in admin_ids:
                    if admin_id not in ipc.get_all_agent_ids():
                        ipc.register_agent(admin_id)
                    ipc.send_message(
                        sender_id="healthcheck-daemon",
                        receiver_id=admin_id,
                        message_type=MessageType.ERROR,
                        subject=f"task failed by healthcheck: {task_id}",
                        content=(
                            f"Worker {agent_id} の復旧が上限回数を超えたため、"
                            f"task {task_id} を failed にしました。"
                        ),
                        priority=MessagePriority.HIGH,
                        metadata={
                            "agent_id": agent_id,
                            "task_id": task_id,
                            "reason": reason,
                        },
                    )
            except Exception as e:
                detail["notify_error"] = str(e)

            # ダッシュボード更新成否に関わらず Worker 状態は必ず解放する
            agent.current_task = None
            agent.status = AgentStatus.IDLE
            agent.last_activity = datetime.now()
            try:
                from src.tools.helpers import save_agent_to_file

                save_agent_to_file(app_ctx, agent)
            except Exception:
                pass
        elif task_id:
            # app_ctx がない場合でも in-memory だけは解放する
            agent.current_task = None
            agent.status = AgentStatus.IDLE
            agent.last_activity = datetime.now()

        return detail

    def get_summary(self) -> dict:
        """ヘルスチェックのサマリーを取得する。"""
        return {
            "total_agents": len(self.agents),
            "healthcheck_interval_seconds": self.healthcheck_interval_seconds,
            "stall_timeout_seconds": self.stall_timeout_seconds,
            "max_recovery_attempts": self.max_recovery_attempts,
            "last_monitor_at": self.last_monitor_at.isoformat() if self.last_monitor_at else None,
        }

    async def monitor_and_recover_workers(self, app_ctx: Any | None = None) -> dict:
        """Worker の健全性を監視し、必要なら段階復旧する。"""
        from src.models.agent import AgentRole, AgentStatus

        now = datetime.now()
        self.last_monitor_at = now
        self._prune_state()

        recovered: list[dict[str, str]] = []
        escalated: list[dict[str, str]] = []
        failed_tasks: list[dict[str, str]] = []
        skipped: list[str] = []

        for agent_id, agent in list(self.agents.items()):
            if agent.role != AgentRole.WORKER.value:
                continue

            current_key = self._recovery_key(agent_id, agent.current_task)
            stale_keys = [
                key
                for key in self._recovery_failures
                if key.startswith(f"{agent_id}:") and key != current_key
            ]
            for stale_key in stale_keys:
                self._recovery_failures.pop(stale_key, None)

            if not agent.current_task and agent.status == AgentStatus.IDLE.value:
                skipped.append(agent_id)
                continue

            health = await self.check_agent(agent_id)
            recovery_reason: str | None = None
            force_recovery = False

            if not health.is_healthy:
                recovery_reason = "tmux_session_dead"
            elif await self._is_worker_stalled(agent_id, agent, now):
                recovery_reason = "task_stalled"
                force_recovery = True

            if recovery_reason is None:
                continue

            task_key = current_key
            success, message = await self.attempt_recovery(agent_id, force=force_recovery)
            if success:
                agent.ai_bootstrapped = False
                if app_ctx is not None:
                    try:
                        from src.tools.helpers import save_agent_to_file

                        save_agent_to_file(app_ctx, agent)
                    except Exception:
                        pass
                self._recovery_failures.pop(task_key, None)
                recovered.append(
                    {
                        "agent_id": agent_id,
                        "reason": recovery_reason,
                        "method": "attempt_recovery",
                        "message": message,
                    }
                )
                continue

            full_success = False
            full_message = ""
            if app_ctx is not None:
                full_success, full_message = await self._run_full_recovery(app_ctx, agent_id)

            if full_success:
                if app_ctx is not None:
                    try:
                        from src.tools.helpers import save_agent_to_file

                        current_agent = app_ctx.agents.get(agent_id)
                        if current_agent is not None:
                            current_agent.ai_bootstrapped = False
                            save_agent_to_file(app_ctx, current_agent)
                    except Exception:
                        pass
                self._recovery_failures.pop(task_key, None)
                recovered.append(
                    {
                        "agent_id": agent_id,
                        "reason": recovery_reason,
                        "method": "full_recovery",
                        "message": full_message,
                    }
                )
                continue

            attempts = self._recovery_failures.get(task_key, 0) + 1
            self._recovery_failures[task_key] = attempts

            escalated.append(
                {
                    "agent_id": agent_id,
                    "reason": recovery_reason,
                    "attempts": str(attempts),
                    "message": (
                        f"attempt_recovery failed: {message}; "
                        f"full_recovery failed: {full_message or 'not_executed'}"
                    ),
                }
            )

            if attempts >= self.max_recovery_attempts:
                failed = await self._finalize_failed_task(app_ctx, agent_id, agent, message)
                failed_tasks.append(failed)
                self._recovery_failures.pop(task_key, None)

        return {
            "recovered": recovered,
            "escalated": escalated,
            "failed_tasks": failed_tasks,
            "skipped": skipped,
            "healthcheck_interval_seconds": self.healthcheck_interval_seconds,
            "stall_timeout_seconds": self.stall_timeout_seconds,
            "max_recovery_attempts": self.max_recovery_attempts,
            "last_monitor_at": self.last_monitor_at.isoformat(),
        }
