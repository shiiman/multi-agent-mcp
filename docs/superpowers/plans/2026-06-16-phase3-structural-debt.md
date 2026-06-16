# Phase 3 構造負債解消 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 設計書 §6（構造負債・最高リスク）を解消する — ai_cli_manager のデッドコード約520行を除去し、managers→tools の逆依存（永続化/sync/find/send）を managers 配下モジュールへ移して解消し、tmux 層のテストを拡充する。

**Architecture:** (1) デッドコードはテスト側の参照を先に整理してから本体を削除（既存挙動は `terminal/` Executor とそのテストが網羅）。(2) 逆依存は「1ファイル移動=1コミット」で `helpers_git`/`helpers_registry`/`helpers_persistence` を `src/managers/` 配下へ移し、`src/tools/` 側は薄い re-export シムを残して後方互換を維持、`helpers.py` ファサードの symbol→module マップを更新。`send_with_scoped_rate_limit` は tools 非依存なので managers へ抽出。`ensure_*`（合成層 `runtime_bootstrap`）はサービスロケータ性質のため遅延 import のまま据置し理由をコメント明記。(3) tmux は `_run`/`_run_exec` をモックして組み立てコマンド文字列を `assert_called_with` で検証し、Codex 再送・Cursor 信頼・失敗系を追加。

**Tech Stack:** Python 3.10+, pytest + pytest-asyncio, unittest.mock, ruff (line-length=100)。`uv run pytest` / `uv tool run ruff check src/`。

**Branch:** `feature/audit-phase3`（main から作成済み）。1 PR = Phase 3 全体、サブステップごとにコミット分割。

**前提（着手前に1回だけ実行して状態を把握）:**
```bash
git branch --show-current   # => feature/audit-phase3
uv run pytest -q 2>&1 | tail -5   # ベースライン: 1123 passed を確認
uv tool run ruff check src/       # ベースライン: src/ クリーンを確認
```

**コミット規約:** Conventional Commits（日本語・`type(scope): 説明`）。`--no-verify` 禁止。メッセージ末尾に空行 + 以下を付与:
```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

---

## §6.1 — ai_cli_manager デッドコード除去（Task 1-3）

> 方針（ユーザー確定）: **削除中心＋差分のみ移植**。デッドメソッドを直接テストする `TestAiCliManagerTerminal` 全体は削除し、`terminal/` Executor のテストに無い差分（iTerm2/Terminal の単一引用符エスケープ）だけ移植する。循環 mock テスト（`TestInitializeAgentIntegration`）は削除、実経路テスト（test_agent_tools）は番兵行のみ除去。`_run_shell` も削除。

### Task 1: デッドメソッドを参照するテストを整理する

本体（`open_worktree` / `open_worktree_in_terminal` とその支援メソッド）は Task 2 で削除する。先にテスト側から参照を除去しておくことで、Task 2 の本体削除を安全な「未参照コードの削除」にする。

**Files:**
- Modify: `tests/test_ai_cli_manager.py`（`TestAiCliManagerTerminal` クラス: 472行〜末尾を削除）
- Modify: `tests/test_initialize_agent.py`（`TestInitializeAgentIntegration` クラス: 294-435 を削除）
- Modify: `tests/tools/test_agent_tools.py`（1235-1238 の `open_worktree_in_terminal` patch と 1261 の `assert_not_called` を除去）
- 参照確認: `tests/test_terminal_executors.py`

- [ ] **Step 1: Executor 側の同等カバレッジを確認する**

削除予定の `TestAiCliManagerTerminal` が検証している挙動が `terminal/` Executor のテストで担保されているか確認する。

Run:
```bash
grep -n "single_quote\|escape\|osascript\|open_in_tab\|open_workspace\|is_running\|is_available" tests/test_terminal_executors.py
grep -n "def test_" tests/test_ai_cli_manager.py | sed -n '/TestAiCliManagerTerminal/,$p'
sed -n '472,760p' tests/test_ai_cli_manager.py | grep -n "def test_\|_escape\|single_quote\|escapes_single_quote"
```
Expected: Ghostty(`test_open_in_tab_with_single_quote_command`)・Cmux(`test_open_workspace_with_single_quote_command`)・iTerm2/Terminal(`test_execute_script_uses_osascript_exec`) が存在。`test_ai_cli_manager.py` 側の `test_open_in_iterm2_escapes_single_quote_in_worktree_path` / `test_open_in_terminal_app_escapes_single_quote_in_worktree_path` に相当する「iTerm2/Terminal の単一引用符エスケープ」アサーションが Executor テストに**無い**場合は Step 3 で移植する。

- [ ] **Step 2: 削除対象テストを削除する**

`tests/test_ai_cli_manager.py` の `class TestAiCliManagerTerminal:`（472行）からファイル末尾までを削除する（このクラスの全テストはデッドメソッド `_detect_terminal`/`_open_in_ghostty`/`_open_in_iterm2`/`_open_in_terminal_app`/`open_worktree_in_terminal` を直接テストしている）。

`tests/test_initialize_agent.py` の `class TestInitializeAgentIntegration:`（294-435行）を削除する（4テストは `open_worktree_in_terminal` を mock して同メソッドを直接呼ぶ循環構造で、テンプレート読込は `TestTemplateLoaderForInitializeAgent`、CLI 解決は `TestInitializeAgentCLISelection` が既に網羅）。削除後、ファイル冒頭の未使用 import（`tempfile`, `AsyncMock`, `Agent`, `AgentStatus`, `TerminalApp` など `TestInitializeAgentIntegration` でのみ使われていたもの）は Step 5 の ruff --fix で除去する。

`tests/tools/test_agent_tools.py` の該当テスト（`initialize_agent` の iterm2 経路テスト, 1235行付近）から以下を除去する:
- `patch.object(app_ctx.ai_cli, "open_worktree_in_terminal", new_callable=AsyncMock) as mock_open_terminal,`（with 文の1項）
- 末尾の `mock_open_terminal.assert_not_called()`（1261行）

`with` 文が `is_available` patch のみになるよう整形する（実経路アサーション `open_session_in_terminal.assert_awaited_once_with(...)` 等は残す）。

- [ ] **Step 3: Executor テストに不足分を移植する（Step 1 で不足が判明した場合のみ）**

`tests/test_terminal_executors.py` の iTerm2/Terminal セクションに、単一引用符を含む worktree パスがエスケープされる検証が無ければ追加する。例（`TestITerm2Executor` クラス内、実装の引数構築を読んで実際の AppleScript エスケープ仕様に合わせること）:

```python
    @pytest.mark.asyncio
    async def test_execute_script_escapes_single_quote_in_path(self):
        """worktree パスに含まれる単一引用符が AppleScript 用にエスケープされる。"""
        executor = ITerm2Executor()
        captured = {}

        async def _fake_run_osascript(script: str):
            captured["script"] = script
            return (0, "", "")

        executor._run_osascript = _fake_run_osascript  # type: ignore[assignment]
        await executor.execute_script("/tmp/it's test", "echo ok")
        # 生の単一引用符が裸で残っていないこと（AppleScript 文字列が壊れない）
        assert "/tmp/it's test" not in captured["script"]
