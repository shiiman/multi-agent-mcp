# Multi-Agent MCP

Claude Code + tmux + git worktree を使用したマルチエージェントワークフローの MCP サーバー。

## 概要

このMCPサーバーは、複数のClaude Codeインスタンスを tmux セッションで管理し、並列作業を実現します。

### 階層構造

- **Owner** (1体): 全体指揮、タスク分解、Issue作成
- **Admin** (1体): Worker管理、進捗管理、ダッシュボード更新
- **Worker** (最大6体): 割り当てられたタスクの実行

## 必要条件

- Python 3.10以上
- tmux
- uv（推奨）または pip

## インストール

GitHub から直接インストールできます（リポジトリの clone は不要）。

### CLI で追加

```bash
# グローバル設定（全プロジェクトで使用可能）
claude mcp add --scope user multi-agent-mcp -- uvx --reinstall --from git+https://github.com/shiiman/multi-agent-mcp multi-agent-mcp

# プロジェクト設定（そのプロジェクトのみ、チーム共有）
claude mcp add --scope project multi-agent-mcp -- uvx --reinstall --from git+https://github.com/shiiman/multi-agent-mcp multi-agent-mcp
```

### 設定ファイルに直接記述

**グローバル設定** (`~/.claude.json`):

```json
{
  "mcpServers": {
    "multi-agent-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--reinstall",
        "--from", "git+https://github.com/shiiman/multi-agent-mcp",
        "multi-agent-mcp"
      ],
      "env": {
        "MCP_MAX_WORKERS": "6"
      }
    }
  }
}
```

**プロジェクト設定** (`.mcp.json` をプロジェクトルートに作成):

```json
{
  "mcpServers": {
    "multi-agent-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--reinstall",
        "--from", "git+https://github.com/shiiman/multi-agent-mcp",
        "multi-agent-mcp"
      ],
      "env": {
        "MCP_MAX_WORKERS": "6"
      }
    }
  }
}
```

### 自動更新について

上記の例では `--reinstall` オプションを使用しており、起動時に毎回 GitHub から最新版を再インストールします。

> **Note**: `--refresh` オプションでは Git リポジトリのキャッシュが効いたままになり、更新が反映されないことがあります。確実に最新版を使用するには `--reinstall` を推奨します。

**自動更新が不要な場合**（高速起動）:

`--reinstall` を削除すると、初回のみ GitHub から取得し、以降はキャッシュを使用します。

```bash
claude mcp add --scope user multi-agent-mcp -- uvx --from git+https://github.com/shiiman/multi-agent-mcp multi-agent-mcp
```

**手動更新方法**（`--reinstall` なしの場合）:

```bash
uv cache clean multi-agent-mcp
# または
uv tool install --force --from git+https://github.com/shiiman/multi-agent-mcp multi-agent-mcp
```

### 設定の確認

```bash
claude mcp list
```

## 提供するTools（85個）

### セッション管理（4個）

| Tool | 説明 |
|------|------|
| `init_tmux_workspace` | ターミナルを開いてtmuxワークスペースを構築（8ペイングリッド） |
| `cleanup_workspace` | 全エージェントを終了しリソースを解放 |
| `check_all_tasks_completed` | 全タスクの完了状態をチェック |
| `cleanup_on_completion` | 全タスク完了時にワークスペースをクリーンアップ |

### エージェント管理（6個）

| Tool | 説明 |
|------|------|
| `create_agent` | 新しいエージェントを作成（tmuxセッション起動） |
| `list_agents` | 全エージェントの一覧を取得 |
| `get_agent_status` | 指定エージェントの詳細ステータスを取得 |
| `terminate_agent` | エージェントを終了 |
| `initialize_agent` | エージェントにロールテンプレートを渡してAI CLIを起動 |
| `create_workers_batch` | 複数のWorkerを並列で作成しタスクを割り当て |

### コマンド実行（5個）

| Tool | 説明 |
|------|------|
| `send_command` | エージェントにコマンドを送信 |
| `get_output` | エージェントのtmux出力を取得 |
| `send_task` | タスク指示をファイル経由でWorkerに送信 |
| `open_session` | エージェントのtmuxセッションをターミナルで開く |
| `broadcast_command` | 全エージェント（または特定役割）にコマンド送信 |

### Git Worktree管理（7個）

