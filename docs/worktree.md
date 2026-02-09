# Git Worktree システム

Worker エージェントに分離された作業環境を提供するシステムの解説です。

## アーキテクチャ概要

```
┌─────────────────────────────────────────────────────────────────┐
│                        Git Worktree 構造                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  メインリポジトリ（/project）                                    │
│  ├── .git/                    # 共有される Git オブジェクト      │
│  ├── src/                                                       │
│  └── ...                                                        │
│                                                                 │
│  Worktree 1（/parent/.worktrees/feature-a）                     │
│  ├── .git → /project/.git     # メインを参照                    │
│  ├── src/                     # 独立した作業コピー               │
│  └── ...                      # Worker 1 が編集                 │
│                                                                 │
│  Worktree 2（/parent/.worktrees/feature-b）                     │
│  ├── .git → /project/.git     # メインを参照                    │
│  ├── src/                     # 独立した作業コピー               │
│  └── ...                      # Worker 2 が編集                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### なぜ Worktree を使うか

| 方式 | メリット | デメリット |
| ---- | -------- | ---------- |
| **Worktree** | 各 Worker が独立して作業可能 | 初期セットアップが必要 |
| 単一リポジトリ | シンプル | ファイル競合のリスク |

## バックエンド選択

### gtr vs Native Git

```
┌─────────────────────────────────────────────────────────────────┐
│                      バックエンド選択フロー                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  check_gtr_available()                                          │
│         │                                                       │
│         ▼                                                       │
│    gtr がある？ ─── Yes ──→ gtr を使用（推奨）                   │
│         │                                                       │
│        No                                                       │
│         │                                                       │
│         ▼                                                       │
│    Native git worktree を使用（フォールバック）                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### gtr (git-worktree-runner) とは

