# タスク（No Git モード）: {task_id}

## What

{task_description}

## Why

プロジェクト「{project_name}」の要求を満たすために実施します。

## Who

あなたは **{persona_name}** として作業します。

{persona_prompt}

## 作業環境

{work_env_section}

## 制約

- No Git モードのため git 操作は行わない
- 既存コードスタイルを維持する
- 必要なテストを実施する
- 不明点は Admin（{admin_id}）へ連絡する

## メモリ情報

{memory_context}

## Self-Check

- タスクID: {task_id}
- エージェントID: {agent_id}
- ブランチ表記（参考）: {branch_name}
- 開始時刻: {timestamp}

## 完了時必須

1. `save_to_memory` で成果を保存
2. `{mcp_tool_prefix}report_task_completion(...)` で完了報告
