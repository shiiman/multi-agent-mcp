# Memory システム

エージェント間での知識共有と永続化を実現するシステムの解説です。

## アーキテクチャ概要

```
┌─────────────────────────────────────────────────────────────────┐
│                      Memory レイヤー構造                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Layer 2: グローバルメモリ（~/.multi-agent-mcp/memory/）         │
│  ├── 全プロジェクトで共有                                        │
│  ├── ユーザーの好み・設定                                        │
│  └── クロスプロジェクトの学び                                    │
│                                                                 │
│  Layer 3: プロジェクトメモリ（{project}/.multi-agent-mcp/{session_id}/memory/）│
│  ├── プロジェクト固有の知識                                      │
│  ├── セッション間で共有                                          │
│  └── 決定事項・技術的コンテキスト                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### レイヤーの使い分け

| レイヤー | スコープ | 用途例 |
| -------- | -------- | ------ |
| グローバル | 全プロジェクト | コーディング規約、ユーザーの好み、共通ツールの使い方 |
| プロジェクト | 単一プロジェクト | API設計の決定、アーキテクチャ選択、技術的負債 |

## ファイル構造

```
~/.multi-agent-mcp/
└── memory/                           # グローバルメモリ
    ├── entry-name.md                 # 通常エントリ
    └── archive/                      # アーカイブ
        └── entry-name.md

{project}/.multi-agent-mcp/
└── {session_id}/memory/              # セッション単位のプロジェクトメモリ
    ├── entry-name.md                 # 通常エントリ
    └── archive/                      # アーカイブ
        └── entry-name.md
```

`session_id` が未設定の場合は、`{project}/.multi-agent-mcp/memory/` が使用されます。

### エントリファイルの形式

YAML Front Matter + Markdown 本文:

```markdown
---
key: api-design-decision
tags:
  - architecture
  - api
  - decision
created_at: 2024-01-15T10:30:00
updated_at: 2024-01-15T10:30:00
---

## API設計の決定事項

REST API は以下の方針で設計する:
- リソース指向のエンドポイント設計
- バージョニングは URL パスで（/api/v1/...）
- エラーレスポンスは RFC 7807 形式
```

## ライフサイクル

```
┌─────────┐  save_to_memory   ┌────────────┐
│ エージェント │ ───────────────→│ Memory     │
└─────────┘                   │ (active)   │
                              └─────┬──────┘
                                    │
              ┌─────────────────────┴─────────────────────┐
              │                                           │
              ▼                                           ▼
        自動クリーンアップ                           手動削除（delete_*）
   (TTL 超過 / エントリ数超過)                      -> archive 移動なし
              │
              ▼
       ┌────────────┐
       │ Archive    │
       │ (archive/) │
       └─────┬──────┘
             │
             ▼ restore_from_memory_archive
       ┌────────────┐
       │ Memory     │
       │ (active)   │
       └────────────┘
```

### 自動クリーンアップ

| 条件 | デフォルト値 | 動作 |
| ---- | ------------ | ---- |
| TTL 超過 | 90日 | アクセスがないエントリをアーカイブに移動 |
| エントリ数超過 | 1000件 | 古いエントリをアーカイブに移動 |

**注意**: クリーンアップは**削除ではなくアーカイブ**です。いつでも復元可能です。

## ツール一覧

### プロジェクトメモリ

| ツール | 説明 | 使用者 |
| ------ | ---- | ------ |
| `save_to_memory` | メモリに保存 | Owner, Admin, Worker |
| `retrieve_from_memory` | キーワード検索 | Owner, Admin, Worker |
| `get_memory_entry` | キーで取得 | Owner, Admin, Worker |
| `list_memory_entries` | 一覧取得 | Owner, Admin, Worker |
| `delete_memory_entry` | 削除（アーカイブ移動なし） | Owner, Admin |
| `get_memory_summary` | サマリー取得 | Owner, Admin, Worker |

### プロジェクトメモリ・アーカイブ操作

| ツール | 説明 | 使用者 |
| ------ | ---- | ------ |
| `search_memory_archive` | アーカイブ検索 | Owner, Admin, Worker |
| `list_memory_archive` | アーカイブ一覧 | Owner, Admin, Worker |
| `restore_from_memory_archive` | アーカイブから復元 | Owner, Admin |
| `get_memory_archive_summary` | アーカイブサマリー | Owner, Admin, Worker |

### グローバルメモリ

| ツール | 説明 | 使用者 |
| ------ | ---- | ------ |
| `save_to_global_memory` | グローバルに保存 | Owner, Admin, Worker |
| `retrieve_from_global_memory` | グローバル検索 | Owner, Admin, Worker |
| `list_global_memory_entries` | グローバル一覧 | Owner, Admin, Worker |
| `get_global_memory_summary` | グローバルサマリー | Owner, Admin, Worker |
| `delete_global_memory_entry` | グローバル削除（アーカイブ移動なし） | Owner, Admin |

### グローバルアーカイブ

| ツール | 説明 | 使用者 |
| ------ | ---- | ------ |
| `search_global_memory_archive` | グローバルアーカイブ検索 | Owner, Admin, Worker |
| `list_global_memory_archive` | グローバルアーカイブ一覧 | Owner, Admin, Worker |
| `restore_from_global_memory_archive` | グローバルアーカイブから復元 | Owner, Admin |
| `get_global_memory_archive_summary` | グローバルアーカイブサマリー | Owner, Admin, Worker |

## 重要なポイント

### 保存すべき情報

| 保存する ✅ | 保存しない ❌ |
| ----------- | ------------ |
| ユーザーの好み・設定 | 現在進行中のタスク詳細 |
| 重要な決定事項とその理由 | 一時的なエラーメッセージ |
| クロスプロジェクトで活用できる学び | タスクの進捗状況 |
| 問題解決のパターン | 作業中の中間成果物 |

### タグの活用

タグを使って効率的に検索・整理:

```python
save_to_memory(
    key="api-auth-decision",
    content="認証方式は JWT を採用...",
    tags=["api", "auth", "decision", "jwt"],
    caller_agent_id="admin_xxx"
)

# タグで検索
retrieve_from_memory(query="auth", tags=["decision"])
```

### セッション復帰時のコンテキスト取得

```python
# 1. プロジェクトメモリから関連情報を取得
retrieve_from_memory(query="{session_id}")

# 2. グローバルメモリからユーザー設定を取得
retrieve_from_global_memory(query="preferences")
```

## 環境変数

| 変数 | デフォルト | 説明 |
| ---- | ---------- | ---- |
| `MCP_MEMORY_MAX_ENTRIES` | 1000 | 最大エントリ数（超過分はアーカイブ） |
| `MCP_MEMORY_TTL_DAYS` | 90 | エントリの保持期間（日） |

## トラブルシューティング

### メモリが見つからない

確認事項:
1. 正しいプロジェクトディレクトリで実行しているか
2. キーのスペルが正しいか
3. アーカイブに移動していないか（`search_memory_archive` で確認）

```python
# アーカイブを検索
search_memory_archive(query="探しているキーワード")
```

### アーカイブから復元

```python
# アーカイブ一覧を確認
list_memory_archive()

# 復元
restore_from_memory_archive(key="api-design-decision")
```

### グローバル vs プロジェクトの判断

- **グローバル**: 他のプロジェクトでも使える汎用的な知識
- **プロジェクト**: このプロジェクト固有の決定・コンテキスト

迷ったら**プロジェクトメモリ**に保存（後でグローバルに昇格可能）。
