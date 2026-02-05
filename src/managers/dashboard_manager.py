"""ダッシュボード管理モジュール。

複数プロセス対応: インメモリキャッシュを使わず、毎回ファイルから読み書きする。
YAML Front Matter 付き Markdown で統一管理。
"""

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from src.config.settings import get_mcp_dir
from src.models.agent import Agent
from src.models.dashboard import (
    AgentSummary,
    ChecklistItem,
    Dashboard,
    TaskInfo,
    TaskLog,
    TaskStatus,
)

if TYPE_CHECKING:
    from src.managers.agent_manager import AgentManager
    from src.managers.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


class DashboardManager:
    """ダッシュボードを管理するクラス。

    複数プロセス対応のため、インメモリキャッシュを使わず
    毎回ファイルから読み書きする。
    """

    def __init__(
        self,
        workspace_id: str,
        workspace_path: str,
        dashboard_dir: str,
    ) -> None:
        """DashboardManagerを初期化する。

        Args:
            workspace_id: ワークスペースID
            workspace_path: ワークスペースパス
            dashboard_dir: ダッシュボードファイルを保存するディレクトリ
        """
        self.workspace_id = workspace_id
        self.workspace_path = workspace_path
        self.dashboard_dir = Path(dashboard_dir)

    def initialize(self) -> None:
        """ダッシュボード環境を初期化する。"""
        self.dashboard_dir.mkdir(parents=True, exist_ok=True)
        # 初期ダッシュボードを作成して保存
        dashboard = Dashboard(
            workspace_id=self.workspace_id,
            workspace_path=self.workspace_path,
        )
        self._write_dashboard(dashboard)
        logger.info(f"ダッシュボード環境を初期化しました: {self.dashboard_dir}")

    def cleanup(self) -> None:
        """ダッシュボード環境をクリーンアップする。"""
        dashboard_path = self._get_dashboard_path()
        if dashboard_path.exists():
            try:
                dashboard_path.unlink()
            except OSError as e:
                logger.warning(f"ダッシュボードファイル削除エラー: {e}")
        logger.info("ダッシュボード環境をクリーンアップしました")

    def _get_dashboard_path(self) -> Path:
        """ダッシュボードファイルパスを取得する。"""
        return self.dashboard_dir / f"dashboard_{self.workspace_id}.md"

    def _get_legacy_json_path(self) -> Path:
        """レガシー JSON ダッシュボードファイルパスを取得する（移行用）。"""
        return self.dashboard_dir / f"dashboard_{self.workspace_id}.json"

    def _write_dashboard(self, dashboard: Dashboard) -> None:
        """ダッシュボードをファイルに保存する（YAML Front Matter + Markdown）。

        Args:
            dashboard: 保存するDashboardオブジェクト
        """
        dashboard_path = self._get_dashboard_path()
        try:
            # YAML Front Matter 用のデータ
            front_matter_data = dashboard.model_dump(mode="json")

            # Markdown コンテンツを生成
            md_content = self._generate_markdown_body(dashboard)

            # YAML Front Matter + Markdown を結合
            yaml_str = yaml.dump(
                front_matter_data,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
            content = f"---\n{yaml_str}---\n\n{md_content}"

            with open(dashboard_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            logger.error(f"ダッシュボード保存エラー: {e}")

    def _read_dashboard(self) -> Dashboard:
        """ダッシュボードをファイルから読み込む（YAML Front Matter から）。

        Returns:
            Dashboardオブジェクト（ファイルがない場合は新規作成）
        """
        dashboard_path = self._get_dashboard_path()

        if dashboard_path.exists():
            try:
                content = dashboard_path.read_text(encoding="utf-8")
                data = self._parse_yaml_front_matter(content)
                if data:
                    return Dashboard(**data)
            except (yaml.YAMLError, OSError) as e:
                logger.warning(f"ダッシュボード読み込みエラー: {e}")

        # レガシー JSON ファイルからの移行
        legacy_path = self._get_legacy_json_path()
        if legacy_path.exists():
            try:
                import json

                with open(legacy_path, encoding="utf-8") as f:
                    data = json.load(f)
                    dashboard = Dashboard(**data)
                    # 新形式で保存し直す
                    self._write_dashboard(dashboard)
                    # レガシーファイルを削除
                    legacy_path.unlink()
                    logger.info(f"レガシー JSON を Markdown に移行しました: {legacy_path}")
                    return dashboard
            except Exception as e:
                logger.warning(f"レガシーファイル移行エラー: {e}")

        # ファイルがない場合は新規作成
        return Dashboard(
            workspace_id=self.workspace_id,
            workspace_path=self.workspace_path,
        )

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

        lines = [
            "# Multi-Agent Dashboard",
            "",
            f"**更新時刻**: {now}",
            "",
            "---",
            "",
            "## エージェント状態",
            "",
            "| ID | 役割 | 状態 | 現在のタスク | Worktree |",
            "|:---|:---|:---|:---|:---|",
        ]

        status_emoji = {
            "idle": "🟢",
            "busy": "🔵",
            "error": "🔴",
            "offline": "⚫",
        }

        for agent in dashboard.agents:
            emoji = status_emoji.get(str(agent.status).lower(), "⚪")
            current_task = agent.current_task_id or "-"
            worktree = agent.worktree_path or "-"
            lines.append(
                f"| `{agent.agent_id[:8]}` | {agent.role} | {emoji} {agent.status} | "
                f"{current_task} | `{worktree}` |"
            )

        lines.extend([
            "",
            "---",
            "",
            "## タスク状態",
            "",
            "| ID | タイトル | 状態 | 担当 | 進捗 |",
            "|:---|:---|:---|:---|:---|",
        ])

        task_emoji = {
            "pending": "⏳",
            "in_progress": "🔄",
            "completed": "✅",
            "failed": "❌",
            "blocked": "🚫",
            "cancelled": "🗑️",
        }

        for task in dashboard.tasks:
            emoji = task_emoji.get(str(task.status.value).lower(), "❓")
            assigned = task.assigned_agent_id[:8] if task.assigned_agent_id else "-"
            lines.append(
                f"| `{task.id[:8]}` | {task.title} | {emoji} {task.status.value} | "
                f"`{assigned}` | {task.progress}% |"
            )

        # タスク詳細セクション（進行中のタスクのみ）
        in_progress_tasks = [
            t for t in dashboard.tasks if t.status == TaskStatus.IN_PROGRESS
        ]
        if in_progress_tasks:
            lines.extend([
                "",
                "---",
                "",
                "## タスク詳細",
            ])

            for task in in_progress_tasks:
                lines.extend([
                    "",
                    f"### {task.title}",
                    "",
                    f"**進捗**: {task.progress}%",
                ])

                # チェックリスト
                if task.checklist:
                    lines.extend([
                        "",
                        "**チェックリスト**:",
                    ])
                    for item in task.checklist:
                        check = "x" if item.completed else " "
                        lines.append(f"- [{check}] {item.text}")

                # 最新ログ
                if task.logs:
                    lines.extend([
                        "",
                        "**最新ログ**:",
                    ])
                    for log in task.logs[-5:]:
                        time_str = log.timestamp.strftime("%H:%M")
                        lines.append(f"- {time_str} - {log.message}")

        lines.extend([
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
        ])

        return "\n".join(lines)

    def get_dashboard(self) -> Dashboard:
        """現在のダッシュボードを取得する。

        Returns:
            Dashboard オブジェクト
        """
        return self._read_dashboard()

    # タスク管理メソッド

    def create_task(
        self,
        title: str,
        description: str = "",
        assigned_agent_id: str | None = None,
        branch: str | None = None,
        worktree_path: str | None = None,
        metadata: dict | None = None,
    ) -> TaskInfo:
        """新しいタスクを作成する。

        Args:
            title: タスクタイトル
            description: タスク説明
            assigned_agent_id: 割り当て先エージェントID
            branch: 作業ブランチ
            worktree_path: worktreeパス
            metadata: 追加メタデータ

        Returns:
            作成されたTaskInfo
        """
        dashboard = self._read_dashboard()

        task = TaskInfo(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            status=TaskStatus.PENDING,
            assigned_agent_id=assigned_agent_id,
            branch=branch,
            worktree_path=worktree_path,
            metadata=metadata or {},
            created_at=datetime.now(),
        )

        dashboard.tasks.append(task)
        dashboard.calculate_stats()
        self._write_dashboard(dashboard)

        logger.info(f"タスクを作成しました: {task.id} - {title}")
        return task

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        progress: int | None = None,
        error_message: str | None = None,
    ) -> tuple[bool, str]:
        """タスクのステータスを更新する。

        Args:
            task_id: タスクID
            status: 新しいステータス
            progress: 進捗率
            error_message: エラーメッセージ

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        dashboard = self._read_dashboard()

        task = dashboard.get_task(task_id)
        if not task:
            return False, f"タスク {task_id} が見つかりません"

        old_status = task.status
        task.status = status

        if progress is not None:
            task.progress = progress

        if error_message is not None:
            task.error_message = error_message

        # ステータス変更時の日時記録
        now = datetime.now()
        if status == TaskStatus.IN_PROGRESS and old_status == TaskStatus.PENDING:
            task.started_at = now
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            task.completed_at = now
            if status == TaskStatus.COMPLETED:
                task.progress = 100

        dashboard.calculate_stats()
        self._write_dashboard(dashboard)

        logger.info(f"タスク {task_id} のステータスを更新: {old_status} -> {status}")
        return True, f"ステータスを更新しました: {status.value}"

    def assign_task(
        self,
        task_id: str,
        agent_id: str,
        branch: str | None = None,
        worktree_path: str | None = None,
    ) -> tuple[bool, str]:
        """タスクをエージェントに割り当てる。

        Args:
            task_id: タスクID
            agent_id: エージェントID
            branch: 作業ブランチ
            worktree_path: worktreeパス

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        dashboard = self._read_dashboard()

        task = dashboard.get_task(task_id)
        if not task:
            return False, f"タスク {task_id} が見つかりません"

        task.assigned_agent_id = agent_id
        if branch:
            task.branch = branch
        if worktree_path:
            task.worktree_path = worktree_path

        self._write_dashboard(dashboard)

        logger.info(f"タスク {task_id} をエージェント {agent_id} に割り当てました")
        return True, f"タスクを割り当てました: {agent_id}"

    def remove_task(self, task_id: str) -> tuple[bool, str]:
        """タスクを削除する。

        Args:
            task_id: タスクID

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        dashboard = self._read_dashboard()

        task = dashboard.get_task(task_id)
        if not task:
            return False, f"タスク {task_id} が見つかりません"

        dashboard.tasks = [t for t in dashboard.tasks if t.id != task_id]
        dashboard.calculate_stats()
        self._write_dashboard(dashboard)

        logger.info(f"タスク {task_id} を削除しました")
        return True, "タスクを削除しました"

    def get_task(self, task_id: str) -> TaskInfo | None:
        """タスクを取得する。

        Args:
            task_id: タスクID

        Returns:
            TaskInfo、見つからない場合はNone
        """
        dashboard = self._read_dashboard()
        return dashboard.get_task(task_id)

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        agent_id: str | None = None,
    ) -> list[TaskInfo]:
        """タスク一覧を取得する。

        Args:
            status: フィルターするステータス
            agent_id: フィルターするエージェントID

        Returns:
            TaskInfoのリスト
        """
        dashboard = self._read_dashboard()
        tasks = dashboard.tasks

        if status is not None:
            tasks = [t for t in tasks if t.status == status]

        if agent_id is not None:
            tasks = [t for t in tasks if t.assigned_agent_id == agent_id]

        return tasks

    def update_task_checklist(
        self,
        task_id: str,
        checklist: list[dict[str, bool | str]] | None = None,
        log_message: str | None = None,
    ) -> tuple[bool, str]:
        """タスクのチェックリストとログを更新する。

        Args:
            task_id: タスクID
            checklist: チェックリストアイテムのリスト [{"text": "...", "completed": True/False}, ...]
            log_message: 追加するログメッセージ

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        dashboard = self._read_dashboard()

        task = dashboard.get_task(task_id)
        if not task:
            return False, f"タスク {task_id} が見つかりません"

        # チェックリストを更新
        if checklist is not None:
            task.checklist = [
                ChecklistItem(text=item["text"], completed=item.get("completed", False))
                for item in checklist
            ]
            # チェックリストから進捗を計算
            if task.checklist:
                completed_count = sum(1 for item in task.checklist if item.completed)
                task.progress = int((completed_count / len(task.checklist)) * 100)

        # ログを追加（最新5件を保持）
        if log_message:
            task.logs.append(TaskLog(message=log_message))
            task.logs = task.logs[-5:]  # 最新5件のみ保持

        self._write_dashboard(dashboard)

        logger.info(f"タスク {task_id} のチェックリスト/ログを更新しました")
        return True, "チェックリスト/ログを更新しました"

    # エージェントサマリー管理メソッド

    def update_agent_summary(self, agent: Agent) -> None:
        """エージェントサマリーを更新する。

        Args:
            agent: Agentオブジェクト
        """
        dashboard = self._read_dashboard()

        # 既存のサマリーを検索
        existing = dashboard.get_agent(agent.id)

        summary = AgentSummary(
            agent_id=agent.id,
            role=agent.role,  # use_enum_values=True のため既に文字列
            status=agent.status,  # use_enum_values=True のため既に文字列
            current_task_id=agent.current_task,
            worktree_path=agent.worktree_path,
            branch=None,  # 別途取得が必要
            last_activity=agent.last_activity,
        )

        if existing:
            # 既存のサマリーを更新
            idx = next(
                i
                for i, a in enumerate(dashboard.agents)
                if a.agent_id == agent.id
            )
            dashboard.agents[idx] = summary
        else:
            # 新規追加
            dashboard.agents.append(summary)

        dashboard.calculate_stats()
        self._write_dashboard(dashboard)

    def remove_agent_summary(self, agent_id: str) -> None:
        """エージェントサマリーを削除する。

        Args:
            agent_id: エージェントID
        """
        dashboard = self._read_dashboard()

        dashboard.agents = [
            a for a in dashboard.agents if a.agent_id != agent_id
        ]
        dashboard.calculate_stats()
        self._write_dashboard(dashboard)

    # ワークスペース統計更新メソッド

    async def update_worktree_stats(
        self,
        worktree_manager: "WorktreeManager",
    ) -> None:
        """worktree統計を更新する。

        Args:
            worktree_manager: WorktreeManager インスタンス
        """
        dashboard = self._read_dashboard()

        worktrees = await worktree_manager.list_worktrees()
        dashboard.total_worktrees = len(worktrees)

        # アクティブなworktree（エージェントに割り当てられている）をカウント
        assigned_paths = {
            a.worktree_path for a in dashboard.agents if a.worktree_path
        }
        dashboard.active_worktrees = len(
            [wt for wt in worktrees if wt.path in assigned_paths]
        )

        self._write_dashboard(dashboard)

    def sync_from_agent_manager(self, agent_manager: "AgentManager") -> None:
        """AgentManagerからエージェント情報を同期する。

        Args:
            agent_manager: AgentManager インスタンス
        """
        dashboard = self._read_dashboard()
        dashboard.agents = []

        for agent in agent_manager.agents.values():
            summary = AgentSummary(
                agent_id=agent.id,
                role=agent.role,
                status=agent.status,
                current_task_id=agent.current_task,
                worktree_path=agent.worktree_path,
                branch=None,
                last_activity=agent.last_activity,
            )
            dashboard.agents.append(summary)

        dashboard.calculate_stats()
        self._write_dashboard(dashboard)

    def get_summary(self) -> dict:
        """ダッシュボードのサマリーを取得する。

        Returns:
            サマリー情報の辞書
        """
        dashboard = self._read_dashboard()
        return {
            "workspace_id": dashboard.workspace_id,
            "total_agents": dashboard.total_agents,
            "active_agents": dashboard.active_agents,
            "total_tasks": dashboard.total_tasks,
            "completed_tasks": dashboard.completed_tasks,
            "failed_tasks": dashboard.failed_tasks,
            "pending_tasks": len(
                dashboard.get_tasks_by_status(TaskStatus.PENDING)
            ),
            "in_progress_tasks": len(
                dashboard.get_tasks_by_status(TaskStatus.IN_PROGRESS)
            ),
            "total_worktrees": dashboard.total_worktrees,
            "active_worktrees": dashboard.active_worktrees,
            "updated_at": dashboard.updated_at.isoformat(),
        }

    # タスクファイル管理メソッド（ファイルベースのタスク配布）

    def write_task_file(
        self, project_root: Path, session_id: str, agent_id: str, task_content: str
    ) -> Path:
        """Worker用のタスクファイルを作成する（Markdown形式）。

        Args:
            project_root: プロジェクトルートパス
            session_id: Issue番号または一意なタスクID（例: "94", "a1b2c3d4"）
            agent_id: エージェントID
            task_content: タスク内容

        Returns:
            作成したタスクファイルのパス
        """
        task_dir = project_root / get_mcp_dir() / session_id / "tasks"
        task_dir.mkdir(parents=True, exist_ok=True)
        task_file = task_dir / f"{agent_id}.md"
        task_file.write_text(task_content, encoding="utf-8")
        logger.info(f"タスクファイルを作成しました: {task_file}")
        return task_file

    def get_task_file_path(
        self, project_root: Path, session_id: str, agent_id: str
    ) -> Path:
        """Worker用のタスクファイルパスを取得する。

        Args:
            project_root: プロジェクトルートパス
            session_id: Issue番号または一意なタスクID
            agent_id: エージェントID

        Returns:
            タスクファイルのパス
        """
        return project_root / get_mcp_dir() / session_id / "tasks" / f"{agent_id}.md"

    def read_task_file(
        self, project_root: Path, session_id: str, agent_id: str
    ) -> str | None:
        """Worker用のタスクファイルを読み取る。

        Args:
            project_root: プロジェクトルートパス
            session_id: Issue番号または一意なタスクID
            agent_id: エージェントID

        Returns:
            タスクファイルの内容、存在しない場合はNone
        """
        task_file = self.get_task_file_path(project_root, session_id, agent_id)
        if task_file.exists():
            return task_file.read_text(encoding="utf-8")
        return None

    def clear_task_file(
        self, project_root: Path, session_id: str, agent_id: str
    ) -> bool:
        """タスクファイルをクリアする。

        Args:
            project_root: プロジェクトルートパス
            session_id: Issue番号または一意なタスクID
            agent_id: エージェントID

        Returns:
            削除に成功した場合True
        """
        task_file = self.get_task_file_path(project_root, session_id, agent_id)
        if task_file.exists():
            task_file.unlink()
            logger.info(f"タスクファイルを削除しました: {task_file}")
            return True
        return False

    # Markdown ダッシュボード生成メソッド

    def generate_markdown_dashboard(self) -> str:
        """Markdown形式のダッシュボードを生成する。

        Returns:
            Markdown形式のダッシュボード文字列
        """
        dashboard = self._read_dashboard()
        return self._generate_markdown_body(dashboard)

    def save_markdown_dashboard(self, project_root: Path, session_id: str) -> Path:
        """Markdownダッシュボードをファイルに保存する。

        Args:
            project_root: プロジェクトルートパス
            session_id: Issue番号または一意なタスクID（例: "94", "a1b2c3d4"）

        Returns:
            保存したファイルのパス
        """
        md_content = self.generate_markdown_dashboard()
        dashboard_dir = project_root / get_mcp_dir() / session_id / "dashboard"
        dashboard_dir.mkdir(parents=True, exist_ok=True)
        md_path = dashboard_dir / "dashboard.md"
        md_path.write_text(md_content, encoding="utf-8")
        logger.info(f"Markdownダッシュボードを保存しました: {md_path}")
        return md_path
