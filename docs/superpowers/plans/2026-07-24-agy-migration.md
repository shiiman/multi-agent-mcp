# Gemini CLI → Antigravity CLI (agy) 移行 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** multi-agent-mcp の AI CLI 選択肢を `gemini` から後継の `agy`（Antigravity CLI 端末版）へクリーン置換する。

**Architecture:** `AICli.GEMINI` を `AICli.AGY` にリネームし、tmux ワーカー起動コマンドを agy の実フラグ（`--model` / `--dangerously-skip-permissions` / `--effort` / `--prompt-interactive`）で組み立てる。モデル ID 依存部分（デフォルト値・コスト表）はフェーズ1でプレースホルダを置き、agy ログイン後にフェーズ2で実 ID に確定する。

**Tech Stack:** Python 3.10+, Pydantic v2, pytest / pytest-asyncio, ruff。

## Global Constraints

- 行長は表示幅で最大 100 文字（ruff E501, CJK=2幅）。
- 型ヒント必須、union は `X | None` 記法。docstring は日本語 Google スタイル。
- **コミットは Global CLAUDE.md 準拠でユーザーの明示的な承認がある場合のみ実行**。各タスクの「Commit」ステップはコマンドを提示し、承認後に実行する（`--no-verify` 禁止、Conventional Commits・日本語説明）。
- 変更後は必ず `uv run pytest` 緑、`uv tool run ruff check src/` を通す。失敗テストを残さない。
- enum はクリーン置換（後方互換エイリアスなし）。旧 `"gemini"` 永続値は `AICli("gemini")` で `ValueError`。
- agy コマンドは PATH 優先前提で文字列 `"agy"` を使用（デスクトップアプリ版と衝突する点は README に明記）。
- モデル ID はフェーズ2（ログイン後）まで暫定プレースホルダ（現行 Gemini 3 系の名前を流用）を用いる。

---

## ファイル構成

| ファイル | 責務 | 変更種別 |
|---|---|---|
| `src/config/settings.py` | AICli enum / デフォルトコマンド / モデル定数 / 設定フィールド / コスト表 / モデル互換判定 | Modify |
| `src/managers/ai_cli_manager.py` | 起動コマンド組み立て（agy フラグ・effort マッピング） | Modify |
| `src/managers/dashboard_cost.py` | CLI 別コスト集計キー | Modify |
| `src/managers/dashboard_markdown_mixin.py` | コスト prefix 判定 | Modify |
| `src/managers/healthcheck_manager.py` | AI 実行中プロセス prefix | Modify |
| `src/models/dashboard.py` | ai_cli フィールド説明 | Modify |
| `src/tools/session_env.py` | .env テンプレート | Modify |
| `src/config/workflow_guides.py`, `src/tools/agent_helpers.py` | コメント文言 | Modify |
| `src/managers/gtrconfig_manager.py` | 指示ファイル一覧 | Modify |
| `templates/roles/admin.md`, `admin_no_git.md` | CLI 一覧表 | Modify |
| `README.md`, `CLAUDE.md` | ドキュメント | Modify |
| 各 `tests/test_*.py` | gemini→agy テスト更新 + agy 固有テスト追加 | Modify |

---

## Task 1: AICli enum とコマンド組み立ての中核移行

`AICli.GEMINI`→`AICli.AGY` のリネームは import 時に波及するため、enum・デフォルトコマンド・互換判定・起動コマンド組み立て・直接参照テストを 1 タスクで完結させる。

**Files:**
- Modify: `src/config/settings.py`（L52 enum, L179-180 互換判定, L213 デフォルトコマンド）
- Modify: `src/managers/ai_cli_manager.py`（L3 docstring, L242-258 build_stdin_command, L336-339 _build_cli_args）
- Test: `tests/test_ai_cli_manager.py`, `tests/test_initialize_agent.py`, `tests/test_worker_resolution.py`

**Interfaces:**
- Produces: `AICli.AGY`（value `"agy"`）。`build_stdin_command` / `_build_cli_args` が agy 分岐を返す。
- Consumes: なし（起点タスク）。