```
Expected: 実装のエスケープ方式（`escape_applescript` 等）に合わせ、エスケープ後の文字列が含まれることを確認。Step 1 で同等テストが既存と判明した場合は本 Step をスキップ。

- [ ] **Step 4: 変更したテストファイルを実行して緑を確認する**

Run:
```bash
uv run pytest tests/test_ai_cli_manager.py tests/test_initialize_agent.py tests/tools/test_agent_tools.py tests/test_terminal_executors.py -q
```
Expected: PASS（削除分を除いて全緑。`open_worktree_in_terminal` を参照する箇所が無いこと）

- [ ] **Step 5: import を整理してコミット**

Run:
```bash
uv tool run ruff check --fix tests/test_initialize_agent.py tests/test_ai_cli_manager.py tests/tools/test_agent_tools.py tests/test_terminal_executors.py
uv tool run ruff check src/   # src/ に影響なしを確認
git add tests/test_ai_cli_manager.py tests/test_initialize_agent.py tests/tools/test_agent_tools.py tests/test_terminal_executors.py
git commit -m "$(cat <<'EOF'
test(ai_cli): デッドメソッドを参照するテストを整理

- TestAiCliManagerTerminal を削除（terminal/ Executor テストが挙動を網羅）
- TestInitializeAgentIntegration を削除（循環 mock 構造・他クラスが網羅）
- test_agent_tools の open_worktree_in_terminal 番兵 patch を除去
- 不足していた iTerm2/Terminal の引用符エスケープ検証を Executor テストへ移植

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 2: ai_cli_manager のデッドコード本体を削除する

**Files:**
- Modify: `src/managers/ai_cli_manager.py`（`open_worktree` 362-424 と `open_worktree_in_terminal`+支援メソッド 458-916 を削除。間の `refresh_availability`/`get_cli_info`/`get_all_cli_info` 425-457 は残す）

- [ ] **Step 1: 削除前に本番経路が Executor 経由であることを最終確認する**

Run:
```bash
grep -rn "\.open_worktree_in_terminal\|\.open_worktree(" src/   # => 0 件（本番呼び出しなし）
grep -rn "launch_workspace_in_terminal\|CmuxExecutor\|GhosttyExecutor" src/managers/tmux_workspace_mixin.py src/tools/session_state.py | head
```
Expected: `src/` 本番コードに `ai_cli` 経由の呼び出しが 0 件。実経路は `tmux_workspace_mixin.launch_workspace_in_terminal` → `terminal/` Executor と `session_state.py` の `CmuxExecutor`。

- [ ] **Step 2: デッドメソッドを削除する**

`src/managers/ai_cli_manager.py` から以下を削除する:
- `async def open_worktree(` ブロック全体（362行〜 `except (OSError, ValueError)` の 423行まで、メソッド全体）
- `async def open_worktree_in_terminal(` 以降、ファイル末尾（916行）までの全メソッド（`open_worktree_in_terminal`, `_detect_terminal`, `_open_in_cmux`, `_is_cmux_running`, `_open_cmux_workspace`, `_open_in_ghostty`, `_is_ghostty_running`, `_open_in_ghostty_tab`, `_open_in_iterm2`, `_open_in_terminal_app`）

`refresh_availability`/`get_cli_info`/`get_all_cli_info`（425-457）は**残す**（呼び出し元あり）。削除後はファイル末尾がこの3メソッドになる。

- [ ] **Step 3: 未使用になった import を除去する**

削除により未使用になる import を除去する（`shutil`/`shlex` は残存使用ありなので残す）:
- `import asyncio`（6行）→ 削除
- `from pathlib import Path`（10行）→ 削除
- 13行 `from src.config.settings import DEFAULT_AI_CLI_COMMANDS, AICli, TerminalApp, resolve_model_for_cli` から `TerminalApp` を除去（`DEFAULT_AI_CLI_COMMANDS, AICli, resolve_model_for_cli` は残す）
- `from src.managers.tmux_shared import escape_applescript`（14行）→ 削除

Run（自動検出）:
```bash
uv tool run ruff check src/managers/ai_cli_manager.py   # F401 で未使用 import を列挙
uv tool run ruff check --fix src/managers/ai_cli_manager.py   # 自動除去
```
Expected: F401 が `asyncio`/`Path`/`TerminalApp`/`escape_applescript` を指摘 → --fix で解消。

- [ ] **Step 4: テストと lint を実行する**

Run:
```bash
uv run pytest tests/test_ai_cli_manager.py tests/test_initialize_agent.py tests/tools/test_agent_tools.py -q
uv run pytest -q 2>&1 | tail -5
uv tool run ruff check src/
```
Expected: 全 PASS、ruff クリーン。`ai_cli_manager.py` が約916行→約460行に縮小。

- [ ] **Step 5: コミット**

```bash
git add src/managers/ai_cli_manager.py
git commit -m "$(cat <<'EOF'
refactor(ai_cli): 未使用の open_worktree 系デッドコードを削除

- open_worktree と open_worktree_in_terminal および支援メソッド群（約520行）を削除
- 本番経路は terminal/ Executor へ移行済みで参照ゼロを確認
- 未使用となった asyncio/Path/TerminalApp/escape_applescript import を除去

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 3: terminal/base.py の未使用 `_run_shell` を削除する

**Files:**
- Modify: `src/managers/terminal/base.py`（`_run_shell` 69行〜、唯一の `create_subprocess_shell`）
- Modify: `tests/test_terminal_executors.py`（`test_run_shell_timeout_...` 削除、`_run_shell` 番兵 mock の整理）

- [ ] **Step 1: 本番未呼出を確認する**

Run:
```bash
grep -rn "_run_shell\|create_subprocess_shell" src/   # base.py の定義のみ（呼び出しなし）
grep -rn "_run_shell" tests/   # test_terminal_executors.py のみ
```
Expected: `src/` では `terminal/base.py` の定義 1 箇所のみ（各 Executor は `_run_exec` を使用し `_run_shell` を呼ばない）。

- [ ] **Step 2: 該当テストを整理する**

`tests/test_terminal_executors.py` から:
- `test_run_shell_timeout_kills_process_and_returns_structured_error`（100行付近、`_run_shell` を直接テスト）を削除。
- 各 Executor テストの `executor._run_shell = AsyncMock(side_effect=AssertionError(...))` と対応する `executor._run_shell.assert_not_called()`（158/197/221/250行付近）を削除する。これらは「`_run_shell` を使わない」番兵だが、メソッド削除で構造的に保証されるため不要（`_run_exec` 使用の検証は各テストに残す）。

- [ ] **Step 3: `_run_shell` を削除する**

`src/managers/terminal/base.py` から `async def _run_shell(self, command: str)` メソッド全体（69行〜、`create_subprocess_shell` を含むブロック）を削除する。削除後 `asyncio` import が他で使われているか確認し、未使用なら ruff --fix で除去。

- [ ] **Step 4: テストと lint**

Run:
```bash
uv run pytest tests/test_terminal_executors.py -q
uv tool run ruff check --fix src/managers/terminal/base.py && uv tool run ruff check src/
uv run pytest -q 2>&1 | tail -5
```
Expected: 全 PASS、ruff クリーン。

- [ ] **Step 5: コミット**

```bash
git add src/managers/terminal/base.py tests/test_terminal_executors.py
git commit -m "$(cat <<'EOF'
refactor(terminal): 未使用の _run_shell を削除し攻撃面を縮小

- 各 Executor は _run_exec を使用し _run_shell（唯一の create_subprocess_shell）を呼ばない
- _run_shell 直接テストと不要な assert_not_called 番兵を整理

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## §6.2 — managers→tools 逆依存の解消（Task 4-9）

> 方針（ユーザー確定）: **永続化 trio 移動＋send 抽出、ensure_* は据置**。`helpers_git`/`helpers_registry`/`helpers_persistence` を `src/managers/` 配下へ 1ファイル=1コミットで移動し `src/tools/` 側に re-export シムを残す。`send_with_scoped_rate_limit` は tools 非依存なので managers へ抽出。`find_agents_by_role` は agent 状態クエリとして `agent_persistence` に同梱。`ensure_*`（`runtime_bootstrap`=合成層）は遅延 import のまま、理由をコメント明記。

