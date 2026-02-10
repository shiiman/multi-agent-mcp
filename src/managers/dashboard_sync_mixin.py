"""Dashboard の外部同期ロジック mixin。"""

import json
import logging
from datetime import datetime
from pathlib import Path

import yaml

from src.models.dashboard import AgentSummary, MessageSummary

logger = logging.getLogger(__name__)


class DashboardSyncMixin:
    """agents.json / IPC との同期機能を提供する mixin。"""

    def save_markdown_dashboard(self, project_root: Path, session_id: str) -> Path:
        """Markdownダッシュボードをファイルに保存する。

        Args:
            project_root: プロジェクトルートパス
            session_id: Issue番号または一意なタスクID（例: "94", "a1b2c3d4"）

        Returns:
            保存したファイルのパス（{session_id}/dashboard/dashboard.md）
        """
        session_dir = self.dashboard_dir.parent  # {mcp_dir}/{session_id}/
        agents_file = session_dir / "agents.json"

        def _sync(dashboard) -> None:
            if dashboard.session_started_at is None:
                dashboard.session_started_at = datetime.now()

            # 🔴 agents.json からエージェント情報を同期
            if agents_file.exists():
                try:
                    with open(agents_file, encoding="utf-8") as f:
                        agents_data = json.load(f)

                    dashboard.agents = []
                    for agent_id, agent_dict in agents_data.items():
                        # last_activity を datetime に変換
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
                    logger.debug(f"agents.json から {len(dashboard.agents)} 件のエージェントを同期")
                except Exception as e:
                    logger.warning(f"agents.json の読み込みに失敗: {e}")

            # 🔴 IPC メッセージを収集（Dashboard 表示用）
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
                    # 時系列順ソート（全件保持）
                    all_messages.sort(key=lambda m: m.created_at or datetime.min)
                    dashboard.messages = all_messages
                    logger.debug(f"IPC メッセージ {len(dashboard.messages)} 件を収集")
                except Exception as e:
                    logger.warning(f"IPC メッセージの収集に失敗: {e}")

            self._write_messages_markdown(dashboard)

        self.run_dashboard_transaction(_sync)
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
