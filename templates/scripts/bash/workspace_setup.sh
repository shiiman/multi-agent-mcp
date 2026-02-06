#!/bin/bash
set -e

SESSION="{session_name}"
WD="{working_dir}"

# ターミナルタブ名をセッション名に設定
printf '\033]0;%s\007' "$SESSION"

# セッションが存在しない場合のみ作成
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Creating new tmux session: $SESSION"

    # 1. セッション作成（ウィンドウ名: main）
    tmux new-session -d -s "$SESSION" -c "$WD" -n main

    # セッション固有のオプション設定（base-index に依存しないようにする）
    tmux set-option -t "$SESSION" base-index 0
    tmux set-option -t "$SESSION" pane-base-index 0

    # 分割順序: 右側を先に完成させる
    # これにより pane 0 が途中で番号変更されるのを防ぐ

    # 2. 左右40:60に分割（左40% Admin, 右60% Workers）
    # pane 0 = 左40%, pane 1 = 右60%
    tmux split-window -h -t "$SESSION:main" -p 60

    # 3. 右側（pane 1）を3列に分割
    tmux split-window -h -t "$SESSION:main.1" -p 67
    tmux split-window -h -t "$SESSION:main.2" -p 50
    # pane 0 = Admin, pane 1 = W列1, pane 2 = W列2, pane 3 = W列3

    # 4. 各Worker列を上下に分割（6ペイン）
    # 重要: 逆順（.3 → .2 → .1）で分割することで、
    # 分割時のペイン番号シフトを回避
    tmux split-window -v -t "$SESSION:main.3"
    tmux split-window -v -t "$SESSION:main.2"
    tmux split-window -v -t "$SESSION:main.1"
    # pane 0 = Admin, pane 1-6 = Workers

    # Owner の分割は不要（起点の AI CLI が Owner の役割を担う）

    echo "Workspace layout created"
else
    echo "Session $SESSION already exists"
fi

# セッションにattach
exec tmux attach -t "$SESSION"