- [ ] **Step 1: 失敗するテストを書く（agy コマンド組み立て）**

`tests/test_ai_cli_manager.py` の gemini テストを agy に置換し、agy 固有アサーションを追加する。

```python
def test_build_stdin_command_agy(self, ai_cli_manager):
    """agy のコマンドが正しく構築されることをテスト。"""
    cmd = ai_cli_manager.build_stdin_command(
        AICli.AGY, "/tmp/task.md", "/path/to/worktree"
    )
    assert "agy" in cmd
    assert "--dangerously-skip-permissions" in cmd
    assert "--prompt-interactive" in cmd
    assert "--yolo" not in cmd

def test_build_stdin_command_agy_effort_mapping(self, ai_cli_manager):
    """agy の effort が low/medium/high 透過・xhigh→high・none→省略になること。"""
    high = ai_cli_manager.build_stdin_command(
        AICli.AGY, "/tmp/task.md", reasoning_effort="high"
    )
    assert "--effort high" in high

    xhigh = ai_cli_manager.build_stdin_command(
        AICli.AGY, "/tmp/task.md", reasoning_effort="xhigh"
    )
    assert "--effort high" in xhigh  # xhigh は high に丸める

    none = ai_cli_manager.build_stdin_command(
        AICli.AGY, "/tmp/task.md", reasoning_effort="none"
    )
    assert "--effort" not in none
```

`tests/test_ai_cli_manager.py` L32-33（get_command）, L114-119, L183-186, L227- の `AICli.GEMINI`/`"gemini"` を `AICli.AGY`/`"agy"` に更新。L54 の件数アサーション（`== 4`）は据え置き（CLI 総数は不変）。

`tests/test_initialize_agent.py` L243-279 を agy に更新:

```python
def test_agy_with_prompt(self, ai_cli_manager):
    """agy CLI でプロンプトが --prompt-interactive で渡されることをテスト。"""
    args = ai_cli_manager._build_cli_args(AICli.AGY, "/tmp/test", "テストプロンプト")
    assert "agy" in args
    assert "--prompt-interactive" in args
    assert "テストプロンプト" in args

def test_agy_without_prompt_has_skip_permissions(self, ai_cli_manager):
    """agy CLI でプロンプトなしでも --dangerously-skip-permissions が含まれること。"""
    args = ai_cli_manager._build_cli_args(AICli.AGY, "/tmp/test", None)
    assert "--dangerously-skip-permissions" in args
```

`tests/test_worker_resolution.py` L118-122 を更新: `agent.ai_cli = AICli.AGY` / `assert resolve_agent_cli_name(agent, app_ctx) == "agy"`。

`tests/test_settings_env.py` L263-265 を更新（enum リネームで `AICli.GEMINI` 参照が壊れるため本タスクで実施。フィールド改名とは独立）:
```python
        settings.worker_cli_2 = "agy"
        assert settings.get_worker_cli(2) == AICli.AGY
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_ai_cli_manager.py tests/test_initialize_agent.py tests/test_worker_resolution.py -v`
Expected: FAIL（`AICli.AGY` 未定義 / gemini フラグのまま）

- [ ] **Step 3: enum とデフォルトコマンドを更新**

`src/config/settings.py` L52-53:
```python
    AGY = "agy"
    """Antigravity CLI（Gemini CLI 後継）"""
```
L213:
```python
    AICli.AGY: "agy",
```
L179-180（`resolve_model_for_cli` 内 `_is_model_compatible`）: `"gemini"` 分岐を撤廃し agy は無検証にする。
```python
        if target_cli == "agy":
            # agy は Gemini/Claude/GPT-OSS など混在モデルを扱うため prefix 検証しない
            return True
```

- [ ] **Step 4: 起動コマンド組み立てを更新**

`src/managers/ai_cli_manager.py` L3 docstring の "Gemini" を "Antigravity(agy)" に更新。

