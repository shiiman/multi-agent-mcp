# タスク: {task_id}

**このタスクは No Git モードで実行されます。git/branch/worktree 操作は行わないでください。**

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
- ユーザーには質問せず、判断が必要な場合は `send_message` で Admin に質問する
- 軽微な曖昧さは妥当な前提を置いて自己判断で前進し、判断内容を Admin に共有する
- No Git モードのため git 操作は行わない
- git commit / branch / worktree 操作は行わない

## Current State（現状）

### 作業環境

{work_env_section}

### 関連情報（メモリから取得）

{memory_context}

### Self-Check（コンテキスト圧縮からの復帰用）

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

## 🔴 成果の明示（必須 - 完了報告の前に必ず実行）

**⚠️ 重要: 作業が完了したら、完了報告の前に変更内容を明示してください。**

**明示しないと:**
- ❌ Admin が変更内容を検証できない
- ❌ 他 Worker との競合確認ができない
- ❌ 成果物が追跡できない

```text
- 変更したファイル
- 主要な実装内容
- 実施したテストと結果
```

**✅ 上記を整理したうえで、完了報告を行ってください。**

## 完了報告（必須）

**作業が完了したら、Dashboard を更新してください。**

```
{mcp_tool_prefix}report_task_completion(
    task_id="{task_id}",
    status="completed",  # または "failed"
    message="作業内容の要約",
    summary="結果の詳細（メモリに保存される）",
    caller_agent_id="{agent_id}"
)
```

**⚠️ 完了報告では別途 `send_message` は不要です。**
`report_task_completion` が自動的に Admin に IPC 通知を送信します。
