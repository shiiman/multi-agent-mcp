# Wave3-J 受入条件 #1-#12 検証レポート

## 検証方針
- 受入条件ごとに **実装コード / テスト / 実行結果** を突合して判定。
- 判定は `OK / NG / PARTIAL` の3段階。
- 全体テスト実行結果は `env -i PATH="$PATH" HOME="$HOME" uv run pytest`（643 passed）を参照。

## 判定サマリー
- OK: #1, #3, #6, #7, #9, #10, #12
- PARTIAL: #11
- NG: #2, #4, #5, #8

## 受入条件別の根拠
| # | 判定 | 根拠 |
|---|---|---|
| 1 | OK | `.env` の `MCP_MODEL_PROFILE_STANDARD_CLI=codex` 反映は `tests/tools/test_agent_tools.py:129` と `tests/tools/test_command_tools.py:649` で検証。実装側も `src/tools/agent_lifecycle_tools.py:85` (`refresh_app_settings`) と `src/tools/agent_lifecycle_tools.py:114` (`get_worker_cli`) で env 優先解決。 |
| 2 | NG | 要件「agents.json に ai_cli=claude が残っていても Worker 起動時に env 値へ再解決」に対する直接テストが見当たらない。実装は `src/tools/agent_lifecycle_tools.py:463` と `src/tools/agent_helpers.py:109` で `agent.ai_cli` を優先しており、stale 値温存リスクが残る。 |
| 3 | OK | `messages.md` 履歴保持は `tests/test_dashboard_manager.py:585` で検証。実装は `src/managers/dashboard_sync_mixin.py:97`（全件収集）と `src/managers/dashboard_markdown_mixin.py:294`（messages.md生成）で担保。 |
| 4 | NG | `read_screenshot` は `src/tools/screenshot.py:157` で `screenshot_dir / filename` をそのまま使用し、`resolve()/relative_to()` による path traversal 防止が未実装。拒否テストも現行ツリーで未確認。 |
| 5 | NG | Worker の他agent `read_messages/get_unread_count/get_output` 禁止要件に対し、`src/config/role_permissions.py:71` `src/config/role_permissions.py:74` `src/config/role_permissions.py:75` で Worker 許可のみ定義。`src/tools/helpers.py:230` 以降にも target_agent_id による self-scope 強制がない。 |
| 6 | OK | TERMINATED Worker 除外は `src/managers/healthcheck_daemon.py:28` で実装、`tests/test_healthcheck_daemon.py:139` で検証。 |
| 7 | OK | cleanup 後の worker branch 削除は `src/managers/worktree_manager.py:330`（`git branch -D`）で実装、`tests/test_worktree_manager.py:219` で検証。 |
| 8 | NG | dashboard 表示要件（開始/終了 + crash/recovery 表示）に対し、モデルには時刻保持項目がある (`src/models/dashboard.py:80`) が Markdown 出力側に該当表示ロジックを確認できず（`src/managers/dashboard_markdown_mixin.py`）。専用検証テストも未確認。 |
| 9 | OK | `shutdown_state.json` 非生成は `tests/test_server_lifecycle.py:9` で検証。実装は `src/server.py:24` で no-op。 |
| 10 | OK | `report_task_completion` の保存先 `.multi-agent-mcp/memory` 固定は `tests/tools/test_dashboard_tools.py:660` で検証。実装は `src/tools/helpers_managers.py:153`。 |
| 11 | PARTIAL | 指定パス `.multi-agent-mcp/<session_id>/reports/*.md` には現時点で `wave1-a-security-rbac.md` は存在。今回 `wave3-j-acceptance.md` を同パスにも配置し増強。ただし Wave1-B/C/D/E の成果物が同パスに未集約で完全充足は未達。 |
| 12 | OK | cooldown 既定値 2.0 は `src/config/settings.py:274` で維持。`.env` テンプレート出力も `src/tools/session_env.py:169` で連動。 |

## #4 / #11 最終確定
- #4: **NG（未充足）**
  - 理由: `read_screenshot` で path canonicalization とディレクトリ境界チェックが未実装。
- #11: **PARTIAL（部分充足）**
  - 理由: session reports 配下への成果物配置は存在するが、Wave1 系成果物の未集約が残る。

## 推奨差分タスク（不足分）
1. #4 対応
- `src/tools/screenshot.py` に `resolve()` + `relative_to()` を追加し、`../` を含む入力を拒否。
- `tests/tools/test_screenshot_tools.py` を追加し path traversal 拒否ケースを回帰化。

2. #2 対応
- Worker 起動時に `agent.ai_cli` が stale な場合でも `settings.get_worker_cli(...)` で再解決する処理を追加。
- `agents.json` に `ai_cli=claude` が残るケースの回帰テストを追加。

3. #5 対応
- self-scope 対象ツール（`read_messages/get_unread_count/get_output`）に target agent 強制を追加。
- Worker が他agent指定時に拒否されるテストを追加。

4. #8 対応
- `dashboard_markdown_mixin` に session開始/終了時刻、crash/recoveryカウンタ表示を追加。
- 表示検証テストを追加。

5. #11 完全充足
- Wave1-B/C/D/E の成果物を `.multi-agent-mcp/refactor3-integrated-fixes/reports/` に集約。

## 実行ログ
- `env -i PATH="$PATH" HOME="$HOME" uv run pytest` -> 643 passed
