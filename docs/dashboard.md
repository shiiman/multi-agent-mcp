# Dashboard/Task/Cost システム

タスクの状態管理、ダッシュボード表示、コスト追跡を実現するシステムの解説です。

## アーキテクチャ概要

```
┌─────────────────────────────────────────────────────────────────┐
│                    Dashboard システム構造                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────┐  create/update   ┌─────────────────┐              │
│  │  Admin  │ ───────────────→│ Dashboard File  │               │
│  └─────────┘                 │ (dashboard.md)  │               │
│                              └────────┬────────┘               │
│                                       ▲                        │
│  ┌─────────┐  read_messages           │                        │
│  │  Admin  │ ─────────────────────────┘                        │
│  └─────────┘                                                   │
│         ▲                                                       │
│         │ IPC 通知（進捗/完了）                                  │
│  ┌─────────┐                                                   │
│  │ Worker  │                                                   │
│  └─────────┘                                                   │
│                                                                 │
│  ┌─────────┐  get_dashboard   ┌─────────────────┐              │
│  │  Owner  │ ←────────────────│ YAML + Markdown │              │
│  └─────────┘                  │ (構造化データ)   │              │
│                               └─────────────────┘              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 複数プロセス対応の設計

各エージェントは独立した MCP サーバープロセスで動作するため、**インメモリキャッシュを使用しません**。

```
Worker プロセス ── IPC 通知 ──> Admin プロセス
                                      │
                                      │ 書き込み
                                      ▼
                           ┌─────────────────────┐
                           │    dashboard.md     │
                           │ (唯一の真実の源)     │
                           └─────────────────────┘
                            ▲        ▲        ▲
                            │        │        │
                         読み込み  読み込み  読み込み
                            │        │        │
                      Worker プロセス  Admin プロセス  Owner プロセス
```

**重要**:
- Worker は `report_task_progress` / `report_task_completion` で Admin へ通知し、Dashboard を直接更新しません。
- Dashboard 更新は Admin/Owner 側の操作（例: `create_task`, `update_task_status`, Admin の `read_messages`）で行われます。
- 毎回ファイル I/O を行うため、常に最新状態を反映できます。

## ファイル構造

```
{project}/.multi-agent-mcp/{session_id}/
├── dashboard/
│   └── dashboard.md          # ダッシュボード本体
└── tasks/
    └── {agent_id}.md         # Worker 別タスクファイル
```

### ダッシュボードファイルの形式

YAML Front Matter + Markdown 本文（実装準拠の例）:

```markdown
---
workspace_id: abc12345
workspace_path: /path/to/project
updated_at: 2024-01-15T10:20:00
agents:
  - agent_id: worker_xxx
    name: codex1
    role: worker
    status: busy
    current_task_id: task-001
    worktree_path: /path/to/project/.worktrees/feature-task-001
    branch: feature/task-001
    last_activity: 2024-01-15T10:19:00
tasks:
  - id: task-001
    title: ユーザー認証機能
    description: JWT 認証の実装
    status: in_progress
    assigned_agent_id: worker_xxx
    branch: feature/task-001
    worktree_path: /path/to/project/.worktrees/feature-task-001
    progress: 50
    checklist:
      - text: API 設計
        completed: true
      - text: 実装
        completed: false
    logs:
      - timestamp: 2024-01-15T10:10:00
        message: タスク開始
    created_at: 2024-01-15T10:05:00
    started_at: 2024-01-15T10:10:00
    completed_at: null
    error_message: null
    metadata: {}
total_agents: 1
active_agents: 1
total_tasks: 1
completed_tasks: 0
failed_tasks: 0
total_worktrees: 1
active_worktrees: 1
cost:
  total_api_calls: 15
  estimated_tokens: 45000
  estimated_cost_usd: 0.45
  actual_cost_usd: 0.12
  total_cost_usd: 0.57
  warning_threshold_usd: 10.0
  calls:
    - ai_cli: claude
      model: claude-3-5-sonnet
      tokens: 3000
      estimated_cost_usd: 0.03
      actual_cost_usd: 0.02
      cost_source: actual
      status_line: null
      timestamp: 2024-01-15T10:10:00
      agent_id: worker_xxx
      task_id: task-001
