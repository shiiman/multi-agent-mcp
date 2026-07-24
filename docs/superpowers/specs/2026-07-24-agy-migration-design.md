# 設計: Gemini CLI → Antigravity CLI (agy) 移行

- 日付: 2026-07-24
- 対象: multi-agent-mcp における AI CLI 選択肢の `gemini` → `agy` 置き換え
- ステータス: 設計（実装前）

## 背景・事実確認

「Gemini CLI が Antigravity CLI (agy) に統合された」という前提は、正確には **「置き換え（後継）」** である。

- `agy`（Antigravity CLI）は Google の **Gemini CLI の後継**。無料/コンシューマ版 Gemini CLI は **2026-06-18 に停止**。
- 有料 API キーがあれば `gemini` コマンドと併存は可能だが、本プロジェクトでは gemini を廃し agy に一本化する。

### 「agy」という名前のバイナリが 2 種類存在する（重要）

| 種別 | 実体 | ヘッドレス | tmux ペイン適合 |
|---|---|---|---|
| デスクトップアプリ | `/Applications/Antigravity.app`（VS Code フォーク）。`agy chat "..."` は **GUI ウィンドウ**を開く | 不可（GUI） | ✕ |
| 端末 CLI（後継本体） | curl インストールの Go バイナリ。`agy --print` 等でヘッドレス動作 | 可 | ○ |

本プロジェクトは各エージェントを **tmux ペイン内の端末プロセス**として起動するため、統合対象は **端末 CLI 版**のみ。

### 端末 CLI 版 v1.1.5 で検証済みの実フラグ

SHA512 検証済みバイナリを取得し `--help` で確認した実フラグ（gemini との差分）:

| 用途 | 旧 `gemini` | `agy`（端末 CLI v1.1.5） |
|---|---|---|
| モデル指定 | `--model X` | `--model X`（同じ） |
| 自動承認（yolo 相当） | `--yolo` | `--dangerously-skip-permissions` |
| 推論強度 | ❌ 非対応 | ✅ `--effort low\|medium\|high`（**新規対応**） |
| ワンショット実行 | `--prompt "..."` | `-p` / `--print` / `--prompt "..."` |
| 対話継続（初期プロンプト後に継続） | （位置引数系） | `-i` / `--prompt-interactive "..."` ← **tmux ワーカー向き** |
| その他 | — | `--mode accept-edits\|plan`, `--add-dir`, `--sandbox`, サブコマンド `models`/`install`/`plugin`/`update` |

## 確定した設計判断

1. **移行方式**: gemini を agy へ**置き換え**（新規追加ではない）。
2. **enum 後方互換**: **エイリアスなし（クリーン置換）**。`AICli.GEMINI` を削除し `AICli.AGY` に置換。旧値 `"gemini"` が永続データ/環境変数に残っている場合は手動修正が必要（`AICli("gemini")` は `ValueError`）。
3. **コマンド解決**: **PATH 優先を前提に `"agy"` を使用**。端末 CLI 版が PATH で先勝ちすることを前提とし、セットアップ手順を README に明記。
4. **モデル ID**: **agy ログイン後に `agy models` で実 ID を確定**。それまではプレースホルダ。

## アーキテクチャ / コンポーネント設計

### フェーズ 1: フラグ・enum・コマンド構造の移行（モデル ID 不要・先行実装可能）

#### 1-1. AICli enum — [settings.py](../../../src/config/settings.py#L43-L56)
```python
# 変更前
GEMINI = "gemini"
# 変更後
AGY = "agy"
```
docstring も「Antigravity CLI（Gemini CLI 後継）」に更新。

#### 1-2. デフォルトコマンド — [settings.py](../../../src/config/settings.py#L210-L215)
```python
AICli.AGY: "agy",   # 旧: AICli.GEMINI: "gemini"
```

#### 1-3. 起動コマンド組み立て — [ai_cli_manager.py](../../../src/managers/ai_cli_manager.py)
`build_stdin_command`（L242-L258）と `_build_cli_args`（L336-L339）の GEMINI 分岐を AGY 分岐へ置換。

