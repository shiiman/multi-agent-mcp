# Merge ガイド

完了タスクの作業ブランチを統合ブランチへ「commit なし」で展開する
`merge_completed_tasks` の運用ガイドです。

## 対象ツール

| ツール | 説明 | 使用者 |
| ------ | ---- | ------ |
| `merge_completed_tasks` | 完了タスク branch を commit なしで統合ブランチへ展開 | Owner, Admin |

## 前提

- Dashboard 上で `status=completed` のタスクに `branch` が設定されていること
- `repo_path` が有効な Git リポジトリであること
- `base_branch` が存在すること
- 作業ツリーがクリーンであること（未コミット変更がないこと）

## 処理フロー

`merge_completed_tasks` は以下を実行します。

1. `base_branch` を checkout
2. completed タスクから branch を重複除去して収集
3. `base_branch` / 各 branch の存在確認
4. 既に取り込み済みか判定（`git merge-base --is-ancestor`）
5. 未取り込み branch を `--no-commit` で適用
6. 複数 branch を連続適用するため一時コミットを作成
7. 最後に `git reset --mixed <base_head>` で commit を打ち消し、
   **統合結果を unstaged diff として残す**
8. Dashboard の messages に結果要約を記録

返却値には以下が含まれます。

- `preview_merge`（常に `true`）
- `working_tree_updated`
- `base_head`
- `merged`
- `already_merged`
- `failed`
- `conflicts`
- `strategy_warning`（`strategy=rebase` 指定時のみ）

`failed` と `conflicts` がゼロのとき `success=true` です。

## strategy パラメータ

| `strategy` | 実際の適用 |
| ---------- | ---------- |
| `merge` | `git merge --no-ff --no-commit <branch>` |
| `squash` | `git merge --squash <branch>` |
| `rebase` | no-commit プレビューでは非対応のため `merge` 相当で適用 |

## 失敗/衝突時の扱い

- ブランチが存在しない場合は `failed` に `branch_not_found` を記録
- 競合時は `conflicts` に記録し `merge --abort` を試行
- `failed` がある場合は `success=false`

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

- 実行後、統合ブランチに **unstaged diff** が残ります。
- commit / push は自動実行しません。
- 差分確認後に `git add` / `git commit` を行ってください。