---

# Multi-Agent Dashboard

**更新時刻**: 2024-01-15 10:20:00

---

## エージェント状態

| ID | 名前 | 役割 | 状態 | 現在のタスク | worktree |
|:---|:---|:---|:---|:---|:---|
| `worker_xxx` | `codex1` | worker | 🔵 busy | task-001 | `.worktrees/feature-task-001` |

---

## タスク状態

| ID | タイトル | 状態 | 担当 | 進捗 |
|:---|:---|:---|:---|:---|
| `task-001` | ユーザー認証機能 | 🔄 in_progress | `codex1` | 50% |

---

## タスク詳細

### ユーザー認証機能

**状態**: `in_progress`

**進捗**: 50%

**チェックリスト**:
- [x] API 設計
- [ ] 実装

**最新ログ**:
- 10:10 - タスク開始

---

## 統計

- **総エージェント数**: 1
- **アクティブエージェント**: 1
- **総タスク数**: 1
- **完了タスク**: 0
- **失敗タスク**: 0

---

## コスト情報

- **総API呼び出し数**: 15
- **推定トークン数**: 45,000
- **実測コスト (Claude)**: $0.1200
- **推定コスト (全CLI)**: $0.4500
- **合算コスト**: $0.5700
- **警告閾値**: $10.00
```

## タスク状態遷移

```
┌─────────────┐
│   PENDING   │  ← create_task で作成
└──────┬──────┘
       │
       │ assign_task_to_agent
       │ または Worker が作業開始
       ▼
┌─────────────┐
│ IN_PROGRESS │  ← started_at を記録
└──────┬──────┘
       │
       │ report_task_completion
       ▼
┌─────────────┐
│  COMPLETED  │  ← completed_at を記録
└─────────────┘
       または
┌─────────────┐
│   FAILED    │  ← completed_at を記録、エラー情報を保存
└─────────────┘
```

### 状態と日時の記録

| 状態 | 記録される日時 |
| ---- | -------------- |
| PENDING | `created_at` |
| IN_PROGRESS | `started_at` |
| COMPLETED | `completed_at` |
| FAILED | `completed_at` |

## コスト管理

ダッシュボードはセッション内の API コストを追跡します。

```
┌─────────────────────────────────────────────────────────────────┐
│                    コスト追跡の流れ                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────┐  API 呼び出し    ┌─────────────────┐               │
│  │ Worker  │ ────────────────→│  dashboard.md   │               │
│  └─────────┘                  │  (cost セクション)│               │
│                               └────────┬────────┘               │
│  ┌─────────┐  get_cost_summary        │                        │
│  │  Admin  │ ←────────────────────────┤                        │
│  └─────────┘                          │                        │
│                                       ▼                        │
│  ┌─────────┐  警告チェック    ┌─────────────────┐              │
│  │  Owner  │ ←────────────────│ 閾値超過検出     │              │
│  └─────────┘                  └─────────────────┘              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### コスト情報の構造

```yaml
cost:
  total_api_calls: 15        # API 呼び出し回数
  estimated_tokens: 45000    # 推定トークン数
  estimated_cost_usd: 0.45   # 推定コスト（USD, 参考）
  actual_cost_usd: 0.12      # 実測コスト（Claude statusLine）
  total_cost_usd: 0.57       # 合算コスト（実測優先 + 推定）
  warning_threshold_usd: 10.0 # 警告閾値（USD）
  calls:                     # 呼び出し履歴
    - ai_cli: claude
      model: claude-3-5-sonnet
      tokens: 3000
      estimated_cost_usd: 0.03
      actual_cost_usd: 0.02
      cost_source: actual
      status_line: null
      timestamp: 2024-01-15T10:10:00
      agent_id: worker_xxx
      task_id: task-001
```

### コスト見積もりの計算

モデルごとの 1K トークン単価（デフォルト、`MCP_MODEL_COST_TABLE_JSON`）:

| キー | 単価 (USD / 1K tokens) |
| ---- | ---------------------- |
| `claude:opus` | 0.03 |
| `claude:sonnet` | 0.015 |
| `claude:claude-opus-4-8` | 0.03 |
| `claude:claude-opus-4-7` | 0.03 |
| `claude:claude-opus-4-6` | 0.03 |
| `claude:claude-sonnet-4-6` | 0.015 |
| `claude:claude-haiku-4-5-20251001` | 0.003 |
| `codex:gpt-5.5` | 0.01 |
| `codex:gpt-5.4` | 0.01 |
| `codex:gpt-5.3-codex` | 0.01 |
| `gemini:gemini-3-pro-preview` | 0.012 |
| `gemini:gemini-3-flash-preview` | 0.003 |
| `gemini:gemini-3-pro` (legacy) | 0.005 |
| `gemini:gemini-3-flash` (legacy) | 0.0025 |
| `cursor:composer-1.5` | 0.01 |

未定義モデルは `MCP_MODEL_COST_DEFAULT_PER_1K`（デフォルト 0.01）を使用します。
後方互換のため legacy キーも同じテーブルに併存させています。

### コスト警告

閾値を超えると警告メッセージが返されます:

```python
# 閾値を設定
set_cost_warning_threshold(
    threshold_usd=5.0,
    caller_agent_id="owner_xxx"
)

# コスト確認時に警告をチェック
result = get_cost_summary(caller_agent_id="admin_xxx")
summary = result["summary"]
if summary.get("warning_message"):
    print(f"警告: {summary['warning_message']}")
```

### コストの集計方法

| 集計単位 | 取得方法 |
| -------- | -------- |
| セッション全体 | `get_cost_summary()` |
| AI CLI 別 | `get_cost_summary()` の `summary.by_cli` |

`by_agent` / `by_task` の詳細内訳は内部メソッド `get_cost_detailed_breakdown()` の対象で、現状 MCP ツールとしては公開されていません。

## ツール一覧

### タスク管理ツール

| ツール | 説明 | 使用者 |
| ------ | ---- | ------ |
| `create_task` | タスクを作成 | Owner, Admin |
| `update_task_status` | ステータスを更新 | Admin |
| `assign_task_to_agent` | Worker に割り当て | Admin |
| `list_tasks` | タスク一覧取得 | Owner, Admin, Worker |
| `get_task` | タスク詳細取得 | Owner, Admin, Worker |
| `remove_task` | タスク削除 | Owner, Admin |
| `report_task_progress` | 進捗報告（Worker用） | Worker |
| `report_task_completion` | 完了報告（Worker用） | Worker |
| `get_dashboard` | ダッシュボード全体取得 | Owner, Admin, Worker |
| `get_dashboard_summary` | サマリーのみ取得 | Owner, Admin, Worker |

### コスト管理ツール

| ツール | 説明 | 使用者 |
| ------ | ---- | ------ |
| `get_cost_estimate` | 現在のコスト見積もり取得 | Owner, Admin |
| `get_cost_summary` | コストサマリー取得 | Owner, Admin, Worker |
| `set_cost_warning_threshold` | 警告閾値を設定 | Owner |
| `reset_cost_counter` | コストカウンターをリセット | Owner |

## 重要なポイント

### 正データと二次データ

| 種別 | データ | 説明 |
| ---- | ------ | ---- |
| **正データ** | `list_tasks()` | タスクの真の状態 |
| **正データ** | `list_agents()` | エージェントの真の状態 |
| 二次データ | `get_dashboard()` | 整形された要約（参考用） |

**矛盾がある場合は正データを信用してください。**

### チェックリストと進捗の関係

`report_task_progress` に `checklist` を渡すと、Admin の `read_messages()` 取り込み時に進捗が自動計算されます:

```python
# Worker から進捗 + チェックリストを送信
report_task_progress(
    task_id="task-001",
    message="API 設計完了",
    checklist=[
        {"text": "API 設計", "completed": True},
        {"text": "実装", "completed": False},
        {"text": "テスト", "completed": False}
    ],
    caller_agent_id="worker_xxx",
)

# Admin が read_messages() を実行すると Dashboard に反映される
read_messages(agent_id="admin_xxx", caller_agent_id="admin_xxx")

# 1つ完了 → 進捗 33%
# 2つ完了 → 進捗 66%
# 3つ完了 → 進捗 100%
```