> **共通の注意（全 move タスク）:** tools シムは後方互換のため残す。`from src.tools.helpers_X import ...` の直接 import 元はシム経由で動き続ける。ただし**文字列パス指定の patch/monkeypatch は実体モジュールを更新する必要がある**（後述の各タスクで列挙）。`helpers.py` の `_SYMBOL_TO_MODULE`（symbol→module の dict）は実体の新パスへ更新する。

### Task 4: `helpers_git` → `src/managers/git_utils.py` へ移動

**Files:**
- Create: `src/managers/git_utils.py`（`src/tools/helpers_git.py` の中身を移動）
- Modify: `src/tools/helpers_git.py`（re-export シム化）
- Modify: `src/tools/helpers.py`（`resolve_main_repo_root` の module を更新）
- Modify: `tests/test_helpers_git.py`（`patch("src.tools.helpers_git.subprocess.run")` → `src.managers.git_utils.subprocess.run`）

- [ ] **Step 1: 実体を managers へ移動する**

`src/tools/helpers_git.py` の全内容を `src/managers/git_utils.py` として新規作成する（docstring は「Git ヘルパー関数（リポジトリルート解決・ブランチ統合判定）。」等に調整）。`git_utils.py` の末尾に `__all__` を追加し公開 API を列挙する:
```python
__all__ = [
    "clear_main_repo_root_cache",
    "resolve_main_repo_root",
]
```
（`_check_branch_merge_state` など `_` 接頭辞は外部で直接 import されるためシムで明示 re-export する。）

- [ ] **Step 2: tools 側をシム化する**

`src/tools/helpers_git.py` の中身を全削除し、以下のシムにする:
```python
"""Git ヘルパーの互換ファサード（実体は src.managers.git_utils）。"""

from src.managers.git_utils import *  # noqa: F401,F403
from src.managers.git_utils import (  # noqa: F401  外部が直接 import する非公開名の明示 re-export
    _check_branch_merge_state,
)
```
> 注: `from src.tools.helpers_git import _check_branch_merge_state` は `merge.py` 等が使用。`resolve_main_repo_root` は `__all__` 経由で `import *` により再エクスポートされる。

- [ ] **Step 3: ファサードと patch ターゲットを更新する**

`src/tools/helpers.py` の `_SYMBOL_TO_MODULE` で `"resolve_main_repo_root": "src.tools.helpers_git"` を `"src.managers.git_utils"` に変更する。

`tests/test_helpers_git.py` の `patch("src.tools.helpers_git.subprocess.run", ...)`（20・39行）を `patch("src.managers.git_utils.subprocess.run", ...)` に変更する。

- [ ] **Step 4: テストと lint**

Run:
```bash
uv run pytest tests/test_helpers_git.py tests/test_helpers.py tests/test_session_state.py tests/test_session_tools.py tests/test_merge*.py -q
uv tool run ruff check src/
uv run pytest -q 2>&1 | tail -5
```
Expected: 全 PASS。`src/managers/` から `src/tools/` への import が `git_utils.py` には存在しないこと（`grep -n "from src.tools" src/managers/git_utils.py` => 0 件）。

- [ ] **Step 5: コミット**

```bash
git add src/managers/git_utils.py src/tools/helpers_git.py src/tools/helpers.py tests/test_helpers_git.py
git commit -m "$(cat <<'EOF'
refactor(managers): helpers_git を managers/git_utils へ移動

- リポジトリルート解決・ブランチ統合判定を managers 配下の下位モジュールへ移動
- src/tools/helpers_git.py は後方互換の re-export シムとして維持
- helpers.py ファサードと test の patch ターゲットを新パスへ更新

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 5: `helpers_registry` → `src/managers/project_registry.py` へ移動

**Files:**
- Create: `src/managers/project_registry.py`
- Modify: `src/tools/helpers_registry.py`（シム化）
- Modify: `src/tools/helpers.py`（registry 由来 symbol の module を更新）

- [ ] **Step 1: 実体を移動し内部 import を managers 化する**

`src/tools/helpers_registry.py` の内容を `src/managers/project_registry.py` として作成する。冒頭の `from src.tools.helpers_git import resolve_main_repo_root` を `from src.managers.git_utils import resolve_main_repo_root` に変更する（managers→managers の正方向）。末尾に `__all__` を追加:
```python
__all__ = [
    "InvalidConfigError",
    "ensure_session_id",
    "get_enable_git_from_config",
    "get_mcp_tool_prefix_from_config",
    "get_project_root_from_config",
    "get_project_root_from_registry",
    "get_session_id_from_config",
    "get_session_id_from_registry",
    "remove_agent_from_registry",
    "remove_agents_by_owner",
    "save_agent_to_registry",
]
```

- [ ] **Step 2: tools 側をシム化する**

`src/tools/helpers_registry.py` を以下にする:
```python
"""レジストリ・設定 JSON ヘルパーの互換ファサード（実体は src.managers.project_registry）。"""

from src.managers.project_registry import *  # noqa: F401,F403
from src.managers.project_registry import (  # noqa: F401  外部/ファサードが参照する非公開名
    _get_agent_registry_dir,
    _get_from_config,
    _get_global_mcp_dir,
)
```

- [ ] **Step 3: ファサードを更新する**

`src/tools/helpers.py` の `_SYMBOL_TO_MODULE` で、値が `"src.tools.helpers_registry"` の全エントリ（`InvalidConfigError`, `_get_agent_registry_dir`, `_get_from_config`, `_get_global_mcp_dir`, `ensure_session_id`, `get_enable_git_from_config`, `get_mcp_tool_prefix_from_config`, `get_project_root_from_config`, `get_project_root_from_registry`, `get_session_id_from_config`, `get_session_id_from_registry`, `remove_agent_from_registry`, `remove_agents_by_owner`, `save_agent_to_registry`）を `"src.managers.project_registry"` に置換する。

Run（確認）:
```bash
grep -n "helpers_registry" src/tools/helpers.py   # => 0 件（全て project_registry に置換済み）
```

- [ ] **Step 4: テストと lint**

Run:
```bash
uv run pytest tests/test_helpers.py tests/test_helpers_registry*.py tests/test_session_state.py tests/test_session_tools.py -q 2>/dev/null
uv tool run ruff check src/
grep -n "from src.tools" src/managers/project_registry.py   # => 0 件
uv run pytest -q 2>&1 | tail -5
```
Expected: 全 PASS、`project_registry.py` に tools 依存なし。

- [ ] **Step 5: コミット**

```bash
git add src/managers/project_registry.py src/tools/helpers_registry.py src/tools/helpers.py
git commit -m "$(cat <<'EOF'
refactor(managers): helpers_registry を managers/project_registry へ移動

- グローバルエージェントレジストリと config.json アクセスを managers 配下へ移動
- 内部の helpers_git 依存を managers/git_utils へ付け替え
- src/tools/helpers_registry.py はシムとして維持、ファサードを新パスへ更新

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 6: `helpers_persistence` → `src/managers/agent_persistence.py` へ移動（`find_agents_by_role` 同梱）

**Files:**
- Create: `src/managers/agent_persistence.py`
- Modify: `src/tools/helpers_persistence.py`（シム化）
- Modify: `src/tools/helpers_permissions.py`（`find_agents_by_role` を agent_persistence から re-export）
- Modify: `src/tools/helpers.py`（persistence/find 由来 symbol の module を更新）
- Modify: patch ターゲット — `tests/test_helpers_persistence.py`, `tests/test_session_state.py`, `tests/test_session_tools.py`, `tests/test_helpers.py`

- [ ] **Step 1: 実体を移動し内部 import を managers 化する**

