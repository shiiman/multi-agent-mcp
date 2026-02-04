"""タスクテンプレート生成モジュール。

Admin および Worker エージェント用のタスク指示テンプレートを生成する。
"""

from datetime import datetime

from src.config.settings import Settings
from src.config.template_loader import get_template_loader


def generate_admin_task(
    session_id: str,
    agent_id: str,
    plan_content: str,
    branch_name: str,
    worker_count: int,
    memory_context: str,
    project_name: str,
    mcp_tool_prefix: str = "mcp__multi-agent-mcp__",
    settings: Settings | None = None,
) -> str:
    """Admin エージェント用のタスク指示を生成する。

    Args:
        session_id: セッションID（Issue番号など）
        agent_id: Admin エージェントID
        plan_content: 計画書またはタスク説明
        branch_name: 作業ブランチ名
        worker_count: Worker 数
        memory_context: メモリから取得した関連情報
        project_name: プロジェクト名
        mcp_tool_prefix: MCP ツールの完全名プレフィックス
        settings: MCP 設定（省略時は新規作成）

    Returns:
        Admin 用のタスク指示（Markdown形式）
    """
    if settings is None:
        settings = Settings()

    max_iterations = settings.quality_check_max_iterations
    same_issue_limit = settings.quality_check_same_issue_limit
    timestamp = datetime.now().isoformat()

    # memory_context が空の場合のデフォルト値
    memory_context_display = memory_context if memory_context else "（関連情報なし）"

    loader = get_template_loader()
    return loader.render(
        "tasks",
        "admin_task",
        session_id=session_id,
        agent_id=agent_id,
        plan_content=plan_content,
        branch_name=branch_name,
        worker_count=worker_count,
        memory_context=memory_context_display,
        project_name=project_name,
        mcp_tool_prefix=mcp_tool_prefix,
        timestamp=timestamp,
        max_iterations=max_iterations,
        same_issue_limit=same_issue_limit,
    )


def generate_7section_task(
    task_id: str,
    agent_id: str,
    task_description: str,
    persona_name: str,
    persona_prompt: str,
    memory_context: str,
    project_name: str,
    worktree_path: str | None = None,
    branch_name: str | None = None,
) -> str:
    """7セクション構造のタスクファイルを生成する。

    Args:
        task_id: タスクID（session_id）
        agent_id: エージェントID
        task_description: タスク内容
        persona_name: ペルソナ名
        persona_prompt: ペルソナのシステムプロンプト
        memory_context: メモリから取得した関連情報
        project_name: プロジェクト名
        worktree_path: 作業ディレクトリパス（省略可）
        branch_name: 作業ブランチ名（省略可）

    Returns:
        7セクション構造のMarkdown文字列
    """
    timestamp = datetime.now().isoformat()

    # 作業環境情報
    work_env_lines = []
    if worktree_path:
        work_env_lines.append(f"- **作業ディレクトリ**: `{worktree_path}`")
    if branch_name:
        work_env_lines.append(f"- **作業ブランチ**: `{branch_name}`")
    work_env_section = (
        "\n".join(work_env_lines) if work_env_lines else "（メインリポジトリで作業）"
    )

    # memory_context が空の場合のデフォルト値
    memory_context_display = memory_context if memory_context else "（関連情報なし）"

    loader = get_template_loader()
    return loader.render(
        "tasks",
        "worker_task",
        task_id=task_id,
        agent_id=agent_id,
        task_description=task_description,
        persona_name=persona_name,
        persona_prompt=persona_prompt,
        memory_context=memory_context_display,
        project_name=project_name,
        work_env_section=work_env_section,
        branch_name=branch_name if branch_name else "HEAD",
        timestamp=timestamp,
    )
