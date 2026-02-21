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
        if ipc_dir.exists():
            try:
                all_messages: list[MessageSummary] = []
                for agent_dir in ipc_dir.iterdir():
                    if agent_dir.is_dir():
                        for msg_file in agent_dir.glob("*.md"):
                            msg = self._parse_ipc_message(msg_file)
                            if msg:
                                all_messages.append(msg)
                all_messages.sort(key=lambda m: m.created_at or datetime.min)
                prefetched_messages = all_messages
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
                    task.status
                    in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
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

                    dashboard.calculate_stats()
                    logger.debug(
                        f"agents.json から {len(dashboard.agents)} 件のエージェントを同期"
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
                logger.debug(f"IPC メッセージ {len(dashboard.messages)} 件を収集")
                sync_report["ipc_sync"]["count"] = len(dashboard.messages)
            else:
                sync_report["ipc_sync"]["count"] = len(dashboard.messages)

            try:
                self._write_messages_markdown(dashboard)
            except (OSError, ValueError, TypeError) as e:
                sync_report["messages_write"]["success"] = False
                sync_report["messages_write"]["error"] = self._format_sync_error(e)
                logger.warning("messages.md の書き込みに失敗: %s", e)

            sync_report["messages_write"]["count"] = len(dashboard.messages)
            sync_report["success"] = (
                sync_report["agents_sync"]["success"]
                and sync_report["ipc_sync"]["success"]
                and sync_report["messages_write"]["success"]
            )

        self.run_dashboard_transaction(_sync)
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