`src/tools/helpers_persistence.py` の内容を `src/managers/agent_persistence.py` として作成する。冒頭 import を変更:
- `from src.tools.helpers_git import resolve_main_repo_root` → `from src.managers.git_utils import resolve_main_repo_root`
- `from src.tools.helpers_registry import (ensure_session_id, get_project_root_from_config)` → `from src.managers.project_registry import (ensure_session_id, get_project_root_from_config)`

さらに `find_agents_by_role`（agent 状態クエリ）を `src/tools/helpers_permissions.py:230` から本モジュールへ移動する。`agent_persistence.py` に追加:
```python
def find_agents_by_role(app_ctx: AppContext, role: str) -> list[str]:
    """指定されたロールのエージェントIDを取得する。

    Args:
        app_ctx: アプリケーションコンテキスト
        role: 検索するロール（"owner", "admin", "worker"）

    Returns:
        該当するエージェントIDのリスト
    """
    return [agent_id for agent_id, agent in app_ctx.agents.items() if agent.role == role]
```
末尾に `__all__`:
```python
__all__ = [
    "delete_agents_file",
    "find_agents_by_role",
    "load_agents_from_file",
    "remove_agent_from_file",
    "reset_sync_cache",
    "save_agent_to_file",
    "sync_agents_from_file",
]
```

- [ ] **Step 2: tools 側をシム化する**

`src/tools/helpers_persistence.py` を以下にする:
```python
"""エージェント永続化ヘルパーの互換ファサード（実体は src.managers.agent_persistence）。"""

from src.managers.agent_persistence import *  # noqa: F401,F403
from src.managers.agent_persistence import (  # noqa: F401  外部/ファサード/テストが参照する非公開名
    _atomic_write_json,
    _get_agents_file_path,
    fcntl,
    json,
    resolve_main_repo_root,
)
```
> 注: `tests/test_helpers.py` が `src.tools.helpers_persistence.fcntl.flock` を、`tests/test_helpers_persistence.py` が `src.tools.helpers_persistence.json.load` を patch していたが、Step 4 で patch ターゲットを実体（managers）へ移すため、ここでの `fcntl`/`json`/`resolve_main_repo_root` の明示 re-export は「他に直接参照する箇所が残る場合の保険」。grep で参照が消えていれば省略可。

`src/tools/helpers_permissions.py` の `find_agents_by_role` 定義（230-240行）を削除し、ファイル冒頭付近に re-export を追加:
```python
from src.managers.agent_persistence import find_agents_by_role  # noqa: F401  後方互換 re-export
```

- [ ] **Step 3: ファサードを更新する**

`src/tools/helpers.py` の `_SYMBOL_TO_MODULE` で:
- 値が `"src.tools.helpers_persistence"` の全エントリ（`_get_agents_file_path`, `delete_agents_file`, `load_agents_from_file`, `remove_agent_from_file`, `save_agent_to_file`, `sync_agents_from_file`）→ `"src.managers.agent_persistence"`
- `"find_agents_by_role": "src.tools.helpers_permissions"` → `"src.managers.agent_persistence"`

- [ ] **Step 4: patch ターゲットを更新する**

ファイル移動で実体が managers へ移るため、文字列パス指定の patch を更新する:
- `tests/test_helpers_persistence.py:78` `"src.tools.helpers_persistence.json.load"` → `"src.managers.agent_persistence.json.load"`
- `tests/test_session_state.py:18` `_RESOLVE_PATCH = "src.tools.helpers_persistence.resolve_main_repo_root"` → `"src.managers.agent_persistence.resolve_main_repo_root"`
- `tests/test_session_tools.py:20` 同上 → `"src.managers.agent_persistence.resolve_main_repo_root"`
- `tests/test_helpers.py:593,620` `"src.tools.helpers_persistence.fcntl.flock"` → `"src.managers.agent_persistence.fcntl.flock"`

Run（取りこぼし検出）:
```bash
grep -rn "src.tools.helpers_persistence\.\|src.tools.helpers_git\.\|src.tools.helpers_registry\." tests/ | grep -i "patch\|setattr"
```
Expected: 上記4ファイルの更新後は 0 件（残っていれば同様に managers パスへ更新）。

- [ ] **Step 5: テストと lint**

Run:
```bash
uv run pytest tests/test_helpers_persistence.py tests/test_helpers.py tests/test_session_state.py tests/test_session_tools.py -q
grep -n "from src.tools" src/managers/agent_persistence.py   # => 0 件
uv tool run ruff check src/
uv run pytest -q 2>&1 | tail -5
```
Expected: 全 PASS、`agent_persistence.py` に tools 依存なし。

- [ ] **Step 6: コミット**

```bash
git add src/managers/agent_persistence.py src/tools/helpers_persistence.py src/tools/helpers_permissions.py src/tools/helpers.py tests/test_helpers_persistence.py tests/test_session_state.py tests/test_session_tools.py tests/test_helpers.py
git commit -m "$(cat <<'EOF'
refactor(managers): helpers_persistence を managers/agent_persistence へ移動

- agents.json の永続化/sync/load と find_agents_by_role を managers 配下へ移動
- 内部依存を managers/git_utils・managers/project_registry へ付け替え
- tools シム・helpers ファサード・test の patch ターゲットを新パスへ更新

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 7: 3 managers の永続化/find import を managers パスへ付け替える

> ここで初めて managers→tools の逆 import が実際に解消される（Task 4-6 はシムで温存していた）。

**Files:**
- Modify: `src/managers/dashboard_manager.py:205`
- Modify: `src/managers/healthcheck_manager.py:118`
- Modify: `src/managers/healthcheck_daemon.py:32,140`

- [ ] **Step 1: import 元を managers へ変更する**

- `src/managers/dashboard_manager.py:205` `from src.tools.helpers_persistence import save_agent_to_file` → `from src.managers.agent_persistence import save_agent_to_file`
- `src/managers/healthcheck_manager.py:118` `from src.tools.helpers_persistence import save_agent_to_file` → `from src.managers.agent_persistence import save_agent_to_file`
- `src/managers/healthcheck_daemon.py:32` `from src.tools.helpers import find_agents_by_role, sync_agents_from_file` → `from src.managers.agent_persistence import find_agents_by_role, sync_agents_from_file`
- `src/managers/healthcheck_daemon.py:140` `from src.tools.helpers import sync_agents_from_file` → `from src.managers.agent_persistence import sync_agents_from_file`

> `ensure_dashboard_manager`/`ensure_ipc_manager`/`ensure_healthcheck_manager`（helpers_managers 経由）は Task 9 で扱うため、ここでは変更しない。

- [ ] **Step 2: 逆依存が永続化分だけ減ったことを確認する**

Run:
```bash
grep -rn "from src.tools.helpers_persistence\|from src.tools.helpers import find_agents_by_role\|from src.tools.helpers import.*sync_agents_from_file" src/managers/
```
Expected: 0 件（永続化/find/sync の managers→tools import が消えた。残るのは `ensure_*` と `send_with_scoped_rate_limit` のみ）。

- [ ] **Step 3: テストと lint**

Run:
```bash
uv run pytest tests/test_dashboard_manager*.py tests/test_healthcheck*.py -q
uv tool run ruff check src/
uv run pytest -q 2>&1 | tail -5
```
Expected: 全 PASS。

- [ ] **Step 4: コミット**

```bash
git add src/managers/dashboard_manager.py src/managers/healthcheck_manager.py src/managers/healthcheck_daemon.py
git commit -m "$(cat <<'EOF'
refactor(managers): 永続化/sync/find の逆 import を managers 直参照へ解消