| Tool | 説明 |
|------|------|
| `create_worktree` | 新しいgit worktreeを作成 |
| `list_worktrees` | worktree一覧を取得 |
| `remove_worktree` | worktreeを削除 |
| `assign_worktree` | エージェントにworktreeを割り当て |
| `get_worktree_status` | worktreeのgitステータスを取得 |
| `check_gtr_available` | gtr (git-worktree-runner) の利用可否を確認 |
| `open_worktree_with_ai` | gtr aiでworktreeをAIツールで開く |

### IPC/メッセージング（5個）

| Tool | 説明 |
|------|------|
| `send_message` | エージェント間でメッセージを送信 |
| `read_messages` | エージェントのメッセージを読み取る |
| `get_unread_count` | 未読メッセージ数を取得 |
| `clear_messages` | メッセージをクリア |
| `register_agent_to_ipc` | エージェントをIPCシステムに登録 |

### ダッシュボード/タスク管理（14個）

| Tool | 説明 |
|------|------|
| `create_task` | 新しいタスクを作成 |
| `update_task_status` | タスクのステータスを更新（Admin専用） |
| `assign_task_to_agent` | タスクをエージェントに割り当て（Admin専用） |
| `list_tasks` | タスク一覧を取得 |
| `report_task_progress` | Workerがタスクの進捗を報告 |
| `report_task_completion` | WorkerがAdminにタスク完了を報告（Worker専用） |
| `get_task` | タスクの詳細を取得 |
| `remove_task` | タスクを削除 |
| `get_dashboard` | ダッシュボード全体を取得 |
| `get_dashboard_summary` | ダッシュボードのサマリーを取得 |
| `get_cost_estimate` | 現在のコスト推定を取得 |
| `set_cost_warning_threshold` | コスト警告の閾値を設定 |
| `reset_cost_counter` | コストカウンターをリセット |
| `get_cost_summary` | コストサマリーを取得 |

### Gtrconfig（3個）

| Tool | 説明 |
|------|------|
| `check_gtrconfig` | .gtrconfigの存在確認と内容取得 |
| `analyze_project_for_gtrconfig` | プロジェクト構造を解析して推奨設定を提案 |
| `generate_gtrconfig` | .gtrconfigを自動生成 |

### テンプレート（4個）

| Tool | 説明 |
|------|------|
| `list_workspace_templates` | 利用可能なテンプレート一覧を取得 |
| `get_workspace_template` | 特定テンプレートの詳細を取得 |
| `get_role_guide` | 特定ロールのワークフローガイドを取得 |
| `list_role_guides` | 利用可能なロールガイド一覧を取得 |

### スケジューラー（3個）

| Tool | 説明 |
|------|------|
| `enqueue_task` | タスクをスケジューラーキューに追加 |
| `auto_assign_tasks` | 空いているWorkerにタスクを自動割り当て |
| `get_task_queue` | 現在のタスクキューを取得 |

### ヘルスチェック（5個）

| Tool | 説明 |
|------|------|
| `healthcheck_agent` | 特定エージェントのヘルスチェックを実行 |
| `healthcheck_all` | 全エージェントのヘルスチェックを実行 |
| `get_unhealthy_agents` | 異常なエージェント一覧を取得 |
| `attempt_recovery` | エージェントの復旧を試みる |
| `record_heartbeat` | ハートビートを記録 |

### ペルソナ（3個）

| Tool | 説明 |
|------|------|
| `detect_task_type` | タスクの説明からタスクタイプを検出 |
| `get_optimal_persona` | タスクに最適なペルソナを取得 |
| `list_personas` | 利用可能なペルソナ一覧を取得 |

### メモリ管理（19個）

| Tool | 説明 |
|------|------|
| `save_to_memory` | 知識をプロジェクトメモリに保存 |
| `retrieve_from_memory` | プロジェクトメモリから知識を検索 |
| `get_memory_entry` | キーでメモリエントリを取得 |
| `list_memory_entries` | メモリエントリ一覧を取得 |
| `delete_memory_entry` | メモリエントリを削除 |
| `get_memory_summary` | メモリのサマリー情報を取得 |
| `search_memory_archive` | アーカイブされたメモリを検索 |
| `list_memory_archive` | アーカイブエントリ一覧を取得 |
| `restore_from_memory_archive` | アーカイブからエントリを復元 |
| `get_memory_archive_summary` | アーカイブのサマリー情報を取得 |
| `save_to_global_memory` | グローバルメモリに保存（全プロジェクト共通） |
| `retrieve_from_global_memory` | グローバルメモリから検索 |
| `list_global_memory_entries` | グローバルメモリエントリ一覧を取得 |
| `get_global_memory_summary` | グローバルメモリのサマリーを取得 |
| `delete_global_memory_entry` | グローバルメモリエントリを削除 |
| `search_global_memory_archive` | グローバルアーカイブを検索 |
| `list_global_memory_archive` | グローバルアーカイブ一覧を取得 |
| `restore_from_global_memory_archive` | グローバルアーカイブからエントリを復元 |
| `get_global_memory_archive_summary` | グローバルアーカイブのサマリーを取得 |

