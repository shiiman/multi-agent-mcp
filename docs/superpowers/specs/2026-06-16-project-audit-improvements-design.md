# 設計: 包括監査に基づく改善 + Opus 4.8 対応

- 日付: 2026-06-16
- 対象: multi-agent-mcp
- 方針: アプローチA（リスク昇順の段階的PR・4フェーズ）。Dashboard キャッシュ問題は「実装を正」とする。

## 1. 背景と目的

包括監査（コード品質/セキュリティ/パフォーマンス/アーキテクチャ整合性/テスト/ドキュメント正確性の6観点）の結果、
基盤は健全（テスト1092 passed / 0 failed、カバレッジ81%）だが、以下の負債が確認された。

- 実害あり・低コスト: コマンドインジェクション余地、async ループをブロックする同期 git 呼び出し、lint 2件
- ドキュメント乖離: CLAUDE.md の構造図/設計ルールが実コードと不一致（CLAUDE.md 自身が「実コードで検証せよ」と規定）
- 中規模負債: 重複ロジックの例外処理ドリフト、無効化されないキャッシュ、過剰ファイルI/O、レイヤー規約違反
- 大規模負債: 約450行のデッドコード、managers→tools の逆依存
- Opus 4.8 がコストテーブル・ドキュメントに未反映

本作業の目的は、これらをリスク昇順の4フェーズで解消し、各フェーズで `uv run pytest` をグリーンに保ちながら
安全に改善すること。Opus 4.8 対応はエイリアス方式を維持し、コストテーブル/ドキュメントへの追加で対応する。

## 2. スコープ外（YAGNI）

- 新機能の追加。本作業は既存負債の解消とドキュメント整合に限定。
- Opus 4.8 をデフォルトにハードピンすること（エイリアス `opus`/`sonnet` 方式を維持）。
- command.py の危険コマンド正規表現ブロックの allowlist 化（多層防御の位置づけを文書化するに留める）。
- メモリ key の予約名拒否・長さ制限等の堅牢化（実害低のため別途）。

## 3. 設計原則

- 各フェーズ＝独立PR。フェーズ間で `uv run pytest` 全グリーン、`uv tool run ruff check src/` クリーン。
- マルチプロセス安全性の設計意図（flock + atomic replace、ファイルが source of truth）を壊さない。
- 既存のコードスタイル（型ヒント必須、`str | None` 記法、Google スタイル日本語 docstring、100文字行長）に準拠。
- ドキュメント構造図はリファクタ完了後（Phase 4）に最終形へ更新する。

---

## 4. Phase 1 — 安全性 + 即効（低リスク・独立）

各項目は相互に独立。1つのPRにまとめる。

### 4.1 セキュリティ: `working_dir` のシェルエスケープ
- 箇所: `src/managers/tmux_workspace_mixin.py:699-714` と `templates/scripts/bash/workspace_setup.sh:5`
- 問題: `working_dir` が `os.path.isdir`/`expanduser` のみの検証で `WD="{working_dir}"` に未エスケープ展開され、
  temp の `.sh` として `bash` 実行される。`"`/バッククォート/`$()` を含む実在ディレクトリ名で引用符を抜けコマンド実行が可能。
- 対応: スクリプト生成時に `shlex.quote(working_dir)` を用いる（または許可文字に制限し展開前に拒否）。
- テスト: `"`/`$()`/バッククォートを含む `working_dir` でスクリプト生成しても展開・実行されないことを検証する単体テストを追加。

### 4.2 性能: `resolve_main_repo_root` のプロセス内キャッシュ化
- 箇所: `src/tools/helpers_git.py`（`resolve_main_repo_root`）、呼び出し元 `src/tools/helpers_persistence.py:42-52,92-96` ほか
- 問題: git mode で `save_agent_to_file`/`sync_agents_from_file` の度に同期 `git rev-parse` を2回実行。
  `save_agent_to_file` は41箇所から呼ばれ、healthcheck daemon の async ループ内でもイベントループをブロックする。
- 対応: `project_root → main_repo_root` の解決結果をプロセス内辞書でキャッシュ（同一パスは git を1回だけ実行）。
  キャッシュは入力パスをキーにする。テストではキャッシュを無効化できる手段（クリア関数 or fixture）を用意。
- テスト: 同一 project_root に対し `git rev-parse` 相当が1回しか呼ばれないことをモックで検証。

