# Phase 2: 正確性リファクタ 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 永続化/同期層の重複・無効化漏れ・過剰I/O・レイヤー違反を、挙動を保ったまま解消する。

**Architecture:** 設計ドキュメント `docs/superpowers/specs/2026-06-16-project-audit-improvements-design.md` の Phase 2。共通化したユーティリティは `src/managers/` 配下（tools に依存しない下位層）へ置き、tools→managers の正方向依存に揃える。各タスク独立コミット、TDD/特性テストで挙動不変を担保。

**Tech Stack:** Python 3.10+, pytest + pytest-asyncio, ruff, uv。

**前提:** ブランチ `feature/audit-phase2`（main の最新=Phase 1 マージ済みから作成）。各タスク完了時に `uv run pytest` 全グリーン、`uv tool run ruff check src/` クリーンを維持。`--no-verify` 禁止。型ヒント必須・`str | None` 記法・日本語docstring・行長100。

**タスク順序（独立・低リスク → 複雑・高リスク）:**
1. atomic_io 共通化（基盤）
2. private 呼び出し是正（独立・局所）
3. IPC同期キャッシュ mtime 検証（独立・局所）
4. worker_resolution 統合（複雑・逆依存解消）
5. Dashboard トランザクション集約（複雑）

---

## Task 1: atomic_write ユーティリティの共通化

6箇所にコピペされた atomic-write パターンを `src/managers/atomic_io.py` に集約する。挙動は各呼び出し元で完全保持する。

**現状の6箇所（調査済み）:**
- `src/tools/helpers_persistence.py` `_atomic_write_json`（JSON, chmod+fsync, `default=str`）
- `src/tools/session_state.py`（インライン, **chmod なし/fsync なし**, JSON）
- `src/tools/helpers_registry.py`（インライン, chmod+fsync, JSON, flock ブロック内）
- `src/managers/ipc_manager.py` `_atomic_write`（テキスト, chmod+fsync）
- `src/managers/memory_manager.py` `_atomic_write_private_file`（staticmethod, テキスト, chmod+fsync）
- `src/managers/dashboard_writer_mixin.py` `_atomic_write_text`（テキスト, chmod+fsync）

**Files:**
- Create: `src/managers/atomic_io.py`
- Create: `tests/test_atomic_io.py`
- Modify: 上記6ファイル

- [ ] **Step 1: PRIVATE_FILE_MODE の定義場所を確認**

Run: `grep -rn "PRIVATE_FILE_MODE" src/config/ src/managers/ src/tools/ | head`
Expected: `src/config/constants.py` 等に定義（`0o600`）。atomic_io.py はそこから import する。import 元を以降のコードに反映すること。

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_atomic_io.py` を新規作成:

```python
"""atomic_io のテスト。"""

import json
import os
import stat

from src.managers.atomic_io import atomic_write_json, atomic_write_text


def test_atomic_write_text_writes_content(tmp_path):
    target = tmp_path / "sub" / "a.txt"
    atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    # mkdir=True で親ディレクトリが作られる
    assert target.parent.is_dir()


def test_atomic_write_text_sets_private_mode_by_default(tmp_path):
    target = tmp_path / "a.txt"
    atomic_write_text(target, "x")
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


def test_atomic_write_text_skips_chmod_when_mode_none(tmp_path):
    target = tmp_path / "a.txt"
    atomic_write_text(target, "x", mode=None)
    # mode=None のとき chmod しない（OS デフォルト権限のまま）
    assert target.read_text(encoding="utf-8") == "x"


