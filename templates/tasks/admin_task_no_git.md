# Admin タスク（No Git モード）: {session_id}

このセッションは **No Git モード** です。git/worktree 前提の操作は行わないでください。

## 重要パラメータ

- **Admin ID**: {agent_id}
- **プロジェクト**: {project_name}
- **作業ディレクトリ**: {working_dir}
- **セッションID**: {session_id}
- **Worker 数**: {worker_count}
- **開始時刻**: {timestamp}

## 計画書

{plan_content}

## 実行ルール

1. まず `create_task` でサブタスクを登録する（必須）
2. `create_workers_batch` へ渡す各 worker_config に `task_id` を含める
3. 同一ファイルを編集するタスクは同時並列にしない
4. Worker の完了通知を受けて再割り当てする
5. 全タスク完了後に Owner へ報告する

## 主要ツール

- `{mcp_tool_prefix}create_task`
- `{mcp_tool_prefix}create_workers_batch`
- `{mcp_tool_prefix}send_task`
- `{mcp_tool_prefix}read_messages`
- `{mcp_tool_prefix}report_task_completion`

## 関連メモ

{memory_context}

## 品質ゲート

- 最大反復回数: {max_iterations}
- 同一問題の許容回数: {same_issue_limit}

## 禁止

- `create_worktree`, `merge_completed_tasks`, `gtrconfig` 系の呼び出し
- `create_task` を省略した Worker 起動
