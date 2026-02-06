# Multi-Agent MCP Server (Codex Guide)

このドキュメントは、Codex で本リポジトリを開発・運用する際の実務ガイドです。

## Project Overview

このプロジェクトは、tmux と git worktree を使って複数 AI エージェントを並列実行する MCP (Model Context Protocol) サーバーです。
Codex は主に以下を担当します。

- 仕様に沿った機能追加・修正
- 既存アーキテクチャ制約の順守
- テスト実行と失敗の解消
- ドキュメントと実装の整合性維持

## Key Features

- Multi-Agent Management: Owner / Admin / Worker ロール管理
- Tmux Integration: エージェントごとの独立セッション
- Git Worktree Support: 並列開発用の分離ワークスペース
- AI CLI Selection: Claude Code / Codex / Gemini CLI 切り替え
- Task Scheduling: 優先度と依存関係を持つキュー
- Health Monitoring: ハートビート監視と自動復旧
- Cost Tracking: Dashboard へのコスト集計

## Project Structure

```text
multi-agent-mcp/
├── src/
│   ├── server.py
│   ├── context.py
│   ├── config/
│   ├── models/
│   ├── managers/
│   └── tools/
├── templates/
├── tests/
├── pyproject.toml
└── README.md
```

詳細は `CLAUDE.md` の構成一覧に準拠。新規ファイル追加時は同じ命名規則を維持すること。

## Development Commands

```bash
# 依存関係インストール
uv sync --extra dev

# 全テスト
uv run pytest

# 詳細表示
uv run pytest -v

# 個別テスト
uv run pytest tests/test_scheduler_manager.py

# Lint / Format
uv run ruff check src/
uv run ruff format src/

# MCP サーバー起動
uv run multi-agent-mcp
```

## Codex Working Rules

- 変更前に関連実装を確認し、推測で修正しない。
- 1 つの責務に集中して最小差分で修正する。
- 既存の公開 API・ツール I/F 変更は、必要性と影響範囲を明示する。
- 変更後は必ずテストを実行し、失敗を残したまま完了報告しない。
- ドキュメント更新が必要なら同一コミット粒度で更新する。

## Code Style Guidelines

### Python

- すべての関数で型ヒントを付与
- Union は `|` を使用 (`str | None`)
- Docstring は日本語・Google style
- 1 行 100 文字以内
- import 順序は ruff に従う

### Pydantic

- `ConfigDict` を使用
- メタデータ・デフォルトは `Field()` を使用
- `dict()` ではなく `model_dump()` を優先

### Async

- tmux と相互作用する manager メソッドは async
- async 呼び出しは `await` を徹底
- テストは `@pytest.mark.asyncio` を使用

### Testing

- manager ごとに `tests/test_<manager_name>.py`
- fixture は `tests/conftest.py`
- 命名規則:
  - class: `Test<ClassName>`
  - method: `test_<method_name>_<scenario>`

## Architecture Constraints (Must Follow)

### IPC は Event-Driven

- Admin↔Worker 通信は tmux `send_keys_to_pane()` による通知駆動
- 送信時、`src/tools/ipc.py` が `[IPC] 新しいメッセージ` を受信 pane に通知
- Admin/Worker は通知を契機に処理し、ポーリングループは禁止
- 例外は healthcheck の生存確認ポーリングのみ

### Agent State 永続化

- `agents.json` を source of truth とする
- `src/tools/helpers.py` の保存/読込ロジックを利用
- cross-instance 操作前に file -> memory 同期を行う
- terminate 時は削除せず `TERMINATED` に遷移

### Dashboard 永続化

- `dashboard.md` (YAML Front Matter + Markdown) を使用
- マルチプロセス安全性のため毎回 file I/O (メモリキャッシュ禁止)
- I/O は `src/managers/dashboard_manager.py` に集約

### Documentation Accuracy

- 設計記述は必ず実装を確認してから更新
- Event-driven 実装を polling と誤記しない
- 古い記述を見つけたら差分として明示的に更新

## Test Policy

- 変更後は `uv run pytest` を実行
- 失敗した場合は原因を特定して修正してから完了報告
- 回帰防止のため、必要ならテストを追加

## Environment Variables

運用変数は `CLAUDE.md` の Environment Variables テーブルに準拠。
Codex で `.env` テンプレートを更新する際は次を守ること。

- 既存キー名を破壊的変更しない
- デフォルト値と説明を同期して更新
- モデルプロファイル系 (`MCP_MODEL_PROFILE_*`) と CLI デフォルト系 (`MCP_CLI_DEFAULT_*`) の整合性を保つ

## Change Workflow (Recommended)

1. 要件と関連ファイルを特定 (`src/managers`, `src/tools`, `tests`)
2. 影響範囲を確認して最小差分で実装
3. 必要なテストを追加/更新
4. `uv run pytest` 実行
5. 必要に応じて `ruff check` / `ruff format`
6. ドキュメント (`README.md`, `CLAUDE.md`, `CODEX.md`) を同期

## Common Tasks

### New Manager 追加

1. `src/managers/<name>_manager.py` を作成
2. `src/managers/__init__.py` に追加
3. `tests/conftest.py` に fixture 追加
4. `tests/test_<name>_manager.py` を追加
5. 必要な MCP tool を `src/tools/` に実装

### New MCP Tool 追加

1. `src/tools/` の適切な module を選択（必要なら新規作成）
2. `register_tools(mcp)` 内に `@mcp.tool()` で定義
3. 型ヒント・docstring・エラーハンドリングを実装
4. 複雑レスポンスは構造化 dict を返却
5. 新規 module の場合は `src/tools/__init__.py` に登録

---

実装判断に迷う場合は、まず「既存 manager/tool の責務境界を壊していないか」を優先して確認すること。
