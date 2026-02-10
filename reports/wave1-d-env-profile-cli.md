# Wave1-D: 設定整合（.env 正準）と Worker CLI 再解決

## 概要

本対応では、モデルプロファイルと Worker CLI/モデル解決を `.env` 正準に寄せ、
Worker 起動時に `agents.json` の stale `ai_cli` が残っていても `.env` を優先して
再解決するように修正した。あわせて `worker_model_mode` の適用不整合を修正し、
`MCP_SEND_COOLDOWN_SECONDS` の既定値 `2.0` を維持する検証を追加した。

## 変更ファイル

- `src/tools/model_profile.py`
- `src/config/settings.py`
- `src/tools/session_env.py`
- `src/tools/agent_helpers.py`
- `src/tools/agent_lifecycle_tools.py`
- `src/tools/command.py`
- `tests/test_settings_env.py`
- `tests/test_session_env.py`
- `tests/test_agent_helpers.py`
- `tests/tools/test_agent_tools.py`
- `tests/tools/test_command_tools.py`
- `tests/tools/test_model_profile_tools.py`

## 実装内容

### 1. `switch_model_profile` を `.env` 永続化へ統一

- `switch_model_profile` で `settings.model_profile_active` をメモリ直接変更する実装を廃止。
- `src/tools/session_env.py` に `set_env_value()` を追加し、
  `MCP_MODEL_PROFILE_ACTIVE` を `.env` へ upsert。
- 更新後に `refresh_app_settings()` を実行し、実行中設定へ反映。
- `config.json` へ profile を保存する処理は追加していない（`.env` のみ）。

### 2. Worker CLI を起動時に再解決（env 優先）

- `src/tools/agent_helpers.py::_resolve_agent_cli_name()` を修正。
- Worker の場合、`agent.ai_cli` より `settings.get_worker_cli(worker_no)` を優先。
- これにより `agents.json` に旧 `ai_cli` が残っていても、起動時は最新 `.env` 設定が適用される。

### 3. `initialize_agent` / `send_task` / `create_agent` で設定再読込

- `create_agent` と `initialize_agent` 前に `refresh_app_settings()` を実行。
- `initialize_agent` の Worker CLI 選択は slot ベース再解決へ変更。
- `send_task` でも dispatch 前に `.env` を再読込して profile 設定を再計算。

### 4. `worker_model_mode` の適用修正

- `src/config/settings.py::get_worker_model()` が誤って `worker_cli_mode` を見ていたため、
  `worker_model_mode` を参照するよう修正。
- `uniform` 時は `worker_model_uniform`（未設定なら profile モデル）を返す。

### 5. `.env` テンプレート整合

- `src/tools/session_env.py` のテンプレートへ以下を追加:
  - `MCP_WORKER_MODEL_MODE`
  - `MCP_WORKER_MODEL_UNIFORM`
- Worker 1..16 の CLI/MODEL 行生成は、固定値ではなく
  `Settings.get_worker_cli()` / `Settings.get_worker_model()` で算出するように変更。

## 受入条件の対応

### #1 `.env` が `MCP_MODEL_PROFILE_STANDARD_CLI=codex` の時 Worker が codex 起動

- テスト:
  - `tests/test_agent_helpers.py::TestSendTaskToWorker::test_worker_bootstrap_resolves_cli_from_env`
  - `tests/tools/test_agent_tools.py::TestInitializeAgent::test_initialize_worker_resolves_cli_from_env`
- 検証内容:
  - `.env` に codex を設定し、Worker 起動コマンド生成時 `cli="codex"` になることを確認。

### #2 `agents.json` に `ai_cli=claude` が残っていても Worker 起動時に env 値へ再解決

- テスト:
  - `tests/test_agent_helpers.py::TestResolveHelpers::test_resolve_worker_cli_name_prefers_env_even_if_agent_cli_stale`
  - `tests/test_agent_helpers.py::TestSendTaskToWorker::test_worker_bootstrap_resolves_cli_from_env`
- 検証内容:
  - `agent.ai_cli=claude`（stale）を与えても `.env` の codex が優先されることを確認。

### #12 cooldown 既定値 2.0 維持

- テスト:
  - `tests/test_settings_env.py::TestGenerateEnvTemplate::test_template_contains_healthcheck_settings`
- 検証内容:
  - 生成テンプレートに `MCP_SEND_COOLDOWN_SECONDS=2.0` が含まれることを確認。

## 追加した回帰テスト

- `tests/tools/test_model_profile_tools.py`
  - `test_switch_model_profile_updates_env_only`
  - `switch_model_profile` が `.env` 更新のみを行い、`config.json` に profile を書かないことを確認。
- `tests/test_session_env.py`
  - `TestSetEnvValue`（既存キー更新 / 新規キー追加）

## 実行結果

- `env -u MCP_PROJECT_ROOT uv run pytest -q`
  - **649 passed**
- `env -u MCP_PROJECT_ROOT uv run ruff check src tests`
  - **All checks passed**

## 備考

- このシェル環境では `MCP_PROJECT_ROOT` が外部プロジェクトを指していたため、
  そのまま `uv run pytest` を実行すると外部 `.env` の影響を受ける。
- 上記を避けるため、検証は `env -u MCP_PROJECT_ROOT` 付きで実行した。
