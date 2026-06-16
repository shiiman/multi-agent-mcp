# Phase 1: 安全性 + 即効 + Opus 4.8 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** コマンドインジェクション余地・async ブロッキング・lint 2件を解消し、Opus 4.8 をコストテーブルに追加する（低リスク・各タスク独立）。

**Architecture:** 設計ドキュメント `docs/superpowers/specs/2026-06-16-project-audit-improvements-design.md` の Phase 1。各タスクは独立しており TDD（失敗テスト→実装→グリーン→コミット）で進める。

**Tech Stack:** Python 3.10+, pytest + pytest-asyncio, ruff, uv。

**前提:** ブランチ `feature/audit-improvements`（作成済み）。各タスク完了時に `uv run pytest` 全グリーン、`uv tool run ruff check src/` クリーンを維持。

---

## Task 1: `working_dir` のシェルエスケープ（セキュリティ）

`working_dir` がワークスペース構築スクリプトに未エスケープで展開され、`"`/`$()`/バッククォートを含む
実在ディレクトリ名でコマンドインジェクションが可能。`shlex.quote` で解消する。

**Files:**
- Modify: `src/managers/tmux_workspace_mixin.py:654-673`（`_generate_workspace_script`）
- Modify: `templates/scripts/bash/workspace_setup.sh:5`
- Test: `tests/test_tmux_workspace_services.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tmux_workspace_services.py` に以下を追加。`_generate_workspace_script` は `self` の状態を一切
使わない（`get_template_loader()` を呼ぶのみ）ため、`MagicMock()` を self として渡しメソッドを直接テストする
（同ファイルは async fixture を使わず直接構築する方針なのに合わせる）:

```python
import shlex
from unittest.mock import MagicMock

from src.managers.tmux_workspace_mixin import TmuxWorkspaceMixin


def test_generate_workspace_script_escapes_malicious_working_dir():
    """working_dir に含まれるシェルメタ文字が安全に引用符化されること。"""
    malicious_wd = '/tmp/foo"; touch /tmp/pwned #'
    script = TmuxWorkspaceMixin._generate_workspace_script(
        MagicMock(), "test-session", malicious_wd
    )

    # shlex.quote 済みの値がそのまま WD= 行に現れる（破壊的展開が起きない）
    assert f"WD={shlex.quote(malicious_wd)}" in script
    # 未エスケープの危険な行 `WD="/tmp/foo"; touch ...` が生成されていない
    assert 'WD="/tmp/foo";' not in script
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_tmux_workspace_services.py::test_generate_workspace_script_escapes_malicious_working_dir -v`
Expected: FAIL（現状は `WD="/tmp/foo"; touch /tmp/pwned #"` が生成され assert に合致しない）

- [ ] **Step 3: テンプレートを修正**

`templates/scripts/bash/workspace_setup.sh` の 5行目を変更:

```bash
WD={working_dir}
```

（`WD="{working_dir}"` のダブルクォートを除去。値側で `shlex.quote` するため）

- [ ] **Step 4: スクリプト生成で `shlex.quote` を適用**

`src/managers/tmux_workspace_mixin.py` の `_generate_workspace_script` を変更。ファイル冒頭付近の import に `shlex` を追加し（既存 import 群に合わせて配置）、`render` 呼び出しを次のようにする:

```python
def _generate_workspace_script(self, session_name: str, working_dir: str) -> str:
    """ワークスペース構築用のシェルスクリプトを生成する。

    セッション作成・ペイン分割・attachを一度に行うスクリプトを生成。
    Owner は tmux ペインに配置しない（実行AIエージェントが担う）。
    working_dir はシェルインジェクション防止のため shlex.quote でエスケープする。

    Args:
        session_name: tmuxセッション名（プレフィックス付き）
        working_dir: 作業ディレクトリのパス

    Returns:
        シェルスクリプト文字列
    """
    import shlex

    loader = get_template_loader()
    return loader.render(
        "scripts/bash",
        "workspace_setup",
        session_name=session_name,
        working_dir=shlex.quote(working_dir),
    )
```

注: `template_loader._safe_render` は `$`→`$$` エスケープを **テンプレート本文** に適用し、`safe_substitute` で渡す値は
リテラル挿入される。`shlex.quote` の出力（単一引用符化）は値として挿入され、`WD={working_dir}` 行は
`WD='...'` の安全な形になる。