- **ワーカー起動（`build_stdin_command`）**:
  ```
  agy --model <M> --dangerously-skip-permissions [--effort <E>] --prompt-interactive "<launch_prompt>"
  ```
  - `--yolo` → `--dangerously-skip-permissions`
  - ワンショット `--prompt` → **`--prompt-interactive`**（tmux でセッション継続させるため）
- **effort マッピング**（本プロジェクトの値 → agy の値）:

  | 入力 | agy |
  |---|---|
  | low / medium / high | そのまま `--effort` に渡す |
  | xhigh | `high` に丸める |
  | none | `--effort` を省略 |

  ※ 現状 gemini 分岐は effort を warning で無視していたが、agy は対応するため活かす。

#### 1-4. モデル互換判定 — [settings.py `resolve_model_for_cli`](../../../src/config/settings.py#L146-L193)
agy は Gemini 3.x / Claude 4.6 / GPT-OSS など**混在モデル**を扱うため、`_is_model_compatible` の `"gemini"` 分岐（`startswith("gemini")`）を撤廃。agy は prefix 検証せず**指定モデルをそのまま通す**（`return True` 相当）。

### フェーズ 2: モデル ID 依存部分（agy ログイン後に確定）

#### 前提作業（ユーザー操作 + 調査）
1. 端末 CLI 版 agy をインストールし、PATH でデスクトップアプリの `agy`（現状 PATH #2）より優先させる。
2. `agy`（引数なし）でサインイン。
3. `agy models` で正確な `--model` 識別子を取得 → 以下を実 ID で確定。

#### 2-1. モデル定数 — [settings.py `ModelDefaults`](../../../src/config/settings.py#L127-L140)
- `GEMINI_DEFAULT` / `GEMINI_LIGHT` → `AGY_DEFAULT` / `AGY_LIGHT`（実 ID、暫定は Gemini 3 系）。
- `CLI_DEFAULTS` の `"gemini"` キー → `"agy"`。

#### 2-2. 設定フィールド — [settings.py](../../../src/config/settings.py#L407-L417)
- `cli_default_gemini_admin_model` / `cli_default_gemini_worker_model` → `cli_default_agy_*`。
- `get_cli_default_models()`（L621-L640）の `"gemini"` キー → `"agy"`。

#### 2-3. コスト表 — [settings.py `model_cost_table_json`](../../../src/config/settings.py#L519-L531)
`gemini:*` エントリを `agy:*` に置換（実モデル ID で単価設定）。

### 追随変更（gemini 参照の一括更新）

| ファイル | 箇所 | 対応 |
|---|---|---|
| [dashboard_cost.py](../../../src/managers/dashboard_cost.py) | L21 `_SUPPORTED_COST_CLI_KEYS`, L186/L212 集計キー | `"gemini"` → `"agy"` |
| [dashboard_markdown_mixin.py](../../../src/managers/dashboard_markdown_mixin.py) | L131 prefix 判定 | `"gemini"` → `"agy"` |
| [healthcheck_manager.py](../../../src/managers/healthcheck_manager.py) | L35 `_AI_RUNNING_COMMAND_PREFIXES` | `"gemini"` → `"agy"` |
| [models/dashboard.py](../../../src/models/dashboard.py) | L103 description | 文言更新（claude/codex/agy/cursor） |
| [session_env.py](../../../src/tools/session_env.py) | L193-L195 env テンプレート | `MCP_CLI_DEFAULT_GEMINI_*` → `MCP_CLI_DEFAULT_AGY_*` |
| [workflow_guides.py](../../../src/config/workflow_guides.py) | L99 コメント | 文言更新（agy のワークスペース外参照制限に言及） |
| [agent_helpers.py](../../../src/tools/agent_helpers.py) | L558 コメント | 文言更新 |
| [gtrconfig_manager.py](../../../src/managers/gtrconfig_manager.py) | L184 の指示ファイル一覧 `GEMINI.md` | agy は `AGENTS.md`（既にリストに存在）を参照するため `GEMINI.md` を削除。実装時に agy の指示ファイル規約を再確認 |
| [templates/roles/admin.md](../../../templates/roles/admin.md), [admin_no_git.md](../../../templates/roles/admin_no_git.md) | L372/L371 CLI 一覧表 | Gemini 行を agy 行に |