L242-258 の GEMINI 分岐を置換:
```python
        elif cli == AICli.AGY:
            # export MCP_PROJECT_ROOT=... && cd <path> &&
            # agy --model <model> --dangerously-skip-permissions
            #     [--effort <e>] --prompt-interactive "<instruction>"
            parts = [cmd]
            if resolved_model:
                parts.extend(["--model", resolved_model])
            parts.append("--dangerously-skip-permissions")
            mapped = self._map_agy_effort(effort)
            if mapped:
                parts.extend(["--effort", mapped])
            # --prompt-interactive で初期プロンプト実行後にセッションを継続（tmux 向き）
            parts.extend(["--prompt-interactive", quoted_prompt])
            command = " ".join(parts)
            if working_dir:
                return f"{env_prefix}cd {shlex.quote(working_dir)} && {command}"
            return f"{env_prefix}{command}"
```

L336-339 の GEMINI 分岐を置換（`_build_cli_args`）:
```python
        elif cli == AICli.AGY:
            args.append("--dangerously-skip-permissions")
            if prompt:
                args.extend(["--prompt-interactive", prompt])
```

effort マッピングのヘルパを `AiCliManager` に追加（クラス内、`build_stdin_command` の前あたり）:
```python
    @staticmethod
    def _map_agy_effort(effort: str) -> str | None:
        """本プロジェクトの effort を agy の --effort 値へマッピングする。

        agy は low/medium/high のみ対応。xhigh は high に丸め、none は省略。
        """
        if effort in {"low", "medium", "high"}:
            return effort
        if effort == "xhigh":
            return "high"
        return None  # none → --effort 省略
```

- [ ] **Step 5: テストを実行して成功を確認**

Run: `uv run pytest tests/test_ai_cli_manager.py tests/test_initialize_agent.py tests/test_worker_resolution.py -v`
Expected: PASS

- [ ] **Step 6: 全体テストと lint**

Run: `uv run pytest && uv tool run ruff check src/`
Expected: 緑（string "gemini" のコスト集計・設定フィールド・.env テンプレートは未変更のまま該当テストも "gemini" 期待で緑。本タスクで壊れる `AICli.GEMINI` 参照テストは全て本タスクで更新済み）

- [ ] **Step 7: Commit（承認後）**

```bash
git add src/config/settings.py src/managers/ai_cli_manager.py tests/test_ai_cli_manager.py tests/test_initialize_agent.py tests/test_worker_resolution.py
git commit -m "refactor(cli): AICli.GEMINI を AICli.AGY へ置換しコマンド組み立てを agy 対応"
```

---

## Task 2: モデル定数・設定フィールド・.env テンプレートの移行

**Files:**
- Modify: `src/config/settings.py`（L127-140 ModelDefaults, L138 CLI_DEFAULTS, L407-417 フィールド, L632-635 get_cli_default_models）
- Modify: `src/tools/session_env.py`（L193-195）
- Test: `tests/test_settings_env.py`（L126-134, L263-265）

**Interfaces:**
- Consumes: `AICli.AGY`（Task 1）。
- Produces: `Settings.cli_default_agy_admin_model` / `cli_default_agy_worker_model`、`ModelDefaults.AGY_DEFAULT` / `AGY_LIGHT`、`get_cli_default_models()["agy"]`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_settings_env.py` L126-134 を更新:
```python
        assert "MCP_CLI_DEFAULT_AGY_ADMIN_MODEL" in template
        assert "MCP_CLI_DEFAULT_AGY_WORKER_MODEL" in template
        # ...
        assert ModelDefaults.AGY_DEFAULT in template
        assert ModelDefaults.AGY_LIGHT in template
```
（worker_cli の `AICli.AGY` テストは Task 1 で更新済み。本タスクは env テンプレート/モデル定数のみ）

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_settings_env.py -v`
Expected: FAIL（`AGY_DEFAULT` 未定義 / env テンプレートが GEMINI のまま）

- [ ] **Step 3: ModelDefaults と CLI_DEFAULTS を更新**