### ログの保持

各タスクは最新 5 件のログを保持します。  
ログ追加は `report_task_progress` の `checklist` 経由で Admin が取り込む際（`read_messages`）に行われます。

```python
# Worker 側: 進捗を送信
report_task_progress(
    task_id="task-001",
    progress=50,
    message="API 実装完了"
)

# Admin 側: メッセージ取り込み時にログへ反映
read_messages(agent_id="admin_xxx", caller_agent_id="admin_xxx")

# ログ構造
{
    "timestamp": "2024-01-15T10:30:00",
    "message": "API 実装完了"
}
```

### Worker の完了報告フロー

```python
# 1. 進捗を随時報告（25% ごと推奨）
report_task_progress(
    task_id="task-001",
    progress=25,
    message="設計完了",
    caller_agent_id="worker_xxx"
)

# 2. 完了時に report_task_completion を呼ぶ
#    （Admin への IPC 自動送信。Dashboard 更新は Admin の read_messages 時）
report_task_completion(
    task_id="task-001",
    status="completed",
    message="タスク完了",
    summary="認証機能を実装。JWT 方式を採用。",
    caller_agent_id="worker_xxx"
)
```

## Markdown 生成のカスタマイズ

ダッシュボードの Markdown 出力には以下が含まれます:

- `# Multi-Agent Dashboard`
- `## エージェント状態`（表）
- `## タスク状態`（表）
- `## タスク詳細`
  （`in_progress` または `failed` かつ `checklist/log/error_message` のいずれかがある場合のみ）
- `## 統計`（箇条書き）
- `## コスト情報`（API 呼び出しがある場合のみ、箇条書き）
- ステータス絵文字: `⏳` pending / `🔄` in_progress / `✅` completed / `❌` failed / `🚫` blocked / `🗑️` cancelled

## トラブルシューティング

### タスクが表示されない

確認事項:
1. `create_task` を呼んだか
2. 正しい `session_id` を使用しているか
3. `caller_agent_id` を指定したか

```python
# 正しい呼び出し例
create_task(
    title="タスク名",
    description="説明",
    caller_agent_id="admin_xxx"  # 必須
)
```

### 進捗が更新されない

確認事項:
1. `report_task_progress` を呼んでいるか
2. Worker の `caller_agent_id` が正しいか

```python
# Worker からの進捗報告
report_task_progress(
    task_id="task-001",
    progress=50,
    message="進捗メッセージ",
    caller_agent_id="worker_xxx"  # Worker 自身の ID
)
```

### Dashboard と list_tasks の結果が異なる

`get_dashboard` は整形された表示用データです。
**正確な状態を取得するには `list_tasks` を使用してください。**

```python
# 正確なタスク状態
tasks = list_tasks(caller_agent_id="admin_xxx")
for task in tasks:
    print(f"{task['id']}: {task['status']}")
```

### コストが記録されない

確認事項:

1. ダッシュボードが初期化されているか
2. `session_id` が正しく設定されているか

```python
# ダッシュボード初期化確認
dashboard = get_dashboard(caller_agent_id="admin_xxx")
if dashboard.get("error"):
    # init_tmux_workspace でセッションを開始する
    pass
```

### コスト警告が表示されない

確認事項:

1. 閾値が正しく設定されているか
2. コストが閾値を超えているか

```python
# 閾値の確認と設定
result = get_cost_summary(caller_agent_id="admin_xxx")
summary = result["summary"]
print(f"現在のコスト: ${summary['estimated_cost_usd']}")
print(f"閾値: ${summary['warning_threshold_usd']}")

# 閾値を下げてテスト
set_cost_warning_threshold(
    threshold_usd=0.10,
    caller_agent_id="owner_xxx"
)
```

### コストをリセットしたい

新しいセッションを開始するか、`reset_cost_counter` を使用:

```python
# コストカウンターをリセット
result = reset_cost_counter(caller_agent_id="owner_xxx")
print(f"リセットされた呼び出し数: {result['deleted_count']}")
```