- [ ] **Step 5: テストを実行して成功を確認**

Run: `uv run pytest tests/test_tmux_workspace_services.py::test_generate_workspace_script_escapes_malicious_working_dir -v`
Expected: PASS

- [ ] **Step 6: 関連テストの回帰確認**

Run: `uv run pytest tests/test_tmux_workspace_services.py tests/test_tmux_manager_terminal_open.py -v`
Expected: 全 PASS（正常な working_dir でもスクリプトが従来どおり機能すること）

- [ ] **Step 7: コミット**

```bash
git add src/managers/tmux_workspace_mixin.py templates/scripts/bash/workspace_setup.sh tests/test_tmux_workspace_services.py
git commit -m "$(cat <<'EOF'
fix(security): workspace_setupのworking_dirをshlex.quoteでエスケープ

- 未エスケープのworking_dir展開によるコマンドインジェクション余地を解消
- テンプレートのWD=行をクォート除去し、値側でshlex.quoteを適用

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `resolve_main_repo_root` のプロセス内キャッシュ化（パフォーマンス）

`save_agent_to_file`/`sync_agents_from_file` の度に同期 `git rev-parse` を2回実行し、async ループをブロックする。
同一パスの解決結果をプロセス内キャッシュし、git 実行を1回に抑える。

**Files:**
- Modify: `src/tools/helpers_git.py:12-66`（`resolve_main_repo_root`）
- Modify: `tests/conftest.py`（キャッシュクリア用 autouse fixture）
- Test: `tests/test_helpers_git.py`（新規）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_helpers_git.py` を新規作成:

```python
"""helpers_git のテスト。"""

from unittest.mock import MagicMock, patch

from src.tools import helpers_git


def test_resolve_main_repo_root_caches_result():
    """同一パスの解決結果はキャッシュされ、git は1回しか実行されないこと。"""
    helpers_git.clear_main_repo_root_cache()

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        if "--show-toplevel" in cmd:
            result.stdout = "/repo\n"
        else:  # --git-common-dir
            result.stdout = "/repo/.git\n"
        return result

    with patch("src.tools.helpers_git.subprocess.run", side_effect=fake_run) as mock_run:
        first = helpers_git.resolve_main_repo_root("/repo/sub")
        second = helpers_git.resolve_main_repo_root("/repo/sub")

    assert first == "/repo"
    assert second == "/repo"
    # 1回目で2回（show-toplevel + git-common-dir）、2回目はキャッシュヒットで0回
    assert mock_run.call_count == 2


def test_clear_main_repo_root_cache_forces_recompute():
    """キャッシュクリア後は再計算されること。"""
    helpers_git.clear_main_repo_root_cache()

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.stdout = "/repo\n" if "--show-toplevel" in cmd else "/repo/.git\n"
        return result

    with patch("src.tools.helpers_git.subprocess.run", side_effect=fake_run) as mock_run:
        helpers_git.resolve_main_repo_root("/repo/sub")
        helpers_git.clear_main_repo_root_cache()
        helpers_git.resolve_main_repo_root("/repo/sub")

    assert mock_run.call_count == 4  # クリアで再計算され 2回 + 2回
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_helpers_git.py -v`
Expected: FAIL（`clear_main_repo_root_cache` が存在せず AttributeError、またはキャッシュ無しで call_count=4）

- [ ] **Step 3: キャッシュを実装**

`src/tools/helpers_git.py` を変更。`logger = logging.getLogger(__name__)` の直後にモジュールレベルキャッシュを追加:

```python
# プロセス内キャッシュ: 入力パス文字列 → メインリポジトリルート
# 同一パスのリポジトリ構成はプロセス生存中に変化しないため安全にキャッシュ可能
_main_repo_root_cache: dict[str, str] = {}


def clear_main_repo_root_cache() -> None:
    """resolve_main_repo_root のプロセス内キャッシュをクリアする（主にテスト用）。"""
    _main_repo_root_cache.clear()
```

`resolve_main_repo_root` の本体を「キャッシュ参照 → 未計算なら内部関数で解決 → 保存」に分離する。
既存の解決ロジックを `_resolve_main_repo_root_uncached` へ移し、公開関数は薄くする:

