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

- 作業結果は `save_to_memory` で保存

## 完了報告（必須）

**作業が完了したら必ず `report_task_completion` を呼び出してください。**

```
mcp__multi-agent-mcp__report_task_completion(
    task_id="{task_id}",
    status="completed",  # または "failed"
    message="作業内容の要約",
    summary="結果の詳細（メモリに保存される）",
    caller_agent_id="{agent_id}"
)
```

これを呼び出さないと Admin がタスク完了を検知できません。
