# Task: {task_id}

## What（何をするか）

{task_description}

## Why（なぜやるか）

プロジェクト「{project_name}」の開発タスクとして実行します。

## Who（誰がやるか）

あなたは **{persona_name}** として作業します。

{persona_prompt}

## Constraints（制約）

- コードは既存のスタイルに合わせる
- テストが必要な場合は必ず追加する
- セキュリティ脆弱性を作らない
- 不明点がある場合は `send_message` で Admin に質問する

## Current State（現状）

### 作業環境

{work_env_section}

### 関連情報（メモリから取得）

{memory_context}

### Self-Check（コンパクション復帰用）

コンテキストが失われた場合、以下を確認してください：

- **タスクID**: {task_id}
- **担当エージェント**: {agent_id}
- **開始時刻**: {timestamp}
- **復帰コマンド**: `retrieve_from_memory "{task_id}"`

## Decisions（決定事項）

（作業中に重要な決定があれば `save_to_memory` で記録してください）

## Notes（メモ）

### 🔴 作業結果の保存（必須）

**⚠️ 作業完了時、必ず save_to_memory で結果を保存してください。**

```python
save_to_memory(
    key="{task_id}-result",
    content="""
    ## タスク結果
    - 作成/修正したファイル: ...
    - 主な変更点: ...
    - 注意点: ...
    """,
    tags=["{task_id}", "worker", "result"],
    caller_agent_id="{agent_id}"
)
```

**保存しないと:**
- ❌ 次回のセッションで参照できない
- ❌ 同じ問題を繰り返す可能性がある

## 🔴 コミット・プッシュ（必須 - 完了報告の前に必ず実行）

**⚠️ 重要: 作業が完了したら、完了報告の前に必ずコミット・プッシュしてください。**

**コミット・プッシュしないと:**
- ❌ Admin が変更をマージできない
- ❌ 他の Worker の作業と統合できない
- ❌ 成果物が失われる

```bash
# 1. 変更をステージング
git add -A

# 2. コミット（作業内容を要約したメッセージ）
git commit -m "feat: {作業内容の要約}"

# 3. リモートにプッシュ（必須！）
git push origin {branch_name}
```

**✅ プッシュ完了を確認してから、完了報告を行ってください。**

## 完了報告（必須 - 2ステップ）

**作業が完了したら、以下の 2 つを必ず実行してください。**

### ステップ 1: Dashboard 更新

```
mcp__multi-agent-mcp__report_task_completion(
    task_id="{task_id}",
    status="completed",  # または "failed"
    message="作業内容の要約",
    summary="結果の詳細（メモリに保存される）",
    caller_agent_id="{agent_id}"
)
```

### ステップ 2: Admin に IPC 通知（必須！）

**⚠️ これがないと Admin が完了を検知できません。**

```
mcp__multi-agent-mcp__send_message(
    receiver_id="{admin_id}",
    message_type="task_complete",
    content="タスク完了: {作業内容の要約}",
    caller_agent_id="{agent_id}"
)
```

### なぜ 2 ステップ必要か

| ステップ | 役割 |
|----------|------|
| `report_task_completion` | Dashboard のタスク状態を更新 |
| `send_message` | Admin に IPC で通知（Admin はこれを待っている） |

**両方を実行しないと、Admin が完了を検知できず、ワークフローが停止します。**