```python
def resolve_main_repo_root(path: str | Path) -> str:
    """パスからメインリポジトリのルートを解決する（プロセス内キャッシュ付き）。

    git worktree の場合はメインリポジトリのルートを返す。
    通常のリポジトリの場合はそのままルートを返す。
    成功結果は入力パスをキーにプロセス内キャッシュされる。

    Args:
        path: 解決するパス（worktree またはリポジトリ内のパス）

    Returns:
        メインリポジトリのルートパス
    """
    cache_key = str(Path(path))
    cached = _main_repo_root_cache.get(cache_key)
    if cached is not None:
        return cached
    resolved = _resolve_main_repo_root_uncached(path)
    _main_repo_root_cache[cache_key] = resolved
    return resolved


def _resolve_main_repo_root_uncached(path: str | Path) -> str:
    """git コマンドでメインリポジトリのルートを解決する（キャッシュ無し）。"""
    path = Path(path)

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path),
            capture_output=True,
            text=True,
            check=True,
        )
        repo_root = result.stdout.strip()

        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(path),
            capture_output=True,
            text=True,
            check=True,
        )
        git_common_dir = result.stdout.strip()

        if not os.path.isabs(git_common_dir):
            git_common_dir = os.path.join(repo_root, git_common_dir)

        git_common_dir = os.path.normpath(git_common_dir)
        if git_common_dir.endswith(".git"):
            return os.path.dirname(git_common_dir)
        else:
            git_dir_index = git_common_dir.find("/.git")
            if git_dir_index == -1:
                return repo_root
            return git_common_dir[:git_dir_index]

    except subprocess.CalledProcessError as e:
        raise ValueError(f"{path} は git リポジトリではありません: {e}") from e
```

注: 例外（非 git パス）はキャッシュしない（毎回再評価され従来挙動を保つ）。

- [ ] **Step 4: テスト間のキャッシュ汚染を防ぐ autouse fixture を追加**

`tests/conftest.py` に以下を追加（既存 import に合わせて配置）:

```python
@pytest.fixture(autouse=True)
def _clear_main_repo_root_cache():
    """各テスト前後で resolve_main_repo_root のプロセス内キャッシュをクリアする。"""
    from src.tools import helpers_git

    helpers_git.clear_main_repo_root_cache()
    yield
    helpers_git.clear_main_repo_root_cache()
```

- [ ] **Step 5: テストを実行して成功を確認**

Run: `uv run pytest tests/test_helpers_git.py -v`
Expected: 両テスト PASS

- [ ] **Step 6: 全体回帰（永続化・healthcheck 経路への影響確認）**

Run: `uv run pytest tests/test_helpers_persistence.py tests/test_healthcheck_manager.py -q`
Expected: 全 PASS

- [ ] **Step 7: コミット**

```bash
git add src/tools/helpers_git.py tests/test_helpers_git.py tests/conftest.py
git commit -m "$(cat <<'EOF'
perf(git): resolve_main_repo_rootをプロセス内キャッシュ化

- agents.json保存/同期の度に走る同期git rev-parse(x2)をパス単位でキャッシュ
- async healthcheckループのブロッキングを軽減
- テスト用にclear_main_repo_root_cacheとautouse fixtureを追加

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: lint 2件の修正

**Files:**
- Modify: `src/managers/terminal/cmux.py:179`（F541）
- Modify: `src/tools/ipc.py:293`（E501）

- [ ] **Step 1: 現状の lint エラーを確認**

Run: `uv tool run ruff check src/`
Expected: 2 errors（cmux.py の F541、ipc.py:293 の E501）

- [ ] **Step 2: cmux.py の F541 を修正**

`src/managers/terminal/cmux.py:179` の `close_script = f'''` を、`f` プレフィックスを除去して通常の文字列にする
（当該ブロックは `{}` プレースホルダを含まないため）:

```python
            close_script = '''
```

- [ ] **Step 3: ipc.py の E501 を修正**

`src/tools/ipc.py:293` の長いコメント行を2行に折り返す:

```python
        # 仕様: macOS通知は admin→owner の task_complete のみに限定。
        # tmux失敗時のフォールバックは行わない