- dashboard_manager・healthcheck_manager・healthcheck_daemon が
  src.tools.helpers* ではなく src.managers.agent_persistence を直接 import
- managers→tools の依存方向違反（永続化分）を解消

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 8: `send_with_scoped_rate_limit` を `src/managers/dispatch_rate_limit.py` へ抽出

**Files:**
- Create: `src/managers/dispatch_rate_limit.py`
- Modify: `src/tools/agent_helpers.py`（抽出した関数群を re-export して内部使用を維持）
- Modify: `src/managers/healthcheck_manager.py:1218`（managers から直接 import）
- Modify: `tests/test_agent_helpers.py`（send 系テストの patch ターゲットを managers へ）

- [ ] **Step 1: 関数群を managers へ抽出する**

`src/managers/dispatch_rate_limit.py` を新規作成し、`src/tools/agent_helpers.py` の以下を移動する（いずれも tools 非依存・`app_ctx`/`tmux`/stdlib のみ使用）:
- `_resolve_dispatch_lock_store`（55-61）
- `_resolve_dispatch_timestamp_store`（64-70）
- `_build_dispatch_scope_key`（73-82）
- `send_with_scoped_rate_limit`（85-155）

```python
"""ペイン送信のスコープ別レート制御。"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.context import AppContext

__all__ = ["send_with_scoped_rate_limit"]


# （_resolve_dispatch_lock_store / _resolve_dispatch_timestamp_store /
#   _build_dispatch_scope_key / send_with_scoped_rate_limit を agent_helpers から移動）
```
> 関数本体は agent_helpers の現行実装をそのままコピーする（`unittest.mock` の遅延 import を含むテスト検出ロジックも保持）。

- [ ] **Step 2: agent_helpers を re-export に変更する**

`src/tools/agent_helpers.py` から上記4関数の定義を削除し、import で再エクスポートする（agent_helpers 内の他コードが `send_with_scoped_rate_limit` を内部使用しているため、また後方互換のため）:
```python
from src.managers.dispatch_rate_limit import (  # noqa: F401
    _build_dispatch_scope_key,
    _resolve_dispatch_lock_store,
    _resolve_dispatch_timestamp_store,
    send_with_scoped_rate_limit,
)
```
削除後に未使用となる import（`time` が agent_helpers の他所で使われていなければ）は ruff --fix で除去。

- [ ] **Step 3: healthcheck_manager を managers 直参照へ**

`src/managers/healthcheck_manager.py:1218` `from src.tools.agent_helpers import send_with_scoped_rate_limit` → `from src.managers.dispatch_rate_limit import send_with_scoped_rate_limit`

- [ ] **Step 4: send 系テストの patch ターゲットを更新する**

`tests/test_agent_helpers.py` の send_with_scoped_rate_limit cooldown テスト（165-207行付近）で、実体が managers へ移ったため patch を更新:
- `"src.tools.agent_helpers.time.monotonic"` → `"src.managers.dispatch_rate_limit.time.monotonic"`
- `"src.tools.agent_helpers.asyncio.sleep"` → `"src.managers.dispatch_rate_limit.asyncio.sleep"`

テスト冒頭の `from src.tools.agent_helpers import send_with_scoped_rate_limit`（あれば）は re-export 経由で動くため変更不要。

Run（取りこぼし検出）:
```bash
grep -rn "src.tools.agent_helpers.time.monotonic\|src.tools.agent_helpers.asyncio.sleep" tests/
```
Expected: send_with_scoped_rate_limit を対象にした箇所は 0 件（他の用途で agent_helpers.asyncio.sleep を patch しているテストがあればそれは触らない）。

- [ ] **Step 5: テストと lint**

Run:
```bash
uv run pytest tests/test_agent_helpers.py tests/test_healthcheck*.py -q
grep -rn "from src.tools" src/managers/dispatch_rate_limit.py   # => 0 件
uv tool run ruff check src/
uv run pytest -q 2>&1 | tail -5
```
Expected: 全 PASS（特に `test_waits_when_same_pane_is_reused_within_cooldown` が `sleep_mock.assert_awaited_once_with(4.0)` で緑）。

- [ ] **Step 6: コミット**

```bash
git add src/managers/dispatch_rate_limit.py src/tools/agent_helpers.py src/managers/healthcheck_manager.py tests/test_agent_helpers.py
git commit -m "$(cat <<'EOF'
refactor(managers): send_with_scoped_rate_limit を managers/dispatch_rate_limit へ抽出

- レート制御送信ロジック（tools 非依存）を managers 配下へ移動
- agent_helpers は後方互換の re-export に変更、healthcheck_manager は managers 直参照
- send 系テストの patch ターゲットを実体（managers）へ更新

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 9: 残存する `ensure_*` 遅延 import の据置理由を明記する

> `ensure_*` は `runtime_bootstrap`（managers を構築する合成層）にあり、managers がそれを参照するのはサービスロケータ的結合で、物理移動するとモジュールレベルの循環になる。今回は遅延 import のまま維持し、意図をコメントで明記する（監査指摘の「規約の形骸化」を「意図的な例外」として可視化）。

**Files:**
- Modify: `src/managers/healthcheck_manager.py:130`（`ensure_dashboard_manager` 遅延 import 箇所）
- Modify: `src/managers/healthcheck_daemon.py:33,104,141`（`ensure_*` 遅延 import 箇所）

- [ ] **Step 1: 据置理由のコメントを各遅延 import 直前に追加する**

各 `from src.tools.helpers_managers import ensure_*` / `from src.tools.helpers import sync_agents_from_file`（※sync は Task 7 で解消済みなので対象は ensure_* のみ）の直前に、統一文言のコメントを付す:
```python
# 合成層（runtime_bootstrap）のマネージャ生成はサービスロケータ的結合のため、
# モジュールレベル循環を避けて遅延 import で参照する（Phase 3 §6.2 の意図的例外）。
```
対象:
- `src/managers/healthcheck_manager.py:130` `from src.tools.helpers_managers import ensure_dashboard_manager`
- `src/managers/healthcheck_daemon.py:33` `from src.tools.helpers_managers import ensure_dashboard_manager, ensure_ipc_manager`
- `src/managers/healthcheck_daemon.py:104` `from src.tools.helpers_managers import ensure_dashboard_manager`
- `src/managers/healthcheck_daemon.py:141` `from src.tools.helpers_managers import ensure_healthcheck_manager`

> `healthcheck_daemon.py:32` の `find_agents_by_role, sync_agents_from_file` は Task 7 で managers 直参照へ解消済み。本タスクでは触らない。

- [ ] **Step 2: 残る逆依存が ensure_* のみであることを確認する**

Run:
```bash
grep -rn "from src.tools\|import src.tools" src/managers/
```
Expected: ヒットは `helpers_managers`（ensure_*）の遅延 import のみ。永続化/find/send は 0 件。

- [ ] **Step 3: テストと lint・コミット**

Run:
```bash
uv run pytest tests/test_healthcheck*.py -q
uv tool run ruff check src/
git add src/managers/healthcheck_manager.py src/managers/healthcheck_daemon.py
git commit -m "$(cat <<'EOF'
docs(managers): ensure_* 遅延 import の据置理由を明記

- 合成層 runtime_bootstrap のマネージャ生成参照を意図的例外として可視化
- 永続化/find/send の逆依存は Task 4-8 で解消済み

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## §6.3 — tmux 層テスト拡充（Task 10-13）

> 方針（ユーザー確定）: **既存ファイル増補＋70% 目安**。新規ファイルは作らず既存 `tests/test_tmux_*.py` を増補（または `tests/test_tmux_manager_commands.py` / `tests/test_tmux_workspace_send.py` を新設）。`_run` をモックして組み立てコマンド文字列を `assert_called_with` で検証。Codex 再送・rate-limit・Cursor 信頼分岐・失敗系を追加。両モジュール 70% 前後を目安（達成度で調整）。

