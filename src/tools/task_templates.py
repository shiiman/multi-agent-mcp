"""タスクテンプレート生成モジュール。

Admin および Worker エージェント用のタスク指示テンプレートを生成する。
"""

from datetime import datetime

from src.config.settings import Settings


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

    return f"""# Admin タスク: {session_id}

## あなたの役割

あなたは **Admin エージェント** です。
以下の計画書に基づいてタスクを分割し、Worker を管理してください。

## 🚨 最重要ルール（絶対厳守）

**Admin は絶対にコードを書いてはいけません。**

- ❌ ファイルの作成・編集・削除（Write, Edit ツール使用禁止）
- ❌ コードの実装・修正
- ✅ MCP ツールのみ使用（create_task, create_worktree, create_agent, send_task 等）
- ✅ Worker にタスクを割り当てて実装させる

**違反した場合は F001 違反となり、タスクは失敗とみなされます。**

## ⚠️ MCP ツールの呼び出し方法

**MCP ツールは以下の完全名で呼び出してください:**

```
{mcp_tool_prefix}{{ツール名}}
```

**主要ツール一覧:**

| 短縮名 | 完全名 |
|--------|--------|
| `create_task` | `{mcp_tool_prefix}create_task` |
| `create_agent` | `{mcp_tool_prefix}create_agent` |
| `create_worktree` | `{mcp_tool_prefix}create_worktree` |
| `assign_worktree` | `{mcp_tool_prefix}assign_worktree` |
| `assign_task_to_agent` | `{mcp_tool_prefix}assign_task_to_agent` |
| `send_task` | `{mcp_tool_prefix}send_task` |
| `send_message` | `{mcp_tool_prefix}send_message` |
| `get_dashboard` | `{mcp_tool_prefix}get_dashboard` |
| `get_dashboard_summary` | `{mcp_tool_prefix}get_dashboard_summary` |
| `list_tasks` | `{mcp_tool_prefix}list_tasks` |
| `list_agents` | `{mcp_tool_prefix}list_agents` |
| `read_messages` | `{mcp_tool_prefix}read_messages` |
| `healthcheck_all` | `{mcp_tool_prefix}healthcheck_all` |

**呼び出し例:**
```
{mcp_tool_prefix}create_task(title="タスク名", description="説明")
{mcp_tool_prefix}create_agent(role="worker", working_dir="/path/to/worktree")
{mcp_tool_prefix}send_task(agent_id="xxx", task_content="内容", session_id="{session_id}")
```

## 計画書

{plan_content}

## 作業情報

- **プロジェクト**: {project_name}
- **作業ブランチ**: {branch_name}
- **Worker 数**: {worker_count}
- **開始時刻**: {timestamp}

## 実行手順

**⚠️ 実行前の確認**: Admin は MCP ツールのみ使用し、コードは一切書きません。実装は全て Worker に委譲します。

### 1. スクリーンショット確認（UI タスクの場合）
- `list_screenshots` でスクリーンショットの有無を確認
- UI 関連タスクの場合は `read_latest_screenshot` で視覚的問題を分析
- 分析結果をタスク分割に反映

### 2. タスク分割（MCP ツールで登録のみ）
- 計画書から並列実行可能なサブタスクを抽出
- 各サブタスクを Dashboard に登録（`create_task`）

### 3. Worker 作成・タスク割り当て
各 Worker に対して以下を実行：
1. Worktree 作成（`create_worktree`）
2. Worker エージェント作成（`create_agent(role="worker")`）
3. Worktree 割り当て（`assign_worktree`）
4. タスク割り当て（`assign_task_to_agent`）
5. タスク送信（`send_task`）

### 4. 進捗監視
- `get_dashboard_summary` で進捗確認
- `healthcheck_all` で Worker 状態確認
- `read_messages` で Worker からの質問に対応

### 5. 結果確認・品質チェック
- 全 Worker 完了後、変更内容をレビュー
- UI タスクの場合は `read_latest_screenshot` で視覚的確認
- **実際に動作確認**:
  1. `git pull` で最新を取得
  2. アプリを実行してテスト（例: `npm start`, `python main.py`）
  3. エラーがないか、期待通りに動作するか確認

### 6. 品質イテレーション（問題がある場合）

**⚠️ 重要: Admin は問題を特定するのみ。修正コードは絶対に書かない！**

バグや改善点を発見した場合、**Worker に修正を依頼**してサイクルを回す:

```
while (品質に問題あり && イテレーション < {max_iterations}):
    1. 問題を分析・リスト化（コードは読むが書かない）
    2. 修正タスクを create_task で登録
    3. 新しい Worker を作成 or 既存 Worker に send_task
       - session_id は元のタスクと同じ（例: "{session_id}"）を使用
    4. Worker 完了を待機
    5. 再度品質チェック
```

**注意事項**:
- ❌ Admin が直接コードを編集してはいけない（F001 違反）
- ✅ 必ず Worker に send_task で修正を依頼する
- 1回のイテレーションで1-2個の問題に絞る（過度な修正を避ける）
- 同じ問題が{same_issue_limit}回以上繰り返される場合は Owner に相談
- 最大イテレーション回数: {max_iterations}回（超えたら Owner に報告）
- 修正内容はメモリに保存（`save_to_memory`）して学習

### 7. 完了報告
品質チェックをパスした後、Owner に `send_message` で結果を報告:
- 完了したタスク一覧
- 品質チェックの結果
- イテレーション回数（もしあれば）
- 残存する既知の問題（もしあれば）

## 🔴 RACE-001: 同一論理ファイルの編集禁止（マージ競合防止）

**複数の Worker が同じ論理ファイルを編集すると、マージ時に conflict が発生します。**

- ❌ Worker 1 が src/utils.ts 編集 / Worker 2 も src/utils.ts 編集 → マージ時 conflict
- ✅ Worker 1 が src/utils-a.ts 編集 / Worker 2 が src/utils-b.ts 編集 → OK

タスク分割時に編集対象ファイルが重複しないか確認してください。

## 関連情報（メモリから取得）

{memory_context if memory_context else "（関連情報なし）"}

## Self-Check（コンパクション復帰用）

コンテキストが失われた場合：
- **セッションID**: {session_id}
- **Admin ID**: {agent_id}
- **復帰コマンド**: `retrieve_from_memory "{session_id}"`

## 完了条件

- 全 Worker のタスクが completed 状態
- 全ての変更が {branch_name} にマージ済み
- コンフリクトがないこと
- **品質チェックをパスしていること**:
  - アプリが正常に起動・動作する
  - 明らかなバグがない
  - UI が期待通りに表示される（UI タスクの場合）
"""


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
    work_env_section = "\n".join(work_env_lines) if work_env_lines else "（メインリポジトリで作業）"

    return f"""# Task: {task_id}

## What（何をするか）

{task_description}

## Why（なぜやるか）

プロジェクト「{project_name}」の開発タスクとして実行します。

## Who（誰がやるか）

あなたは **{persona_name}** として作業します。

{persona_prompt}

## Constraints（制約）

- コードは既存のスタイルに合わせる
- テストが必要な場合は必ず追加する
- セキュリティ脆弱性を作らない
- 不明点がある場合は `send_message` で Admin に質問する

## Current State（現状）

### 作業環境

{work_env_section}

### 関連情報（メモリから取得）

{memory_context if memory_context else "（関連情報なし）"}

### Self-Check（コンパクション復帰用）

コンテキストが失われた場合、以下を確認してください：

- **タスクID**: {task_id}
- **担当エージェント**: {agent_id}
- **開始時刻**: {timestamp}
- **復帰コマンド**: `retrieve_from_memory "{task_id}"`

## Decisions（決定事項）

（作業中に重要な決定があれば `save_to_memory` で記録してください）

## Notes（メモ）

- 作業完了時は `report_task_completion` で Admin に報告
- 作業結果は `save_to_memory` で保存
"""
