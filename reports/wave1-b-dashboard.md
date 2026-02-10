# Wave1-B: Dashboard整合 / 状態遷移制約

## 概要

Dashboard 系の整合性を高めるため、以下を実装した。

- `dashboard.md` 読み書きにファイルロック + fail-fast を導入
- `messages.md` の履歴追記を実装（上書きで消えない）
- タスク再割当時に旧担当の `current_task_id` をクリア
- `update_task_status` に状態遷移制約を追加し、終端状態からの再開を `reopen_task` に分離
- `Dashboard` モデルへ `session_started_at` / `session_finished_at` /
  `process_crash_count` / `process_recovery_count` を追加
- Markdown 統計セクションとサマリー API に新フィールドを反映
- healthcheck 復旧監視から crash/recovery カウンタを更新

## 変更ファイル

- `src/managers/dashboard_manager.py`
- `src/managers/dashboard_tasks_mixin.py`
- `src/managers/dashboard_markdown_mixin.py`
- `src/managers/dashboard_sync_mixin.py`
- `src/managers/dashboard_cost.py`
- `src/managers/healthcheck_manager.py`
- `src/models/dashboard.py`
- `tests/test_dashboard_manager.py`
- `tests/test_healthcheck_manager.py`
- `reports/wave1-b-dashboard.md`

## 実装詳細

### 1. lock + fail-fast

- `DashboardManager` に `dashboard.lock` ベースの排他ロックを追加。
- `run_dashboard_transaction()` を追加し、更新系処理をロック下で実行。
- ロック取得が `1.0s` で取れない場合は `TimeoutError` を送出し fail-fast。

### 2. messages.md 履歴保持

- `DashboardTasksMixin.add_message()` をトランザクション化。
- `DashboardMarkdownMixin._append_message_markdown()` を追加し、
  `messages.md` へ単発追記できるようにした。
- これにより `add_message` 連続呼び出し時に過去メッセージが失われない。

### 3. 再割当時の旧担当クリア

- `assign_task()` で `previous_agent_id` を追跡し、
  旧担当の `current_task_id` が対象タスクなら `None` に戻す。

### 4. 状態遷移制約 + reopen_task

- 許可遷移表を `DashboardTasksMixin` に実装。
- 終端状態（`completed/failed/cancelled`）からの `in_progress` などを拒否。
- 終端から再開するための `reopen_task()` を追加。

### 5. セッション時刻 / crash-recovery 表示

- `Dashboard` に以下フィールドを追加。
  - `session_started_at`
  - `session_finished_at`
  - `process_crash_count`
  - `process_recovery_count`
- `update_task_status()` でセッション開始/終了時刻を更新。
- `get_summary()` と Markdown 統計に新項目を表示。
- `HealthcheckManager.monitor_and_recover_workers()` で
  異常検出時に crash を、復旧成功時に recovery を加算。

## 受入条件対応

### #3 messages.md 履歴保持

- 実装: `add_message` から `messages.md` 追記を実装
- テスト:
  - `tests/test_dashboard_manager.py::test_add_message_appends_to_messages_md_without_overwrite`

### #8 dashboard に 開始/終了 + crash/recovery 表示

- 実装: `Dashboard` フィールド追加、`update_task_status` / Markdown / healthcheck 反映
- テスト:
  - `tests/test_dashboard_manager.py::test_save_markdown_dashboard_sets_session_metadata`
  - `tests/test_dashboard_manager.py::test_markdown_stats_includes_session_and_process_counts`
  - `tests/test_healthcheck_manager.py::test_monitor_marks_task_failed_after_recovery_limit`
  - `tests/test_healthcheck_manager.py::test_monitor_recovers_in_progress_no_ipc_timeout`

## テスト結果

- `uv run ruff check src tests`
  - pass
- `uv run pytest tests/test_dashboard_manager.py tests/test_healthcheck_manager.py tests/tools/test_dashboard_tools.py tests/test_merge.py -q`
  - pass (`86 passed`)
- `env -i PATH="$PATH" HOME="$HOME" uv run pytest -q`
  - pass (`648 passed`)

## 備考

- ローカルの `MCP_*` 環境変数に依存する既存テストがあるため、
  全体テストはクリーン環境（`env -i`）で最終確認した。
