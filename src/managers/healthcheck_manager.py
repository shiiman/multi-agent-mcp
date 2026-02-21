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
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.context import AppContext
    from src.managers.dashboard_manager import DashboardManager
    from src.managers.tmux_manager import TmuxManager
    from src.models.agent import Agent
    from src.models.dashboard import TaskInfo

logger = logging.getLogger(__name__)

_SHELL_COMMANDS = {"zsh", "bash", "sh", "fish"}
_AI_RUNNING_COMMAND_PREFIXES = ("codex", "claude", "gemini", "agent", "cursor-agent")


def _is_ai_running(pane_command: str) -> bool:
    """pane_current_command が AI CLI 実行中かを判定する。

    tmux の pane_current_command は ``codex-aarch64-a`` のように
    アーキテクチャサフィックス付きの派生名を返すことがあるため、
    前方一致で判定する。
    """
    normalized = pane_command.strip().lower()
    return normalized.startswith(_AI_RUNNING_COMMAND_PREFIXES)


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
    def _persist_agent(app_ctx: "AppContext | None", agent: "Agent") -> bool:
        """エージェント状態をファイルに永続化する。

        循環参照回避のため遅延 import を1箇所に集約している。
        （src.tools.__init__ が src.context を再帰 import するため
        トップレベル import は不可）
        """
        if app_ctx is None:
            return False
        from src.tools.helpers_persistence import save_agent_to_file

        return save_agent_to_file(app_ctx, agent)

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
        if not session_name or agent.window_index is None or agent.pane_index is None:
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

    async def _is_pane_unchanged_for(
        self,
        agent_id: str,
        agent: "Agent",
        timeout_seconds: int,
        now: datetime,
    ) -> bool:
        """ペインの出力が指定時間以上変化していないかを判定する。

        Args:
            agent_id: エージェントID
            agent: エージェントオブジェクト
            timeout_seconds: 判定に使うタイムアウト秒数
            now: 現在時刻

        Returns:
            ペインが timeout_seconds 以上変化していなければ True
        """
        pane_hash = await self._capture_pane_hash(agent)
        if pane_hash is None:
            # pane 情報が取得できない場合は異常扱い
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

        return await self._is_pane_unchanged_for(
            agent_id, agent, self.stall_timeout_seconds, now
        )

    @staticmethod
    def _task_activity_at(active_task: "TaskInfo") -> datetime | None:
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
        active_task: "TaskInfo",
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

        return await self._is_pane_unchanged_for(
            agent_id, agent, timeout_seconds, now
        )

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
        """全エージェントのヘルスチェックを並列で行う。"""
        import asyncio

        coros = [self.check_agent(agent_id) for agent_id in self.agents]
        return list(await asyncio.gather(*coros))

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
                code, _, stderr = await self.tmux_manager._run("send-keys", "-t", target, "C-c")
                if code != 0:
                    return False, f"強制復旧に失敗しました: {stderr}"
                return True, f"エージェント {agent_id} に割り込みを送信しました"
            except (OSError, subprocess.SubprocessError) as e:
                return False, f"強制復旧に失敗しました: {e}"

        logger.info("エージェント %s の tmux セッションを再作成します", agent_id)
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

    async def _run_full_recovery(
        self, app_ctx: "AppContext", agent_id: str
    ) -> dict[str, Any]:
        """段階復旧の 2 段目として full_recovery を実行する。"""
        try:
            # 循環参照回避のため遅延 import（tools レイヤーの関数）
            from src.tools.healthcheck import execute_full_recovery

            result = await execute_full_recovery(app_ctx, agent_id)
            if not result.get("success"):
                return {
                    "status": "failed",
                    "message": result.get("error", result.get("message", "full_recovery failed")),
                    "resume_required_task_ids": [],
                }

            recovery_status = str(result.get("recovery_status", "recovered"))
            return {
                "status": recovery_status,
                "message": result.get("message", "full_recovery succeeded"),
                "resume_required_task_ids": result.get("resume_required_task_ids", []),
            }
        except (OSError, subprocess.SubprocessError, ImportError, ValueError) as e:
            return {
                "status": "failed",
                "message": str(e),
                "resume_required_task_ids": [],
            }

    @staticmethod
    def _compose_recovery_failure_reason(
        recovery_reason: str,
        attempt_error: str,
        full_recovery_status: str,
        full_recovery_error: str,
    ) -> str:
        """復旧失敗理由を一貫した粒度で文字列化する。"""
        return (
            f"recovery_reason={recovery_reason}; "
            f"attempt_recovery_error={attempt_error or 'none'}; "
            f"full_recovery_status={full_recovery_status}; "
            f"full_recovery_error={full_recovery_error or 'none'}"
        )

    async def _notify_admins_task_failed(
        self,
        app_ctx: "AppContext",
        dashboard: "DashboardManager | None",
        agent_id: str,
        task_id: str,
        reason: str,
    ) -> str | None:
        """タスク失敗を dashboard 更新 + Admin IPC 通知する。エラー時は文字列を返す。"""
        import asyncio

        try:
            from src.models.dashboard import TaskStatus
            from src.models.message import MessagePriority, MessageType

            if dashboard is not None:
                await asyncio.to_thread(
                    dashboard.update_task_status,
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error_message=f"healthcheck_recovery_failed: {reason}",
                )
                if app_ctx.project_root and app_ctx.session_id:
                    await asyncio.to_thread(
                        dashboard.save_markdown_dashboard,
                        Path(app_ctx.project_root),
                        app_ctx.session_id,
                    )

            ipc = app_ctx.ipc_manager
            if ipc is None:
                return None
            admin_ids = [wid for wid, w in self.agents.items() if w.role == "admin"]
            for aid in admin_ids:
                if aid not in ipc.get_all_agent_ids():
                    ipc.register_agent(aid)
                ipc.send_message(
                    sender_id="healthcheck-daemon",
                    receiver_id=aid,
                    message_type=MessageType.ERROR,
                    subject=f"task failed by healthcheck: {task_id}",
                    content=(
                        f"Worker {agent_id} の復旧上限超過により task {task_id} "
                        f"を failed 化。理由: {reason}"
                    ),
                    priority=MessagePriority.HIGH,
                    metadata={"agent_id": agent_id, "task_id": task_id, "reason": reason},
                )
        except (OSError, KeyError, ValueError) as e:
            return str(e)
        return None

    async def _finalize_failed_task(
        self,
        app_ctx: "AppContext | None",
        dashboard: "DashboardManager | None",
        agent_id: str,
        agent: "Agent",
        reason: str,
    ) -> dict[str, str]:
        """復旧失敗上限を超えたタスクを failed 化し、Admin に通知する。"""
        from src.models.agent import AgentStatus

        task_id = agent.current_task
        detail = {"agent_id": agent_id, "task_id": task_id or "", "reason": reason}

        if app_ctx is not None and task_id:
            err = await self._notify_admins_task_failed(
                app_ctx, dashboard, agent_id, task_id, reason
            )
            if err:
                detail["notify_error"] = err
            try:
                # reset_agent_to_idle をインライン化（helpers.py への逆依存を回避）
                agent.current_task = None
                agent.status = AgentStatus.IDLE
                agent.last_activity = datetime.now()
                self._persist_agent(app_ctx, agent)
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
        dashboard: "DashboardManager | None",
        app_ctx: "AppContext | None",
    ) -> tuple["TaskInfo | None", str | None]:
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
                        self._persist_agent(app_ctx, agent)
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
                        self._persist_agent(app_ctx, agent)
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
        active_task: "TaskInfo | None",
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
            # AI CLI が実行中でセッション健全な場合は
            # no-IPC だけで強制復旧しない（長時間推論で誤検知しやすいため）。
            if _is_ai_running(pane_command):
                logger.info(
                    "in_progress_no_ipc をスキップ: agent=%s pane=%s",
                    agent_id,
                    pane_command,
                )
            else:
                return "in_progress_no_ipc", True

        if await self._is_worker_stalled(agent_id, agent, now):
            pane_command = (health.pane_current_command or "").strip().lower()
            if _is_ai_running(pane_command):
                logger.info(
                    "task_stalled をスキップ: agent=%s pane=%s（AI CLI 実行中）",
                    agent_id,
                    pane_command,
                )
            else:
                return "task_stalled", True

        return None, False

    def _save_agent_after_recovery(
        self,
        app_ctx: "AppContext | None",
        agent: "Agent",
        label: str,
    ) -> None:
        """復旧後のエージェント保存。"""
        if app_ctx is None:
            return
        try:
            agent.ai_bootstrapped = False
            self._persist_agent(app_ctx, agent)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.debug("%s 後のエージェント保存に失敗: %s", label, e)

    def _increment_recovery_counter(
        self,
        dashboard: "DashboardManager | None",
        agent_id: str,
        task_id: str | None,
        recovery_reason: str,
    ) -> None:
        """復旧成功時のカウンタを更新する。

        Dashboard の拡張フィールドが存在する場合はそれも更新し、
        未拡張環境では task.metadata のみ更新する。
        """
        if dashboard is None or not task_id:
            return

        try:
            run_transaction = getattr(dashboard, "run_dashboard_transaction", None)
            if not callable(run_transaction):
                return

            def _mutate_dashboard(dashboard_data: Any) -> None:
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

                if not updated:
                    return

            run_transaction(_mutate_dashboard)
        except (
            OSError,
            TimeoutError,
            ValueError,
            AttributeError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as e:
            logger.debug("復旧カウンタ更新に失敗: %s", e)

    @staticmethod
    def _resolve_resume_task_content(
        app_ctx: "AppContext",
        task: "TaskInfo",
    ) -> tuple[str | None, str | None]:
        """resume_pending 時に再送する task_content を解決する。

        優先順位:
        1. metadata.requested_description
        2. task_file_path の実ファイル内容
        3. description
        4. title

        Returns:
            (task_content, error_message)
        """
        metadata = dict(getattr(task, "metadata", {}) or {})
        requested = metadata.get("requested_description")
        if isinstance(requested, str) and requested.strip():
            return requested.strip(), None

        task_file_path = getattr(task, "task_file_path", None)
        if isinstance(task_file_path, str) and task_file_path.strip():
            project_root = Path(str(app_ctx.project_root or ".")).resolve()
            file_path = Path(task_file_path)
            if not file_path.is_absolute():
                file_path = project_root / file_path
            file_path = file_path.resolve()
            # project_root 配下のみ許可（パストラバーサル防止）
            try:
                file_path.relative_to(project_root)
            except ValueError:
                return None, f"task_file_path is outside project_root: {task_file_path}"
            try:
                text = file_path.read_text(encoding="utf-8").strip()
                if text:
                    return text, None
            except OSError as e:
                return None, f"task_file read failed: {e}"

        description = str(getattr(task, "description", "") or "").strip()
        if description:
            return description, None

        title = str(getattr(task, "title", "") or "").strip()
        if title:
            return title, None
        return None, "task content is empty"

    async def _resume_single_task(
        self,
        app_ctx: "AppContext",
        dashboard: "DashboardManager",
        agent: "Agent",
        task_id: str,
        session_id: str,
        worker_no: int,
        worker_index: int,
        enable_worktree: bool,
        profile_settings: Any,
        caller_agent_id: str | None,
        send_task_fn: Any,
    ) -> dict[str, str] | None:
        """個別タスクの再送を試みる。失敗時は dict を返し、成功時は None を返す。"""
        task = dashboard.get_task(task_id)
        if task is None:
            return {"task_id": task_id, "error": "task not found"}

        task_content, content_error = self._resolve_resume_task_content(app_ctx, task)
        if task_content is None:
            return {"task_id": task_id, "error": content_error or "task content unavailable"}

        branch = (
            str(task.branch)
            if getattr(task, "branch", None)
            else str(getattr(agent, "branch", "") or "")
        )
        if not branch:
            branch = f"worker-{worker_no}"

        task_worktree = (
            str(task.worktree_path)
            if getattr(task, "worktree_path", None)
            else str(agent.worktree_path or agent.working_dir or app_ctx.project_root or ".")
        )

        send_result = await send_task_fn(
            app_ctx,
            agent,
            task_content,
            task_id,
            branch,
            task_worktree,
            session_id,
            worker_index,
            enable_worktree,
            profile_settings,
            caller_agent_id,
        )
        if bool(send_result.get("task_sent")):
            return None

        return {
            "task_id": task_id,
            "error": str(send_result.get("dispatch_error") or "dispatch failed"),
        }

    @staticmethod
    def _resolve_worker_dispatch_params(
        app_ctx: "AppContext",
        agent: "Agent",
        resolve_worker_number_from_slot: Any,
        get_current_profile_settings: Any,
    ) -> tuple[int, int, Any, bool, str | None]:
        """Worker番号・プロファイル設定・Admin IDを解決する。

        Returns:
            (worker_no, worker_index, profile_settings, enable_worktree, caller_agent_id)
        """
        profile_settings = get_current_profile_settings(app_ctx)
        enable_worktree = bool(app_ctx.settings.is_worktree_enabled())

        worker_no = 1
        if agent.window_index is not None and agent.pane_index is not None:
            try:
                worker_no = resolve_worker_number_from_slot(
                    app_ctx.settings, agent.window_index, agent.pane_index
                )
            except (ValueError, TypeError):
                worker_no = 1
        worker_index = max(worker_no - 1, 0)

        admin_ids = [
            aid
            for aid, a in app_ctx.agents.items()
            if str(getattr(getattr(a, "role", ""), "value", getattr(a, "role", ""))) == "admin"
        ]
        caller_agent_id = admin_ids[0] if admin_ids else None

        return worker_no, worker_index, profile_settings, enable_worktree, caller_agent_id

    async def _auto_resume_tasks_after_recovery(
        self,
        app_ctx: "AppContext | None",
        dashboard: "DashboardManager | None",
        agent_id: str,
        resume_task_ids: list[str],
    ) -> dict[str, Any]:
        """full_recovery 後に resume_pending タスクを自動再送する。"""
        if app_ctx is None:
            return {"success": False, "error": "app_ctx is None", "resumed": [], "failed": []}
        if not resume_task_ids:
            return {"success": True, "resumed": [], "failed": []}

        session_id = str(app_ctx.session_id or "")
        if not session_id:
            return {"success": False, "error": "session_id is missing", "resumed": [], "failed": []}

        agent = app_ctx.agents.get(agent_id)
        if agent is None:
            return {"success": False, "error": f"agent not found: {agent_id}", "resumed": [], "failed": []}

        if dashboard is None:
            return {"success": False, "error": "dashboard is None", "resumed": [], "failed": []}

        try:
            # 循環参照回避のため遅延 import（tools レイヤーの関数）
            from src.tools.agent_helpers import (
                _send_task_to_worker,
                resolve_worker_number_from_slot,
            )
            from src.tools.model_profile import get_current_profile_settings
        except ImportError as e:
            return {"success": False, "error": str(e), "resumed": [], "failed": []}

        worker_no, worker_index, profile_settings, enable_worktree, caller_agent_id = (
            self._resolve_worker_dispatch_params(
                app_ctx, agent, resolve_worker_number_from_slot, get_current_profile_settings
            )
        )

        resumed: list[str] = []
        failed: list[dict[str, str]] = []
        for task_id in resume_task_ids:
            error = await self._resume_single_task(
                app_ctx, dashboard, agent, task_id, session_id,
                worker_no, worker_index, enable_worktree,
                profile_settings, caller_agent_id, _send_task_to_worker,
            )
            if error is None:
                resumed.append(task_id)
            else:
                failed.append(error)

        return {"success": len(failed) == 0, "resumed": resumed, "failed": failed}

    async def _handle_resume_pending(
        self,
        app_ctx: "AppContext | None",
        dashboard: "DashboardManager | None",
        agent_id: str,
        recovery_reason: str,
        full_result: dict[str, Any],
        full_message: str,
    ) -> dict[str, Any]:
        """full_recovery の resume_pending 状態を処理する。"""
        resume_ids = [
            str(task_id)
            for task_id in full_result.get("resume_required_task_ids", [])
            if task_id
        ]
        auto_resume = await self._auto_resume_tasks_after_recovery(
            app_ctx, dashboard, agent_id, resume_ids,
        )
        if auto_resume.get("success"):
            return {
                "status": "recovered",
                "detail": {
                    "agent_id": agent_id,
                    "reason": recovery_reason,
                    "method": "full_recovery_auto_resume",
                    "resumed_tasks": ",".join(auto_resume.get("resumed", [])),
                    "message": full_message,
                },
            }

        failed = auto_resume.get("failed", [])
        failed_ids = ",".join(
            [
                str(item.get("task_id"))
                for item in failed
                if isinstance(item, dict) and item.get("task_id")
            ]
        )
        return {
            "status": "escalated",
            "detail": {
                "agent_id": agent_id,
                "reason": recovery_reason,
                "method": "full_recovery",
                "status": "resume_pending",
                "resume_required_tasks": ",".join(resume_ids),
                "auto_resume_failed_tasks": failed_ids,
                "auto_resume_error": str(auto_resume.get("error", "")),
                "message": full_message,
            },
        }

    async def _handle_recovery_escalation(
        self,
        app_ctx: "AppContext | None",
        dashboard: "DashboardManager | None",
        agent_id: str,
        agent: "Agent",
        recovery_reason: str,
        message: str,
        full_status: str,
        full_message: str,
        task_key: str,
    ) -> dict[str, Any]:
        """復旧失敗時のエスカレーション / failed 化を処理する。"""
        attempts = self._recovery_failures.get(task_key, 0) + 1
        self._recovery_failures[task_key] = attempts
        failure_reason = self._compose_recovery_failure_reason(
            recovery_reason=recovery_reason,
            attempt_error=message,
            full_recovery_status=full_status,
            full_recovery_error=full_message,
        )
        escalation = {
            "agent_id": agent_id,
            "reason": recovery_reason,
            "attempts": str(attempts),
            "attempt_recovery_error": message,
            "full_recovery_status": full_status,
            "full_recovery_error": full_message,
            "message": failure_reason,
        }
        if attempts >= self.max_recovery_attempts:
            failed = await self._finalize_failed_task(
                app_ctx, dashboard, agent_id, agent, failure_reason,
            )
            self._recovery_failures.pop(task_key, None)
            return {"status": "failed", "detail": escalation, "failed_task": failed}
        return {"status": "escalated", "detail": escalation}

    async def _attempt_staged_recovery(
        self,
        app_ctx: "AppContext | None",
        dashboard: "DashboardManager | None",
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
                dashboard, agent_id, recovery_task_id, recovery_reason,
            )
            self._recovery_failures.pop(task_key, None)
            return {
                "status": "recovered",
                "detail": {
                    "agent_id": agent_id,
                    "reason": recovery_reason,
                    "method": "attempt_recovery",
                    "message": message,
                },
            }

        full_result: dict[str, Any] = {
            "status": "not_executed",
            "message": "not_executed",
            "resume_required_task_ids": [],
        }
        if app_ctx is not None:
            full_result = await self._run_full_recovery(app_ctx, agent_id)

        full_status = str(full_result.get("status", "failed"))
        full_message = str(full_result.get("message", "full_recovery failed"))
        if full_status == "recovered":
            target = (app_ctx.agents.get(agent_id) if app_ctx else None) or agent
            self._save_agent_after_recovery(app_ctx, target, "full_recovery")
            self._increment_recovery_counter(
                dashboard, agent_id, recovery_task_id, recovery_reason,
            )
            self._recovery_failures.pop(task_key, None)
            return {
                "status": "recovered",
                "detail": {
                    "agent_id": agent_id,
                    "reason": recovery_reason,
                    "method": "full_recovery",
                    "message": full_message,
                },
            }

        if full_status == "resume_pending":
            self._recovery_failures.pop(task_key, None)
            return await self._handle_resume_pending(
                app_ctx, dashboard, agent_id, recovery_reason, full_result, full_message,
            )

        return await self._handle_recovery_escalation(
            app_ctx, dashboard, agent_id, agent,
            recovery_reason, message, full_status, full_message, task_key,
        )

    def _collect_workers_to_diagnose(
        self,
        app_ctx: "AppContext | None",
        dashboard: "DashboardManager | None",
    ) -> tuple[list[tuple[str, "Agent", "TaskInfo | None", str | None, str]], list[str]]:
        """フェーズ1: 診断対象の Worker を収集する。

        Returns:
            (workers_to_diagnose, skipped)
        """
        from src.models.agent import AgentRole, AgentStatus

        workers_to_diagnose: list[
            tuple[str, "Agent", "TaskInfo | None", str | None, str]
        ] = []
        skipped: list[str] = []

        for agent_id, agent in list(self.agents.items()):
            if agent.role != AgentRole.WORKER.value:
                continue
            if agent.status in (AgentStatus.TERMINATED, AgentStatus.TERMINATED.value):
                stale_keys = [
                    key for key in self._recovery_failures if key.startswith(f"{agent_id}:")
                ]
                for stale_key in stale_keys:
                    self._recovery_failures.pop(stale_key, None)
                skipped.append(agent_id)
                continue

            active_task, active_task_id = self._sync_worker_active_task(
                agent_id, agent, dashboard, app_ctx
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

            workers_to_diagnose.append(
                (agent_id, agent, active_task, active_task_id, current_key)
            )

        return workers_to_diagnose, skipped

    async def _process_recovery_results(
        self,
        app_ctx: "AppContext | None",
        dashboard: "DashboardManager | None",
        workers_to_diagnose: list[tuple[str, "Agent", "TaskInfo | None", str | None, str]],
        diagnose_results: list[Any],
    ) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
        """フェーズ3: 診断結果に基づき復旧を逐次実行する。

        Returns:
            (recovered, escalated, failed_tasks)
        """
        recovered: list[dict[str, str]] = []
        escalated: list[dict[str, str]] = []
        failed_tasks: list[dict[str, str]] = []

        for (
            agent_id, agent, _active_task, _active_task_id, current_key
        ), diag_result in zip(workers_to_diagnose, diagnose_results):
            if isinstance(diag_result, Exception):
                logger.debug("Worker 診断に失敗: agent=%s error=%s", agent_id, diag_result)
                continue

            recovery_reason, force_recovery = diag_result
            if recovery_reason is None:
                continue

            if dashboard is not None:
                try:
                    dashboard.increment_process_crash_count()
                except (AttributeError, ValueError) as e:
                    logger.debug("process_crash_count 更新に失敗: %s", e)

            result = await self._attempt_staged_recovery(
                app_ctx, dashboard, agent_id, agent, recovery_reason, force_recovery, current_key
            )

            if result["status"] == "recovered":
                if dashboard is not None:
                    try:
                        dashboard.increment_process_recovery_count()
                    except (AttributeError, ValueError) as e:
                        logger.debug("process_recovery_count 更新に失敗: %s", e)
                recovered.append(result["detail"])
            elif result["status"] in ("escalated", "failed"):
                escalated.append(result["detail"])
                if result["status"] == "failed":
                    failed_tasks.append(result["failed_task"])

        return recovered, escalated, failed_tasks

    async def monitor_and_recover_workers(
        self, app_ctx: "AppContext | None" = None
    ) -> dict[str, Any]:
        """Worker の健全性を監視し、必要なら段階復旧する。"""
        import asyncio

        now = datetime.now()
        self.last_monitor_at = now
        self._prune_state()

        dashboard: DashboardManager | None = (
            app_ctx.dashboard_manager if app_ctx is not None else None
        )

        # フェーズ1: 診断対象の Worker を収集（同期処理）
        workers_to_diagnose, skipped = self._collect_workers_to_diagnose(app_ctx, dashboard)

        # フェーズ2: 診断を並列実行
        diagnose_results = await asyncio.gather(
            *[
                self._diagnose_worker_issue(agent_id, agent, active_task, now)
                for agent_id, agent, active_task, _active_task_id, _current_key
                in workers_to_diagnose
            ],
            return_exceptions=True,
        )

        # フェーズ3: 復旧は副作用があるため逐次実行
        recovered, escalated, failed_tasks = await self._process_recovery_results(
            app_ctx, dashboard, workers_to_diagnose, diagnose_results
        )

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