`src/config/settings.py` L127-132（プレースホルダ: 現行 Gemini 3 系名を流用、フェーズ2で確定）:
```python
    # Antigravity CLI (agy) — フェーズ2で agy models の実IDに確定
    AGY_DEFAULT = "gemini-3-pro-preview"
    """agy デフォルトモデル（暫定プレースホルダ）"""

    AGY_LIGHT = "gemini-3-flash-preview"
    """agy 軽量モデル（暫定プレースホルダ）"""
```
L138:
```python
        "agy": {"admin": AGY_DEFAULT, "worker": AGY_LIGHT},
```
L158 docstring の CLI 名列挙を `"claude", "codex", "agy", "cursor"` に更新。

- [ ] **Step 4: 設定フィールドと get_cli_default_models を更新**

`src/config/settings.py` L407-417:
```python
    cli_default_agy_admin_model: str = Field(
        default=ModelDefaults.AGY_DEFAULT,
        description="Antigravity CLI (agy) の Admin デフォルトモデル",
    )
    """agy で Admin に使用するデフォルトモデル"""

    cli_default_agy_worker_model: str = Field(
        default=ModelDefaults.AGY_LIGHT,
        description="Antigravity CLI (agy) の Worker デフォルトモデル",
    )
    """agy で Worker に使用するデフォルトモデル"""
```
L632-635:
```python
            "agy": {
                "admin": self.cli_default_agy_admin_model,
                "worker": self.cli_default_agy_worker_model,
            },
```

- [ ] **Step 5: .env テンプレートを更新**

`src/tools/session_env.py` L193-195:
```python
# Antigravity CLI (agy)
MCP_CLI_DEFAULT_AGY_ADMIN_MODEL={v(s.cli_default_agy_admin_model)}
MCP_CLI_DEFAULT_AGY_WORKER_MODEL={v(s.cli_default_agy_worker_model)}
```

- [ ] **Step 6: テストを実行して成功を確認**

Run: `uv run pytest tests/test_settings_env.py -v`
Expected: PASS（コスト表キーのテスト L154-157 は Task 3 で更新するため、必要なら該当テストを Task 3 まで xfail 回避のため本 Step では対象外指定 `-k "not cost_table"` で確認）

- [ ] **Step 7: Commit（承認後）**

```bash
git add src/config/settings.py src/tools/session_env.py tests/test_settings_env.py
git commit -m "refactor(cli): Gemini デフォルトモデル/設定フィールドを agy に移行（モデルIDは暫定）"
```

---

## Task 3: コスト集計・コスト表の移行

**Files:**
- Modify: `src/managers/dashboard_cost.py`（L21, L186, L212）
- Modify: `src/managers/dashboard_markdown_mixin.py`（L131）
- Modify: `src/models/dashboard.py`（L103）
- Modify: `src/config/settings.py`（L526-528 コスト表）
- Test: `tests/test_dashboard_manager.py`（L1438-1445）, `tests/test_settings_env.py`（L154-157）

**Interfaces:**
- Consumes: `AICli.AGY`（Task 1）。
- Produces: コスト集計辞書のキー `agy` / `agy_calls`、コスト表キー `agy:*`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_dashboard_manager.py` L1438-1445:
```python
        dashboard_manager.record_api_call(ai_cli="agy", estimated_tokens=200)
        # ...
        assert estimate["agy_calls"] == 1
```
`tests/test_settings_env.py` L154-157:
```python
        assert "agy:gemini-3-pro-preview" in template
        assert "agy:gemini-3-flash-preview" in template
        assert "agy:gemini-3-pro" in template
        assert "agy:gemini-3-flash" in template
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_dashboard_manager.py -k api_call tests/test_settings_env.py -k cost_table -v`
Expected: FAIL

- [ ] **Step 3: コスト集計キーを更新**

`src/managers/dashboard_cost.py`:
- L21: `_SUPPORTED_COST_CLI_KEYS = ("claude", "codex", "agy", "cursor")`
- L37 docstring: `claude/codex/agy/cursor`
- L186: `"agy_calls": cli_counts.get("agy", 0),`
- L212: `"agy": cli_counts.get("agy", 0),`

`src/managers/dashboard_markdown_mixin.py` L131:
```python
        if cli_prefix not in ("claude", "codex", "agy", "cursor"):
```

`src/models/dashboard.py` L103:
```python
    ai_cli: str = Field(..., description="使用したAI CLI（claude/codex/agy/cursor）")