def test_atomic_write_text_no_temp_left_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "a.txt"

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr("src.managers.atomic_io.os.replace", boom)
    try:
        atomic_write_text(target, "x")
    except RuntimeError:
        pass
    # temp ファイル(.tmp)が残っていない
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_json_roundtrip(tmp_path):
    target = tmp_path / "a.json"
    atomic_write_json(target, {"k": "v", "n": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": "v", "n": 1}


def test_atomic_write_json_uses_default_str_for_nonserializable(tmp_path):
    from datetime import datetime

    target = tmp_path / "a.json"
    atomic_write_json(target, {"t": datetime(2026, 1, 1)})
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert "2026" in loaded["t"]
```

- [ ] **Step 3: 失敗確認**

Run: `uv run pytest tests/test_atomic_io.py -v`
Expected: FAIL（モジュール未作成で ImportError）

- [ ] **Step 4: atomic_io.py を実装**

`src/managers/atomic_io.py` を作成（PRIVATE_FILE_MODE の import 元は Step 1 の結果に合わせる）:

```python
"""ファイルへのアトミック書き込みユーティリティ。

mkstemp → fsync → chmod → os.replace の順で、書き込み途中の破損やレース時の
中途半端な内容を避ける。tools/managers の双方から利用される下位ユーティリティのため、
標準ライブラリのみに依存し他層を import しない。
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from src.config.constants import PRIVATE_FILE_MODE


def atomic_write_text(
    file_path: Path,
    content: str,
    *,
    mode: int | None = PRIVATE_FILE_MODE,
    fsync: bool = True,
    mkdir: bool = True,
) -> None:
    """テキストをアトミックに書き込む。

    Args:
        file_path: 書き込み先パス
        content: 書き込む文字列
        mode: 設定する権限（None の場合は chmod を行わない）
        fsync: True の場合 fsync でディスク同期する
        mkdir: True の場合、親ディレクトリを作成する
    """
    if mkdir:
        file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(file_path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            if fsync:
                f.flush()
                os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp_path, mode)
        os.replace(tmp_path, str(file_path))
        if mode is not None:
            os.chmod(file_path, mode)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(
    file_path: Path,
    payload: Any,
    *,
    ensure_ascii: bool = False,
    indent: int = 2,
    default: Any = str,
    mode: int | None = PRIVATE_FILE_MODE,
    fsync: bool = True,
    mkdir: bool = True,
) -> None:
    """JSON をアトミックに書き込む（atomic_write_text の薄いラッパー）。"""
    content = json.dumps(payload, ensure_ascii=ensure_ascii, indent=indent, default=default)
    atomic_write_text(file_path, content, mode=mode, fsync=fsync, mkdir=mkdir)
```

- [ ] **Step 5: テスト成功確認**

Run: `uv run pytest tests/test_atomic_io.py -v`
Expected: 全 PASS

- [ ] **Step 6: 6箇所を共通関数へ置換（挙動完全保持）**

各ファイルの atomic-write 実装本体を削除し、`from src.managers.atomic_io import atomic_write_text, atomic_write_json` を import して置換する。挙動を変えないため以下の対応表に厳密に従う:

| ファイル | 置換 |
|---|---|
| `helpers_persistence.py` `_atomic_write_json` | 本体を `atomic_write_json(file_path, payload)` の1行に（`default=str` はデフォルト一致）。関数名・シグネチャは互換のため残し中身だけ委譲。 |
| `session_state.py`（インライン） | `atomic_write_json(config_file, config, mode=None, fsync=False)`（chmod/fsync 無しを保持） |
| `helpers_registry.py`（flock 内インライン） | flock ブロック内で `atomic_write_json(agent_file, data)` を呼ぶ（flock 取得・解放は現状のまま外に残す） |
| `ipc_manager.py` `_atomic_write` | 本体を `atomic_write_text(file_path, content)` に委譲（メソッド名は互換維持） |
| `memory_manager.py` `_atomic_write_private_file` | 本体を `atomic_write_text(file_path, content)` に委譲（staticmethod のまま） |
| `dashboard_writer_mixin.py` `_atomic_write_text` | 本体を `atomic_write_text(file_path, content)` に委譲（メソッド名は互換維持） |

注:
- 各ファイルで不要になった `tempfile`/`os`（他で使っていなければ）の import を整理。ただし他用途で使っていれば残す（ruff で確認）。
- 既存の関数名/メソッド名は呼び出し元互換のため変更しない（中身だけ委譲）。
- `session_state.py` は意図的に `mode=None, fsync=False`（現状維持）であることをコメントで明示。

- [ ] **Step 7: 回帰確認（永続化・IPC・メモリ・ダッシュボード・セッション）**

Run: `uv run pytest tests/test_helpers_persistence.py tests/test_session_state.py tests/test_ipc_manager.py tests/test_memory_manager.py tests/test_dashboard_manager.py -q`
Expected: 全 PASS

- [ ] **Step 8: 全体テスト + lint**

Run: `uv run pytest -q && uv tool run ruff check src/`
Expected: 全 PASS / `All checks passed!`

- [ ] **Step 9: コミット**

```bash
git add src/managers/atomic_io.py tests/test_atomic_io.py src/tools/helpers_persistence.py src/tools/session_state.py src/tools/helpers_registry.py src/managers/ipc_manager.py src/managers/memory_manager.py src/managers/dashboard_writer_mixin.py
git commit -m "$(cat <<'EOF'
refactor(io): atomic書き込みをsrc/managers/atomic_io.pyへ共通化

- 6箇所のmkstemp→fsync→chmod→os.replaceパターンをatomic_write_text/jsonへ集約
- 各呼び出し元は挙動を完全保持(session_stateはmode=None/fsync=Falseで現状維持)
- tools→managersの正方向依存で配置

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: TmuxManager private 呼び出しの是正

`terminate_agent` が `tmux._get_window_name(...)` と `tmux._run("send-keys", ...)` という private を直接呼んでいる。
公開メソッド `send_interrupt_to_pane` を追加して置換する。

**Files:**
- Modify: `src/managers/tmux_workspace_mixin.py`（`send_interrupt_to_pane` 追加）
- Modify: `src/tools/agent_lifecycle_tools.py`（310-323行付近）
- Modify: `tests/conftest.py`、`tests/tools/test_agent_tools.py`（mock 更新）
- Test: `tests/test_tmux_workspace_services.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tmux_workspace_services.py` に追加（`_pane_target` を用いて C-c を送る公開メソッドの検証。`_run` をモックして引数を確認）:

```python
import pytest
from unittest.mock import AsyncMock

from src.config.settings import Settings
from src.managers.tmux_manager import TmuxManager


@pytest.mark.asyncio
async def test_send_interrupt_to_pane_sends_ctrl_c():
    """send_interrupt_to_pane が対象ペインに C-c を送ること。"""
    mgr = TmuxManager(Settings())
    mgr._run = AsyncMock(return_value=(0, "", ""))

    ok = await mgr.send_interrupt_to_pane("sess", 0, 1)

    assert ok is True
    # _run が send-keys -t <target> C-c で呼ばれている
    args = mgr._run.await_args.args
    assert args[0] == "send-keys"
    assert "-t" in args
    assert args[-1] == "C-c"
```

注: `TmuxManager(Settings())` の構築シグネチャは既存テスト（test_tmux_manager_subprocess.py 等）の構築方法に合わせること。引数が異なる場合はそれに従う。

- [ ] **Step 2: 失敗確認**

Run: `uv run pytest tests/test_tmux_workspace_services.py::test_send_interrupt_to_pane_sends_ctrl_c -v`
Expected: FAIL（`send_interrupt_to_pane` 未定義）

- [ ] **Step 3: 公開メソッドを追加**

`src/managers/tmux_workspace_mixin.py` に追加（`_pane_target` static と `_run`、`logger` は既存）:

```python
async def send_interrupt_to_pane(self, session: str, window: int, pane: int) -> bool:
    """指定ペインに C-c を送信してプロセスを中断する。

    Args:
        session: tmux セッション名
        window: ウィンドウインデックス
        pane: ペインインデックス

    Returns:
        送信に成功したかどうか
    """
    target = self._pane_target(session, window, pane)
    code, _, stderr = await self._run("send-keys", "-t", target, "C-c")
    if code != 0:
        logger.error(f"C-c 送信エラー: {stderr}")
        return False
    return True
```

注: `_pane_target` の存在とシグネチャ（`(session, window, pane) -> str`）を実コードで確認すること。無ければ既存の target 生成方法に合わせる。

- [ ] **Step 4: terminate_agent の private 呼び出しを置換**

`src/tools/agent_lifecycle_tools.py` の 321-323行付近を置換:

```python
# Before
window_name = tmux._get_window_name(agent.window_index)
target = f"{session_name}:{window_name}.{agent.pane_index}"
await tmux._run("send-keys", "-t", target, "C-c")

# After
await tmux.send_interrupt_to_pane(
    agent.session_name, agent.window_index, agent.pane_index
)
```

注: 直前の `send_keys_to_pane(..., "", literal=False)` 行は**変更しない**（挙動差を避けるためスコープ外）。不要になった `session_name` ローカル変数が他で使われていなければ削除（使われていれば残す）。

- [ ] **Step 5: テストの mock を更新**

`terminate_agent` 系テストが `mock_tmux._get_window_name` / `mock_tmux._run` に依存している箇所を `send_interrupt_to_pane` に更新:
- `tests/conftest.py`（108-110行付近）: `mock_tmux.send_interrupt_to_pane = AsyncMock(return_value=True)` を追加（既存の `_get_window_name`/`_run` mock は他テストが使うため削除しない）。
- `tests/tools/test_agent_tools.py`: `TestTerminateAgent` が send-keys 呼び出しを検証している場合、`send_interrupt_to_pane` の呼び出し検証へ更新。

注: まず `uv run pytest tests/tools/test_agent_tools.py -q` を実行して失敗箇所を特定し、最小限の mock 更新を行う。

- [ ] **Step 6: テスト成功確認**

Run: `uv run pytest tests/test_tmux_workspace_services.py tests/tools/test_agent_tools.py -q`
Expected: 全 PASS

- [ ] **Step 7: terminate を使う他テストの回帰確認**

Run: `uv run pytest tests/test_healthcheck_manager.py tests/test_integration.py -q`
Expected: 全 PASS（失敗時は private 依存の mock を最小修正）

- [ ] **Step 8: 全体 + lint**

Run: `uv run pytest -q && uv tool run ruff check src/`
Expected: 全 PASS / クリーン

- [ ] **Step 9: コミット**

```bash
git add src/managers/tmux_workspace_mixin.py src/tools/agent_lifecycle_tools.py tests/conftest.py tests/tools/test_agent_tools.py tests/test_tmux_workspace_services.py
git commit -m "$(cat <<'EOF'
refactor(tmux): terminate_agentのprivate呼び出しを公開API化

- TmuxManagerにsend_interrupt_to_pane公開メソッドを追加
- agent_lifecycle_toolsの_get_window_name/_run直接呼び出しを置換
- tools層がマネージャのprivateを跨ぐ規約違反を解消

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: IPC同期キャッシュに mtime 検証を追加

`_ipc_sync_cache_*` は mtime 無効化が無く、別プロセスが `ipc_sync_state.json` を更新しても古い状態を返す。
read_cache（`dashboard_reader_mixin.py`）の mtime 検証パターンを移植する。

**Files:**
- Modify: `src/managers/dashboard_manager.py`（キャッシュ属性初期化 58-60行付近）
- Modify: `src/managers/dashboard_sync_mixin.py`（`_load_ipc_sync_state` / `_set_ipc_sync_cache` / `_clear_ipc_sync_cache`）
- Test: `tests/test_dashboard_manager.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_dashboard_manager.py` に追加（既存の dashboard manager fixture/構築に合わせる。`ipc_sync_state.json` の mtime を巻き戻して別プロセス更新を模擬）:

```python
def test_ipc_sync_cache_invalidated_when_state_file_mtime_changes(
    dashboard_manager_factory,  # 既存の構築ヘルパに合わせて調整
):
    """別プロセスが ipc_sync_state.json を更新したらキャッシュが無効化されること。"""
    # 1. 初回 _set_ipc_sync_cache 相当でキャッシュを温める
    # 2. ipc_sync_state.json の mtime を未来に進める（os.utime）
    # 3. _load_ipc_sync_state がキャッシュヒットせず再読込すること（cache_hit フラグ False）を検証
    ...
```

注: 既存テスト `test_save_markdown_dashboard_ipc_sync_*`（591-778行付近）の構築・検証スタイルに厳密に合わせて具体化すること。`_load_ipc_sync_state` の戻り値タプルの3要素目（cache_hit bool）を利用する。`os.utime(state_path, ...)` で mtime を変更する。

- [ ] **Step 2: 失敗確認**

Run: `uv run pytest tests/test_dashboard_manager.py -k ipc_sync_cache_invalidated -v`
Expected: FAIL（現状は mtime 変化を無視してキャッシュヒットする）

- [ ] **Step 3: キャッシュ mtime 属性を追加**

`src/managers/dashboard_manager.py` の `_ipc_sync_cache_*` 初期化（58-60行付近）に追加:

```python
self._ipc_sync_cache_mtime: int = 0
```

- [ ] **Step 4: `_set_ipc_sync_cache` で mtime を記録**

`src/managers/dashboard_sync_mixin.py` の `_set_ipc_sync_cache`（79-88行付近）末尾に追加:

```python
        state_path = self._get_ipc_sync_state_path()
        try:
            self._ipc_sync_cache_mtime = state_path.stat().st_mtime_ns
        except OSError:
            self._ipc_sync_cache_mtime = 0
```

- [ ] **Step 5: `_load_ipc_sync_state` のヒット判定に mtime 検証を追加**

キャッシュヒット条件（96-114行付近）に state ファイル mtime の一致確認を追加（read_cache と同じく、ファイル不存在 `0` のときはヒットさせない）:

```python
        state_path = self._get_ipc_sync_state_path()
        try:
            current_mtime_ns = state_path.stat().st_mtime_ns
        except OSError:
            current_mtime_ns = 0

        if (
            cached_ipc_dir == resolved_ipc_dir
            and isinstance(cached_messages, list)
            and isinstance(cached_cursors, dict)
            and current_mtime_ns != 0
            and current_mtime_ns == self._ipc_sync_cache_mtime
        ):
            return (
                [msg.model_copy(deep=True) for msg in cached_messages],
                dict(cached_cursors),
                True,
            )
```

注: 既存のヒット判定の条件・戻り値構造に厳密に合わせて差分を当てること（上記は調査結果に基づく形。実コードの変数名・戻り値タプルに合わせる）。

- [ ] **Step 6: `_clear_ipc_sync_cache` で mtime をリセット**

`_clear_ipc_sync_cache` に `self._ipc_sync_cache_mtime = 0` を追加。

- [ ] **Step 7: テスト成功確認 + 既存 IPC 同期テスト回帰**

Run: `uv run pytest tests/test_dashboard_manager.py -q`
Expected: 新規含め全 PASS（特に `test_save_markdown_dashboard_ipc_sync_uses_delta_after_initial_snapshot` 等の差分同期テストが引き続き通ること＝同一プロセス書き込み直後はヒット維持）

- [ ] **Step 8: 全体 + lint**

Run: `uv run pytest -q && uv tool run ruff check src/`
Expected: 全 PASS / クリーン

- [ ] **Step 9: コミット**

```bash
git add src/managers/dashboard_manager.py src/managers/dashboard_sync_mixin.py tests/test_dashboard_manager.py
git commit -m "$(cat <<'EOF'
fix(dashboard): IPC同期キャッシュにmtime検証を追加

- 別プロセスのipc_sync_state.json更新時に古い同期状態を返す問題を解消
- read_cacheと同じmtimeベース無効化を移植(同一プロセス書込直後はヒット維持)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: worker 解決ロジックの統合（逆依存解消）

`healthcheck_manager`（managers）と `agent_helpers`（tools）に重複する worker 解決ロジックを
`src/managers/worker_resolution.py` に統合。両者がそこを import する（healthcheck=intra-layer、agent_helpers=tools→managers の正方向）ことで managers→tools の逆依存も解消する。

**挙動差の統一方針（調査済み・重要）:**
- 引数順: `resolve_agent_cli_name(agent, app_ctx)` に統一（agent_helpers 側に合わせる）。
- Role 比較: `agent.role == AgentRole.WORKER or agent.role == AgentRole.WORKER.value`（Enum/文字列の双方を許容＝JSON 復元時の文字列 role も WORKER 判定。healthcheck 版の防御性を維持）。
- 例外型: `except (ValueError, TypeError)` に統一（狭い型。`get_worker_cli` は ValueError のみ送出のため実害なし）。
- None ガード: `resolve_worker_model_for_cli` は `window_index/pane_index` が None なら None を返す（healthcheck 版を採用）。**agent_helpers 側の呼び出し元が None 戻りを扱えるか確認必須**。

**Files:**
- Create: `src/managers/worker_resolution.py`
- Create: `tests/test_worker_resolution.py`
- Modify: `src/tools/agent_helpers.py`（重複関数を委譲 + 後方互換 re-export）
- Modify: `src/managers/healthcheck_manager.py`（4 staticmethod を共通関数呼び出しに置換）

- [ ] **Step 1: 既存挙動の特性テストを先に作る（リファクタの安全網）**

統合前に、現状の agent_helpers 版・healthcheck 版それぞれの挙動を固定する特性テストを `tests/test_worker_resolution.py` に作成する。最低限:

```python
"""worker_resolution 統合の特性/単体テスト。"""

from unittest.mock import MagicMock

import pytest


# --- resolve_worker_number_from_slot ---
def test_resolve_worker_number_window0_returns_pane():
    from src.managers.worker_resolution import resolve_worker_number_from_slot

    settings = MagicMock()
    settings.workers_per_extra_window = 10
    assert resolve_worker_number_from_slot(settings, 0, 3) == 3


def test_resolve_worker_number_extra_window():
    from src.managers.worker_resolution import resolve_worker_number_from_slot

    settings = MagicMock()
    settings.workers_per_extra_window = 10
    # window 1, pane 0 → 6 + 0*10 + 0 + 1 = 7
    assert resolve_worker_number_from_slot(settings, 1, 0) == 7


def test_resolve_worker_model_returns_none_when_slot_missing():
    from src.managers.worker_resolution import resolve_worker_model_for_cli

    app_ctx = MagicMock()
    agent = MagicMock()
    agent.window_index = None
    agent.pane_index = None
    assert resolve_worker_model_for_cli(app_ctx, agent, {"worker_model": "x"}) is None
```

注: 既存の `tests/test_agent_helpers.py:276-287`（`resolve_worker_number_from_slot`）と `:83-218`（`_resolve_agent_cli_name`）の検証シナリオを参考に、`resolve_agent_cli_name` の WORKER/非WORKER・ai_cli_pinned・role が文字列/Enum 双方のケースを網羅する。実際の `resolve_worker_number_from_slot` の計算式は既存実装（`window0→pane` / `extra→6+(w-1)*per+pane+1`）を実コードで確認して合わせる。

- [ ] **Step 2: 失敗確認**

Run: `uv run pytest tests/test_worker_resolution.py -v`
Expected: FAIL（モジュール未作成）

- [ ] **Step 3: worker_resolution.py を実装**

`src/managers/worker_resolution.py` を作成。実装は調査で得た統一版を用いる（`normalize_cli_name`/`resolve_model_for_cli` は `src/config/settings.py` から import 可能なことを確認）:

```python
"""Worker の CLI/モデル/番号解決ロジック（managers/tools 共通）。

healthcheck_manager と agent_helpers に重複していた解決ロジックを集約。
managers 配下に置くことで tools→managers の正方向依存に揃える。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.config.settings import normalize_cli_name, resolve_model_for_cli

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.context import AppContext
    from src.models.agent import Agent


def resolve_worker_number_from_slot(
    settings: Settings | Any,
    window_index: int,
    pane_index: int,
) -> int:
    """tmux スロット(window,pane)から Worker 番号(1..N)を計算する。"""
    if window_index == 0:
        return pane_index
    workers_per_extra = int(getattr(settings, "workers_per_extra_window", 10))
    return 6 + ((window_index - 1) * workers_per_extra) + pane_index + 1


def resolve_agent_cli_name(agent: Agent, app_ctx: AppContext) -> str:
    """Agent の実行 CLI 名を解決する。"""
    from src.models.agent import AgentRole

    is_worker = agent.role == AgentRole.WORKER or agent.role == AgentRole.WORKER.value
    if is_worker:
        if getattr(agent, "ai_cli_pinned", False) and agent.ai_cli:
            return normalize_cli_name(agent.ai_cli)
        if agent.window_index is not None and agent.pane_index is not None:
            try:
                worker_no = resolve_worker_number_from_slot(
                    app_ctx.settings, agent.window_index, agent.pane_index
                )
                return app_ctx.settings.get_worker_cli(worker_no).value
            except (ValueError, TypeError):
                pass
    if agent.ai_cli:
        return normalize_cli_name(agent.ai_cli)
    return normalize_cli_name(app_ctx.ai_cli.get_default_cli())


def resolve_worker_model_for_cli(
    app_ctx: AppContext,
    agent: Agent,
    profile_settings: dict[str, Any],
    agent_cli_name: str | None = None,
) -> str | None:
    """Worker の実行 CLI に整合するモデル名を解決する。スロット未確定なら None。"""
    if agent.window_index is None or agent.pane_index is None:
        return None
    cli_name = (agent_cli_name or resolve_agent_cli_name(agent, app_ctx)).lower()
    worker_no = resolve_worker_number_from_slot(
        app_ctx.settings, agent.window_index, agent.pane_index
    )
    profile_worker_model = str(profile_settings.get("worker_model", "") or "")
    configured_model = app_ctx.settings.get_worker_model(worker_no, profile_worker_model)
    return resolve_model_for_cli(
        cli_name,
        configured_model,
        role="worker",
        cli_defaults=app_ctx.settings.get_cli_default_models(),
    )
```

重要: 上記は調査ベースの統一版。実装前に **既存 agent_helpers 版と healthcheck 版の本体を再読**し、各分岐（ai_cli_pinned の有無、get_default_cli の呼び方、resolve_model_for_cli の引数）が実コードと一致するか確認して厳密に合わせること。差異があれば実コード優先。

- [ ] **Step 4: agent_helpers を委譲 + 後方互換 re-export**

`src/tools/agent_helpers.py`:
- `resolve_worker_number_from_slot` / `_resolve_agent_cli_name` / `_resolve_worker_model_for_cli` の本体を削除し、`src.managers.worker_resolution` から import して委譲。
- 既存呼び出し元（`cost_capture.py`/`command.py`/`agent_lifecycle_tools.py`/`agent_batch_tools.py` が `from src.tools.agent_helpers import resolve_worker_number_from_slot` 等）の互換のため、import した名前をモジュールレベルに re-export（`resolve_worker_number_from_slot = ...`、`_resolve_agent_cli_name` は引数順が変わるため後述）。
- **引数順の差異**: 旧 `_resolve_agent_cli_name(agent, app_ctx)` と新 `resolve_agent_cli_name(agent, app_ctx)` は同順なので、`_resolve_agent_cli_name = resolve_agent_cli_name` で alias 可能。`_resolve_worker_model_for_cli(app_ctx, agent, profile_settings, agent_cli_name=None)` も新版と同順のため alias 可能。

`agent_helpers.py` の該当呼び出し元（`:271,272,745,746,801,985,986`）が alias 経由で動くことを確認。

- [ ] **Step 5: healthcheck_manager を共通関数へ置換**

`src/managers/healthcheck_manager.py`:
- `_resolve_worker_number_from_slot` / `_resolve_agent_cli_name` / `_resolve_worker_model_for_cli` の3 staticmethod を削除。
- `from src.managers.worker_resolution import (resolve_worker_number_from_slot, resolve_agent_cli_name, resolve_worker_model_for_cli)` を import。
- 呼び出し元（`:1190,1193,1289,1309,1314`）を共通関数呼び出しに置換。**引数順に注意**（healthcheck 旧版は `_resolve_agent_cli_name(app_ctx, agent)` だったので、新 `resolve_agent_cli_name(agent, app_ctx)` へ引数順を入れ替える）。
- `_get_current_profile_settings` は `from src.tools.model_profile import get_current_profile_settings` で代替できるか確認。**ただし** これは managers→tools の遅延 import を増やすため、worker 3キーのみ返す現状の `_get_current_profile_settings` は healthcheck 内に残してもよい（逆依存の主対象は worker 解決3関数）。判断: `_get_current_profile_settings` と `_resolve_worker_dispatch_params` は **今回は移動せず据え置く**（スコープを worker 解決3関数の重複解消に限定し、リスクを抑える）。

- [ ] **Step 6: 失敗系/回帰テスト**

Run: `uv run pytest tests/test_worker_resolution.py tests/test_agent_helpers.py tests/test_healthcheck_manager.py tests/test_agent_batch_tools.py tests/tools/test_command_tools.py tests/test_cost_capture.py -q`
Expected: 全 PASS。失敗時は引数順・alias・role 比較を実コードと突き合わせて修正。

- [ ] **Step 7: None 戻り変更の影響確認**

`agent_helpers.py:745,986` 付近（`_resolve_worker_model_for_cli` の呼び出し元）で、None ガード追加により None が返るケースの後続処理が破綻しないか実コードで確認。旧 agent_helpers 版は None ガードが無かったため、slot 未確定時の挙動が変わる。問題があれば呼び出し元で None ハンドリングを追加（最小限）。

- [ ] **Step 8: 全体 + lint**

Run: `uv run pytest -q && uv tool run ruff check src/`
Expected: 全 PASS / クリーン

- [ ] **Step 9: コミット**

```bash
git add src/managers/worker_resolution.py tests/test_worker_resolution.py src/tools/agent_helpers.py src/managers/healthcheck_manager.py
git commit -m "$(cat <<'EOF'
refactor(core): worker解決ロジックをworker_resolutionへ統合

- healthcheck_managerとagent_helpersの重複(例外処理ドリフト)を解消
- 例外型を(ValueError,TypeError)に統一、role比較はEnum/文字列双方を許容、Noneガード採用
- src/managers配下に集約しmanagers→toolsの逆依存を解消(agent_helpersは後方互換re-export)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Dashboard `apply_task_messages` のトランザクション集約

N件の task message で `update_task_status`＋`update_task_checklist` を各々独立トランザクション化し、最後に
`save_markdown_dashboard` でも全読み書きするため最悪 2N+1 回。1トランザクションに集約する。

**Files:**
- Modify: `src/managers/dashboard_manager.py`（`apply_task_messages` 238-376行付近、および status/checklist 適用の純粋メソッド抽出）
- Modify: `src/managers/dashboard_tasks_mixin.py`（必要なら mutator の Dashboard 直接適用版を抽出）
- Test: `tests/test_dashboard_manager.py`

- [ ] **Step 1: 既存挙動の特性テスト + 書き込み回数テスト**

`tests/test_dashboard_manager.py` に追加:
- (a) 複数 task message（status 変更 + checklist）を適用した後の Dashboard 状態が、集約前と同じになることを検証する特性テスト。
- (b) `run_dashboard_transaction`（または `_write_dashboard_unlocked`）を `unittest.mock` でラップし、N件適用時の呼び出し回数が削減される（集約後は status/checklist 適用が1トランザクション）ことを検証。
- (c) 1件が `task_not_found` のとき、そのメッセージが defer され他が適用される（部分失敗の挙動維持）ことを検証。

```python
def test_apply_task_messages_uses_single_transaction(dashboard_manager_factory):
    """複数メッセージ適用が status/checklist について1トランザクションに集約されること。"""
    # _write_dashboard_unlocked を spy し、apply_task_messages 呼び出しで
    # 書き込み回数が (旧: 2N+1) から削減されることを assert
    ...

def test_apply_task_messages_defers_unknown_task(dashboard_manager_factory):
    """存在しない task_id のメッセージは defer され、他は適用されること。"""
    ...
```

注: 既存の dashboard manager 構築・Message 構築（`tests/tools/test_ipc_tools.py` や `test_dashboard_manager.py` のパターン）に合わせて具体化。`apply_task_messages` 専用テストは現状0件のため、まず現行実装に対して (a)(c) が通る状態を作り（特性テスト）、その後 (b) を集約実装で満たす。

- [ ] **Step 2: 失敗確認（集約前は (b) が失敗）**

Run: `uv run pytest tests/test_dashboard_manager.py -k apply_task_messages -v`
Expected: (a)(c) PASS、(b) FAIL（集約前は書き込み回数が多い）

- [ ] **Step 3: status/checklist の Dashboard 直接適用メソッドを抽出**

`update_task_status` / `update_task_checklist` が内部で `run_dashboard_transaction(_update)` に渡しているクロージャ本体を、
`Dashboard` を引数に取る純粋メソッド `_apply_status_to_dashboard(dashboard, task_id, ...)` /
`_apply_checklist_to_dashboard(dashboard, task_id, ...)` として抽出する（既存の `_resolve_task`/`_validate_task_transition`/
`_release_agent_from_task` は Dashboard 引数を取る純粋メソッドなので転用）。`update_task_status`/`update_task_checklist` は
その純粋メソッドを `run_dashboard_transaction` 経由で呼ぶ薄いラッパーに変更（公開シグネチャ・挙動は不変）。

- [ ] **Step 4: `apply_task_messages` を1トランザクション化**

`apply_task_messages` の status/checklist 適用ループを、1つの `run_dashboard_transaction(_apply_all)` 内に収める。
`_apply_all(dashboard)` 内で task_map を `dashboard.tasks` から構築し、各メッセージを `_apply_status_to_dashboard`/
`_apply_checklist_to_dashboard` で適用。**部分失敗の挙動を維持**するため、各メッセージ処理を try/except で囲み、失敗は
`skipped_reasons`/`deferred_message_ids` に積んで継続（例外で全ロールバックさせない）。戻り値タプル
`(updated, applied, skipped_reasons, ack_message_ids, deferred_message_ids)` の契約を維持。
`save_markdown_dashboard` は **別トランザクションのまま末尾で1回**呼ぶ（IPC/agents 同期を含むため合流させない）。

注: 集約後は最悪 `1(apply) + 1(save) = 2` 回のトランザクションになる（旧 2N+1）。`get_task` のロック外読みは `_apply_all` 内の `dashboard` 直接参照に置換して不要化。

- [ ] **Step 5: テスト成功確認**

Run: `uv run pytest tests/test_dashboard_manager.py -q`
Expected: (a)(b)(c) 含め全 PASS

- [ ] **Step 6: IPC ツール経由の回帰**

Run: `uv run pytest tests/tools/test_ipc_tools.py -q`
Expected: 全 PASS（`read_messages` → `apply_task_messages` 経路の契約維持）

- [ ] **Step 7: 全体 + lint**

Run: `uv run pytest -q && uv tool run ruff check src/`
Expected: 全 PASS / クリーン

- [ ] **Step 8: コミット**

```bash
git add src/managers/dashboard_manager.py src/managers/dashboard_tasks_mixin.py tests/test_dashboard_manager.py
git commit -m "$(cat <<'EOF'
perf(dashboard): apply_task_messagesを単一トランザクションに集約

- N件のtask messageで2N+1回だったロック/読み/書きを最小化
- status/checklist適用をDashboard直接適用メソッドに抽出し1トランザクション内で適用
- 部分失敗のdefer挙動・戻り値契約は維持、save_markdown_dashboardは別途1回

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 完了確認

- [ ] **全テストグリーン** — Run: `uv run pytest -q` → 全 PASS（Phase 1 の 1096 + Phase 2 追加分、失敗0）
- [ ] **lint クリーン** — Run: `uv tool run ruff check src/` → `All checks passed!`
- [ ] **逆依存の確認** — Run: `grep -rn "from src.tools" src/managers/ | grep -i "agent_helpers\|worker"` で worker 解決に関する managers→tools 逆 import が解消されていることを確認（helpers_persistence/helpers_managers の逆 import は Phase 3 対象のため残ってよい）。
- [ ] **コミット列確認** — Run: `git log --oneline main..HEAD` → Task1〜5 の5コミットが並ぶ

---

## Self-Review 結果

- **Spec coverage:** Phase 2 の5項目（5.1 atomic_io / 5.2 worker_resolution / 5.3 sync cache mtime / 5.4 dashboard transaction / 5.5 private 是正）すべてにタスクあり。
- **Placeholder scan:** Task 3/4/5 のテストは「既存構築スタイルに合わせて具体化」と記載＝実装時に既存 fixture へ依存する部分が残る。これは既存テストの構築ヘルパに厳密依存するため意図的（実装者が既存パターンを読んで埋める）。コア実装コード（atomic_io, send_interrupt_to_pane, mtime 検証, worker_resolution, transaction 集約）は具体コードを提示済み。
- **Type consistency:** `atomic_write_text`/`atomic_write_json`、`send_interrupt_to_pane`、`resolve_worker_number_from_slot`/`resolve_agent_cli_name`/`resolve_worker_model_for_cli`、`_apply_status_to_dashboard`/`_apply_checklist_to_dashboard` の名称はタスク内で一貫。
- **依存順序:** Task1(atomic_io)→他、は独立。Task4(worker_resolution)は逆依存解消の本体。Task5 は dashboard 内で完結。順序どおりなら衝突なし。
- **リスク管理:** 高リスクの Task4/5 は特性テスト先行（安全網）を Step 1 に明記。

## 次フェーズ

Phase 2 マージ後、Phase 3（構造負債: デッドコード除去・残りの逆依存解消・tmux層テスト拡充）の計画を作成する。
