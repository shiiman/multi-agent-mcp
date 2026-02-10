# Wave1-F ドキュメント/テンプレート整合レポート

## 対象タスク
- Task ID: `6ff090f0-2880-48af-b0a6-aefc73c6d330`
- Scope: `templates/tasks/admin_task.md`, `templates/roles/worker.md`, `README.md`

## 実施内容

### 1. `templates/tasks/admin_task.md`
- `create_task` 運用に `metadata` を追加する指針を反映。
  - `task_kind`
  - `requires_playwright`
  - `output_dir`
- タスク分割コード例を更新し、`metadata` を付与する形に統一。
- `create_task` の戻り値参照を互換的に修正。
  - `result.get("task_id") or result.get("task", {}).get("id")`
- 状態遷移制約を追記。
  - 終端状態からの再開は `update_task_status` ではなく `reopen_task` を利用する運用を明記。
- 調査/検証成果物の出力先ルールを追記。
  - 正本は `.multi-agent-mcp/{session_id}/reports/*.md`

### 2. `templates/roles/worker.md`
- Worker の進捗反映フローを実装方針に合わせて修正。
  - Worker は Dashboard を直接更新しない
  - `report_task_progress` により Admin に通知し、Admin 側で Dashboard 反映
- ワークフロー記述の誤りを修正。
  - 「作業開始時に `update_task_status`」→「初回 `report_task_progress`」
  - 「進捗更新に `update_task_status`」→「`report_task_progress`」
- Self-check のツール確認を修正。
  - `update_task_status` を削除し `report_task_progress` を明記
- レポート出力規律を追記。

### 3. `README.md`
- ダッシュボード/タスク管理セクションを拡張。
  - `reopen_task` を追加
  - `create_task` metadata 運用を記載
  - `update_task_status` 遷移制約と `reopen_task` 方針を明記
- 調査レポート出力ルールを追記。
  - `.multi-agent-mcp/{session_id}/reports/*.md`
- `switch_model_profile` 方針を追記。
  - `config.json` ではなく `.env` を正本にする運用
- 公開I/Fとしての主要フィールド記述を追加。
  - Agent: `session_name`, `window_index`, `pane_index`, `ai_cli`, `ai_bootstrapped` など
  - Dashboard/Task: `task_file_path`, `metadata`, 各種時刻、運用フィールド
- ディレクトリ構造に `{session_id}/reports/` を追記。

## 反映した要件との対応
- create_task metadata (`task_kind`/`requires_playwright`/`output_dir`) の運用記載: ✅
- reports 配下 md 出力ルール: ✅
- 公開I/F変更の文書反映
  - `create_task` metadata: ✅
  - `update_task_status` 遷移制約: ✅
  - `reopen_task` 方針: ✅
  - Agent フィールド: ✅
  - Dashboard フィールド: ✅
  - `switch_model_profile` 方針: ✅

## 補足
- 本タスクでは文書・テンプレート整合のみを対象とし、実装コード変更は行っていません。
