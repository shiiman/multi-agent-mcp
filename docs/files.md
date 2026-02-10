# ファイル管理システム

Multi-Agent MCP が保存・編集するファイルの一覧と、そのディレクトリ構造を解説します。

## アーキテクチャ概要

```
┌─────────────────────────────────────────────────────────────────┐
│                    ファイル管理の2層構造                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  グローバル層: ~/.multi-agent-mcp/                               │
│  ├── 全プロジェクトで共有                                        │
│  ├── メモリ・学習内容                                            │
│  └── エージェントレジストリ                                      │
│                                                                 │
│  プロジェクト層: {project}/.multi-agent-mcp/                     │
│  ├── プロジェクト固有の設定                                      │
│  ├── セッション別のデータ                                        │
│  └── タスク・ダッシュボード・IPC                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## ディレクトリ構造

### グローバル層

```
~/.multi-agent-mcp/
├── memory/                            # グローバルメモリ
│   ├── {key}.md                       # メモリエントリ（YAML FM + MD）
│   └── archive/                       # アーカイブ（自動移動先）
└── agents/                            # エージェントレジストリ
    └── {agent_id}.json                # エージェント情報
```

### プロジェクト層

```
{project}/
├── .multi-agent-mcp/                  # MCP 設定ディレクトリ
│   ├── .env                           # プロジェクト別環境変数
│   ├── config.json                    # MCP ツール設定
│   ├── memory/                        # プロジェクトメモリ
│   │   ├── {key}.md
│   │   └── archive/
│   ├── screenshot/                    # スクリーンショット
│   │   └── *.png/jpg/jpeg/gif/webp
│   └── {session_id}/                  # セッション別ディレクトリ
│       ├── dashboard/
│       │   └── dashboard.md           # ダッシュボード
│       ├── tasks/                     # Worker別タスク指示ファイル
│       │   └── {agent_id}.md
│       ├── ipc/                       # プロセス間通信
│       │   └── {agent_id}/
│       │       └── {timestamp}_{msg_id}.md
│       ├── agents.json                # セッション内エージェント一覧
│       └── memory/                    # セッション別メモリ
│           ├── {key}.md
│           └── archive/
└── .gtrconfig                         # Git worktree 設定
```

## ファイル詳細

### 1. 設定ファイル

#### `.multi-agent-mcp/.env`

| 項目 | 内容 |
| ---- | ---- |
| パス | `{project}/.multi-agent-mcp/.env` |
| フォーマット | ENV（KEY=VALUE 形式） |
| 用途 | プロジェクト別の環境変数設定 |
| 読み込み | MCP サーバー起動時（Settings で自動読み込み） |
| 書き込み | `init_tmux_workspace` で初期作成 |

```env
MCP_MAX_WORKERS=6
MCP_ENABLE_WORKTREE=true
MCP_COST_WARNING_THRESHOLD_USD=10.0
```

#### `.multi-agent-mcp/config.json`

| 項目 | 内容 |
| ---- | ---- |
| パス | `{project}/.multi-agent-mcp/config.json` |
| フォーマット | JSON |
| 用途 | MCP ツール設定（`session_id`, `enable_git` など） |
| 読み込み | 各ツール実行時 |
| 書き込み | `init_tmux_workspace` で初期作成 |

```json
{
  "mcp_tool_prefix": "mcp__multi-agent-mcp__",
  "enable_git": true,
  "session_id": "issue-123"
}
```

#### `.gtrconfig`

| 項目 | 内容 |
| ---- | ---- |
| パス | `{project}/.gtrconfig` |
| フォーマット | TOML |
| 用途 | Git worktree 設定（パッケージマネージャー、除外パターンなど） |
| 読み込み | `check_gtrconfig`, worktree 作成時 |
| 書き込み | `generate_gtrconfig` で自動生成 |
| 管理 | `GtrconfigManager` |

```toml
[copy]
include = ["*.md", "CLAUDE.md"]
exclude = ["**/.git/**", "**/__pycache__/**", "**/.venv/**"]

