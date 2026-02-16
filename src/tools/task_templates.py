"""タスクテンプレート生成モジュール。

Admin および Worker エージェント用のタスク指示テンプレートを生成する。
"""

from datetime import datetime
from pathlib import Path

from src.config.settings import Settings, load_effective_settings_for_project
from src.config.template_loader import get_template_loader

_IMAGE_TASK_HINTS = (
    "image generation",
    "generate image",
    "infographic",
    "ogp",
    "banner",
    "icon",
    "logo",
    "画像生成",
    "画像を作成",
    "画像を生成",
    "インフォグラフィック",
    "図を生成",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".svg",
)


def _looks_like_image_generation_task(task_description: str) -> bool:
    """タスク説明が画像生成タスクかどうかを判定する。"""
    normalized = (task_description or "").lower()
    return any(hint in normalized for hint in _IMAGE_TASK_HINTS)


def _build_image_task_policy_section(
    task_description: str,
    enable_cursor_image_routing: bool,
) -> str:
    """画像生成タスク用の追加ポリシー文面を返す。"""
    if not enable_cursor_image_routing:
        return ""
    if not _looks_like_image_generation_task(task_description):
        return ""

    return """
## Image Task Policy（画像生成タスク専用）

- 最終成果物は Cursor の画像生成機能で直接生成し、モデルは Google Nano Banana Pro を優先利用する
- Python スクリプト（Pillow / matplotlib / OpenCV など）や SVG/HTML 描画からの PNG 変換で代替しない
- HTML を作ってブラウザ/Playwright でスクリーンショットして PNG 化する方法は不可
- UI テスト用キャプチャ画像を成果物として提出しない
- 生成画像の出力先は Admin 指示（またはタスク指定）に従い、最終パスを報告する
- 画像生成が実行不能な場合は勝手に代替せず
  `send_message(message_type=\"request\")` で Admin にエスカレーションする
- 完了報告には生成手段・使用ツール/モデル
  （例: Cursor + Google Nano Banana Pro）・最終画像パス・プロンプト要点を明記する
""".strip()


def _build_admin_image_task_routing_section(
    enable_cursor_image_routing: bool,
    section_number: str,
) -> str:
    """Admin タスク向けの画像生成ルーティング文面を返す。"""
    if not enable_cursor_image_routing:
        return ""

    return f"""
#### {section_number}. 画像生成タスクの Cursor Worker ルーティング

**AI 自体が画像ファイルを生成するタスク**は **Cursor CLI Worker** に割り当てます。

**🔴 画像生成タスクの定義（重要）:**

| 画像生成タスク ✅（Cursor 対象） | 画像生成タスクではない ❌（通常 Worker） |
| --- | --- |
| ロゴ・アイコンの作成 | Playwright でのスクリーンショット取得 |
| バナー・OGP 画像の生成 | UI テスト用のキャプチャ |
| UI モックアップ・デザインカンプの生成 | 既存画像のリサイズ・変換処理 |
| 図・ダイアグラムの AI 生成 | デバッグ用の画面録画 |

**判定キーワード（AI による画像生成を示すもの）:**
- 画像生成、画像を作成、ロゴ作成、アイコン作成
- バナー作成、OGP 画像、モックアップ生成
- 図を生成、ダイアグラム作成、ビジュアル生成

**🔴 画像生成タスクの task_content 必須ルール:**
- Cursor の画像生成機能を使い、**Google Nano Banana Pro** で生成する旨を task_content に明記する
- Python スクリプト（Pillow / matplotlib / OpenCV など）や SVG/HTML 描画からの PNG 変換で代替しない
- 「HTML を作ってスクリーンショットで PNG 化」は禁止
- Playwright/ブラウザのキャプチャ画像を成果物として提出しない
- 出力先パスを task_content に明記し、タスク要件に応じて Admin が決定する
- 画像生成機能が使えない場合は Worker に代替実装させず、`request` で Admin が判断する

**画像生成タスクの同時並列実行数: 最大 2**
画像生成タスクが多くても、同時に実行できるのは 2 タスクまでです。
3つ以上の画像タスクがある場合は、先行する画像タスクの完了を待ってから次を割り当ててください。
（idle な Cursor Worker は制限にカウントされないため、完了後すぐ次の画像タスクを受け入れ可能）

**初回バッチ作成時（Worker がまだいない場合）:**

画像生成タスクがある場合、`worker_configs` で `preferred_cli: "cursor"` を指定します。
コード実装タスク用の Worker 数は画像タスク分を差し引いて調整してください。

```python
worker_configs = [
    {{
        "task_title": "コード実装タスク",
        "task_id": task_ids[0],
        "task_content": "..."
        # preferred_cli 省略 → デフォルト CLI (Claude)
    }},
    {{
        "task_title": "ロゴ画像生成タスク",
        "task_id": task_ids[1],
        "task_content": "...",
        "preferred_cli": "cursor"  # ← Cursor Worker で実行
    }},
]
```

**追加タスク時（既に Worker が稼働中の場合）:**

1. `list_agents` で既存の idle Cursor Worker を探す
2. idle Cursor Worker がある → `send_task` でタスクを割り当て
3. idle Cursor Worker がない & 画像タスク並列実行数が 2 未満 & idle Claude Worker がある場合:
   - idle Claude Worker を `terminate_agent` で終了
   - `create_agent(role="worker", ai_cli="cursor", working_dir="...")` で Cursor Worker を作成
   - `send_task` でタスクを割り当て
4. 画像生成タスクが既に 2 つ並列実行中
   → いずれかの完了を待ってから idle Cursor Worker に `send_task` で次の画像タスクを割り当て
5. idle Worker が全くない → Worker 完了を待ってから上記を実行
""".strip()


