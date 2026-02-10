# Wave1-E: Memory / Shutdown / Session 残骸修正

## 概要
セッション残骸と保存先の不整合を解消するため、以下を実施した。

- `shutdown_state.json` の新規生成を停止（互換 no-op 化）
- `report_task_completion` が利用するメモリ保存先を
  `project/.multi-agent-mcp/memory` に固定
- `provisional-*` ディレクトリの残骸掃除を強化（対象未指定時は一括削除）

## 変更ファイル
- `src/server.py`
- `src/tools/helpers_managers.py`
- `src/tools/session_state.py`
- `src/tools/session_tools.py`
- `tests/test_server_lifecycle.py`
- `tests/test_session_state.py`
- `tests/test_session_tools.py`
- `tests/tools/test_session_tools.py`
- `tests/tools/test_dashboard_tools.py`
- `reports/wave1-e-memory-shutdown-session.md`

## 実装詳細
### 1. shutdown_state 廃止整合
- `src/server.py` の `_save_shutdown_state` を no-op とし、常に `False` を返す実装に変更。
- 既存のライフサイクル呼び出しは維持しつつ、`shutdown_state.json` を新規作成しない。

### 2. report_task_completion 保存先固定
- `src/tools/helpers_managers.py` の `ensure_memory_manager` を変更し、
  常に `{project_root}/{mcp_dir}/memory` を使用。
- 既存 `MemoryManager` がセッション配下を向いている場合も、
  固定保存先へ差し替える。

### 3. provisional 残骸掃除強化
- `src/tools/session_state.py` の `cleanup_orphan_provisional_sessions` を拡張。
  - `target_session_ids=None` 時に `provisional-*` を全走査して削除可能。
  - `preserve_session_ids` を追加し、必要時は除外指定可能。
- `cleanup_session_resources` では一括掃除モードを使用。
- `src/tools/session_tools.py` の `init_tmux_workspace` でも一括掃除を適用。

## テスト
### 追加・更新した主なテスト
- `tests/test_server_lifecycle.py`
  - `shutdown_state.json` が新規生成されないことを検証
- `tests/tools/test_dashboard_tools.py`
  - `report_task_completion` の保存先が
    `.multi-agent-mcp/memory` であることを検証
- `tests/test_session_state.py`
  - cleanup 時に `provisional-*` 残骸が一括削除されることを検証
- `tests/tools/test_session_tools.py`
  - `init_tmux_workspace` で orphan provisional が削除されることを検証
- `tests/test_session_tools.py`
  - `target_session_ids=None` 時の一括削除動作を検証

### 実行結果
- `uv run ruff check src/server.py src/tools/helpers_managers.py src/tools/session_state.py src/tools/session_tools.py tests/test_server_lifecycle.py tests/test_session_state.py tests/test_session_tools.py tests/tools/test_session_tools.py tests/tools/test_dashboard_tools.py`
  - 成功
- `uv run pytest tests/test_server_lifecycle.py tests/test_session_state.py tests/test_session_tools.py tests/tools/test_session_tools.py tests/tools/test_dashboard_tools.py`
  - 成功
- `env -i PATH="$PATH" HOME="$HOME" uv run pytest`
  - **643 passed**

## 受入条件対応
- #9 `shutdown_state.json` が新規生成されない
  - 実装: `_save_shutdown_state` no-op 化
  - 検証: `tests/test_server_lifecycle.py`
- #10 `report_task_completion` 結果が `.multi-agent-mcp/memory` 保存
  - 実装: `ensure_memory_manager` の保存先固定化
  - 検証: `tests/tools/test_dashboard_tools.py`

## 備考
- ローカル環境の `MCP_*` 変数が残っていると、設定デフォルト系テストに影響するため、
  全体テストはクリーン環境（`env -i`）で実行して確認した。