### 4.3 lint 2件
- `src/managers/terminal/cmux.py:179`（F541 プレースホルダ無し f-string）: `f` プレフィックス除去（`ruff --fix`）。
- `src/tools/ipc.py:293`（E501 105>100 コメント行）: 改行で折り返し。

### 4.4 Opus 4.8 コストテーブル追加
- 箇所: `src/config/settings.py:519-530`（`model_cost_table_json` の default）
- 対応: `"claude:claude-opus-4-8":0.03` を追加（Opus 4.8 は $5/$25 per 1M で 4.7 と同額のため単価据え置き）。
- 注: ドキュメント側（CLAUDE.md の例、docs/dashboard.md のコスト表）は Phase 4 でまとめて更新する。
- テスト: `get_model_cost_table()` が新キーを含むことを確認（必要なら）。

### Phase 1 完了条件
- 上記4項目を実装、新規テスト追加、`uv run pytest` 全グリーン、`ruff check` クリーン。

---

## 5. Phase 2 — 正確性リファクタ（中・永続化/同期層）

永続化・同期層に集中。Phase 3 のレイヤー解消の前提となる共通化を先に行う。

### 5.1 `atomic_write_json()` 共通ユーティリティ化
- 箇所（コピペ元）: `helpers_persistence.py:139`、`session_state.py`、`helpers_registry.py`、`ipc_manager.py:353`、
  `memory_manager.py`、`dashboard_writer_mixin.py`
- 問題: mkstemp→fdopen/fsync→chmod→os.replace→`except BaseException: unlink; raise` のパターンが5-6箇所で逐語コピー。
- 対応: 共通関数 `atomic_write_json(path, payload, mode=...)` を新設（配置先は後述の判断に従い `src/managers/` 配下の
  共通モジュール、例: `src/managers/atomic_io.py` or 既存の `subprocess_utils.py` に倣った `io_utils.py`）。
  各箇所をこの関数呼び出しに置換。BaseException 時の temp ファイルクリーンアップ挙動を保持。
- 配置上の注意: tools 層と managers 層の双方から使うため、依存方向の下位（managers 配下、tools に依存しない）に置く。
- テスト: 正常書き込み・書き込み失敗時の temp クリーンアップ・権限モード保持を検証。既存テストの回帰確認。

### 5.2 worker解決ロジックの重複統合
- 箇所: `src/managers/healthcheck_manager.py:1244-1334` と `src/tools/agent_helpers.py:226-332`
  （`_resolve_worker_number_from_slot`/`_resolve_agent_cli_name`/`_resolve_worker_model_for_cli`/`_get_current_profile_settings`）
- 問題: ほぼ同一の再実装で、例外処理が分岐（healthcheck=`(ValueError,TypeError)` vs agent_helpers=広域 `Exception`）し挙動がドリフト。
- 対応: 単一の実装に集約。例外の取り扱いを統一（狭い例外型 `(ValueError, TypeError)` に寄せ、想定外は伝播）。
  Phase 3.2 の逆依存解消と二重移動にならないよう、**最初から managers 配下の共通モジュールに新設**し、
  `healthcheck_manager` と `agent_helpers` の双方がそれを呼ぶ形にする（tools 側は後方互換のため必要に応じて re-export）。
  これにより managers は tools に依存せず worker解決を利用できる。
- テスト: 統合後の関数に対し、各 CLI/profile/slot 入力での解決結果と例外挙動を検証。

### 5.3 IPC同期キャッシュに mtime 検証を追加
- 箇所: `src/managers/dashboard_sync_mixin.py:79-114,158-159`
- 問題: `_ipc_sync_cache_*` は read_cache と異なり mtime/存在チェックによる無効化が無く、キャッシュヒット時に state ファイルを
  確認せず即返す。DashboardManager は長期再利用されるため、別 MCP プロセスが state を更新すると古い同期状態を返すリスク。
- 対応: read_cache と同様に state ファイルの mtime を記録し、ヒット時に mtime を検証。変化があれば再読込。
- テスト: state ファイル更新後にキャッシュが無効化され最新を返すことを検証（mtime は `os.utime` で明示設定し時間依存を排除）。

### 5.4 Dashboard `apply_task_messages` のトランザクション集約
- 箇所: `src/managers/dashboard_manager.py:294-376`
- 問題: Admin の `read_messages` 毎に走り、task message N件で `update_task_status`＋`update_task_checklist` が各々独立
  トランザクション（ロック+全読み+全書き）→最後に `save_markdown_dashboard` でも全読み書き。N件で最悪 2N+1 回パース/シリアライズ。
