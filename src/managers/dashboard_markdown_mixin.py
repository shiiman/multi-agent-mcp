"""Dashboard の Markdown 表示ロジック mixin。"""

import logging
import os
import re
from datetime import datetime
from typing import ClassVar

import yaml

from src.models.dashboard import AgentSummary, Dashboard, TaskStatus

logger = logging.getLogger(__name__)


class DashboardMarkdownMixin:
    """Dashboard の Markdown 生成機能を提供する mixin。"""

    _TASK_STATUS_LABELS_JA: ClassVar[dict[str, str]] = {
        "pending": "未着手",
        "in_progress": "進行中",
        "completed": "完了",
        "failed": "失敗",
        "blocked": "ブロック中",
        "cancelled": "キャンセル",
    }

    def _parse_yaml_front_matter(self, content: str) -> dict | None:
        """YAML Front Matter をパースする。

        Args:
            content: Markdown コンテンツ（YAML Front Matter 付き）

        Returns:
            パースされた辞書、失敗時は None
        """
        # YAML Front Matter のパターン: --- で始まり --- で終わる
        pattern = r"^---\n(.*?)\n---"
        match = re.match(pattern, content, re.DOTALL)
        if match:
            yaml_str = match.group(1)
            return yaml.safe_load(yaml_str)
        return None

    def _generate_markdown_body(self, dashboard: Dashboard) -> str:
        """Dashboard オブジェクトから Markdown 本体を生成する。

        Args:
            dashboard: Dashboard オブジェクト

        Returns:
            Markdown 文字列
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session_started = self._format_dashboard_time(dashboard.session_started_at)
        session_finished = self._format_dashboard_time(dashboard.session_finished_at)

        lines = [
            "# Multi-Agent Dashboard",
            "",
            f"**開始時刻**: {session_started}",
            f"**更新時刻**: {now}",
            f"**終了時刻**: {session_finished}",
        ]

        lines.extend(self._generate_agent_table(dashboard))
        lines.extend(self._generate_task_table(dashboard))
        lines.extend(self._generate_task_details(dashboard))
        lines.extend(self._generate_stats_section(dashboard))

        return "\n".join(lines)

    def _format_dashboard_time(self, value: datetime | None) -> str:
        """ダッシュボード時刻を表示用に整形する。"""
        if value is None:
            return "-"
        return value.strftime("%Y-%m-%d %H:%M:%S")

    def _format_worktree_path(self, worktree_path: str | None, workspace_path: str) -> str:
        """Worktree パスを workspace 基準の相対表記に整形する。"""
        if not worktree_path:
            return "-"

        try:
            return os.path.relpath(worktree_path, workspace_path)
        except Exception as e:
            logger.debug("Worktree パスの相対変換に失敗: %s", e)
            return worktree_path

    def _is_worktree_enabled(self, workspace_path: str | None = None) -> bool:
        """worktree 表示が有効かを返す。"""
        try:
            from src.config.settings import load_effective_settings_for_project

            settings = load_effective_settings_for_project(workspace_path)
            return bool(settings.is_worktree_enabled())
        except Exception as e:
            logger.debug("worktree 有効判定に失敗: %s", e)
            return True

    def _extract_agent_index(self, agent_id: str) -> str:
        """agent_id 末尾の数字を抽出する。"""
        match = re.search(r"(\d+)$", agent_id)
        if match:
            value = match.group(1).lstrip("0")
            return value or "0"
        return agent_id[:4]

    def _resolve_worker_index(
        self, window_index: int | None = None, pane_index: int | None = None
    ) -> int | None:
        """tmux slot から Worker 番号（1始まり）を解決する。"""
        if window_index is None or pane_index is None:
            return None
        if window_index == 0 and pane_index >= 1:
            return pane_index
        if window_index >= 1 and pane_index >= 0:
            # 追加ウィンドウは 2x5 固定（10 workers / window）
            return 6 + ((window_index - 1) * 10) + pane_index + 1
        return None

    def _build_worker_name(
        self,
        agent_id: str,
        fallback: str = "worker",
        window_index: int | None = None,
        pane_index: int | None = None,
    ) -> str:
        """Worker の表示名を作成する（cli + index）。"""
        cli_prefix = fallback.lower()
        if cli_prefix not in ("claude", "codex", "agy", "cursor"):
            cli_prefix = "worker"
        worker_index = self._resolve_worker_index(window_index, pane_index)
        if worker_index is not None:
            return f"{cli_prefix}{worker_index}"
        return f"{cli_prefix}{self._extract_agent_index(agent_id)}"

    def _build_agent_label_map(self, dashboard: Dashboard) -> dict[str, str]:
        """agent_id から表示用ラベルへのマップを作成する。"""
        labels: dict[str, str] = {}
        for agent in dashboard.agents:
            if agent.role == "owner":
                label = "owner"
            elif agent.role == "admin":
                label = "admin"
            elif agent.role == "worker":
                label = agent.name or self._build_worker_name(agent.agent_id)
            else:
                label = agent.role
            labels[agent.agent_id] = label
        return labels

    def _label_for_agent(self, agent: AgentSummary) -> str:
        """エージェントの表示名を返す。"""
        if agent.name:
            return agent.name
        if agent.role == "owner":
            return "owner"
        if agent.role == "admin":
            return "admin"
        if agent.role == "worker":
            return self._build_worker_name(agent.agent_id)
        return agent.role

    def _format_agent_display(
        self,
        agent_id: str | None,
        agent_labels: dict[str, str],
        with_id: bool = False,
    ) -> str:
        """メッセージ表示用のエージェント名を整形する。"""
        if not agent_id:
            return "all"

        label = agent_labels.get(agent_id, "unknown")
        if with_id and label != "unknown":
            return f"{label} ({agent_id[:8]})"
        return label

    def _generate_agent_table(self, dashboard: Dashboard) -> list[str]:
        """エージェント状態テーブルを生成する。"""
        status_emoji = {
            "idle": "🟢",
            "busy": "🔵",
            "error": "🔴",
            "offline": "⚫",
        }

        lines = [
            "",
            "---",
            "",
            "## エージェント状態",
            "",
            "| ID | 名前 | 役割 | 状態 | 現在のタスク |",
            "|:---|:---|:---|:---|:---|",
        ]

        for agent in dashboard.agents:
            emoji = status_emoji.get(str(agent.status).lower(), "⚪")
            current_task = agent.current_task_id or "-"
            name = self._label_for_agent(agent)
            lines.append(
                f"| `{agent.agent_id}` | `{name}` | {agent.role} | {emoji} {agent.status} | "
                f"{current_task} |"
            )

        return lines

    def _generate_task_table(self, dashboard: Dashboard) -> list[str]:
        """タスク状態テーブルを生成する。"""
        task_emoji = {
            "pending": "⏳",
            "in_progress": "🔄",
            "completed": "✅",
            "failed": "❌",
            "blocked": "🚫",
            "cancelled": "🗑️",
        }

        show_worktree = self._is_worktree_enabled(dashboard.workspace_path)
        lines = [
            "",
            "---",
            "",
            "## タスク状態",
            "",
        ]
        if show_worktree:
            lines.extend(
                [
                    "| ID | タイトル | 状態 | 担当 | 進捗 | 開始 | 終了 | worktree |",
                    "|:---|:---|:---|:---|:---|:---|:---|:---|",
                ]
            )
        else:
            lines.extend(
                [
                    "| ID | タイトル | 状態 | 担当 | 進捗 | 開始 | 終了 |",
                    "|:---|:---|:---|:---|:---|:---|:---|",
                ]
            )
        agent_labels = self._build_agent_label_map(dashboard)

        for task in dashboard.tasks:
            status_value = str(task.status.value).lower()
            emoji = task_emoji.get(status_value, "❓")
            status_label = self._TASK_STATUS_LABELS_JA.get(status_value, str(task.status.value))
            assigned = (
                self._format_agent_display(
                    task.assigned_agent_id,
                    agent_labels,
                    with_id=False,
                )
                if task.assigned_agent_id
                else "-"
            )
            started_at = self._format_task_time(task.started_at)
            completed_at = self._format_task_time(task.completed_at)
            if show_worktree:
                worktree = self._format_worktree_path(task.worktree_path, dashboard.workspace_path)
                worktree_cell = f"<details><summary>表示</summary><code>{worktree}</code></details>"
                lines.append(
                    f"| `{task.id[:8]}` | {task.title} | {emoji} {status_label} | "
                    f"`{assigned}` | {task.progress}% | {started_at} | {completed_at} | "
                    f"{worktree_cell} |"
                )
            else:
                lines.append(
                    f"| `{task.id[:8]}` | {task.title} | {emoji} {status_label} | "
                    f"`{assigned}` | {task.progress}% | {started_at} | {completed_at} |"
                )

        return lines

    def _format_task_time(self, value: datetime | None) -> str:
        """タスク時刻を表表示向けに整形する。"""
        if value is None:
            return "-"
        return value.strftime("%H:%M:%S")

    def _generate_task_details(self, dashboard: Dashboard) -> list[str]:
        """進行中/失敗タスクの詳細セクションを生成する。"""
        detail_tasks = [
            t
            for t in dashboard.tasks
            if t.status in (TaskStatus.IN_PROGRESS, TaskStatus.FAILED)
            and (t.checklist or t.logs or t.error_message)
        ]
        if not detail_tasks:
            return []

        lines = [
            "",
            "---",
            "",
            "## タスク詳細",
        ]

        for task in detail_tasks:
            status_value = str(task.status.value).lower()
            status_label = self._TASK_STATUS_LABELS_JA.get(status_value, str(task.status.value))
            lines.extend(
                [
                    "",
                    f"### {task.title}",
                    "",
                    f"**状態**: `{status_label}`",
                    "",
                    f"**進捗**: {task.progress}%",
                ]
            )

            if task.error_message:
                lines.extend(["", f"**エラー**: {task.error_message}"])

            if task.checklist:
                lines.extend(["", "**チェックリスト**:"])
                for item in task.checklist:
                    check = "x" if item.completed else " "
                    lines.append(f"- [{check}] {item.text}")

            if task.logs:
                lines.extend(["", "**最新ログ**:"])
                for log in task.logs[-5:]:
                    time_str = log.timestamp.strftime("%H:%M")
                    lines.append(f"- {time_str} - {log.message}")

        return lines

    def _generate_messages_markdown(self, dashboard: Dashboard) -> str:
        """messages.md の本文を生成する。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "# Multi-Agent Messages",
            "",
            f"**更新時刻**: {now}",
            "",
        ]

        if not dashboard.messages:
            lines.append("メッセージはまだありません。")
            return "\n".join(lines)

        type_emoji = {
            "task_progress": "📊",
            "task_complete": "✅",
            "task_failed": "❌",
            "request": "❓",
            "response": "💬",
            "task_approved": "👍",
            "error": "🔴",
        }

        agent_labels = self._build_agent_label_map(dashboard)
        lines.extend(["## メッセージ履歴"])
        for msg in dashboard.messages:
            lines.extend(self._render_message_details(msg, agent_labels, type_emoji))

        return "\n".join(lines)

    def _render_message_details(
        self,
        msg,
        agent_labels: dict[str, str],
        type_emoji: dict[str, str],
    ) -> list[str]:
        """メッセージ1件分の Markdown ブロックを返す。"""
        time_str = msg.created_at.strftime("%H:%M:%S") if msg.created_at else "-"
        emoji = type_emoji.get(msg.message_type, "📨")
        content = msg.content.strip() if msg.content else "(本文なし)"
        sender_id = msg.sender_id or "unknown"
        receiver_id = msg.receiver_id

        def _format_actor(actor_id: str | None) -> str:
            if not actor_id:
                return "unknown"
            if actor_id == "system":
                return "system"
            label = agent_labels.get(actor_id)
            if label:
                return label
            return f"unknown({actor_id[:8]})"

        sender = _format_actor(sender_id)
        receiver = _format_actor(receiver_id) if receiver_id else "broadcast"
        route = f"{sender} → {receiver}"
        return [
            "",
            "<details open>",
            f"<summary>{time_str} {emoji} {route}</summary>",
            "",
            "```text",
            content,
            "```",
            "</details>",
        ]

    def _write_messages_markdown(self, dashboard: Dashboard) -> None:
        """messages.md を保存する。"""
        messages_path = self._get_messages_path()
        try:
            messages_path.write_text(
                self._generate_messages_markdown(dashboard),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error(f"messages.md 保存エラー: {e}")

    def _append_message_markdown(self, dashboard: Dashboard, message) -> None:
        """messages.md へ単一メッセージを追記する。"""
        messages_path = self._get_messages_path()
        type_emoji = {
            "task_progress": "📊",
            "task_complete": "✅",
            "task_failed": "❌",
            "request": "❓",
            "response": "💬",
            "task_approved": "👍",
            "error": "🔴",
        }
        agent_labels = self._build_agent_label_map(dashboard)
        block = "\n".join(self._render_message_details(message, agent_labels, type_emoji))
        try:
            if not messages_path.exists():
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                initial = "\n".join(
                    [
                        "# Multi-Agent Messages",
                        "",
                        f"**更新時刻**: {now}",
                        "",
                        "## メッセージ履歴",
                    ]
                )
                messages_path.write_text(f"{initial}{block}\n", encoding="utf-8")
                return
            with open(messages_path, "a", encoding="utf-8") as f:
                f.write(f"{block}\n")
        except OSError as e:
            logger.error("messages.md 追記エラー: %s", e)

    def _generate_stats_section(self, dashboard: Dashboard) -> list[str]:
        """統計・コスト情報セクションを生成する。"""
        lines = [
            "",
            "---",
            "",
            "## 統計",
            "",
            f"- **総エージェント数**: {dashboard.total_agents}",
            f"- **アクティブエージェント**: {dashboard.active_agents}",
            f"- **総タスク数**: {dashboard.total_tasks}",
            f"- **完了タスク**: {dashboard.completed_tasks}",
            f"- **失敗タスク**: {dashboard.failed_tasks}",
            f"- **プロセスクラッシュ回数**: {dashboard.process_crash_count}",
            f"- **プロセス復旧回数**: {dashboard.process_recovery_count}",
        ]
        pending_tasks = len(dashboard.get_tasks_by_status(TaskStatus.PENDING))
        in_progress_tasks = len(dashboard.get_tasks_by_status(TaskStatus.IN_PROGRESS))
        all_tasks_completed = (
            dashboard.total_tasks > 0
            and pending_tasks == 0
            and in_progress_tasks == 0
            and dashboard.failed_tasks == 0
        )
        lines.append(f"- **実装完了**: {'✅' if all_tasks_completed else '❌'}")

        cost = dashboard.cost
        if cost.total_api_calls > 0:
            agent_labels = self._build_agent_label_map(dashboard)
            role_map = {agent.agent_id: agent.role for agent in dashboard.agents}
            role_stats: dict[str, dict[str, float | int]] = {}
            agent_stats: dict[str, dict[str, int]] = {}
            model_stats: dict[str, dict[str, float | int]] = {}

            for call in cost.calls:
                role = role_map.get(call.agent_id, "unknown") if call.agent_id else "unknown"
                call_cost = (
                    call.actual_cost_usd
                    if call.cost_source == "actual" and call.actual_cost_usd is not None
                    else call.estimated_cost_usd
                )

                role_data = role_stats.setdefault(role, {"calls": 0, "tokens": 0, "cost": 0.0})
                role_data["calls"] += 1
                role_data["tokens"] += call.tokens
                role_data["cost"] += call_cost

                agent_key = call.agent_id or "unknown"
                agent_data = agent_stats.setdefault(agent_key, {"calls": 0, "tokens": 0})
                agent_data["calls"] += 1
                agent_data["tokens"] += call.tokens

                model_key = call.model or "unknown"
                defaults = {"calls": 0, "tokens": 0, "cost": 0.0}
                model_data = model_stats.setdefault(model_key, defaults)
                model_data["calls"] += 1
                model_data["tokens"] += call.tokens
                model_data["cost"] += call_cost

            lines.extend(
                [
                    "",
                    "---",
                    "",
                    "## コスト情報",
                    "",
                    f"- **総API呼び出し数**: {cost.total_api_calls}",
                    f"- **推定トークン数**: {cost.estimated_tokens:,}",
                    f"- **実測コスト (Claude)**: ${cost.actual_cost_usd:.4f}",
                    f"- **推定コスト (全CLI)**: ${cost.estimated_cost_usd:.4f}",
                    f"- **合算コスト**: ${cost.total_cost_usd:.4f}",
                    f"- **警告閾値**: ${cost.warning_threshold_usd:.2f}",
                    "",
                    "**役割別内訳**:",
                ]
            )

            for role in sorted(role_stats):
                data = role_stats[role]
                lines.append(
                    f"- `{role}`: {int(data['calls'])} calls / "
                    f"{int(data['tokens']):,} tokens / ${float(data['cost']):.4f}"
                )

            lines.extend(["", "**エージェント別呼び出し**:"])
            for agent_id, data in sorted(
                agent_stats.items(),
                key=lambda item: item[1]["calls"],
                reverse=True,
            ):
                if agent_id == "unknown":
                    display = "unknown"
                else:
                    label = agent_labels.get(agent_id, "unknown")
                    display = label
                lines.append(f"- `{display}`: {data['calls']} calls / {data['tokens']:,} tokens")

            lines.extend(["", "**モデル別内訳**:"])
            for model_name, data in sorted(
                model_stats.items(),
                key=lambda item: item[1]["calls"],
                reverse=True,
            ):
                lines.append(
                    f"- `{model_name}`: {int(data['calls'])} calls / "
                    f"{int(data['tokens']):,} tokens / ${float(data['cost']):.4f}"
                )

            if cost.total_cost_usd >= cost.warning_threshold_usd:
                lines.extend(
                    [
                        "",
                        "⚠️ **警告**: 合算コストが閾値を超えています！",
                    ]
                )

        return lines

    def generate_markdown_dashboard(self) -> str:
        """Markdown形式のダッシュボードを生成する。

        Returns:
            Markdown形式のダッシュボード文字列
        """
        dashboard = self._read_dashboard()
        return self._generate_markdown_body(dashboard)
