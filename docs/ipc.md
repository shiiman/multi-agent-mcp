# IPC (Inter-Process Communication) システム

エージェント間のメッセージ通信を実現するシステムの解説です。

## アーキテクチャ概要

```
┌─────────┐  send_message   ┌─────────────────┐  tmux send-keys  ┌─────────┐
│ Worker  │ ───────────────→│ IPC メッセージ    │ ────────────────→│  Admin  │
└─────────┘                 │ (個別ファイル)    │                  └─────────┘
                            └─────────────────┘                       │
                                                                      │ read_messages
                                                                      ↓
                                                              メッセージ取得
```

### ハイブリッド通知方式

1. **個別ファイルベースのメッセージキュー**: メッセージ内容の永続化
2. **tmux イベント通知**: 受信者へのリアルタイム通知

## メッセージフロー

### Worker → Admin（完了報告）

```
1. Worker が report_task_completion() を呼ぶ
   ↓
2. IPC ディレクトリにメッセージファイルを作成
   (ipc/{admin_id}/{timestamp}_{message_id}.md)
   ↓
3. Admin の tmux ペインに通知を送信
   echo '[IPC] 新しいメッセージ: task_complete from worker_xxx'
   ↓
4. Admin は read_messages() でメッセージ内容を取得
   ↓
5. read_messages() 内で Dashboard を自動更新
```

### Worker → Admin（質問/ブロック）

```
1. Worker が send_message() を呼ぶ
   ↓
2. IPC ディレクトリにメッセージファイルを作成
   ↓
3. Admin の tmux ペインに通知を送信
   ↓
4. Admin は read_messages() で内容を確認して対応
```

## ファイル構造

```
.multi-agent-mcp/{session_id}/
├── ipc/
│   ├── {agent_id}/
│   │   ├── 20240101_120000_abc12345.md
│   │   └── 20240101_120100_def67890.md
│   └── ...
└── ...
```

### メッセージファイルの形式（YAML Front Matter + Markdown）

```markdown
---
id: abc12345-1234-5678-90ab-cdef12345678
sender_id: worker_abc
receiver_id: admin_xyz
message_type: task_complete
priority: normal
subject: "タスク完了: task-001"
created_at: 2024-01-01T12:00:00
read_at: null
metadata:
  task_id: task-001
---

機能Aの実装が完了しました。

- 追加したファイル: src/feature_a.py
- テスト: tests/test_feature_a.py
```

## 既読管理

### 既読フラグの仕組み

- `read_at: datetime | null` - 既読日時（null = 未読）
- `read_messages(mark_as_read=true)` で既読としてマーク
- メッセージは削除されず、履歴として保持される

### 未読メッセージの取得

```python
# 未読のみ取得
read_messages(agent_id="xxx", unread_only=True)

# 未読数の確認
get_unread_count(agent_id="xxx")
```

## 通知方式の詳細

### tmux 通知（Admin/Worker 間）

受信者が tmux セッション内で動作している場合:

```python
await tmux.send_keys_to_pane(
    session_name,
    window_index,
    pane_index,
    f"echo '[IPC] 新しいメッセージ: {msg_type} from {sender_id}'"
)
```

### macOS 通知（Admin → Owner）

受信者が tmux 外（Owner など）の場合:

```python
subprocess.run([
    "osascript", "-e",
    f'display notification "{content}" with title "Multi-Agent MCP"'
])
```

## ツール一覧

| ツール | 説明 | 使用者 |
|--------|------|--------|
| `send_message` | メッセージ送信（単一宛先/ブロードキャスト） | Owner, Admin, Worker |
| `read_messages` | メッセージ読み取り（既読管理つき） | Owner, Admin, Worker |
| `get_unread_count` | 未読数取得 | Owner, Admin, Worker |
| `register_agent_to_ipc` | IPC ディレクトリを事前登録 | Owner, Admin |

### 関連ツール（Dashboard 側）

| ツール | 説明 | 使用者 |
|--------|------|--------|
| `report_task_completion` | 完了報告（Admin への IPC 自動送信） | Worker |
| `report_task_progress` | 進捗報告（Admin への IPC 自動送信） | Worker |

## 重要なポイント

### Worker が覚えておくこと

1. **完了報告**: `report_task_completion` を使う
   - IPC 通知が**自動で行われる**
   - Dashboard 更新は Admin の `read_messages()` 時に自動反映される
   - 別途 `send_message` は**不要**

2. **質問/ブロック**: `send_message` を使う
   - Admin への質問は手動で IPC を送る必要がある

### Admin が覚えておくこと

1. **Worker 完了待ち**: tmux 通知が来たら `read_messages` で内容を確認（イベント駆動、ポーリング不要）

## マルチプロセス対応

各エージェントは独立した MCP サーバープロセスで動作するため:

- **個別ファイル形式**: 各メッセージが独立したファイル、競合なし
- **ディレクトリベース**: エージェントごとにディレクトリを分離
- **既読フラグ**: ファイル内の `read_at` で管理

## トラブルシューティング

### メッセージが届かない

確認事項:
1. IPC ディレクトリにファイルが作成されているか
2. 受信者の tmux ペイン情報が正しく登録されているか
3. `agents.json` に `session_name`, `window_index`, `pane_index` があるか

確認方法:
```bash
ls .multi-agent-mcp/{session_id}/ipc/{agent_id}/
```

### 通知が届かない

確認事項:
1. 受信者の tmux ペイン情報が正しく登録されているか
2. tmux セッションが存在するか