### スクリーンショット（4個）

| Tool | 説明 |
|------|------|
| `get_screenshot_dir` | スクリーンショットディレクトリを取得 |
| `list_screenshots` | スクリーンショット一覧（最新N件） |
| `read_screenshot` | 指定ファイルを読み取り（Base64） |
| `read_latest_screenshot` | 最新のスクリーンショットを読み取り |

### モデルプロファイル（3個）

| Tool | 説明 |
|------|------|
| `get_model_profile` | 現在のプロファイルを取得 |
| `switch_model_profile` | プロファイルを切り替え（standard/performance） |
| `get_model_profile_settings` | プロファイルの設定詳細を取得 |

## 使用例

```
# ターミナルを開いてtmuxワークスペースを構築
init_tmux_workspace("/path/to/project")

# Ownerエージェントを作成
create_agent("owner", "/path/to/project")

# Workerエージェントを作成
create_agent("worker", "/path/to/worktree1")
create_agent("worker", "/path/to/worktree2")

# エージェント一覧を確認
list_agents()

# Workerにコマンドを送信
send_command("abc12345", "echo 'Hello from Worker'")

# 出力を取得
get_output("abc12345", 100)

# 全Workerにコマンドをブロードキャスト
broadcast_command("git status", "worker")

# クリーンアップ
cleanup_workspace()
```

## ドキュメント

各システムの詳細な解説は以下を参照してください：

| ドキュメント | 説明 |
| ------------ | ---- |
| [IPC システム](docs/ipc.md) | エージェント間メッセージ通信の仕組み |
| [Memory システム](docs/memory.md) | 知識の永続化・共有・アーカイブ機能 |
| [Worktree システム](docs/worktree.md) | Git worktree による分離作業環境 |
| [Dashboard システム](docs/dashboard.md) | タスク状態管理とダッシュボード表示 |

