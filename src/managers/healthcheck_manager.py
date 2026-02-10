"""ヘルスチェックマネージャー。

エージェントの死活監視を行い、異常を検出したら通知・復旧する。
"""

import hashlib
import inspect
import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.managers.tmux_manager import TmuxManager
    from src.models.agent import Agent

logger = logging.getLogger(__name__)

_SHELL_COMMANDS = {"zsh", "bash", "sh", "fish"}


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

    pane_current_command: str | None = None
    """pane で現在実行中のコマンド"""

    def to_dict(self) -> dict:
        """辞書に変換する。"""
        return {
            "agent_id": self.agent_id,
            "is_healthy": self.is_healthy,
            "tmux_session_alive": self.tmux_session_alive,
            "error_message": self.error_message,
            "pane_current_command": self.pane_current_command,
        }


class HealthcheckManager:
    """エージェントのヘルスチェックを管理する。"""

    def __init__(
        self,
        tmux_manager: "TmuxManager",
        agents: dict[str, "Agent"],
        healthcheck_interval_seconds: int = 60,
        stall_timeout_seconds: int = 600,
        in_progress_no_ipc_timeout_seconds: int = 120,
        max_recovery_attempts: int = 3,
    ) -> None:
        """HealthcheckManagerを初期化する。"""
        self.tmux_manager = tmux_manager
        self.agents = agents
        self.healthcheck_interval_seconds = healthcheck_interval_seconds
        self.stall_timeout_seconds = stall_timeout_seconds
        self.in_progress_no_ipc_timeout_seconds = in_progress_no_ipc_timeout_seconds
        self.max_recovery_attempts = max_recovery_attempts
        self.last_monitor_at: datetime | None = None

        # 二段階判定用の状態
        self._pane_hash: dict[str, str] = {}
        self._pane_last_changed_at: dict[str, datetime] = {}

        # 同一 worker/task ごとの復旧試行回数
        self._recovery_failures: dict[str, int] = {}

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
        session_name = agent.resolved_session_name
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
        except (OSError, subprocess.SubprocessError) as e:
            logger.debug("ペインキャプチャに失敗: %s", e)
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

    @staticmethod
    def _task_activity_at(active_task: Any) -> datetime | None:
        """Task の最終活動時刻を取得する。"""
        metadata = getattr(active_task, "metadata", {}) or {}
        raw_last_update = metadata.get("last_in_progress_update_at")
        if isinstance(raw_last_update, datetime):
            return raw_last_update
        if isinstance(raw_last_update, str):
            try:
                return datetime.fromisoformat(raw_last_update)
            except ValueError:
                pass

        logs = getattr(active_task, "logs", []) or []
        if logs:
            log_ts = getattr(logs[-1], "timestamp", None)
            if isinstance(log_ts, datetime):
                return log_ts

        started_at = getattr(active_task, "started_at", None)
        if isinstance(started_at, datetime):
            return started_at
        return None

    async def _is_in_progress_without_ipc(
        self,
        agent_id: str,
        agent: "Agent",
        active_task: Any,
        now: datetime,
    ) -> bool:
        """in_progress タスクの長時間無通信を判定する。"""
        timeout_seconds = self.in_progress_no_ipc_timeout_seconds
        if timeout_seconds <= 0:
            return False

        activity_at = self._task_activity_at(active_task)
        if activity_at is None:
            return False
        if now - activity_at < timedelta(seconds=timeout_seconds):
            return False

        pane_hash = await self._capture_pane_hash(agent)
        if pane_hash is None:
            # pane 情報が取れない場合はタイムアウトのみで異常扱い
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
        return unchanged_for >= timedelta(seconds=timeout_seconds)

    async def check_agent(self, agent_id: str) -> HealthStatus:
        """単一エージェントのヘルスチェックを行う。"""
        from src.models.agent import AgentRole

        agent = self.agents.get(agent_id)
        if not agent:
            return HealthStatus(
                agent_id=agent_id,
                is_healthy=False,
                tmux_session_alive=False,
                error_message="エージェントが見つかりません",
            )

        session_name = agent.resolved_session_name
        if not session_name:
            return HealthStatus(
                agent_id=agent_id,
                is_healthy=False,
                tmux_session_alive=False,
                error_message="tmux セッション情報が未設定です",
            )

        tmux_alive = await self.tmux_manager.session_exists(session_name)
        if not tmux_alive:
            return HealthStatus(
                agent_id=agent_id,
                is_healthy=False,
                tmux_session_alive=False,
                error_message="tmux セッションが見つかりません",
            )

        pane_command: str | None = None
        if agent.window_index is not None and agent.pane_index is not None:
            get_current = getattr(self.tmux_manager, "get_pane_current_command", None)
            if callable(get_current):
                pane_command_result = get_current(
                    session_name,
                    agent.window_index,
                    agent.pane_index,
                )
                if inspect.isawaitable(pane_command_result):
                    pane_command = await pane_command_result
                else:
                    pane_command = pane_command_result
                # 文字列以外が返った場合は安全に変換
                if pane_command is not None and not isinstance(pane_command, str):
                    pane_command = str(pane_command)

        # Worker がタスク中なのに shell に戻っている場合は異常
        role = str(getattr(agent, "role", ""))
        is_worker = role == AgentRole.WORKER.value
        command_name = (pane_command or "").strip().lower()
        if is_worker and agent.current_task and command_name in _SHELL_COMMANDS:
            return HealthStatus(
                agent_id=agent_id,
                is_healthy=False,
                tmux_session_alive=True,
                error_message="ai_process_dead",
                pane_current_command=pane_command,
            )

        return HealthStatus(
            agent_id=agent_id,
            is_healthy=tmux_alive,
            tmux_session_alive=tmux_alive,
            error_message=None,
            pane_current_command=pane_command,
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

        session_name = agent.resolved_session_name
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
                return True, f"エージェント {agent_id} に割り込みを送信しました"
            except (OSError, subprocess.SubprocessError) as e:
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
        except (OSError, subprocess.SubprocessError, ImportError, ValueError) as e:
            return False, str(e)

    def _notify_admins_task_failed(
        self, app_ctx: Any, agent_id: str, task_id: str, reason: str,
    ) -> str | None:
        """タスク失敗を dashboard 更新 + Admin IPC 通知する。エラー時は文字列を返す。"""
        try:
            from pathlib import Path

            from src.models.dashboard import TaskStatus
            from src.models.message import MessagePriority, MessageType
            from src.tools.helpers_managers import ensure_dashboard_manager, ensure_ipc_manager

            dashboard = app_ctx.dashboard_manager or ensure_dashboard_manager(app_ctx)
            dashboard.update_task_status(
                task_id=task_id, status=TaskStatus.FAILED,
                error_message=f"healthcheck_recovery_failed: {reason}",
            )
            if app_ctx.project_root and app_ctx.session_id:
                dashboard.save_markdown_dashboard(Path(app_ctx.project_root), app_ctx.session_id)

            ipc = ensure_ipc_manager(app_ctx)
            admin_ids = [wid for wid, w in self.agents.items() if w.role == "admin"]
            for aid in admin_ids:
                if aid not in ipc.get_all_agent_ids():
                    ipc.register_agent(aid)
                ipc.send_message(
                    sender_id="healthcheck-daemon", receiver_id=aid,
                    message_type=MessageType.ERROR,
                    subject=f"task failed by healthcheck: {task_id}",
                    content=f"Worker {agent_id} の復旧上限超過により task {task_id} を failed 化。",
                    priority=MessagePriority.HIGH,
                    metadata={"agent_id": agent_id, "task_id": task_id, "reason": reason},
                )
        except (OSError, KeyError, ValueError) as e:
            return str(e)
        return None

    async def _finalize_failed_task(
        self, app_ctx: Any, agent_id: str, agent: "Agent", reason: str,
    ) -> dict[str, str]:
        """復旧失敗上限を超えたタスクを failed 化し、Admin に通知する。"""
        from src.models.agent import AgentStatus

        task_id = agent.current_task
        detail = {"agent_id": agent_id, "task_id": task_id or "", "reason": reason}

        if app_ctx is not None and task_id:
            err = self._notify_admins_task_failed(app_ctx, agent_id, task_id, reason)
            if err:
                detail["notify_error"] = err
            agent.current_task = None
            agent.status = AgentStatus.IDLE
            agent.last_activity = datetime.now()
            try:
                from src.tools.helpers import save_agent_to_file
                save_agent_to_file(app_ctx, agent)
            except (OSError, json.JSONDecodeError, ValueError) as e:
                logger.debug("復旧後のエージェント保存に失敗: %s", e)
        elif task_id:
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
            "in_progress_no_ipc_timeout_seconds": self.in_progress_no_ipc_timeout_seconds,
            "max_recovery_attempts": self.max_recovery_attempts,
            "last_monitor_at": self.last_monitor_at.isoformat() if self.last_monitor_at else None,
        }

    def _sync_worker_active_task(
        self,
        agent_id: str,
        agent: "Agent",
        dashboard: Any | None,
        app_ctx: Any | None,
    ) -> tuple[Any, str | None]:
        """Dashboard からアクティブタスクを同期し、エージェント状態を補正する。

        Returns:
            (active_task, active_task_id)
        """
        from src.models.agent import AgentStatus
        from src.models.dashboard import TaskStatus

        active_task = None
        active_task_id = agent.current_task

        if dashboard is None:
            return active_task, active_task_id

        try:
            assigned_tasks = dashboard.list_tasks(agent_id=agent_id)
            active_tasks = [
                task
                for task in assigned_tasks
                if task.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)
            ]
            if active_tasks:
                in_progress = [
                    task for task in active_tasks if task.status == TaskStatus.IN_PROGRESS
                ]
                active_task = (in_progress or active_tasks)[0]
                active_task_id = active_task.id
                if agent.current_task != active_task_id:
                    agent.current_task = active_task_id
                    if agent.status != AgentStatus.BUSY.value:
                        agent.status = AgentStatus.BUSY
                    try:
                        from src.tools.helpers import save_agent_to_file

                        save_agent_to_file(app_ctx, agent)
                    except (OSError, json.JSONDecodeError, ValueError) as e:
                        logger.debug("BUSY ステータス保存に失敗: %s", e)
            elif agent.current_task:
                current_dashboard_task = dashboard.get_task(agent.current_task)
                if current_dashboard_task and current_dashboard_task.status in (
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                ):
                    agent.current_task = None
                    if agent.status == AgentStatus.BUSY.value:
                        agent.status = AgentStatus.IDLE
                    try:
                        from src.tools.helpers import save_agent_to_file

                        save_agent_to_file(app_ctx, agent)
                    except (OSError, json.JSONDecodeError, ValueError) as e:
                        logger.debug("IDLE ステータス保存に失敗: %s", e)
                    active_task_id = None
        except (KeyError, ValueError, AttributeError) as e:
            logger.debug("アクティブタスクの取得に失敗: %s", e)
            active_task = None

        return active_task, active_task_id

    async def _diagnose_worker_issue(
        self,
        agent_id: str,
        agent: "Agent",
        active_task: Any,
        now: datetime,
    ) -> tuple[str | None, bool]:
        """Worker の異常原因を診断する。

        Returns:
            (recovery_reason, force_recovery)
        """
        from src.models.dashboard import TaskStatus

        health = await self.check_agent(agent_id)

        if not health.is_healthy:
            reason = (
                "ai_process_dead"
                if health.error_message == "ai_process_dead"
                else "tmux_session_dead"
            )
            return reason, False

        if (
            active_task is not None
            and active_task.status == TaskStatus.PENDING
            and active_task.started_at is None
            and agent.last_activity is not None
            and (now - agent.last_activity)
            >= timedelta(seconds=max(self.healthcheck_interval_seconds * 2, 30))
        ):
            return "task_not_started", True

        if (
            active_task is not None
            and active_task.status == TaskStatus.IN_PROGRESS
            and await self._is_in_progress_without_ipc(agent_id, agent, active_task, now)
        ):
            pane_command = (health.pane_current_command or "").strip().lower()
            # Codex/Claude/Gemini が実行中でセッション健全な場合は
            # no-IPC だけで強制復旧しない（長時間推論で誤検知しやすいため）。
            if pane_command in {"codex", "claude", "gemini"}:
                logger.info(
                    "in_progress_no_ipc をスキップ: agent=%s pane=%s",
                    agent_id,
                    pane_command,
                )
            else:
                return "in_progress_no_ipc", True

        if await self._is_worker_stalled(agent_id, agent, now):
            pane_command = (health.pane_current_command or "").strip().lower()
            if pane_command in {"codex", "claude", "gemini"}:
                logger.info(
                    "task_stalled をスキップ: agent=%s pane=%s（AI CLI 実行中）",
                    agent_id,
                    pane_command,
                )
            else:
                return "task_stalled", True

        return None, False

    def _save_agent_after_recovery(
        self, app_ctx: Any | None, agent: "Agent", label: str,
    ) -> None:
        """復旧後のエージェント保存。"""
        if app_ctx is None:
            return
        try:
            from src.tools.helpers import save_agent_to_file
            agent.ai_bootstrapped = False
            save_agent_to_file(app_ctx, agent)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.debug("%s 後のエージェント保存に失敗: %s", label, e)

    def _increment_recovery_counter(
        self,
        app_ctx: Any | None,
        agent_id: str,
        task_id: str | None,
        recovery_reason: str,
    ) -> None:
        """復旧成功時のカウンタを更新する。

        Dashboard の拡張フィールドが存在する場合はそれも更新し、
        未拡張環境では task.metadata のみ更新する。
        """
        if app_ctx is None or not task_id:
            return

        try:
            from src.tools.helpers_managers import ensure_dashboard_manager

            dashboard = app_ctx.dashboard_manager or ensure_dashboard_manager(app_ctx)
            if dashboard is None:
                return

            read_dashboard = getattr(dashboard, "_read_dashboard", None)
            write_dashboard = getattr(dashboard, "_write_dashboard", None)
            if not callable(read_dashboard) or not callable(write_dashboard):
                return

            dashboard_data = read_dashboard()
            updated = False

            task = dashboard_data.get_task(task_id)
            if task is not None:
                metadata = dict(task.metadata or {})
                count = int(metadata.get("process_recovery_count", 0))
                metadata["process_recovery_count"] = count + 1
                metadata["last_recovery_reason"] = recovery_reason
                metadata["last_recovery_at"] = datetime.now().isoformat()
                task.metadata = metadata
                updated = True

            agent_summary = dashboard_data.get_agent(agent_id)
            if agent_summary is not None and hasattr(agent_summary, "process_recovery_count"):
                current = int(getattr(agent_summary, "process_recovery_count", 0) or 0)
                agent_summary.process_recovery_count = current + 1
                updated = True

            if updated:
                write_dashboard(dashboard_data)
        except (
            OSError,
            ValueError,
            AttributeError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as e:
            logger.debug("復旧カウンタ更新に失敗: %s", e)

    async def _attempt_staged_recovery(
        self,
        app_ctx: Any | None,
        agent_id: str,
        agent: "Agent",
        recovery_reason: str,
        force_recovery: bool,
        task_key: str,
    ) -> dict[str, Any]:
        """段階復旧（attempt_recovery → full_recovery → escalate）を実行する。"""
        recovery_task_id = agent.current_task
        success, message = await self.attempt_recovery(agent_id, force=force_recovery)
        if success:
            self._save_agent_after_recovery(app_ctx, agent, "attempt_recovery")
            self._increment_recovery_counter(
                app_ctx,
                agent_id,
                recovery_task_id,
                recovery_reason,
            )
            self._recovery_failures.pop(task_key, None)
            return {
                "status": "recovered",
                "detail": {"agent_id": agent_id, "reason": recovery_reason,
                           "method": "attempt_recovery", "message": message},
            }

        full_success, full_message = False, ""
        if app_ctx is not None:
            full_success, full_message = await self._run_full_recovery(app_ctx, agent_id)

        if full_success:
            target = (app_ctx.agents.get(agent_id) if app_ctx else None) or agent
            self._save_agent_after_recovery(app_ctx, target, "full_recovery")
            self._increment_recovery_counter(
                app_ctx,
                agent_id,
                recovery_task_id,
                recovery_reason,
            )
            self._recovery_failures.pop(task_key, None)
            return {
                "status": "recovered",
                "detail": {"agent_id": agent_id, "reason": recovery_reason,
                           "method": "full_recovery", "message": full_message},
            }

        attempts = self._recovery_failures.get(task_key, 0) + 1
        self._recovery_failures[task_key] = attempts
        escalation = {
            "agent_id": agent_id, "reason": recovery_reason,
            "attempts": str(attempts),
            "message": (f"attempt_recovery failed: {message}; "
                        f"full_recovery failed: {full_message or 'not_executed'}"),
        }
        if attempts >= self.max_recovery_attempts:
            failed = await self._finalize_failed_task(app_ctx, agent_id, agent, message)
            self._recovery_failures.pop(task_key, None)
            return {"status": "failed", "detail": escalation, "failed_task": failed}
        return {"status": "escalated", "detail": escalation}

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
        dashboard = None

        if app_ctx is not None:
            if app_ctx.dashboard_manager is not None:
                dashboard = app_ctx.dashboard_manager
            else:
                try:
                    from src.tools.helpers_managers import ensure_dashboard_manager

                    dashboard = ensure_dashboard_manager(app_ctx)
                except (ImportError, OSError, AttributeError, ValueError) as e:
                    logger.debug("Dashboard マネージャー取得に失敗: %s", e)
                    dashboard = None

        for agent_id, agent in list(self.agents.items()):
            if agent.role != AgentRole.WORKER.value:
                continue
            if agent.status == AgentStatus.TERMINATED.value:
                skipped.append(agent_id)
                continue

            if agent.status in (AgentStatus.TERMINATED, AgentStatus.TERMINATED.value):
                stale_keys = [
                    key
                    for key in self._recovery_failures
                    if key.startswith(f"{agent_id}:")
                ]
                for stale_key in stale_keys:
                    self._recovery_failures.pop(stale_key, None)
                skipped.append(agent_id)
                continue

            if agent.status in (AgentStatus.TERMINATED, AgentStatus.TERMINATED.value):
                stale_keys = [
                    key
                    for key in self._recovery_failures
                    if key.startswith(f"{agent_id}:")
                ]
                for stale_key in stale_keys:
                    self._recovery_failures.pop(stale_key, None)
                skipped.append(agent_id)
                continue

            active_task, active_task_id = self._sync_worker_active_task(
                agent_id, agent, dashboard, app_ctx,
            )

            current_key = self._recovery_key(agent_id, active_task_id)
            stale_keys = [
                key
                for key in self._recovery_failures
                if key.startswith(f"{agent_id}:") and key != current_key
            ]
            for stale_key in stale_keys:
                self._recovery_failures.pop(stale_key, None)

            if not active_task_id and agent.status == AgentStatus.IDLE.value:
                skipped.append(agent_id)
                continue

            if active_task_id is not None:
                agent.current_task = active_task_id

            recovery_reason, force_recovery = await self._diagnose_worker_issue(
                agent_id, agent, active_task, now,
            )

            if recovery_reason is None:
                continue

            if dashboard is not None:
                try:
                    dashboard.increment_process_crash_count()
                except (AttributeError, ValueError) as e:
                    logger.debug("process_crash_count 更新に失敗: %s", e)

            result = await self._attempt_staged_recovery(
                app_ctx, agent_id, agent, recovery_reason, force_recovery, current_key,
            )

            if result["status"] == "recovered":
                if dashboard is not None:
                    try:
                        dashboard.increment_process_recovery_count()
                    except (AttributeError, ValueError) as e:
                        logger.debug("process_recovery_count 更新に失敗: %s", e)
                recovered.append(result["detail"])
            elif result["status"] == "escalated":
                escalated.append(result["detail"])
            elif result["status"] == "failed":
                escalated.append(result["detail"])
                failed_tasks.append(result["failed_task"])

        return {
            "recovered": recovered,
            "escalated": escalated,
            "failed_tasks": failed_tasks,
            "skipped": skipped,
            "healthcheck_interval_seconds": self.healthcheck_interval_seconds,
            "stall_timeout_seconds": self.stall_timeout_seconds,
            "in_progress_no_ipc_timeout_seconds": self.in_progress_no_ipc_timeout_seconds,
            "max_recovery_attempts": self.max_recovery_attempts,
            "last_monitor_at": self.last_monitor_at.isoformat(),
        }