- 対応: 1つの `run_dashboard_transaction`（既存の仕組みに準拠）内で全メッセージを適用し、書き込みを1回に集約。
- テスト: 複数メッセージ適用後の Dashboard 状態が従来と一致すること、書き込み回数が削減されること（呼び出し回数をモックで検証）。

### 5.5 tools→TmuxManager private 呼び出しの是正
- 箇所: `src/tools/agent_lifecycle_tools.py:321,323`（`tmux._get_window_name(...)`、`tmux._run("send-keys", ...)`）
- 対応: TmuxManager に公開メソッド（例: `send_ctrl_c_to_pane(...)` 等、適切な粒度）を追加し、tools 側はそれを呼ぶ。
- テスト: 追加した公開メソッドの単体テスト、terminate_agent 経路の回帰確認。

### Phase 2 完了条件
- 上記5項目を実装、テスト追加/更新、`uv run pytest` 全グリーン、`ruff check` クリーン。

---

## 6. Phase 3 — 構造負債（大・最高リスク）

最もリスクが高い。Phase 2 の共通化完了後に着手し、各サブステップ単位でテストグリーンを維持する。

### 6.1 `ai_cli_manager` のデッドコード除去
- 箇所: `src/managers/ai_cli_manager.py:458-916`（`open_worktree_in_terminal` と支援メソッド群＝ファイルの約半分）、
  および `:362`（`open_worktree`、参照ゼロ）。実体は `src/managers/terminal/` の Executor パッケージへ移行済み。
- 問題: テスト（`test_initialize_agent.py`）がエントリ点を mock しているため生存しているだけのデッドコード。
- 対応:
  1. 本番経路（`tmux_workspace_mixin.py`/`session_state.py` → `terminal/` Executor）を確認し、未使用を最終確認。
  2. デッドコード（約450行＋`open_worktree`）を削除。
  3. mock していたテストを実経路（Executor）に合わせて更新。
  4. 併せて `src/managers/terminal/base.py:69` の未使用 `_run_shell`（唯一の `create_subprocess_shell`）の要否を確認し、
     不要なら削除（攻撃面の縮小にもなる）。
- テスト: 削除後も initialize_agent / open_worktree_with_ai 経路が成立することを検証。

### 6.2 managers→tools 逆依存の解消
- 箇所: `dashboard_manager.py:204`、`healthcheck_manager.py:115,127,1217`、`healthcheck_daemon.py:32-33,104,140-141`
  が `from src.tools.helpers*` / `src.tools.agent_helpers` を（遅延）import。
- 問題: 本来 tools→managers の単方向であるべきところ、依存方向が逆。遅延 import で循環を回避している状態は規約の形骸化。
- 対応: 共有ロジック（永続化・sync・worker解決）を managers 配下の共通モジュールへ移し、tools 側はそれを薄くラップする。
  Phase 2.1（atomic_write_json）・2.2（worker解決統合）の成果物を「managers 配下の下位モジュール」に置くことで、
  逆 import を解消する。移動に伴う import パスの更新と後方互換（helpers.py の re-export）を維持。
- リスク管理: サブステップごとに（モジュール単位で）移動→テスト→次、と進める。1コミット1モジュール移動を目安に。
- テスト: 移動後も既存の公開 API（helpers.py 経由の symbol）が解決でき、全テストグリーン。

### 6.3 tmux層のテスト拡充
- 箇所: `src/managers/tmux_manager.py`（49%）、`src/managers/tmux_workspace_mixin.py`（46%）
- 問題: プロジェクトの心臓部だが conftest で `send_keys_to_pane` 等が全面 AsyncMock 化され、組み立てられる tmux コマンド
  文字列が検証されていない。ペイロード破損が現行テストを素通りする。
- 対応: `_run`/`_run_exec` の引数（tmux コマンド文字列）を `assert_called_with` で検証するテストを追加。
  Codex Enter 再送・rate-limit・Cursor 信頼プロンプト分岐の単体テストを追加。conftest の一部 fixture で return_code を
  可変にし失敗系も検証。目標: 両モジュールのカバレッジを有意に引き上げる（数値目標は実装時に設定）。
- 注: このテスト拡充は 6.1（デッドコード除去でテスト更新が発生）と整合させて行う。

