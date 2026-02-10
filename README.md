# Multi-Agent MCP

Claude Code + tmux + git worktree（または非gitディレクトリ）を使用したマルチエージェントワークフローの MCP サーバー。

## 概要

このMCPサーバーは、複数のClaude Codeインスタンスを tmux セッションで管理し、並列作業を実現します。
`MCP_ENABLE_GIT=false` を設定すると、git 管理されていないディレクトリでも実行できます。

### Gitモード

| モード | 設定 | 挙動 |
|------|------|------|
| Git有効（デフォルト） | `MCP_ENABLE_GIT=true` | git リポジトリ前提。worktree/gtr 機能を利用可能 |
| Git無効 | `MCP_ENABLE_GIT=false` | 非gitディレクトリで実行可能。git/worktree/gtr 機能は無効 |

`init_tmux_workspace(enable_git=...)` を指定すると、`.multi-agent-mcp/config.json` に保存され、
以降の同一プロジェクト実行で参照されます。

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

通常運用では `--reinstall` なしを推奨します。
追加コマンドは次の「設定の追加・削除（再インストールとは別）」を参照してください。

### 設定の追加・削除（再インストールとは別）

**Claude**

```bash
# 追加（--reinstall なし）
claude mcp add --scope user multi-agent-mcp -- uvx --from git+https://github.com/shiiman/multi-agent-mcp multi-agent-mcp

# 削除
claude mcp remove multi-agent-mcp
```

**Codex**

```bash
# 追加（--reinstall なし）
codex mcp add multi-agent-mcp -- uvx --from git+https://github.com/shiiman/multi-agent-mcp multi-agent-mcp

# 削除
codex mcp remove multi-agent-mcp
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

`--reinstall` オプションを付けると、起動時に毎回 GitHub から最新版を再インストールします。

> **Note**: `--refresh` オプションでは Git リポジトリのキャッシュが効いたままになり、更新が反映されないことがあります。確実に最新版を使用するには `--reinstall` を推奨します。

`--reinstall` なし運用で更新したい場合は、次の「必要なときだけ再インストールする手順」を実行してください。

**必要なときだけ再インストールする手順（Claude/Codex 共通）**:

```bash
# 1) 1回だけ再インストール（通常運用では毎回不要）
uv tool install --force --from git+https://github.com/shiiman/multi-agent-mcp multi-agent-mcp

# 2) 使用中のクライアントを再起動して MCP を再接続
# - Claude を使っている場合: Claude を再起動
# - Codex を使っている場合: Codex を再起動

# 3) 反映確認（使用クライアントに応じて実行）
claude mcp list
codex mcp get multi-agent-mcp

