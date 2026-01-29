# Multi-Agent MCP

Claude Code + tmux + git worktree を使用したマルチエージェントワークフローの MCP サーバー。

## 概要

このMCPサーバーは、複数のClaude Codeインスタンスを tmux セッションで管理し、並列作業を実現します。

### 階層構造

- **Owner** (1体): 全体指揮、タスク分解、Issue作成
- **Admin** (1体): Worker管理、進捗管理、ダッシュボード更新
- **Worker** (最大5体): 割り当てられたタスクの実行

## 必要条件

- Python 3.10以上
- tmux
- uv（推奨）または pip

## インストール

GitHub から直接インストールできます（リポジトリの clone は不要）。

### 方法1: 自動更新あり（推奨）

起動時に毎回 GitHub から最新版を取得します。

```bash
claude mcp add multi-agent-mcp -- uvx --refresh --from git+https://github.com/shiiman/multi-agent-mcp multi-agent-mcp
```

または設定ファイルに直接記述（`~/.claude.json` または `.mcp.json`）:

```json
{
  "mcpServers": {
    "multi-agent-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--refresh",
        "--from", "git+https://github.com/shiiman/multi-agent-mcp",
        "multi-agent-mcp"
      ],
      "env": {
        "MCP_MAX_WORKERS": "5",
        "MCP_DEFAULT_AI_CLI": "claude"
      }
    }
  }
}
```

### 方法2: 自動更新なし（高速起動）

初回のみ GitHub から取得し、以降はキャッシュを使用します。起動が高速になります。

```bash
claude mcp add multi-agent-mcp -- uvx --from git+https://github.com/shiiman/multi-agent-mcp multi-agent-mcp
```

または設定ファイルに直接記述:

```json
{
  "mcpServers": {
    "multi-agent-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/shiiman/multi-agent-mcp",
        "multi-agent-mcp"
      ],
      "env": {
        "MCP_MAX_WORKERS": "5",
        "MCP_DEFAULT_AI_CLI": "claude"
      }
    }
  }
}
```

**手動更新方法**（方法2の場合）:

```bash
uv cache clean multi-agent-mcp
# または
uv tool install --force --from git+https://github.com/shiiman/multi-agent-mcp multi-agent-mcp
```

### 設定の確認

```bash
claude mcp list
```

## 提供するTools

### セッション管理

| Tool | 説明 |
|------|------|
| `init_workspace` | ワークスペースを初期化 |
| `cleanup_workspace` | 全エージェントを終了しリソースを解放 |

### エージェント管理

| Tool | 説明 |
|------|------|
| `create_agent` | 新しいエージェントを作成（tmuxセッション起動） |
| `list_agents` | 全エージェントの一覧を取得 |
| `get_agent_status` | 指定エージェントの詳細ステータスを取得 |
| `terminate_agent` | エージェントを終了 |

### コマンド実行

| Tool | 説明 |
|------|------|
| `send_command` | エージェントにコマンドを送信 |
| `get_output` | エージェントのtmux出力を取得 |
| `broadcast_command` | 全エージェント（または特定役割）にコマンド送信 |

## 使用例

```
# ワークスペースを初期化
init_workspace("my-project")

# Ownerエージェントを作成
create_agent("owner", "/path/to/project")

# Workerエージェントを作成
create_agent("worker", "/path/to/worktree1")
create_agent("worker", "/path/to/worktree2")

# エージェント一覧を確認
list_agents()

# Workerにコマンドを送信
send_command("abc12345", "echo 'Hello from Worker'")

# 出力を取得
get_output("abc12345", 100)

# 全Workerにコマンドをブロードキャスト
broadcast_command("git status", "worker")

# クリーンアップ
cleanup_workspace()
```

## 環境変数

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `MCP_MAX_WORKERS` | 5 | Workerの最大数 |
| `MCP_TMUX_PREFIX` | mcp-agent | tmuxセッション名のプレフィックス |
| `MCP_WORKSPACE_BASE_DIR` | /tmp/mcp-workspaces | ワークスペースのベースディレクトリ |
| `MCP_MESSAGE_RETENTION_SECONDS` | 3600 | メッセージ保持時間（秒） |
| `MCP_DEFAULT_AI_CLI` | claude | デフォルトのAI CLI（claude/codex/gemini） |
| `MCP_CLAUDE_CODE_COMMAND` | claude | Claude Code実行コマンド |
| `MCP_COST_WARNING_THRESHOLD_USD` | 10.0 | コスト警告の閾値（USD） |
| `MCP_HEALTHCHECK_INTERVAL_SECONDS` | 300 | ヘルスチェック間隔（秒） |
| `MCP_HEARTBEAT_TIMEOUT_SECONDS` | 300 | ハートビートタイムアウト（秒） |

## 開発（コントリビューター向け）

ローカルで開発する場合は、リポジトリをクローンしてください。

```bash
# リポジトリをクローン
git clone https://github.com/shiiman/multi-agent-mcp.git
cd multi-agent-mcp

# 開発用依存関係をインストール
uv sync --all-extras

# テストを実行
uv run pytest

# リンターを実行
uv run ruff check src/
```

## ライセンス

MIT