> 構築パターン（既存テスト準拠）: `manager = TmuxManager(Settings())`。`_run` を `AsyncMock` 化して呼び出し引数を検証する。

### Task 10: tmux_manager のコマンド組み立て文字列を検証する

**Files:**
- Create: `tests/test_tmux_manager_commands.py`
- 参照: `src/managers/tmux_manager.py`（`_run` を呼ぶ各メソッド）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tmux_manager_commands.py` を作成する。各メソッドが組み立てる tmux 引数を `_run` のモックで検証し、失敗系（`_run` が非ゼロ返却）で False を返すことも検証する:

```python
"""TmuxManager の tmux コマンド組み立て検証。"""

from unittest.mock import AsyncMock

import pytest

from src.config.settings import Settings
from src.managers.tmux_manager import TmuxManager


def _manager_with_run(return_value=(0, "", "")):
    manager = TmuxManager(Settings())
    manager._run = AsyncMock(return_value=return_value)
    return manager


@pytest.mark.asyncio
async def test_create_session_builds_new_session_args():
    manager = _manager_with_run()
    ok = await manager.create_session("proj", "/work/dir")
    assert ok is True
    manager._run.assert_called_with("new-session", "-d", "-s", "proj", "-c", "/work/dir")


@pytest.mark.asyncio
async def test_create_session_returns_false_on_error():
    manager = _manager_with_run((1, "", "boom"))
    ok = await manager.create_session("proj", "/work/dir")
    assert ok is False


@pytest.mark.asyncio
async def test_send_keys_literal_sends_text_then_enter():
    manager = _manager_with_run()
    ok = await manager.send_keys("proj", "echo hi", literal=True)
    assert ok is True
    assert manager._run.await_args_list[0].args == ("send-keys", "-t", "proj", "-l", "echo hi")
    assert manager._run.await_args_list[1].args == ("send-keys", "-t", "proj", "Enter")


@pytest.mark.asyncio
async def test_send_keys_non_literal_omits_l_flag():
    manager = _manager_with_run()
    await manager.send_keys("proj", "C-c", literal=False)
    assert manager._run.await_args_list[0].args == ("send-keys", "-t", "proj", "C-c")


@pytest.mark.asyncio
async def test_send_keys_returns_false_when_text_send_fails():
    manager = _manager_with_run((1, "", "err"))
    ok = await manager.send_keys("proj", "echo hi")
    assert ok is False


@pytest.mark.asyncio
async def test_capture_pane_builds_capture_args_and_returns_stdout():
    manager = _manager_with_run((0, "captured-output\n", ""))
    out = await manager.capture_pane("proj", lines=50)
    assert out == "captured-output\n"
    manager._run.assert_called_with("capture-pane", "-t", "proj", "-p", "-S", "-50")


@pytest.mark.asyncio
async def test_kill_session_builds_kill_args():
    manager = _manager_with_run()
    await manager.kill_session("proj")
    manager._run.assert_called_with("kill-session", "-t", "proj")


@pytest.mark.asyncio
async def test_session_exists_uses_has_session():
    manager = _manager_with_run((0, "", ""))
    assert await manager.session_exists("proj") is True
    manager._run.assert_called_with("has-session", "-t", "proj")


@pytest.mark.asyncio
async def test_list_sessions_parses_lines():
    manager = _manager_with_run((0, "a\nb\n\n", ""))
    assert await manager.list_sessions() == ["a", "b"]
    manager._run.assert_called_with("list-sessions", "-F", "#{session_name}")


@pytest.mark.asyncio
async def test_rename_session_builds_rename_args():
    manager = _manager_with_run()
    await manager.rename_session("old", "new")
    manager._run.assert_called_with("rename-session", "-t", "old", "new")
```

- [ ] **Step 2: 実行して緑を確認する**

Run:
```bash
uv run pytest tests/test_tmux_manager_commands.py -v
```
Expected: 全 PASS。万一引数が不一致なら、実装（`src/managers/tmux_manager.py`）の該当メソッドを読んで期待値を実態へ修正する（実装は変更しない — テストを実態に合わせる）。

- [ ] **Step 3: lint とコミット**

```bash
uv tool run ruff check tests/test_tmux_manager_commands.py
git add tests/test_tmux_manager_commands.py
git commit -m "$(cat <<'EOF'
test(tmux): TmuxManager のコマンド組み立てと失敗系を検証

- create_session/send_keys/capture_pane/kill_session/session_exists/
  list_sessions/rename_session の tmux 引数を assert_called_with で検証
- _run 非ゼロ返却時に False を返す失敗系を追加

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 11: send_keys_to_pane の clear_input / literal / 失敗系を検証する

**Files:**
- Create: `tests/test_tmux_workspace_send.py`
- 参照: `src/managers/tmux_workspace_mixin.py:305`（`send_keys_to_pane`）, `_pane_target`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tmux_workspace_send.py` を作成する。`_run` と `_send_enter_key` をモックして、`clear_input` の C-u 先行送信、literal/非literal の引数、失敗系を検証する:

```python
"""TmuxWorkspaceMixin の send 系コマンド組み立て検証。"""

from unittest.mock import AsyncMock

import pytest

from src.config.settings import Settings
from src.managers.tmux_manager import TmuxManager


def _manager(run_return=(0, "", "")):
    manager = TmuxManager(Settings())
    manager._run = AsyncMock(return_value=run_return)
    manager._send_enter_key = AsyncMock(return_value=True)
    return manager


@pytest.mark.asyncio
async def test_send_keys_to_pane_clears_input_with_c_u_first():
    manager = _manager()
    ok = await manager.send_keys_to_pane("sess", 0, 1, "echo hi", clear_input=True)
    assert ok is True
    target = manager._pane_target("sess", 0, 1)
    assert manager._run.await_args_list[0].args == ("send-keys", "-t", target, "C-u")
    assert manager._run.await_args_list[1].args == ("send-keys", "-t", target, "-l", "echo hi")
    manager._send_enter_key.assert_awaited_once_with(target)


@pytest.mark.asyncio
async def test_send_keys_to_pane_skips_clear_when_disabled():
    manager = _manager()
    await manager.send_keys_to_pane("sess", 0, 1, "echo hi", clear_input=False)
    target = manager._pane_target("sess", 0, 1)
    # C-u を送らず、いきなりテキスト送信
    assert manager._run.await_args_list[0].args == ("send-keys", "-t", target, "-l", "echo hi")


@pytest.mark.asyncio
async def test_send_keys_to_pane_non_literal_omits_l_flag():
    manager = _manager()
    await manager.send_keys_to_pane("sess", 0, 1, "C-c", literal=False, clear_input=False)
    target = manager._pane_target("sess", 0, 1)
    assert manager._run.await_args_list[0].args == ("send-keys", "-t", target, "C-c")


@pytest.mark.asyncio
async def test_send_keys_to_pane_returns_false_on_send_error():
    manager = _manager((1, "", "err"))
    ok = await manager.send_keys_to_pane("sess", 0, 1, "echo hi", clear_input=False)
    assert ok is False
    manager._send_enter_key.assert_not_awaited()
```

- [ ] **Step 2: 実行して緑を確認する**

Run:
```bash
uv run pytest tests/test_tmux_workspace_send.py -v
```
Expected: 全 PASS。`_pane_target` の戻り形式（`sess:0.1`）に依存せず `manager._pane_target(...)` 経由で期待値を作っているため実態に追従する。

- [ ] **Step 3: lint とコミット**

```bash
uv tool run ruff check tests/test_tmux_workspace_send.py
git add tests/test_tmux_workspace_send.py
git commit -m "$(cat <<'EOF'
test(tmux): send_keys_to_pane の clear_input/literal/失敗系を検証