[gtr](https://github.com/coderabbitai/git-worktree-runner) は git worktree を簡単に管理するツールです。

| 機能 | gtr | Native git |
| ---- | --- | ---------- |
| Worktree 作成 | `git gtr new branch-name` | `git worktree add path branch` |
| 削除時のブランチ処理 | 自動削除 | 手動で別途削除 |
| AI CLI 連携 | `git gtr ai <branch>` で直接起動 | 手動でディレクトリ移動 |
| Worktree パス | 自動決定 | 明示的に指定 |

### gtr のインストール

```bash
# Homebrew
brew install coderabbitai/tap/git-worktree-runner

# または Cargo
cargo install git-worktree-runner
```

## ライフサイクル

```
┌─────────────┐
│ create_worktree │
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌─────────────────┐
│ Worktree    │ ──→ │ assign_worktree │
│ (作成済み)   │     │ (Worker に割当) │
└──────┬──────┘     └────────┬────────┘
       │                     │
       │                     ▼
       │            ┌─────────────────┐
       │            │ Worker が作業    │
       │            │ (コミット・プッシュ) │
       │            └────────┬────────┘
       │                     │
       ▼                     ▼
┌─────────────┐     ┌─────────────────┐
│ remove_worktree │ │ Admin がマージ    │
│ (削除)       │ ←─ │                 │
└─────────────┘     └─────────────────┘
```

## ファイル構造

### gtr 使用時

```
/project/                          # メインリポジトリ
├── .git/
├── .gtrconfig                     # gtr 設定ファイル
└── src/

~/.gtr/                            # gtr 管理ディレクトリ
└── project/
    ├── feature-a/                 # Worktree 1
    └── feature-b/                 # Worktree 2
```

### Native git 使用時

```
/project/                          # メインリポジトリ
├── .git/
└── src/

/parent/.worktrees/                # Worktree 格納ディレクトリ（例）
├── feature-a/                     # Worktree 1
└── feature-b/                     # Worktree 2
```

## ツール一覧

| ツール | 説明 | 使用者 |
| ------ | ---- | ------ |
| `create_worktree` | Worktree を作成 | Owner, Admin |
| `list_worktrees` | 一覧取得 | Owner, Admin, Worker |
| `remove_worktree` | Worktree を削除 | Owner, Admin |
| `assign_worktree` | Worker に割り当て | Owner, Admin |
| `get_worktree_status` | Git ステータス取得 | Owner, Admin, Worker |
| `check_gtr_available` | gtr の利用可否確認 | Owner, Admin |
| `open_worktree_with_ai` | gtr ai で AI CLI を起動 | Owner, Admin |
| `merge_completed_tasks` | 完了タスクのブランチを統合 | Owner, Admin |

## 重要なポイント

### Worktree 作成の流れ（Admin）

```python
# 1. gtr の利用可否を確認
gtr_available = check_gtr_available()

# 2. Worktree を作成
result = create_worktree(
    repo_path="/project",
    worktree_path="/parent/.worktrees/feature-auth",
    branch="feature-auth",
    base_branch="main"
)

# 3. Worker に割り当て
assign_worktree(
    agent_id="worker_xxx",
    worktree_path=result["worktree_path"],
    branch="feature-auth"
)
```

### ブランチ命名（推奨）

```
{base_branch}-worker-{N}

例（推奨）:
- main-worker-1
- main-worker-2
- feature/auth-worker-1
```

### Non-Worktree モード

Worktree を使用しないモードも利用可能です（`MCP_ENABLE_WORKTREE=false`）。

| モード | 特徴 | 用途 |
| ------ | ---- | ---- |
| Worktree モード | 各 Worker が独立 | 並列作業が多い場合 |
| Non-Worktree モード | 全 Worker が同一ディレクトリ | 順次作業、ファイル競合を手動管理 |

### Non-Git モード

`MCP_ENABLE_GIT=false` を設定すると、git 管理されていないディレクトリでも実行できます。

| 項目 | 挙動 |
| ---- | ---- |
| `init_tmux_workspace` | `enable_git=false` で非gitディレクトリでも成功 |
| Worktree 有効判定 | `enable_git && enable_worktree` |
| git/worktree/gtr ツール | `success=false` で明示エラーを返却 |
| ロール/タスクテンプレート | `*_no_git.md` を自動選択 |

`init_tmux_workspace(enable_git=...)` を指定した場合、設定は
`.multi-agent-mcp/config.json` の `enable_git` に保存されます。

### RACE-001: ファイル競合の防止

```
❌ 悪い例（競合発生）
Worker 1: src/utils.ts を編集
Worker 2: src/utils.ts を編集
→ マージ時に conflict!

✅ 良い例（競合なし）
Worker 1: src/utils-a.ts を編集
Worker 2: src/utils-b.ts を編集
→ 問題なくマージ可能
```

## Porcelain 形式

`git worktree list --porcelain` の出力形式:

```
worktree /path/to/main
HEAD abcd1234567890
branch refs/heads/main

worktree /path/to/feature-a
HEAD efgh5678901234
branch refs/heads/feature-a
```

### フィールド説明

| フィールド | 説明 |
| ---------- | ---- |
| `worktree` | Worktree のパス |
| `HEAD` | 現在の HEAD コミット |
| `branch` | チェックアウト中のブランチ（`refs/heads/...`） |
| `detached` | detached HEAD の場合に出現 |
| `bare` | bare リポジトリの場合に出現 |

## 環境変数

| 変数 | デフォルト | 説明 |
| ---- | ---------- | ---- |
| `MCP_ENABLE_GIT` | true | git 前提機能を有効にするか（false で非gitディレクトリ対応） |
| `MCP_ENABLE_WORKTREE` | true | Worktree を使用するか（`MCP_ENABLE_GIT=false` の場合は無効） |

## トラブルシューティング

### gtr が見つからない

```bash
# インストール確認
which gtr

# インストール
brew install coderabbitai/tap/git-worktree-runner
```

### 非gitディレクトリで初期化に失敗する

`MCP_ENABLE_GIT=true` のまま非gitディレクトリで `init_tmux_workspace` を実行すると失敗します。

解決:
```bash
# 明示的に no-git モードで初期化
init_tmux_workspace("/path/to/non-git-dir", session_id="task-1", enable_git=false)
```

### Worktree の削除に失敗

原因:
- ブランチがまだマージされていない
- 未コミットの変更がある

解決:
```bash
# 強制削除（注意: 未コミットの変更は失われる）
git worktree remove --force /path/to/worktree
git branch -D branch-name
```

### 同じブランチで worktree を作成できない

Git の制約: 1つのブランチは1つの worktree でのみチェックアウト可能。

```bash
# 既存の worktree を確認
git worktree list

# 不要な worktree を削除
remove_worktree(
    repo_path="/project",
    worktree_path="/parent/.worktrees/feature-a"
)
```
