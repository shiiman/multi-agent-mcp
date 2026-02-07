# Healthcheck システム

Worker の死活監視と自動復旧を行う仕組みの解説です。

## 概要

Healthcheck は以下を担当します。

- tmux セッション死活監視（`session_exists`）
- タスク停滞検知（`last_activity` + pane 出力ハッシュ）
- 段階復旧（`attempt_recovery` → `full_recovery`）
- 復旧失敗時の failed 化と Admin 通知
- 常駐 daemon による自動監視ループ

## ツール一覧

| ツール | 説明 | 使用者 |
| ------ | ---- | ------ |
| `healthcheck_agent` | 単一エージェントの健全性確認 | Owner, Admin |
| `healthcheck_all` | 全エージェントの健全性確認 | Owner, Admin |
| `get_unhealthy_agents` | 異常エージェント一覧 | Owner, Admin |
| `attempt_recovery` | 軽量復旧（割り込み/セッション再作成） | Owner, Admin |
| `full_recovery` | Worker 完全復旧（再作成 + 再割り当て） | Admin |
| `monitor_and_recover_workers` | Worker 監視と段階復旧を実行 | Owner, Admin |

## 異常判定ロジック

### 1. tmux セッション異常

- `check_agent()` で `session_exists` が `False`
- 復旧理由: `tmux_session_dead`

### 2. タスク停滞

- `current_task` が設定済み
- `last_activity` から `MCP_HEALTHCHECK_STALL_TIMEOUT_SECONDS` を超過
- かつ pane 出力ハッシュが一定時間変化しない
- 復旧理由: `task_stalled`

## 段階復旧

`monitor_and_recover_workers` は段階的に復旧します。
ツール実行・daemon 実行のいずれも `app_ctx` つきで実行されるため、
`full_recovery` と `task failed` 確定処理まで到達します。

1. `attempt_recovery`
2. 失敗時に `full_recovery`（`app_ctx` がある場合）
3. それでも失敗したら失敗回数を加算
4. `MCP_HEALTHCHECK_MAX_RECOVERY_ATTEMPTS` 超過で task を `failed` 化

`task failed` にした場合は以下が実行されます。

- Dashboard の対象タスクを `FAILED` へ更新
- Worker の `current_task` を解除して `IDLE` に戻す
- Admin に IPC `error` メッセージを送信

## `attempt_recovery` と `full_recovery` の違い

### `attempt_recovery`

- 既定: tmux セッション再作成
- 停滞時の force モード: 対象 pane へ `Ctrl-C` と `clear` を送信
- 既存 Worker をなるべく維持する軽量復旧

### `full_recovery`

異常 Worker を作り直す重い復旧です。主な処理:

1. 旧 Worker を除去
2. 旧 worktree を削除し、同ブランチで再作成
3. 新 Worker を生成（同じ pane を再利用）
4. 未完了タスクを新 Worker へ再割り当て

## 常駐 daemon

`healthcheck_daemon` はバックグラウンドで監視ループを回します。

### 起動タイミング

- `create_agent` で Worker 作成時
- `create_workers_batch` 完了時

### 停止タイミング

- `cleanup_workspace`
- `cleanup_on_completion`
- サーバー終了時（`app_lifespan` cleanup）
- 自動停止条件を満たしたとき

### 自動停止条件

以下を連続で検知すると停止します。

- 全 Worker が `IDLE` で `current_task` なし
- かつ Dashboard の `in_progress_tasks == 0`
- 連続回数が `MCP_HEALTHCHECK_IDLE_STOP_CONSECUTIVE` 以上

## 環境変数

| 変数 | デフォルト | 説明 |
| ---- | ---------- | ---- |
| `MCP_HEALTHCHECK_INTERVAL_SECONDS` | 60 | 監視ループ間隔（秒） |
| `MCP_HEALTHCHECK_STALL_TIMEOUT_SECONDS` | 600 | 無応答判定閾値（秒） |
| `MCP_HEALTHCHECK_MAX_RECOVERY_ATTEMPTS` | 3 | 同一 worker/task の復旧上限 |
| `MCP_HEALTHCHECK_IDLE_STOP_CONSECUTIVE` | 3 | 自動停止までの連続 idle 検知回数 |

## 運用例

```python
# 1. 全体ヘルス確認
healthcheck_all(caller_agent_id="owner_xxx")

# 2. 異常 Worker を抽出
get_unhealthy_agents(caller_agent_id="admin_xxx")

# 3. 監視 + 復旧をまとめて実行
monitor_and_recover_workers(caller_agent_id="admin_xxx")
```
