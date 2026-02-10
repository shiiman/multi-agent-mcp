# Wave1-C Recovery/tmux/worktree 修正レポート

## 変更概要

### 1) `TERMINATED` Worker を復旧対象から除外
- `src/managers/healthcheck_manager.py`
  - `monitor_and_recover_workers()` で Worker ループ開始時に `AgentStatus.TERMINATED` を明示的にスキップ。
  - TERMINATED Worker の stale recovery key も同時にクリーンアップし、不要なエスカレーションを防止。

### 2) no-git モードの復旧経路を補強
- `src/tools/healthcheck.py`
  - `execute_full_recovery()` で `enable_git` を判定し、`enable_git=false` のときは worktree 再作成処理をスキップ。
  - 復旧後 Agent に `working_dir` を維持して再設定。
  - `new_worktree_path` は `worktree_path` が無い場合でも `working_dir` にフォールバックして返却。

### 3) attach-session 復旧時のディレクトリ遷移を安定化
- `src/tools/healthcheck.py`
  - tmux pane への `cd` 先を `new_worktree_path` 固定から、`new_worktree_path or old_working_dir` に変更。
  - no-git/branch 未確定でも復旧直後に有効な作業ディレクトリへ移動可能にした。

### 4) cleanup 後の worker branch 削除を強化
- `src/managers/worktree_manager.py`
  - `_remove_worktree_native()` で worktree パス比較を `realpath` ベースに変更。
  - list 上の path 表記差異（`..` を含む等）でも branch を正しく解決。
  - list から branch が取れない場合、対象 path の現在ブランチを補助的に取得するフォールバックを追加。

### 5) 復旧成功時のカウンタ更新を追加
- `src/managers/healthcheck_manager.py`
  - `_increment_recovery_counter()` を追加。
  - 段階復旧（`attempt_recovery` / `full_recovery`）成功時に task metadata の
    `process_recovery_count` をインクリメントし、`last_recovery_reason` / `last_recovery_at` を保存。
  - Dashboard 拡張モデルが有効な環境では、`agent_summary.process_recovery_count` も更新。

## テスト更新

### 受入条件 #6（TERMINATED 除外）
- `tests/test_healthcheck_manager.py`
  - `test_monitor_skips_terminated_workers` を追加。
  - TERMINATED Worker が `monitor_and_recover_workers()` で `recovered/escalated` 対象にならず、`skipped` に入ることを検証。

### 受入条件 #7（cleanup 後 branch 不残存）
- `tests/test_worktree_manager.py`
  - `test_remove_worktree_native_resolves_branch_with_normalized_path` を追加。
  - path 正規化後一致ケースでも worker branch の `git branch -D` が実行されることを検証。

### no-git 復旧経路
- `tests/tools/test_healthcheck_tools.py`
  - `test_execute_full_recovery_no_git_preserves_working_dir` を追加。
  - `enable_git=false` で worktree 再作成を行わず、`working_dir` 維持で復旧できることを検証。

### 復旧カウンタ更新
- `tests/test_healthcheck_manager.py`
  - `test_monitor_recovers_in_progress_no_ipc_timeout` を拡張し、復旧後に
    `task.metadata["process_recovery_count"] == 1` を検証。

## 実行結果

### 変更関連テスト
- コマンド:
  - `uv run pytest tests/test_healthcheck_manager.py tests/tools/test_healthcheck_tools.py tests/test_worktree_manager.py tests/test_tmux_manager_terminal_open.py -q`
- 結果: **43 passed**

### Lint
- コマンド:
  - `uv run ruff check src/managers/healthcheck_manager.py src/tools/healthcheck.py src/managers/worktree_manager.py tests/test_healthcheck_manager.py tests/tools/test_healthcheck_tools.py tests/test_worktree_manager.py`
- 結果: **All checks passed**

## 変更ファイル
- `src/managers/healthcheck_manager.py`
- `src/tools/healthcheck.py`
- `src/managers/worktree_manager.py`
- `tests/test_healthcheck_manager.py`
- `tests/tools/test_healthcheck_tools.py`
- `tests/test_worktree_manager.py`
- `reports/wave1-c-recovery-tmux-worktree.md`