- clear_input=True で C-u 先行送信、False でスキップを検証
- literal フラグの有無で送信引数が変わることを検証
- 送信失敗時に Enter を送らず False を返すことを検証

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

> **改訂（Task 11 完了後のカバレッジ実測に基づく）:** 当初の Task 12/13 は `send_and_confirm_to_pane` と `_is_pending_codex_prompt` を対象としていたが、両者は既に `tests/test_helpers.py` の `TestCodexPromptConfirmation` / `TestCodexPromptDetection` で網羅済み（重複・DRY 違反になる）。Task 10/11 後の実測（tmux_manager 63% / tmux_workspace_mixin 51%）で判明した**真の未カバー行**へ Task 12/13 を振り替える。

### Task 12: tmux_workspace_mixin のペイン/セッションコマンドビルダーを検証する

未カバーのコマンドビルダー（`_run` 引数を組み立てるだけの純粋なメソッド群）を `assert_called_with` で検証し、tmux_workspace_mixin のカバレッジを大きく引き上げる。

**Files:**
- Create: `tests/test_tmux_workspace_commands.py`
- 参照: `src/managers/tmux_workspace_mixin.py`（`capture_pane_by_index` 549, `get_pane_current_command` 573, `set_pane_title` 598, `list_windows` 618, `get_pane_count` 654, `_create_main_session_window` 166, `_configure_session_options` 183, `_normalize_window_indices` 197）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tmux_workspace_commands.py` を作成する。`TmuxManager(Settings())` を構築し `_run` を `AsyncMock` 化して、各メソッドが組み立てる tmux 引数と失敗系を検証する。期待値は実装（上記行）を読んで一致させること（実装は変更しない）:

```python
"""TmuxWorkspaceMixin のペイン/セッションコマンド組み立て検証。"""

from unittest.mock import AsyncMock, call

import pytest

from src.config.settings import Settings
from src.managers.tmux_manager import TmuxManager


def _manager(run_return=(0, "", "")):
    manager = TmuxManager(Settings())
    manager._run = AsyncMock(return_value=run_return)
    return manager


@pytest.mark.asyncio
async def test_capture_pane_by_index_builds_args_and_returns_stdout():
    manager = _manager((0, "captured\n", ""))
    target = manager._pane_target("sess", 1, 2)
    out = await manager.capture_pane_by_index("sess", 1, 2, lines=80)
    assert out == "captured\n"
    manager._run.assert_called_with("capture-pane", "-t", target, "-p", "-S", "-80")


@pytest.mark.asyncio
async def test_capture_pane_by_index_returns_empty_on_error():
    manager = _manager((1, "", "err"))
    assert await manager.capture_pane_by_index("sess", 0, 0) == ""


@pytest.mark.asyncio
async def test_get_pane_current_command_builds_display_message_args():
    manager = _manager((0, "codex\n", ""))
    target = manager._pane_target("sess", 0, 1)
    cmd = await manager.get_pane_current_command("sess", 0, 1)
    assert cmd == "codex"
    manager._run.assert_called_with(
        "display-message", "-p", "-t", target, "#{pane_current_command}"
    )


@pytest.mark.asyncio
async def test_get_pane_current_command_none_on_empty_or_error():
    assert await _manager((0, "  \n", "")).get_pane_current_command("s", 0, 0) is None
    assert await _manager((1, "", "x")).get_pane_current_command("s", 0, 0) is None


@pytest.mark.asyncio
async def test_set_pane_title_builds_select_pane_args():
    manager = _manager()
    target = manager._pane_target("sess", 0, 3)
    ok = await manager.set_pane_title("sess", 0, 3, "Worker 3")
    assert ok is True
    manager._run.assert_called_with("select-pane", "-t", target, "-T", "Worker 3")


@pytest.mark.asyncio
async def test_list_windows_parses_format_output():
    manager = _manager((0, "0:main:7\n1:workers-1:10\n\n", ""))
    windows = await manager.list_windows("sess")
    assert windows == [
        {"index": 0, "name": "main", "panes": 7},
        {"index": 1, "name": "workers-1", "panes": 10},
    ]
    manager._run.assert_called_with(
        "list-windows", "-t", "sess", "-F", "#{window_index}:#{window_name}:#{window_panes}"
    )


@pytest.mark.asyncio
async def test_get_pane_count_returns_matching_window_panes():
    manager = _manager((0, "0:main:7\n1:workers-1:10\n", ""))
    assert await manager.get_pane_count("sess", 1) == 10
    assert await manager.get_pane_count("sess", 9) == 0


@pytest.mark.asyncio
async def test_create_main_session_window_builds_new_session_with_name():
    manager = _manager()
    ok = await manager._create_main_session_window("sess", "/wd")
    assert ok is True
    manager._run.assert_called_with(
        "new-session", "-d", "-s", "sess", "-c", "/wd",
        "-n", manager.settings.window_name_main,
    )


@pytest.mark.asyncio
async def test_create_main_session_window_returns_false_on_error():
    manager = _manager((1, "", "boom"))
    assert await manager._create_main_session_window("sess", "/wd") is False


@pytest.mark.asyncio
async def test_configure_session_options_sets_base_index_options():
    manager = _manager()
    ok = await manager._configure_session_options("sess")
    assert ok is True
    main = manager.settings.window_name_main
    manager._run.assert_has_awaits([
        call("set-option", "-t", "sess", "base-index", "0"),
        call("set-option", "-t", "sess", "pane-base-index", "0"),
        call("set-window-option", "-t", f"sess:{main}", "pane-base-index", "0"),
    ])


@pytest.mark.asyncio
async def test_normalize_window_indices_builds_move_window_args():
    manager = _manager()
    ok = await manager._normalize_window_indices("sess")
    assert ok is True
    manager._run.assert_called_with("move-window", "-r", "-t", "sess")
```

- [ ] **Step 2: 実行して緑を確認する**

Run: `uv run pytest tests/test_tmux_workspace_commands.py -v`
Expected: 全 PASS。引数不一致なら該当メソッドを読み、期待値を実態へ修正する（実装は変更しない）。

- [ ] **Step 3: lint とコミット**

```bash
uv tool run ruff check tests/test_tmux_workspace_commands.py
git add tests/test_tmux_workspace_commands.py
git commit -m "$(cat <<'EOF'
test(tmux): workspace のペイン/セッションコマンド組み立てを検証

- capture_pane_by_index/get_pane_current_command/set_pane_title/
  list_windows/get_pane_count の tmux 引数と失敗系を検証
- _create_main_session_window/_configure_session_options/
  _normalize_window_indices のオプション組み立てを検証

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 13: Cursor 信頼検知の純関数と未カバー分岐を検証する

既存テスト未カバーの分岐に絞る（Codex/confirm の重複は作らない）: Cursor 信頼検知の純関数 2 つ、`_confirm_cursor_workspace_trust` の承認ループ、および `_is_pending_codex_prompt` のトークン重複緩和分岐（397-408、既存テストは prefix/tab/confirmed のみカバー）。

**Files:**
- Create: `tests/test_tmux_workspace_cursor_trust.py`
- 参照: `src/managers/tmux_workspace_mixin.py`（`_command_may_launch_cursor_agent` 93, `_is_cursor_workspace_trust_prompt` 107, `_confirm_cursor_workspace_trust` 115, `_is_pending_codex_prompt` 357 のトークン重複分岐 397-408）

- [ ] **Step 1: テストを書く**

