"""Dashboard の外部同期ロジック mixin。"""

import copy
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src.models.dashboard import AgentSummary, MessageSummary, TaskStatus

logger = logging.getLogger(__name__)


class DashboardSyncMixin:
    """agents.json / IPC との同期機能を提供する mixin。"""

    _IPC_SYNC_STATE_VERSION = 1
    _last_sync_report: dict[str, Any] | None = None

    @staticmethod
    def _build_sync_stage_report() -> dict[str, Any]:
        """同期ステージの初期レポートを作成する。"""
        return {"success": True, "count": 0, "error": None}

    @staticmethod
    def _format_sync_error(error: Exception) -> dict[str, str]:
        """例外を構造化エラー情報へ変換する。"""
        return {"type": type(error).__name__, "message": str(error)}

    def get_last_sync_report(self) -> dict[str, Any] | None:
        """直近の同期実行レポートを取得する。"""
        if self._last_sync_report is None:
            return None
        return copy.deepcopy(self._last_sync_report)

    def _get_ipc_sync_state_path(self) -> Path:
        """IPC 差分同期用の状態ファイルパスを返す。"""
        return self.dashboard_dir / "ipc_sync_state.json"

    @staticmethod
    def _serialize_message_summary(message: MessageSummary) -> dict[str, Any]:
        """MessageSummary を JSON 互換 dict に変換する。"""
        return {
            "sender_id": message.sender_id,
            "receiver_id": message.receiver_id,
            "message_type": message.message_type,
            "subject": message.subject,
            "content": message.content,
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }

    @staticmethod
    def _deserialize_message_summary(payload: dict[str, Any]) -> MessageSummary | None:
        """JSON dict から MessageSummary を復元する。"""
        created_at = payload.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except ValueError:
                created_at = None
        elif not isinstance(created_at, datetime):
            created_at = None

        try:
            return MessageSummary(
                sender_id=str(payload.get("sender_id", "")),
                receiver_id=payload.get("receiver_id"),
                message_type=str(payload.get("message_type", "")),
                subject=str(payload.get("subject", "")),
                content=str(payload.get("content", "")),
                created_at=created_at,
            )
        except (TypeError, ValueError):
            return None

    def _set_ipc_sync_cache(
        self,
        ipc_dir: Path,
        messages: list[MessageSummary],
        cursors: dict[str, str],
    ) -> None:
        """IPC 同期状態をインメモリキャッシュへ保存する。"""
        self._ipc_sync_cache_ipc_dir = str(ipc_dir.resolve())
        self._ipc_sync_cache_messages = [msg.model_copy(deep=True) for msg in messages]
        self._ipc_sync_cache_cursors = dict(cursors)
        state_path = self._get_ipc_sync_state_path()
        try:
            self._ipc_sync_cache_mtime = state_path.stat().st_mtime_ns
        except OSError:
            self._ipc_sync_cache_mtime = 0

    def _clear_ipc_sync_cache(self) -> None:
        """IPC 同期状態のインメモリキャッシュをクリアする。"""
        self._ipc_sync_cache_ipc_dir = None
        self._ipc_sync_cache_messages = None
        self._ipc_sync_cache_cursors = None
        self._ipc_sync_cache_mtime = 0

    def _load_ipc_sync_state(
        self,
        ipc_dir: Path,
    ) -> tuple[list[MessageSummary], dict[str, str], bool]:
        """永続化済み IPC 同期状態を読み込む。"""
        resolved_ipc_dir = str(ipc_dir.resolve())
        cached_ipc_dir = self._ipc_sync_cache_ipc_dir
        cached_messages = self._ipc_sync_cache_messages
        cached_cursors = self._ipc_sync_cache_cursors
        state_path = self._get_ipc_sync_state_path()
        try:
            current_mtime_ns = state_path.stat().st_mtime_ns
        except OSError:
            current_mtime_ns = 0
        if (
            cached_ipc_dir == resolved_ipc_dir
            and isinstance(cached_messages, list)
            and isinstance(cached_cursors, dict)
            and current_mtime_ns != 0
            and current_mtime_ns == self._ipc_sync_cache_mtime
        ):
            return (
                [msg.model_copy(deep=True) for msg in cached_messages],
                dict(cached_cursors),
                True,
            )

        state_path = self._get_ipc_sync_state_path()
        if not state_path.exists():
            self._clear_ipc_sync_cache()
            return [], {}, False

        try:
            with open(state_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("IPC 同期状態の読み込みに失敗: %s", e)
            self._clear_ipc_sync_cache()
            return [], {}, False

        if data.get("version") != self._IPC_SYNC_STATE_VERSION:
            self._clear_ipc_sync_cache()
            return [], {}, False

        state_ipc_dir = data.get("ipc_dir")
        if not isinstance(state_ipc_dir, str) or state_ipc_dir != resolved_ipc_dir:
            self._clear_ipc_sync_cache()
            return [], {}, False

        raw_messages = data.get("messages")
        raw_cursors = data.get("cursors")
        if not isinstance(raw_messages, list) or not isinstance(raw_cursors, dict):
            self._clear_ipc_sync_cache()
            return [], {}, False

        messages: list[MessageSummary] = []
        for raw_message in raw_messages:
            if not isinstance(raw_message, dict):
                continue
            message = self._deserialize_message_summary(raw_message)
            if message is not None:
                messages.append(message)
        messages.sort(key=lambda m: m.created_at or datetime.min)

        cursors: dict[str, str] = {}
        for agent_id, filename in raw_cursors.items():
            if isinstance(agent_id, str) and isinstance(filename, str):
                cursors[agent_id] = filename

        self._set_ipc_sync_cache(ipc_dir, messages, cursors)
        return ([msg.model_copy(deep=True) for msg in messages], dict(cursors), True)

    def _write_ipc_sync_state(
        self,
        ipc_dir: Path,
        messages: list[MessageSummary],
        cursors: dict[str, str],
    ) -> None:
        """IPC 差分同期状態を永続化する。"""
        payload = {
            "version": self._IPC_SYNC_STATE_VERSION,
            "ipc_dir": str(ipc_dir.resolve()),
            "updated_at": datetime.now().isoformat(),
            "messages": [self._serialize_message_summary(msg) for msg in messages],
            "cursors": dict(sorted(cursors.items())),
        }
        self._atomic_write_text(
            self._get_ipc_sync_state_path(),
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        self._set_ipc_sync_cache(ipc_dir, messages, cursors)

    def _collect_all_ipc_messages(
        self, ipc_dir: Path
    ) -> tuple[list[MessageSummary], dict[str, str], int]:
        """IPC メッセージを全件収集する。"""
        all_messages: list[MessageSummary] = []
        cursors: dict[str, str] = {}
        parsed_files = 0

        for agent_dir in sorted(ipc_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            message_files = sorted(agent_dir.glob("*.md"))
            if not message_files:
                continue
            cursors[agent_dir.name] = message_files[-1].name
            for msg_file in message_files:
                parsed_files += 1
                message = self._parse_ipc_message(msg_file)
                if message is not None:
                    all_messages.append(message)

        all_messages.sort(key=lambda m: m.created_at or datetime.min)
        return all_messages, cursors, parsed_files

    def _collect_delta_ipc_messages(
        self,
        ipc_dir: Path,
        cached_messages: list[MessageSummary],
        cached_cursors: dict[str, str],
    ) -> tuple[list[MessageSummary], dict[str, str], int, int]:
        """IPC メッセージを差分収集する。

        前提: メッセージファイル名は ``{timestamp}_{uuid}.md`` 形式
        （IPCManager._generate_filename() で生成）のため、辞書順ソートが
        時系列順と一致する。カーソル比較（``msg_file.name <= last_seen``）は
        この命名規則に依存している。
        """
        new_messages: list[MessageSummary] = []
        next_cursors: dict[str, str] = {}
        parsed_files = 0

        for agent_dir in sorted(ipc_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            message_files = sorted(agent_dir.glob("*.md"))
            if not message_files:
                continue

            agent_id = agent_dir.name
            last_seen = cached_cursors.get(agent_id)
            next_cursors[agent_id] = message_files[-1].name

            for msg_file in message_files:
                if last_seen and msg_file.name <= last_seen:
                    continue
                parsed_files += 1
                message = self._parse_ipc_message(msg_file)
                if message is not None:
                    new_messages.append(message)

        merged_messages = list(cached_messages)
        if new_messages:
            merged_messages.extend(new_messages)
            merged_messages.sort(key=lambda m: m.created_at or datetime.min)
        return merged_messages, next_cursors, len(new_messages), parsed_files

    def save_markdown_dashboard(self, project_root: Path, session_id: str) -> Path:
        """Markdownダッシュボードをファイルに保存する。

        ロック外で agents.json / IPC メッセージをプリフェッチし、
        ロック内では Dashboard オブジェクト更新と書き込みのみ行う。

        Args:
            project_root: プロジェクトルートパス
            session_id: Issue番号または一意なタスクID（例: "94", "a1b2c3d4"）

        Returns:
            保存したファイルのパス（{session_id}/dashboard/dashboard.md）
        """
        session_dir = self.dashboard_dir.parent  # {mcp_dir}/{session_id}/
        agents_file = session_dir / "agents.json"
        sync_report: dict[str, Any] = {
            "success": True,
            "agents_sync": self._build_sync_stage_report(),
            "ipc_sync": self._build_sync_stage_report(),
            "ipc_checkpoint": self._build_sync_stage_report(),
            "messages_write": self._build_sync_stage_report(),
        }

        # ── ロック外プリフェッチ: agents.json ──
        prefetched_agents: dict | None = None
        agents_file_exists = agents_file.exists()
        if agents_file_exists:
            try:
                with open(agents_file, encoding="utf-8") as f:
                    prefetched_agents = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                sync_report["agents_sync"]["success"] = False
                sync_report["agents_sync"]["error"] = self._format_sync_error(e)
                logger.warning("agents.json の読み込みに失敗: %s", e)

        # ── ロック外プリフェッチ: IPC メッセージ ──
        prefetched_messages: list[MessageSummary] | None = None
        ipc_dir = session_dir / "ipc"
        ipc_cursors: dict[str, str] = {}
        ipc_checkpoint_needs_write = False
        if ipc_dir.exists():
            try:
                cached_messages, cached_cursors, has_checkpoint = self._load_ipc_sync_state(ipc_dir)
                if has_checkpoint:
                    (
                        prefetched_messages,
                        ipc_cursors,
                        new_count,
                        parsed_files,
                    ) = self._collect_delta_ipc_messages(
                        ipc_dir,
                        cached_messages,
                        cached_cursors,
                    )
                    sync_report["ipc_sync"]["mode"] = "delta"
                    ipc_checkpoint_needs_write = new_count > 0 or ipc_cursors != cached_cursors
                else:
                    prefetched_messages, ipc_cursors, parsed_files = self._collect_all_ipc_messages(
                        ipc_dir
                    )
                    new_count = len(prefetched_messages)
                    sync_report["ipc_sync"]["mode"] = "full"
                    ipc_checkpoint_needs_write = True
                sync_report["ipc_sync"]["new_messages"] = new_count
                sync_report["ipc_sync"]["parsed_files"] = parsed_files
            except (OSError, ValueError, TypeError) as e:
                sync_report["ipc_sync"]["success"] = False
                sync_report["ipc_sync"]["error"] = self._format_sync_error(e)
                logger.warning("IPC メッセージの収集に失敗: %s", e)

        # ── ロック内: Dashboard 更新 + 書き込み ──
        def _sync(dashboard) -> None:
            if dashboard.session_started_at is None:
                dashboard.session_started_at = datetime.now()

            # 旧データ互換: pending -> completed/failed 直遷移で started_at が欠損した
            # タスクを同期時に補完する。
            for task in dashboard.tasks:
                if (
                    task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
                    and task.started_at is None
                ):
                    task.started_at = task.completed_at or datetime.now()
                if dashboard.session_started_at is None and task.started_at is not None:
                    dashboard.session_started_at = task.started_at

            # プリフェッチ済み agents データを Dashboard に適用
            if prefetched_agents is not None:
                try:
                    dashboard.agents = []
                    for agent_id, agent_dict in prefetched_agents.items():
                        last_activity = agent_dict.get("last_activity")
                        if isinstance(last_activity, str):
                            try:
                                last_activity = datetime.fromisoformat(last_activity)
                            except ValueError:
                                last_activity = None

                        role = agent_dict.get("role")
                        name = None
                        if role == "owner":
                            name = "owner"
                        elif role == "admin":
                            name = "admin"
                        elif role == "worker":
                            ai_cli = agent_dict.get("ai_cli")
                            if isinstance(ai_cli, dict):
                                cli_name = str(ai_cli.get("value", "worker"))
                            else:
                                cli_name = str(ai_cli or "worker")
                            name = self._build_worker_name(
                                agent_dict.get("id", agent_id),
                                cli_name,
                                window_index=agent_dict.get("window_index"),
                                pane_index=agent_dict.get("pane_index"),
                            )

                        summary = AgentSummary(
                            agent_id=agent_dict.get("id", agent_id),
                            name=name,
                            role=agent_dict.get("role"),
                            status=agent_dict.get("status"),
                            current_task_id=agent_dict.get("current_task"),
                            worktree_path=agent_dict.get("worktree_path"),
                            branch=None,
                            last_activity=last_activity,
                        )
                        dashboard.agents.append(summary)

                    # タスクリカバリ: agents.json に current_task があるが
                    # dashboard.tasks に対応タスクが存在しない場合、スタブを復元する
                    existing_task_ids = {t.id for t in dashboard.tasks}
                    for agent_summary in dashboard.agents:
                        task_id = agent_summary.current_task_id
                        if task_id and task_id not in existing_task_ids:
                            from src.models.dashboard import TaskInfo

                            stub_task = TaskInfo(
                                id=task_id,
                                title=f"(復元) タスク {task_id[:8]}",
                                description="",
                                task_file_path=None,
                                status=TaskStatus.IN_PROGRESS,
                                assigned_agent_id=agent_summary.agent_id,
                                metadata={"recovered_from": "agents.json"},
                                created_at=datetime.now(),
                                started_at=datetime.now(),
                            )
                            dashboard.tasks.append(stub_task)
                            existing_task_ids.add(task_id)
                            logger.warning(
                                "タスク %s を agents.json から復元しました（担当: %s）",
                                task_id,
                                agent_summary.agent_id,
                            )

                    dashboard.calculate_stats()
                    logger.debug(
                        "agents.json から %d 件のエージェントを同期",
                        len(dashboard.agents),
                    )
                    sync_report["agents_sync"]["count"] = len(dashboard.agents)
                except (TypeError, ValueError) as e:
                    sync_report["agents_sync"]["success"] = False
                    sync_report["agents_sync"]["error"] = self._format_sync_error(e)
                    logger.warning("agents データの処理に失敗: %s", e)
            else:
                sync_report["agents_sync"]["count"] = len(dashboard.agents)

            # プリフェッチ済み IPC メッセージを Dashboard に適用
            if prefetched_messages is not None:
                dashboard.messages = prefetched_messages
                logger.debug("IPC メッセージ %d 件を収集", len(dashboard.messages))
                sync_report["ipc_sync"]["count"] = len(dashboard.messages)
            else:
                sync_report["ipc_sync"]["count"] = len(dashboard.messages)

            try:
                self._write_messages_markdown(dashboard)
            except (OSError, ValueError, TypeError) as e:
                sync_report["messages_write"]["success"] = False
                sync_report["messages_write"]["error"] = self._format_sync_error(e)
                logger.warning("messages.md の書き込みに失敗: %s", e)

            if prefetched_messages is not None and ipc_checkpoint_needs_write:
                try:
                    self._write_ipc_sync_state(ipc_dir, dashboard.messages, ipc_cursors)
                    sync_report["ipc_checkpoint"]["count"] = len(ipc_cursors)
                except (OSError, ValueError, TypeError) as e:
                    sync_report["ipc_checkpoint"]["success"] = False
                    sync_report["ipc_checkpoint"]["error"] = self._format_sync_error(e)
                    logger.warning("IPC 同期状態の書き込みに失敗: %s", e)

            sync_report["messages_write"]["count"] = len(dashboard.messages)
            sync_report["success"] = (
                sync_report["agents_sync"]["success"]
                and sync_report["ipc_sync"]["success"]
                and sync_report["ipc_checkpoint"]["success"]
                and sync_report["messages_write"]["success"]
            )

        try:
            self.run_dashboard_transaction(_sync)
        except (ValueError, OSError, Exception) as e:
            # ダッシュボードファイルの読み込みに失敗した場合、
            # 空の Dashboard で上書きしないようにスキップする
            sync_report["success"] = False
            sync_report["read_error"] = self._format_sync_error(e)
            logger.warning("Dashboard 同期をスキップ（読み込みエラー）: %s", e)
        self._last_sync_report = copy.deepcopy(sync_report)
        if not sync_report["success"]:
            logger.warning("Dashboard 同期の部分失敗を検知: %s", sync_report)
        return self._get_dashboard_path()

    def _parse_ipc_message(self, file_path: Path) -> MessageSummary | None:
        """IPC メッセージファイルを軽量パースする。

        Args:
            file_path: メッセージファイルのパス

        Returns:
            MessageSummary またはパース失敗時は None
        """
        try:
            content = file_path.read_text(encoding="utf-8")
            if not content.startswith("---"):
                return None
            parts = content.split("---", 2)
            if len(parts) < 3:
                return None
            front_matter = yaml.safe_load(parts[1])
            if not front_matter:
                return None
            created_at = front_matter.get("created_at")
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            return MessageSummary(
                sender_id=front_matter.get("sender_id", ""),
                receiver_id=front_matter.get("receiver_id"),
                message_type=front_matter.get("message_type", ""),
                subject=front_matter.get("subject", ""),
                content=parts[2].strip(),
                created_at=created_at,
            )
        except Exception as e:
            logger.debug("メッセージサマリーのパースに失敗: %s", e)
            return None