> 注: workflow_guides.py L99 と agent_helpers.py L558 の「ワークスペース外参照制限」は Gemini CLI 固有挙動への言及。agy でも `--add-dir` 前提の同種制限がある可能性が高いため、文言は残しつつ「agy」に更新する（挙動の再検証は実装時に行う）。

### テスト

- 既存 gemini 参照テストを agy に更新:
  - [test_ai_cli_manager.py](../../../tests/test_ai_cli_manager.py)（L32-L33, L54, L114-L119, L183-L186, L227-）
  - [test_initialize_agent.py](../../../tests/test_initialize_agent.py)（L243-L279: `--prompt`/`--yolo` の期待値を agy フラグへ）
  - [test_worker_resolution.py](../../../tests/test_worker_resolution.py)（L118-L122）
  - [test_healthcheck_manager.py](../../../tests/test_healthcheck_manager.py)（L1021-L1025）
  - [test_settings_env.py](../../../tests/test_settings_env.py)（L126-L157: env テンプレ/コスト表キー、L263-L265: worker_cli）
  - [test_dashboard_manager.py](../../../tests/test_dashboard_manager.py)（L1438-L1445: `gemini_calls` 集計）
- **新規テスト**（agy 固有）:
  - effort マッピング（low/medium/high 透過、xhigh→high、none→省略）
  - `--prompt-interactive` が使われること
  - `--dangerously-skip-permissions` が付くこと
- `uv run pytest` 緑を維持、`uv tool run ruff check src/` を通す。

### ドキュメント

- README / CLAUDE.md / .env サンプルの Gemini 記述を agy に更新。
- 端末 CLI 版 agy のインストール手順、**PATH 衝突（デスクトップアプリとの先勝ち）**の解消方法、サインイン手順を明記。
- 環境変数表: `MCP_CLI_DEFAULT_GEMINI_*` → `MCP_CLI_DEFAULT_AGY_*`。

## スコープ外 / 非対応

- デスクトップアプリ版 agy（GUI）の統合。
- gemini との併存・切り替え機能（クリーン置換のため不要）。
- agy の `--mode plan` / `--sandbox` / `--add-dir` の高度活用（初期実装では既存 gemini 相当の起動フローに限定）。
- 既存 agents.json / 環境変数に残る旧 `"gemini"` 値の自動マイグレーション（クリーン置換のため手動修正）。

## リスク・留意点

- **モデル ID 未確定**: フェーズ 2 はログインに依存。ログイン前はプレースホルダのままとし、実装完了扱いにしない。
- **PATH 衝突**: 端末 CLI 版が PATH で先勝ちしないと、`agy` がデスクトップアプリに解決されワーカー起動が GUI 起動になって失敗する。セットアップ手順の明記とトラブルシュートが必須。
- **クリーン置換の破壊性**: 稼働中セッションの agents.json や `MCP_WORKER_CLI_N=gemini` が残ると `AICli("gemini")` で例外。移行時に既存永続データの点検が必要。
- **`--prompt-interactive` の実挙動**: tmux ペイン内でセッションが継続し IPC を受けられるかは、ログイン後に実起動で確認する（設計上の想定であり未検証）。

## 実装順序（サマリ）

1. フェーズ 1（enum/コマンド/フラグ/effort/互換判定）を実装 + テスト更新（プレースホルダモデル）。
2. ユーザーが端末 CLI 版 agy をインストール・PATH 調整・サインイン。
3. `agy models` で実モデル ID 取得。
4. フェーズ 2（モデル定数/設定フィールド/コスト表）を実 ID で確定。
5. 実起動で `--prompt-interactive` + IPC 疎通を確認。
6. ドキュメント更新、`uv run pytest` / ruff 緑を確認。