[hooks]
postCreate = ["uv sync"]
```

### 2. メモリファイル

#### `{key}.md`

| 項目 | 内容 |
| ---- | ---- |
| パス（グローバル） | `~/.multi-agent-mcp/memory/{key}.md` |
| パス（プロジェクト） | `{project}/.multi-agent-mcp/memory/{key}.md` |
| パス（セッション） | `{project}/.multi-agent-mcp/{session_id}/memory/{key}.md` |
| フォーマット | YAML Front Matter + Markdown |
| 用途 | 永続的な知識・学習内容の保存 |
| 読み込み | `retrieve_from_memory`, `get_memory_entry` |
| 書き込み | `save_to_memory` |
| 管理 | `MemoryManager` |

```markdown
---
key: api-design-decision
tags:
  - architecture
  - api
created_at: 2024-01-15T10:30:00
updated_at: 2024-01-15T10:30:00
---

## API設計の決定事項

REST API は以下の方針で設計する...
```

**命名規則**:

- キーをファイル名として使用
- 危険な文字（`< > : " / \ | ? *`）は `_` に置換
- 先頭・末尾の空白とドットは除去

### 3. ダッシュボード

#### `dashboard.md`

| 項目 | 内容 |
| ---- | ---- |
| パス | `{project}/.multi-agent-mcp/{session_id}/dashboard/dashboard.md` |
| フォーマット | YAML Front Matter + Markdown |
| 用途 | タスク状態・エージェント状態・コスト情報の管理 |
| 読み込み | `get_dashboard`, `get_dashboard_summary`, `list_tasks`, `get_task` |
| 書き込み | `create_task`, `update_task_status`, `assign_task_to_agent`, `read_messages`（Admin の自動反映）, `get_dashboard`/`get_dashboard_summary`（Admin/Owner 同期時） |
| 管理 | `DashboardManager` |

```markdown
---
workspace_id: issue-123
workspace_path: /path/to/project
updated_at: 2024-01-15T10:00:00
tasks:
  - id: task-001
    title: ユーザー認証機能
    status: in_progress
    progress: 50
    assigned_agent_id: worker_xxx
agents:
  - agent_id: worker_xxx
    role: worker
    status: busy
    current_task_id: task-001
---

# Multi-Agent Dashboard

## エージェント状態

| ID | 名前 | 役割 | 状態 | 現在のタスク | worktree |
|:---|:---|:---|:---|:---|:---|
| `worker_xxx` | `codex1` | worker | 🔵 busy | task-001 | `.worktrees/feature-task-001` |
```

### 4. タスクファイル

#### `{agent_id}.md`

| 項目 | 内容 |
| ---- | ---- |
| パス | `{project}/.multi-agent-mcp/{session_id}/tasks/{agent_id}.md` |
| フォーマット | Markdown |
| 用途 | Worker へのタスク指示 |
| 読み込み | なし（AI CLI が直接読み込む） |
| 書き込み | `send_task` |

### 5. IPC メッセージ

#### `{timestamp}_{msg_id}.md`

| 項目 | 内容 |
| ---- | ---- |
| パス | `{project}/.multi-agent-mcp/{session_id}/ipc/{agent_id}/{timestamp}_{msg_id}.md` |
| フォーマット | YAML Front Matter + Markdown |
| 用途 | エージェント間のメッセージ通信 |
| 読み込み | `read_messages` |
| 書き込み | `send_message` |
| 管理 | `IPCManager` |

```markdown
---
id: msg-001
sender_id: admin_xxx
receiver_id: worker_001
message_type: task
priority: normal
subject: タスク割り当て
created_at: 2024-01-15T10:00:00
read_at: null
---

認証機能の実装をお願いします。
```

**命名規則**:

- `{YYYYMMDD}_{HHMMSS}_{ffffff}_{message_id_prefix8}.md`
- タイムスタンプ順にソート可能

### 6. エージェントファイル

#### `{agent_id}.json`（グローバル）

| 項目 | 内容 |
| ---- | ---- |
| パス | `~/.multi-agent-mcp/agents/{agent_id}.json` |
| フォーマット | JSON |
| 用途 | エージェントの project_root / session_id を記録 |
| 読み込み | `get_project_root_from_registry`, `get_session_id_from_registry` |
| 書き込み | `save_agent_to_registry` |
| 管理 | `helpers.py` |

```json
{
  "agent_id": "worker_001",
  "owner_id": "owner_xxx",
  "project_root": "/path/to/project",
  "session_id": "issue-123"
}
```

#### `agents.json`（セッション）