## 環境変数

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `MCP_MCP_DIR` | .multi-agent-mcp | MCP設定ディレクトリ名 |
| `MCP_MAX_WORKERS` | 6 | Workerの最大数 |
| `MCP_ENABLE_WORKTREE` | true | git worktreeを使用するか |
| `MCP_WINDOW_NAME_MAIN` | main | メインウィンドウ名（Admin + Worker 1-6） |
| `MCP_WINDOW_NAME_WORKER_PREFIX` | workers- | 追加Workerウィンドウ名のプレフィックス |
| `MCP_MAIN_WORKER_ROWS` | 2 | メインウィンドウのWorkerエリア行数 |
| `MCP_MAIN_WORKER_COLS` | 3 | メインウィンドウのWorkerエリア列数 |
| `MCP_WORKERS_PER_MAIN_WINDOW` | 6 | メインウィンドウのWorker数 |
| `MCP_EXTRA_WORKER_ROWS` | 2 | 追加ウィンドウの行数 |
| `MCP_EXTRA_WORKER_COLS` | 5 | 追加ウィンドウの列数 |
| `MCP_WORKERS_PER_EXTRA_WINDOW` | 10 | 追加ウィンドウのWorker数 |
| `MCP_COST_WARNING_THRESHOLD_USD` | 10.0 | コスト警告の閾値（USD） |
| `MCP_ESTIMATED_TOKENS_PER_CALL` | 2000 | 1回のAPI呼び出しあたりの推定トークン数 |
| `MCP_COST_PER_1K_TOKENS_CLAUDE` | 0.015 | Claudeの1000トークンあたりのコスト（USD） |
| `MCP_COST_PER_1K_TOKENS_CODEX` | 0.01 | Codexの1000トークンあたりのコスト（USD） |
| `MCP_COST_PER_1K_TOKENS_GEMINI` | 0.005 | Geminiの1000トークンあたりのコスト（USD） |
| `MCP_HEALTHCHECK_INTERVAL_SECONDS` | 60 | ヘルスチェック間隔（秒）- 応答なしで異常判断 |
| `MCP_DEFAULT_TERMINAL` | auto | ターミナルアプリ（auto/ghostty/iterm2/terminal） |
| `MCP_MODEL_PROFILE_ACTIVE` | standard | モデルプロファイル（standard/performance） |
| `MCP_MODEL_PROFILE_STANDARD_CLI` | claude | standardプロファイルのAI CLI |
| `MCP_MODEL_PROFILE_STANDARD_ADMIN_MODEL` | claude-opus-4-20250514 | standardプロファイルのAdminモデル |
| `MCP_MODEL_PROFILE_STANDARD_WORKER_MODEL` | claude-sonnet-4-20250514 | standardプロファイルのWorkerモデル |
| `MCP_MODEL_PROFILE_STANDARD_MAX_WORKERS` | 6 | standardプロファイルのWorker上限 |
| `MCP_MODEL_PROFILE_STANDARD_THINKING_MULTIPLIER` | 1.0 | standardプロファイルの思考倍率 |
| `MCP_MODEL_PROFILE_PERFORMANCE_CLI` | claude | performanceプロファイルのAI CLI |
| `MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_MODEL` | claude-opus-4-20250514 | performanceプロファイルのAdminモデル |
| `MCP_MODEL_PROFILE_PERFORMANCE_WORKER_MODEL` | claude-opus-4-20250514 | performanceプロファイルのWorkerモデル |
| `MCP_MODEL_PROFILE_PERFORMANCE_MAX_WORKERS` | 16 | performanceプロファイルのWorker上限 |
| `MCP_MODEL_PROFILE_PERFORMANCE_THINKING_MULTIPLIER` | 2.0 | performanceプロファイルの思考倍率 |
| `MCP_PROJECT_ROOT` | - | プロジェクトルート（.env読み込み用） |
| `MCP_OWNER_THINKING_TOKENS` | 0 | Ownerの思考トークン数 |
| `MCP_ADMIN_THINKING_TOKENS` | 1000 | Adminの思考トークン数 |
| `MCP_WORKER_THINKING_TOKENS` | 10000 | Workerの思考トークン数 |
| `MCP_QUALITY_CHECK_MAX_ITERATIONS` | 5 | 品質チェックの最大イテレーション回数 |
| `MCP_QUALITY_CHECK_SAME_ISSUE_LIMIT` | 3 | 同一問題の繰り返し上限 |
| `MCP_MEMORY_MAX_ENTRIES` | 1000 | メモリの最大エントリ数 |
| `MCP_MEMORY_TTL_DAYS` | 90 | メモリエントリの保持期間（日） |
| `MCP_SCREENSHOT_EXTENSIONS` | [".png",".jpg",...] | スクリーンショットとして認識する拡張子 |

## ディレクトリ構造

`init_tmux_workspace` 実行時に以下のディレクトリと `.env` ファイルが自動作成されます：

```
{project_root}/.multi-agent-mcp/
├── .env                    # プロジェクト設定（テンプレート付き）
├── memory/                 # プロジェクトメモリ
├── screenshot/             # スクリーンショット保存先
└── {session_id}/           # セッション別
    ├── dashboard/          # ダッシュボード
    └── tasks/              # タスクファイル
```

### プロジェクト別設定

プロジェクトごとに設定を変更する場合、`.multi-agent-mcp/.env` ファイルを編集してください。
`init_tmux_workspace` 実行時に、設定可能な全変数がコメント付きで自動生成されます。

**設定の優先順位**:
1. 環境変数（最優先）
2. `.multi-agent-mcp/.env` ファイル
3. デフォルト値

## gitignore 推奨

タスクファイルやダッシュボードは `.multi-agent-mcp/` ディレクトリに出力されます。
このディレクトリは一時ファイルなので、`.gitignore` に追加することを推奨します。

```bash
# プロジェクトの .gitignore に追加
echo ".multi-agent-mcp/" >> .gitignore
```

## 開発（コントリビューター向け）

ローカルで開発する場合は、リポジトリをクローンしてください。

```bash
# リポジトリをクローン
git clone https://github.com/shiiman/multi-agent-mcp.git
cd multi-agent-mcp

# 開発用依存関係をインストール
uv sync --all-extras

# テストを実行
uv run pytest

# リンターを実行
uv run ruff check src/
```

## ライセンス

MIT