実装の正規表現/判定を読んで期待値を確定すること。`_command_may_launch_cursor_agent` は `(^|&&|;|\|\|)` セパレータまたは `\S+/` の直後の `agent`/`cursor-agent\b` のみを真とする（引数中の `agent` は偽）:

```python
"""TmuxWorkspaceMixin の Cursor 信頼検知・Codex トークン分岐検証。"""

from unittest.mock import AsyncMock, patch

import pytest

from src.config.settings import Settings
from src.managers.tmux_manager import TmuxManager

_MIXIN = "src.managers.tmux_workspace_mixin"


@pytest.mark.parametrize(
    "command,expected",
    [
        ("cursor-agent", True),
        ("agent", True),
        ("/usr/local/bin/cursor-agent --flag", True),
        ("echo hi && agent", True),
        ("echo hi; cursor-agent", True),
        ("vim agent.py", False),        # 引数の agent は起動でない
        ("echo agent_helpers", False),  # 語境界なし
        ("codex run", False),
        ("", False),
    ],
)
def test_command_may_launch_cursor_agent(command, expected):
    assert TmuxManager(Settings())._command_may_launch_cursor_agent(command) is expected


@pytest.mark.parametrize(
    "output,expected",
    [
        ("Workspace Trust Required\nTrust this workspace? (y/n)", True),
        ("workspace trust required", False),   # 片方のみ
        ("trust this workspace", False),       # 片方のみ
        ("just normal output", False),
    ],
)
def test_is_cursor_workspace_trust_prompt(output, expected):
    assert TmuxManager(Settings())._is_cursor_workspace_trust_prompt(output) is expected


@pytest.mark.asyncio
async def test_confirm_cursor_trust_returns_true_when_no_prompt():
    manager = TmuxManager(Settings())
    manager.capture_pane_by_index = AsyncMock(return_value="all good")
    manager._run = AsyncMock(return_value=(0, "", ""))
    ok = await manager._confirm_cursor_workspace_trust("sess", 0, 1)
    assert ok is True
    manager._run.assert_not_awaited()  # プロンプトなし→承認キー送らず


@pytest.mark.asyncio
async def test_confirm_cursor_trust_sends_accept_key_then_confirms():
    manager = TmuxManager(Settings())
    prompt = "Workspace Trust Required\nTrust this workspace"
    manager.capture_pane_by_index = AsyncMock(side_effect=[prompt, "cleared"])
    manager._run = AsyncMock(return_value=(0, "", ""))
    target = manager._pane_target("sess", 0, 1)
    with patch(f"{_MIXIN}.asyncio.sleep", new=AsyncMock()):
        ok = await manager._confirm_cursor_workspace_trust("sess", 0, 1)
    assert ok is True
    manager._run.assert_awaited_with("send-keys", "-t", target, "a")


@pytest.mark.asyncio
async def test_confirm_cursor_trust_returns_false_when_key_send_fails():
    manager = TmuxManager(Settings())
    prompt = "Workspace Trust Required\nTrust this workspace"
    manager.capture_pane_by_index = AsyncMock(return_value=prompt)
    manager._run = AsyncMock(return_value=(1, "", "err"))
    with patch(f"{_MIXIN}.asyncio.sleep", new=AsyncMock()):
        ok = await manager._confirm_cursor_workspace_trust("sess", 0, 1)
    assert ok is False


@pytest.mark.parametrize(
    "output,command,expected",
    [
        # トークン重複 >=0.4 で未確定（prefix では一致しないケース）
        ("› gamma alpha zeta", "alpha beta gamma delta", True),
        # トークン重複 <0.4 は確定扱い
        ("› zzz qqq", "alpha beta gamma delta", False),
    ],
)
def test_is_pending_codex_prompt_token_overlap_branch(output, command, expected):
    assert TmuxManager(Settings())._is_pending_codex_prompt(output, command) is expected
```

- [ ] **Step 2: 実行して緑を確認する**

Run: `uv run pytest tests/test_tmux_workspace_cursor_trust.py -v`
Expected: 全 PASS。`_command_may_launch_cursor_agent` の正規表現・`_confirm_cursor_workspace_trust` のリトライ挙動・トークン重複率 0.4 判定が実装と食い違う場合は実装を読んで期待値（parametrize の値）を実態へ修正する。

- [ ] **Step 3: lint とコミット**

```bash
uv tool run ruff check tests/test_tmux_workspace_cursor_trust.py
git add tests/test_tmux_workspace_cursor_trust.py
git commit -m "$(cat <<'EOF'
test(tmux): Cursor 信頼検知の純関数と Codex トークン分岐を検証

- _command_may_launch_cursor_agent/_is_cursor_workspace_trust_prompt の判定
- _confirm_cursor_workspace_trust の承認ループ（早期 true/承認/失敗）
- _is_pending_codex_prompt のトークン重複緩和分岐（既存テスト未カバー）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: フェーズ完了の最終検証

**Files:** なし（検証のみ）

- [ ] **Step 1: 全テスト + lint を実行する**

Run:
```bash
uv run pytest -q 2>&1 | tail -5
uv tool run ruff check src/
```
Expected: 全 PASS（ベースライン 1123 + 新規 tmux テスト分、削除分を差し引いた件数）、`src/` ruff クリーン。

- [ ] **Step 2: 逆依存が ensure_* のみであることを最終確認する**

Run:
```bash
grep -rn "from src.tools\|import src.tools" src/managers/
```
Expected: ヒットは `helpers_managers`（ensure_*）の遅延 import のみ。

- [ ] **Step 3: tmux 層カバレッジを確認する**

Run:
```bash
uv run pytest --cov=src/managers/tmux_manager --cov=src/managers/tmux_workspace_mixin --cov-report=term-missing -q 2>&1 | grep -E "tmux_manager|tmux_workspace_mixin|TOTAL"
```
Expected: `tmux_manager.py` / `tmux_workspace_mixin.py` のカバレッジがベースライン（49% / 46%）から有意に上昇（70% 前後を目安、未達なら未カバー行を見て Task 10-13 にテストを追補）。

- [ ] **Step 4: PR 作成（ユーザーが明示選択した場合のみ）**

ユーザーの明示依頼があれば push + PR 作成:
```bash
git push -u origin feature/audit-phase3
```
PR タイトル/本文は日本語。変更概要（§6.1 デッドコード除去 / §6.2 逆依存解消 / §6.3 tmux テスト拡充）とテストプラン（`uv run pytest` 全緑・`ruff check src/` クリーン・tmux カバレッジ向上）を含める。

---

## 自己レビュー結果

- **スペック網羅:** §6.1（Task 1-3: open_worktree/open_worktree_in_terminal/_run_shell 削除＋テスト整理）、§6.2（Task 4-9: trio 移動・3 managers repoint・send 抽出・ensure_* 据置明記）、§6.3（Task 10-13: tmux コマンド検証・send 分岐・純関数）を全てカバー。設計書 §6 の3項目に対応するタスクあり。
- **プレースホルダ:** なし（各テストは実コードを提示。引数不一致時は「実装を読んで実態に合わせる」明示手順を併記）。
- **型/命名一貫性:** 新 managers モジュール名（`git_utils.py` / `project_registry.py` / `agent_persistence.py` / `dispatch_rate_limit.py`）と再エクスポート対象 symbol は Task 4-8 で一貫。`find_agents_by_role` は Task 6 で agent_persistence へ移動し Task 7 で daemon が参照する流れで整合。
- **既知の注意:** trio 移動の各ステップでシムにより後方互換を保つため、Task 4→5→6 の順序が前提（registry は git に、persistence は git+registry に依存）。文字列パス patch の更新（Task 6 Step 4 / Task 8 Step 4）を飛ばすとテストが落ちるため必須。