def generate_admin_task(
    session_id: str,
    agent_id: str,
    plan_content: str,
    branch_name: str,
    worker_count: int,
    memory_context: str,
    project_name: str,
    working_dir: str | None = None,
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
        working_dir: 作業ディレクトリ（Non-Worktree モード用）
        mcp_tool_prefix: MCP ツールの完全名プレフィックス
        settings: MCP 設定（省略時は新規作成）

    Returns:
        Admin 用のタスク指示（Markdown形式）
    """
    if settings is None:
        settings = load_effective_settings_for_project(working_dir or Path.cwd())

    max_iterations = settings.quality_check_max_iterations
    same_issue_limit = settings.quality_check_same_issue_limit
    timestamp = datetime.now().isoformat()

    # memory_context が空の場合のデフォルト値
    memory_context_display = memory_context if memory_context else "（関連情報なし）"
    image_task_routing_enabled = settings.enable_cursor_image_routing

    loader = get_template_loader()

    # git/worktree 設定に応じてテンプレートを切り替え
    if not settings.enable_git:
        return loader.render(
            "tasks",
            "admin_task_no_git",
            session_id=session_id,
            agent_id=agent_id,
            plan_content=plan_content,
            branch_name=branch_name,
            working_dir=working_dir or ".",
            worker_count=worker_count,
            memory_context=memory_context_display,
            project_name=project_name,
            mcp_tool_prefix=mcp_tool_prefix,
            timestamp=timestamp,
            max_iterations=max_iterations,
            same_issue_limit=same_issue_limit,
            image_task_routing_section=_build_admin_image_task_routing_section(
                image_task_routing_enabled,
                section_number="2.2",
            ),
        )
    if settings.is_worktree_enabled():
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
            project_path=working_dir or ".",  # create_workers_batch 用
            mcp_tool_prefix=mcp_tool_prefix,
            timestamp=timestamp,
            max_iterations=max_iterations,
            same_issue_limit=same_issue_limit,
            image_task_routing_section=_build_admin_image_task_routing_section(
                image_task_routing_enabled,
                section_number="2.5",
            ),
        )
    else:
        return loader.render(
            "tasks",
            "admin_task_no_worktree",
            session_id=session_id,
            agent_id=agent_id,
            plan_content=plan_content,
            branch_name=branch_name,
            working_dir=working_dir or ".",
            worker_count=worker_count,
            memory_context=memory_context_display,
            project_name=project_name,
            mcp_tool_prefix=mcp_tool_prefix,
            timestamp=timestamp,
            max_iterations=max_iterations,
            same_issue_limit=same_issue_limit,
            image_task_routing_section=_build_admin_image_task_routing_section(
                image_task_routing_enabled,
                section_number="2.2",
            ),
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
    admin_id: str | None = None,
    mcp_tool_prefix: str = "mcp__multi-agent-mcp__",
    enable_git: bool = True,
    enable_cursor_image_routing: bool = False,
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
        admin_id: Admin エージェントID（省略可）
        mcp_tool_prefix: MCP ツールの完全名プレフィックス
        enable_git: git 機能を有効化しているか
        enable_cursor_image_routing: 画像生成タスク向け Cursor ルーティングを有効化するか

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
    work_env_section = "\n".join(work_env_lines) if work_env_lines else "（メインリポジトリで作業）"

    # memory_context が空の場合のデフォルト値
    memory_context_display = memory_context if memory_context else "（関連情報なし）"

    loader = get_template_loader()
    template_name = "worker_task" if enable_git else "worker_task_no_git"
    image_task_policy_section = _build_image_task_policy_section(
        task_description,
        enable_cursor_image_routing=enable_cursor_image_routing,
    )
    return loader.render(
        "tasks",
        template_name,
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
        admin_id=admin_id if admin_id else "{{ADMIN_ID}}",
        mcp_tool_prefix=mcp_tool_prefix,
        image_task_policy_section=image_task_policy_section,
    )