```

- [ ] **Step 4: lint がクリーンになったことを確認**

Run: `uv tool run ruff check src/`
Expected: `All checks passed!`（0 errors）

- [ ] **Step 5: テスト回帰確認**

Run: `uv run pytest tests/test_ipc_tools.py -q`
Expected: 全 PASS

- [ ] **Step 6: コミット**

```bash
git add src/managers/terminal/cmux.py src/tools/ipc.py
git commit -m "$(cat <<'EOF'
style(lint): 既存のruffエラー2件を修正

- cmux.py: プレースホルダ無しf-stringのfプレフィックス除去(F541)
- ipc.py: 行長超過コメントを折り返し(E501)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Opus 4.8 をコストテーブルに追加

`claude-opus-4-8` がコストテーブルに無く、ダッシュボードのコスト集計でデフォルト単価にフォールバックする。
4.8 は $5/$25 per 1M で 4.7 と同額のため単価 0.03 を据え置きで追加する。

**Files:**
- Modify: `src/config/settings.py:519-530`（`model_cost_table_json` の default）
- Test: `tests/test_settings_env.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_settings_env.py` に追加（既存の `Settings` 生成パターンに合わせる）:

```python
def test_cost_table_includes_opus_4_8():
    """デフォルトのコストテーブルに claude-opus-4-8 が含まれること。"""
    from src.config.settings import Settings

    # _env_file=None でプロジェクト .env の上書きを排除し、フィールド default を検証
    table = Settings(_env_file=None).get_model_cost_table()
    assert table.get("claude:claude-opus-4-8") == 0.03
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_settings_env.py::test_cost_table_includes_opus_4_8 -v`
Expected: FAIL（キー未定義で None != 0.03）

- [ ] **Step 3: コストテーブルのデフォルトに 4.8 を追加**

`src/config/settings.py` の `model_cost_table_json` default の Claude 行を変更。
`'"claude:claude-opus-4-7":0.03,"claude:claude-opus-4-6":0.03,'` を次に置換:

```python
        '"claude:claude-opus-4-8":0.03,'
        '"claude:claude-opus-4-7":0.03,"claude:claude-opus-4-6":0.03,'
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/test_settings_env.py::test_cost_table_includes_opus_4_8 -v`
Expected: PASS

- [ ] **Step 5: settings/cost 関連の回帰確認**

Run: `uv run pytest tests/test_settings_env.py tests/test_cost_capture.py tests/tools/test_dashboard_cost_tools.py -q`
Expected: 全 PASS

- [ ] **Step 6: コミット**

```bash
git add src/config/settings.py tests/test_settings_env.py
git commit -m "$(cat <<'EOF'
feat(config): コストテーブルにclaude-opus-4-8を追加

- Opus 4.8(=$5/$25 per 1M, 4.7と同額)を単価0.03で追加
- ダッシュボードのコスト集計が4.8でデフォルト単価にフォールバックする問題を解消

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 1 完了確認

- [ ] **全テストグリーン**

Run: `uv run pytest -q`
Expected: 全 PASS（1092件 + 新規追加分、失敗0）

- [ ] **lint クリーン**

Run: `uv tool run ruff check src/`
Expected: `All checks passed!`

- [ ] **差分レビュー**

Run: `git log --oneline feature/audit-improvements -5`
Expected: Task1〜4 の4コミット（＋スペックコミット）が並ぶ

---

## Self-Review 結果

- **Spec coverage:** Phase 1 の4項目（4.1 security / 4.2 perf / 4.3 lint / 4.4 Opus 4.8 cost）すべてに対応タスクあり。
- **Placeholder scan:** なし（全ステップに実コード/実コマンド/期待値を記載）。
- **Type consistency:** `clear_main_repo_root_cache`/`_resolve_main_repo_root_uncached`/`_main_repo_root_cache` の名称は
  Task 2 内で一貫。`_generate_workspace_script` のシグネチャは既存と一致。
- **依存:** 各タスクは独立。順不同で実行可能だが、最後に全体 pytest + ruff を回す。

## 次フェーズ

Phase 1 マージ後、Phase 2（正確性リファクタ）の計画を `docs/superpowers/plans/2026-06-16-phase2-*.md` として作成する。