```

- [ ] **Step 4: コスト表を更新**

`src/config/settings.py` L526-528（`gemini:` を `agy:` に。プレースホルダのモデル名は流用、フェーズ2で確定）:
```python
        '"agy:gemini-3-pro-preview":0.012,'
        '"agy:gemini-3-flash-preview":0.003,'
        '"agy:gemini-3-pro":0.005,"agy:gemini-3-flash":0.0025,'
```

- [ ] **Step 5: テストを実行して成功を確認**

Run: `uv run pytest tests/test_dashboard_manager.py tests/test_settings_env.py -v`
Expected: PASS

- [ ] **Step 6: Commit（承認後）**

```bash
git add src/managers/dashboard_cost.py src/managers/dashboard_markdown_mixin.py src/models/dashboard.py src/config/settings.py tests/test_dashboard_manager.py tests/test_settings_env.py
git commit -m "refactor(cost): コスト集計/コスト表のキーを gemini から agy に移行"
```

---

## Task 4: プロセス検出・テンプレート・ドキュメントの移行

**Files:**
- Modify: `src/managers/healthcheck_manager.py`（L35）
- Modify: `src/config/workflow_guides.py`（L99）, `src/tools/agent_helpers.py`（L558）
- Modify: `src/managers/gtrconfig_manager.py`（L184）
- Modify: `templates/roles/admin.md`（L372）, `templates/roles/admin_no_git.md`（L371）
- Modify: `README.md`, `CLAUDE.md`
- Test: `tests/test_healthcheck_manager.py`（L1021-1025）

**Interfaces:**
- Consumes: なし（文字列・ドキュメント更新）。
- Produces: healthcheck が `agy` プロセスを AI 実行中と判定。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_healthcheck_manager.py` L1021-1025:
```python
    def test_agy_is_detected(self):
        """agy コマンドが AI 実行中と判定されること。"""
        from src.managers.healthcheck_manager import _is_ai_running
        assert _is_ai_running("agy") is True
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_healthcheck_manager.py -k agy -v`
Expected: FAIL（`agy` が prefix に無い）

- [ ] **Step 3: プロセス prefix を更新**

`src/managers/healthcheck_manager.py` L35:
```python
_AI_RUNNING_COMMAND_PREFIXES = ("codex", "claude", "agy", "agent", "cursor-agent")
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/test_healthcheck_manager.py -k agy -v`
Expected: PASS

- [ ] **Step 5: コメント・テンプレート・指示ファイルを更新**

- `src/config/workflow_guides.py` L99: 「Gemini CLI では〜」→「agy では read_file の参照先がワークスペース外だと失敗し得るため、」（`--add-dir` 前提の同種制限として文言更新）。
- `src/tools/agent_helpers.py` L558: コメント「Gemini CLI等の〜」→「agy 等のワークスペース外参照制限を回避」。
- `src/managers/gtrconfig_manager.py` L184: `["CLAUDE.md", "AGENTS.md", "GEMINI.md", ".cursorrules"]` → `["CLAUDE.md", "AGENTS.md", ".cursorrules"]`（agy は `AGENTS.md` を参照。`GEMINI.md` を削除）。
- `templates/roles/admin.md` L372 / `admin_no_git.md` L371: `| Google Gemini | \`gemini\` | \`ai_cli="gemini"\` で指定 |` → `| Antigravity (agy) | \`agy\` | \`ai_cli="agy"\` で指定 |`。

- [ ] **Step 6: ドキュメントを更新**

- `README.md` / `CLAUDE.md` の Gemini 記述・環境変数表（`MCP_CLI_DEFAULT_GEMINI_*` → `MCP_CLI_DEFAULT_AGY_*`、AI CLI 一覧、コスト表デフォルト）を agy に更新。
- README に **端末 CLI 版 agy のインストール手順**（`curl -fsSL https://antigravity.google/cli/install.sh | bash`）と、**デスクトップアプリとの PATH 衝突**（`~/.local/bin` を PATH 優先、または端末 CLI を先勝ちさせる）と**サインイン**（`agy` 引数なし起動）を明記。