# 4) 反映されない場合のみキャッシュクリア
uv cache clean multi-agent-mcp
```

### 設定の確認

```bash
claude mcp list
codex mcp list
```

## 提供するTools（86個）

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
| `create_worktree` | 新しいgit worktreeを作成（git有効時のみ） |
| `list_worktrees` | worktree一覧を取得（git有効時のみ） |
| `remove_worktree` | worktreeを削除（git有効時のみ） |
| `assign_worktree` | エージェントにworktreeを割り当て（git有効時のみ） |
| `get_worktree_status` | worktreeのgitステータスを取得（git有効時のみ） |
| `check_gtr_available` | gtr (git-worktree-runner) の利用可否を確認（git有効時のみ） |
| `open_worktree_with_ai` | gtr aiでworktreeをAIツールで開く（git有効時のみ） |

#### create_worktree の引数契約

`create_worktree` は以下の引数契約です（`branch_name` 引数は存在しません）。

```python
create_worktree(
    repo_path="/path/to/repo",
    worktree_path="/path/to/worktree",
    branch="feature/xxx",
    create_branch=True,
    base_branch="main",
    caller_agent_id="admin-or-owner-id",
)
```

### マージ（1個）

| Tool | 説明 |
|------|------|
| `merge_completed_tasks` | 完了タスクの作業ブランチを commit なしで統合ブランチへ展開 |

### IPC/メッセージング（4個）

| Tool | 説明 |
|------|------|
| `send_message` | エージェント間でメッセージを送信 |
| `read_messages` | エージェントのメッセージを読み取る |
| `get_unread_count` | 未読メッセージ数を取得 |
| `register_agent_to_ipc` | エージェントをIPCシステムに登録 |

### ダッシュボード/タスク管理（15個）

| Tool | 説明 |
|------|------|
| `create_task` | 新しいタスクを作成 |
| `reopen_task` | 終端タスクを再開（再実行用） |
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

#### create_task の metadata 運用

`create_task` では、タスク説明文字列だけでなく metadata を渡す運用を推奨します。

- `task_kind`: タスク種別（例: `implementation` / `qa` / `docs` / `report`）
- `requires_playwright`: Playwright 検証が必要なタスクか（`true`/`false`）
- `output_dir`: 成果物の出力先（例: `.multi-agent-mcp/{session_id}/reports`）

#### update_task_status の遷移制約

- `update_task_status` は通常の前進遷移に使用します。
- `completed` / `failed` / `cancelled` の終端状態になったタスクを再開するときは、
  `update_task_status` で直接戻さず `reopen_task` を使用してください。

#### 調査レポートの出力ルール

- 調査・検証系タスクの Markdown 成果物は
  `.multi-agent-mcp/{session_id}/reports/*.md` に出力します。
- 出力先は `create_task.metadata.output_dir` で明示し、Worker 指示にも同じパスを記載します。

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

### ヘルスチェック（6個）

| Tool | 説明 |
|------|------|
| `healthcheck_agent` | 特定エージェントのヘルスチェックを実行 |
| `healthcheck_all` | 全エージェントのヘルスチェックを実行 |
| `get_unhealthy_agents` | 異常なエージェント一覧を取得 |
| `attempt_recovery` | エージェントの復旧を試みる |
| `full_recovery` | Worker を完全復旧（agent/worktree再作成＋タスク再割り当て） |
| `monitor_and_recover_workers` | Worker監視と段階復旧（attempt→full→failed化）を実行 |

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

#### switch_model_profile の方針

- モデルプロファイルの正準保存先は **`.multi-agent-mcp/.env`**（`MCP_MODEL_PROFILE_ACTIVE`）です。
- `switch_model_profile` は `.env` のみを更新し、`config.json` へは保存しません。
- `config.json` はセッション設定（`session_id`, `enable_git` など）専用です。

### 主要フィールド（公開I/F）

#### Agent

- 主要フィールド: `id`, `role`, `status`, `tmux_session`, `working_dir`, `worktree_path`, `current_task`
- グリッド/CLI 関連: `session_name`, `window_index`, `pane_index`, `ai_cli`, `ai_bootstrapped`

#### Dashboard / Task

- `TaskInfo`: `task_file_path`, `metadata`, `started_at`, `completed_at`, `error_message`
- `metadata` には `requested_description` や運用キー（`task_kind` など）を保持します
- Dashboard 運用フィールド: `session_started_at`, `session_finished_at`,
  `process_crash_count`, `process_recovery_count`

## 使用例

```
# ターミナルを開いてtmuxワークスペースを構築（git有効）
init_tmux_workspace("/path/to/project", session_id="issue-123")

# 非gitディレクトリで実行
init_tmux_workspace("/path/to/non-git-dir", session_id="issue-123", enable_git=false)

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
| [Files システム](docs/files.md) | 永続ファイル/ディレクトリ構造と命名規則 |
| [IPC システム](docs/ipc.md) | エージェント間メッセージ通信の仕組み |
| [Memory システム](docs/memory.md) | 知識の永続化・共有・アーカイブ機能 |
| [Worktree システム](docs/worktree.md) | Git worktree による分離作業環境 |
| [Dashboard システム](docs/dashboard.md) | タスク状態管理とダッシュボード表示 |
| [Healthcheck システム](docs/healthcheck.md) | Worker 監視、段階復旧、daemon 運用 |
| [Merge ガイド](docs/merge.md) | 完了タスクブランチの統合運用 |

## 環境変数

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `MCP_MCP_DIR` | .multi-agent-mcp | MCP設定ディレクトリ名 |
| `MCP_MAX_WORKERS` | 6 | Workerの最大数 |
| `MCP_ENABLE_GIT` | true | git 前提機能を有効化するか（falseで非gitディレクトリ許可） |
| `MCP_ENABLE_WORKTREE` | true | worktreeを使用するか（`MCP_ENABLE_GIT=false` の場合は無効） |
| `MCP_WINDOW_NAME_MAIN` | main | メインウィンドウ名（Admin + Worker 1-6） |
| `MCP_WINDOW_NAME_WORKER_PREFIX` | workers- | 追加Workerウィンドウ名のプレフィックス |
| `MCP_EXTRA_WORKER_ROWS` | 2 | 追加ウィンドウの行数 |
| `MCP_EXTRA_WORKER_COLS` | 5 | 追加ウィンドウの列数 |
| `MCP_WORKERS_PER_EXTRA_WINDOW` | 10 | 追加ウィンドウのWorker数 |
| `MCP_COST_WARNING_THRESHOLD_USD` | 10.0 | コスト警告の閾値（USD） |
| `MCP_ESTIMATED_TOKENS_PER_CALL` | 2000 | 1回のAPI呼び出しあたりの推定トークン数 |
| `MCP_MODEL_COST_TABLE_JSON` | `{"claude:opus":0.03,...}` | モデル別1000トークン単価テーブル（JSON） |
| `MCP_MODEL_COST_DEFAULT_PER_1K` | 0.01 | 未定義モデル向けの汎用単価（USD/1K） |
| `MCP_HEALTHCHECK_INTERVAL_SECONDS` | 60 | ヘルスチェック監視ループの実行間隔（秒） |
| `MCP_HEALTHCHECK_STALL_TIMEOUT_SECONDS` | 600 | 無応答判定の閾値（秒） |
| `MCP_HEALTHCHECK_MAX_RECOVERY_ATTEMPTS` | 3 | 同一worker/taskに対する復旧試行回数の上限 |
| `MCP_HEALTHCHECK_IDLE_STOP_CONSECUTIVE` | 3 | 実作業なし検知が連続したとき daemon を自動停止する閾値 |
| `MCP_DEFAULT_TERMINAL` | auto | ターミナルアプリ（auto/ghostty/iterm2/terminal） |
| `MCP_MODEL_PROFILE_ACTIVE` | standard | モデルプロファイル（standard/performance） |
| `MCP_MODEL_PROFILE_STANDARD_CLI` | claude | standardプロファイルのAI CLI |
| `MCP_MODEL_PROFILE_STANDARD_ADMIN_MODEL` | opus | standardプロファイルのAdminモデル |
| `MCP_MODEL_PROFILE_STANDARD_WORKER_MODEL` | sonnet | standardプロファイルのWorkerモデル |
| `MCP_MODEL_PROFILE_STANDARD_MAX_WORKERS` | 6 | standardプロファイルのWorker上限 |
| `MCP_MODEL_PROFILE_STANDARD_ADMIN_THINKING_TOKENS` | 4000 | standardプロファイルのAdmin思考トークン数 |
| `MCP_MODEL_PROFILE_STANDARD_WORKER_THINKING_TOKENS` | 4000 | standardプロファイルのWorker思考トークン数 |
| `MCP_MODEL_PROFILE_STANDARD_ADMIN_REASONING_EFFORT` | medium | standardプロファイルのAdmin推論強度 |
| `MCP_MODEL_PROFILE_STANDARD_WORKER_REASONING_EFFORT` | medium | standardプロファイルのWorker推論強度 |
| `MCP_MODEL_PROFILE_PERFORMANCE_CLI` | claude | performanceプロファイルのAI CLI |
| `MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_MODEL` | opus | performanceプロファイルのAdminモデル |
| `MCP_MODEL_PROFILE_PERFORMANCE_WORKER_MODEL` | opus | performanceプロファイルのWorkerモデル |
| `MCP_MODEL_PROFILE_PERFORMANCE_MAX_WORKERS` | 16 | performanceプロファイルのWorker上限 |
| `MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_THINKING_TOKENS` | 30000 | performanceプロファイルのAdmin思考トークン数 |
| `MCP_MODEL_PROFILE_PERFORMANCE_WORKER_THINKING_TOKENS` | 4000 | performanceプロファイルのWorker思考トークン数 |
| `MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_REASONING_EFFORT` | high | performanceプロファイルのAdmin推論強度 |
| `MCP_MODEL_PROFILE_PERFORMANCE_WORKER_REASONING_EFFORT` | high | performanceプロファイルのWorker推論強度 |
| `MCP_PROJECT_ROOT` | - | プロジェクトルート（.env読み込み用） |
| `MCP_CLI_DEFAULT_CLAUDE_ADMIN_MODEL` | opus | Claude CLIのAdminデフォルトモデル |
| `MCP_CLI_DEFAULT_CLAUDE_WORKER_MODEL` | sonnet | Claude CLIのWorkerデフォルトモデル |
| `MCP_CLI_DEFAULT_CODEX_ADMIN_MODEL` | gpt-5.3-codex | Codex CLIのAdminデフォルトモデル |
| `MCP_CLI_DEFAULT_CODEX_WORKER_MODEL` | gpt-5.3-codex | Codex CLIのWorkerデフォルトモデル |
| `MCP_CLI_DEFAULT_GEMINI_ADMIN_MODEL` | gemini-3-pro | Gemini CLIのAdminデフォルトモデル |
| `MCP_CLI_DEFAULT_GEMINI_WORKER_MODEL` | gemini-3-flash | Gemini CLIのWorkerデフォルトモデル |
| `MCP_WORKER_CLI_MODE` | uniform | Worker CLI設定モード（uniform/per-worker） |
| `MCP_WORKER_CLI_1..16` | (empty) | per-workerモードでのWorker別CLI設定（未設定時はアクティブプロファイルCLIを利用） |
| `MCP_WORKER_MODEL_MODE` | uniform | Workerモデル設定モード（uniform/per-worker） |
| `MCP_WORKER_MODEL_UNIFORM` | (empty) | uniformモード時のWorkerモデル（未設定時はプロファイルのWORKER_MODEL） |
| `MCP_WORKER_MODEL_1..16` | (empty) | per-workerモードでのWorker別モデル設定（未設定時はUNIFORM→プロファイル順で解決） |
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
├── config.json             # 実行時設定（session_id / enable_git など）
├── memory/                 # プロジェクトメモリ
├── screenshot/             # スクリーンショット保存先
└── {session_id}/           # セッション別
    ├── dashboard/          # ダッシュボード
    ├── tasks/              # タスクファイル
    └── reports/            # 調査/検証レポート（*.md）
```

### プロジェクト別設定

プロジェクトごとに設定を変更する場合、`.multi-agent-mcp/.env` ファイルを編集してください。
`init_tmux_workspace` 実行時に、設定可能な全変数がコメント付きで自動生成されます。

**設定の優先順位**:
1. 環境変数（最優先）
2. `.multi-agent-mcp/.env` ファイル
3. デフォルト値

`enable_git` のみ、実行時は以下の優先順位で解決されます:
1. `init_tmux_workspace(enable_git=...)` の引数
2. `.multi-agent-mcp/config.json` の `enable_git`
3. 環境変数 / `.env`
4. デフォルト値（`true`）

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
