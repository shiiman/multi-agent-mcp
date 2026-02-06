# Merge ガイド

完了タスクの作業ブランチをまとめて統合する `merge_completed_tasks` の運用ガイドです。

## 対象ツール

| ツール | 説明 | 使用者 |
| ------ | ---- | ------ |
| `merge_completed_tasks` | 完了タスクの branch を `base_branch` に統合 | Owner, Admin |

## 前提

- Dashboard 上で `status=completed` のタスクに `branch` が設定されていること
- `repo_path` が有効な Git リポジトリであること
- `base_branch` が存在し checkout 可能であること

## 処理フロー

`merge_completed_tasks` は以下を実行します。

1. `base_branch` を checkout
2. completed タスクから branch を重複除去して収集
3. 既に取り込み済みか判定（`git merge-base --is-ancestor`）
4. 未取り込み branch を戦略に従って統合
5. Dashboard の messages に結果要約を記録

返却値には以下が含まれます。

- `merged`
- `already_merged`
- `failed`
- `conflicts`

`failed` と `conflicts` がゼロのとき `success=true` です。

## 統合戦略

| `strategy` | 実行コマンド | 用途 |
| ---------- | ------------ | ---- |
| `merge` | `git merge --no-ff <branch>` | 履歴を残した通常統合 |
| `squash` | `git merge --squash <branch>` + `git commit` | 1コミットに圧縮 |
| `rebase` | `git rebase <branch>` | 履歴整形（利用時は注意） |

## 衝突時の動作

- エラーメッセージに `conflict` を含む場合は `conflicts` に記録
- `git merge --abort` / `git rebase --abort` を試行
- それ以外の失敗は `failed` に記録
- どちらかが存在すると `success=false`

## 実行例

```python
merge_completed_tasks(
    session_id="issue-123",
    repo_path="/path/to/repo",
    base_branch="main",
    strategy="merge",
    caller_agent_id="admin_xxx",
)
```

## 運用上の注意

- `strategy="rebase"` は履歴を書き換えるため、共有ブランチ運用では慎重に使ってください。
- 実行前に作業ツリーをクリーンにしておくと失敗を減らせます。
- `conflicts` が返った場合は手動解消後、再度実行してください。