- [ ] **Step 7: 全体テストと lint**

Run: `uv run pytest && uv tool run ruff check src/`
Expected: 緑

- [ ] **Step 8: Commit（承認後）**

```bash
git add src/managers/healthcheck_manager.py src/config/workflow_guides.py src/tools/agent_helpers.py src/managers/gtrconfig_manager.py templates/roles/admin.md templates/roles/admin_no_git.md README.md CLAUDE.md tests/test_healthcheck_manager.py
git commit -m "docs(cli): healthcheck/テンプレート/ドキュメントを agy に移行"
```

---

## Task 5 (フェーズ2・agy サインイン後): 実モデル ID 確定・effort フラグ撤去

> 前提: 端末 CLI 版 agy にサインイン済み。`agy models` は成功する。
> **フェーズ2の検証で判明した事実（設計変更の根拠）:**
> 1. **agy のモデル ID は推論 tier を内包**（例 `gemini-3.1-pro-high`, `gemini-3.6-flash-medium`）。`gemini-3.1-pro` は high/low のみで medium が無いなど、tier は独立フラグではなくモデルの離散バリアント。→ **agy では `--effort` を使わず、tier を含む完全 ID をモデル名にする**（Task 1 で入れた `--effort`/`_map_agy_effort` は撤去）。reasoning_effort は Claude/Cursor 同様 agy では未対応扱い（debug ログ）。
> 2. **実起動は eligibility 制限で不可**（`agy --print` が `Eligibility check failed: ... not eligible for Antigravity`）。→ `--prompt-interactive`/IPC の実起動検証は**このアカウントでは実施できない**。README に手順として残し、eligibility 解決後に手動確認する。

`agy models` の実 ID: `gemini-3.6-flash-{high,medium,low}`, `gemini-3.5-flash-{high,medium,low}`, `gemini-3.1-pro-{high,low}`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gpt-oss-120b-medium`。

**Files:**
- Modify: `src/managers/ai_cli_manager.py`（agy 分岐から `--effort` 追加を撤去、`_map_agy_effort` 削除、reasoning_effort は debug ログで無視）
- Modify: `src/config/settings.py`（`ModelDefaults.AGY_DEFAULT`/`AGY_LIGHT` を実 ID に、`model_cost_table_json` の `agy:gemini-3-*` を実 ID に）
- Modify: `tests/test_ai_cli_manager.py`（agy effort テストを「`--effort` を付けない」検証に置換）
- Modify: `tests/test_settings_env.py`（コスト表モデル名アサーションを実 ID に）
- Modify: `README.md`（実起動検証の手順 + eligibility 前提を明記）

**Interfaces:**
- Consumes: `agy models` の実 ID（上記）。
- Produces: 実 ID に確定した agy デフォルトモデル・コスト表。agy 起動コマンドから `--effort` が消える。

- [ ] **Step 1: agy 分岐の失敗テストを書く（--effort 撤去）**

`tests/test_ai_cli_manager.py` の `test_build_stdin_command_agy_effort_mapping` を置換:
```python
def test_build_stdin_command_agy_no_effort_flag(self, ai_cli_manager):
    """agy は tier 内包モデルIDを使うため --effort を付けないことをテスト。"""
    for effort in ("low", "medium", "high", "xhigh", "none"):
        cmd = ai_cli_manager.build_stdin_command(
            AICli.AGY, "/tmp/task.md", reasoning_effort=effort
        )
        assert "--effort" not in cmd
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_ai_cli_manager.py -k agy -v`
Expected: FAIL（現状 `--effort` が付く）

- [ ] **Step 3: agy 分岐から --effort を撤去**

`src/managers/ai_cli_manager.py` の `build_stdin_command` の AGY 分岐: `--effort` の追加行と `_map_agy_effort` 呼び出しを削除。代わりに Claude 分岐と同様、`effort != "none"` の場合 `logger.debug("agy CLI では reasoning_effort=%s は未対応のため無視します", effort)`。未使用になった `_map_agy_effort` メソッドを削除。AGY 分岐の最終形:
```python
        elif cli == AICli.AGY:
            # export MCP_PROJECT_ROOT=... && cd <path> &&
            # agy --model <model> --dangerously-skip-permissions --prompt-interactive "<instruction>"
            parts = [cmd]
            if resolved_model:
                parts.extend(["--model", resolved_model])
            if effort != "none":
                # agy はモデルID(例 gemini-3.1-pro-high)に tier を内包するため --effort は使わない
                logger.debug("agy CLI では reasoning_effort=%s は未対応のため無視します", effort)
            parts.append("--dangerously-skip-permissions")
            parts.extend(["--prompt-interactive", quoted_prompt])
            command = " ".join(parts)
            if working_dir:
                return f"{env_prefix}cd {shlex.quote(working_dir)} && {command}"
            return f"{env_prefix}{command}"