| 項目 | 内容 |
| ---- | ---- |
| パス | `{project}/.multi-agent-mcp/{session_id}/agents.json` |
| フォーマット | JSON |
| 用途 | セッション内の全エージェント情報 |
| 読み込み | `load_agents_from_file` |
| 書き込み | `save_agent_to_file` |
| 管理 | `helpers.py` |

```json
{
  "owner_xxx": {
    "id": "owner_xxx",
    "role": "owner",
    "status": "idle"
  },
  "worker_001": {
    "id": "worker_001",
    "role": "worker",
    "status": "busy",
    "current_task": "task-001"
  }
}
```

### 7. スクリーンショット

| 項目 | 内容 |
| ---- | ---- |
| パス | `{project}/.multi-agent-mcp/screenshot/*.{png,jpg,jpeg,gif,webp}` |
| フォーマット | 画像ファイル |
| 用途 | UI 確認用のスクリーンショット |
| 読み込み | `list_screenshots`, `read_screenshot`, `read_latest_screenshot` |
| 書き込み | 外部から追加（MCP では読み取り専用） |

**対応拡張子**: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`

## ファイル一覧

| カテゴリ | ファイル | フォーマット | 読み | 書き | 自動作成 |
| -------- | -------- | ------------ | ---- | ---- | -------- |
| 設定 | `.env` | ENV | ✓ | ✓ | `init_tmux_workspace` |
| 設定 | `config.json` | JSON | ✓ | ✓ | `init_tmux_workspace` |
| 設定 | `.gtrconfig` | TOML | ✓ | ✓ | `generate_gtrconfig` |
| メモリ | `{key}.md` | YAML FM + MD | ✓ | ✓ | `save_to_memory` |
| ダッシュボード | `dashboard.md` | YAML FM + MD | ✓ | ✓ | `create_task` |
| タスク | `{agent_id}.md` | Markdown | - | ✓ | `send_task` |
| IPC | `{timestamp}_{msg_id}.md` | YAML FM + MD | ✓ | ✓ | `send_message` |
| エージェント(グローバル) | `{agent_id}.json` | JSON | ✓ | ✓ | `save_agent_to_registry` |
| エージェント(セッション) | `agents.json` | JSON | ✓ | ✓ | `save_agent_to_file` |
| スクリーンショット | `*.png/jpg/...` | Image | ✓ | - | 外部 |

## 命名規則

### ファイル名のサニタイズ

メモリキーなどをファイル名に変換する際のルール:

1. 危険な文字を `_` に置換: `< > : " / \ | ? *`
2. 先頭・末尾の空白とドットを除去
3. 空の場合は `entry` をデフォルト名として使用

```python
# 例
"api/design"      → "api_design.md"
"user:settings"   → "user_settings.md"
"  .hidden  "     → "hidden.md"
```

### セッションディレクトリ

- `session_id` がセッションディレクトリ名として使用される
- 通常は Issue 番号や UUID

```
.multi-agent-mcp/
├── issue-123/          # session_id = "issue-123"
├── feature-456/        # session_id = "feature-456"
└── memory/             # session_id なしの場合はこちら
```

### IPC メッセージファイル

- `{YYYYMMDD}_{HHMMSS}_{ffffff}_{message_id_prefix8}.md`
- タイムスタンプ順にソート可能
- `agent_id` はサニタイズされてディレクトリ名に使用

## 環境変数

ディレクトリ設定に関連する環境変数:

| 変数 | デフォルト | 説明 |
| ---- | ---------- | ---- |
| `MCP_MCP_DIR` | `.multi-agent-mcp` | MCP 設定ディレクトリ名 |
| `MCP_PROJECT_ROOT` | - | プロジェクトルートパス |
| `MCP_MEMORY_MAX_ENTRIES` | 1000 | メモリ最大エントリ数 |
| `MCP_MEMORY_TTL_DAYS` | 90 | メモリエントリの有効期限（日） |

## 関連ドキュメント

- [Memory システム](./memory.md) - メモリ機能の詳細
- [Dashboard/Task システム](./dashboard.md) - タスク管理の詳細
- [Git Worktree](./worktree.md) - worktree 機能の詳細
- [IPC](./ipc.md) - エージェント間通信の詳細
- [Healthcheck システム](./healthcheck.md) - Worker 監視と自動復旧
- [Merge ガイド](./merge.md) - 完了タスクブランチの統合