### Phase 3 完了条件
- デッドコード除去・逆依存解消・tmux テスト拡充を実装、`uv run pytest` 全グリーン、`ruff check` クリーン。
- カバレッジが tmux 層で改善していることを確認。

---

## 7. Phase 4 — ドキュメント整合（最後）

リファクタ完了後の最終構造を反映する。

### 7.1 CLAUDE.md Project Structure 更新
- managers 未記載6ファイル: `dashboard_agent_mixin.py`, `dashboard_reader_mixin.py`, `dashboard_writer_mixin.py`,
  `pane_layout_planner.py`, `session_bootstrapper.py`, `subprocess_utils.py`（＋Phase 2/3 で新設・移動したモジュール）。
- tools 未記載3ファイル: `helpers_notifications.py`, `helpers_permissions.py`, `quality_gate.py`。
- config 未記載: `config/constants.py`。
- DashboardManager の mixin 構成を実態（Reader/Writer/Rendering/Cost Mixin）に修正。

### 7.2 Dashboard キャッシュ記述の修正（実装を正）
- CLAUDE.md の「Dashboard Persistence: NO in-memory caching」を実態に修正:
  「mtime 無効化付きの短命 read キャッシュおよび IPC 同期キャッシュ（mtime 検証あり）を採用」と明記。
  Phase 2.3 で IPC 同期キャッシュにも mtime 検証を入れた前提で、安全なキャッシュであることを記述。

### 7.3 環境変数/モデル/コスト表の整合
- CLAUDE.md の `MCP_MODEL_COST_TABLE_JSON` 例に `claude:claude-opus-4-8` を反映。
- `docs/dashboard.md` のコスト表に `claude:claude-opus-4-8`（0.03）と `cursor:composer-1.5`（0.01）を追記。
- `README.md:478` の `MCP_DEFAULT_TERMINAL` 説明に `cmux` を追記（auto: cmux→ghostty→iterm2→terminal）。
- `src/config/settings.py:85,88` の ModelProfile docstring を「gpt-5.5 前提」に更新。

### 7.4 多層防御の文書化
- command.py の危険コマンド正規表現ブロックは「多層防御の一層であり、ペイン側 CLI のサンドボックス/承認に依存しない設計」
  である旨をコード or ドキュメントに明記（監査指摘の意図共有）。

### Phase 4 完了条件
- ドキュメントが実コードと一致。`uv run pytest`（ドキュメントのみのため影響軽微だが）グリーン維持。

---

## 8. テスト戦略

- 各フェーズで `uv run pytest` 全グリーン、`uv tool run ruff check src/` クリーンを必須とする。
- 振る舞いを変える変更（security/性能/リファクタ）は TDD で進める: 失敗するテスト→実装→グリーン。
- リファクタ（5.x/6.x）は「既存挙動を保つ」ことを回帰テストで担保し、必要に応じて特性テストを先に追加。
- カバレッジは Phase 3 の tmux 層で重点的に引き上げる。

## 9. リスクと緩和

| リスク | 緩和策 |
|---|---|
| Phase 3 の逆依存解消で import 経路が広範に変わる | 1モジュール=1コミットで段階移動、helpers.py の re-export 維持、各ステップでテスト |
| デッドコード除去がテスト前提を壊す | 削除前に本番経路を最終確認、テストを実経路へ更新 |
| atomic_write_json 共通化が永続化の正確性を壊す | BaseException 時クリーンアップ挙動を保持、書き込み失敗系テストを追加 |
| Dashboard トランザクション集約で適用順序/結果が変わる | 集約前後で Dashboard 状態が一致する回帰テスト |
| フェーズ間の依存（2→3） | Phase 2 完了を前提に Phase 3 を開始（並行しない） |

## 10. 未確定の実装詳細（計画フェーズで確定）

- `atomic_write_json` と worker解決共通モジュールの最終配置（`src/managers/` 配下の新規モジュール名）。
- TmuxManager に追加する公開メソッドの粒度・命名。
- tmux 層カバレッジの具体的な数値目標。
- 逆依存解消における helpers.py re-export の最終的な扱い（後方互換の範囲）。

## 11. 成果物（PR構成）

- PR1: Phase 1（安全性 + 即効 + Opus 4.8 コスト）
- PR2: Phase 2（正確性リファクタ）
- PR3: Phase 3（構造負債）— サブステップでコミット分割
- PR4: Phase 4（ドキュメント整合）

各 PR は `feature/<issue>` ブランチ → PR の既存ワークフローに従う。