```

- [ ] **Step 4: 実モデル ID・コスト表を確定**

`src/config/settings.py`:
```python
    # Antigravity CLI (agy) — agy models の実 ID（tier 内包）
    AGY_DEFAULT = "gemini-3.1-pro-high"
    """agy デフォルトモデル（Admin 想定・高性能）"""

    AGY_LIGHT = "gemini-3.6-flash-medium"
    """agy 軽量モデル（Worker 想定）"""
```
`model_cost_table_json` の `agy:gemini-3-*` 3 行を実 ID の行へ置換（1K トークン単価は暫定見積り。agy 公式単価が出たら要更新）:
```python
        '"agy:gemini-3.1-pro-high":0.012,"agy:gemini-3.1-pro-low":0.006,'
        '"agy:gemini-3.6-flash-high":0.004,"agy:gemini-3.6-flash-medium":0.003,'
        '"agy:gemini-3.6-flash-low":0.002,'
        '"agy:gemini-3.5-flash-high":0.004,"agy:gemini-3.5-flash-medium":0.003,'
        '"agy:gemini-3.5-flash-low":0.002,'
        '"agy:claude-sonnet-4-6":0.015,"agy:claude-opus-4-6-thinking":0.03,'
        '"agy:gpt-oss-120b-medium":0.01,'
```
`tests/test_settings_env.py` のコスト表アサーション（旧 `agy:gemini-3-pro-preview` 等）を実 ID（例 `agy:gemini-3.1-pro-high`, `agy:gemini-3.6-flash-medium`）に更新。`ModelDefaults.AGY_DEFAULT`/`AGY_LIGHT` を参照するアサーションはそのまま通る。

- [ ] **Step 5: テストと lint**

Run: `uv run pytest && uv tool run ruff check src/`
Expected: 緑

- [ ] **Step 6: README に実起動検証手順と eligibility 前提を明記**

`README.md` の agy セットアップ節に追記:
- **eligibility 要件**: agy でエージェントを起動するには実行可能な Google アカウントが必要（一部 Workspace アカウントは `Eligibility check failed` で不可。その場合は個人アカウント or 管理者による有効化）。
- **実起動確認手順（手動）**: 小規模セッション（Admin + Worker 1）を agy で起動し、tmux ペイン内で agy が `--prompt-interactive` によりセッション継続し、IPC 通知（`[IPC] 新しいメッセージ`）に反応すること、ワンショット終了しないことを確認する。

- [ ] **Step 7: Commit（承認後）**

```bash
git add src/managers/ai_cli_manager.py src/config/settings.py tests/test_ai_cli_manager.py tests/test_settings_env.py README.md
git commit -m "feat(cli): agy の実モデルIDを確定し tier内包に伴い --effort を撤去"
```

---

## Self-Review メモ

- **Spec coverage**: 設計 spec の全項目（enum/コマンド/effort/互換判定/設定/コスト表/周辺/テスト/ドキュメント/フェーズ2）を Task 1-5 で網羅。
- **Placeholder scan**: モデル ID の「プレースホルダ」はフェーズ2で外部データ（`agy models`）により確定する明示的手順であり、TBD ではない。
- **Type consistency**: `AICli.AGY`、`_map_agy_effort`、`cli_default_agy_*`、キー `"agy"` / `agy_calls` を全タスクで一貫使用。
