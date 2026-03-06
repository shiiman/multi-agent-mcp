"""tmux ペイン配置の計画ロジック。"""

from __future__ import annotations

from dataclasses import dataclass

from src.managers.tmux_shared import (
    MAIN_SESSION,
    MAIN_WINDOW_PANE_ADMIN,
    MAIN_WINDOW_WORKER_PANES,
)


@dataclass(frozen=True)
class SplitCommand:
    """tmux 分割コマンドと失敗時メッセージ。"""

    args: tuple[str, ...]
    error_prefix: str


class PaneLayoutPlanner:
    """tmux ワークスペースのレイアウト計画を担う。"""

    def __init__(self, settings) -> None:
        self.settings = settings

    def plan_main_window_splits(self, target: str) -> list[SplitCommand]:
        """メインウィンドウの分割手順を返す。"""
        commands = [
            SplitCommand(
                args=("split-window", "-h", "-t", target, "-p", "60"),
                error_prefix="左右分割エラー",
            ),
            SplitCommand(
                args=("split-window", "-h", "-t", f"{target}.1", "-p", "67"),
                error_prefix="右側列分割エラー(1)",
            ),
            SplitCommand(
                args=("split-window", "-h", "-t", f"{target}.2", "-p", "50"),
                error_prefix="右側列分割エラー(2)",
            ),
        ]
        for pane_idx in [3, 2, 1]:
            commands.append(
                SplitCommand(
                    args=("split-window", "-v", "-t", f"{target}.{pane_idx}"),
                    error_prefix=f"右側行分割エラー(pane {pane_idx})",
                )
            )
        return commands

    def plan_grid_splits(self, target: str, rows: int, cols: int) -> list[SplitCommand]:
        """指定グリッドの分割手順を返す。"""
        commands: list[SplitCommand] = []
        for _ in range(cols - 1):
            commands.append(
                SplitCommand(
                    args=("split-window", "-h", "-t", target),
                    error_prefix="水平分割エラー",
                )
            )
        for col in range(cols - 1, -1, -1):
            pane_target = f"{target}.{col}"
            for _ in range(rows - 1):
                commands.append(
                    SplitCommand(
                        args=("split-window", "-v", "-t", pane_target),
                        error_prefix="垂直分割エラー",
                    )
                )
        return commands

    def get_extra_window_name(self, window_index: int) -> str:
        """追加 Worker ウィンドウ名を返す。"""
        return f"{self.settings.window_name_worker_prefix}{window_index + 1}"

    def get_pane_for_role(
        self,
        role: str,
        worker_index: int = 0,
    ) -> tuple[str, int, int] | None:
        """ロールに対応するペイン位置を返す。"""
        if role == "owner":
            return None
        if role == "admin":
            return MAIN_SESSION, 0, MAIN_WINDOW_PANE_ADMIN
        if role != "worker":
            raise ValueError(f"不明なロール: {role}")

        if worker_index < len(MAIN_WINDOW_WORKER_PANES):
            pane_index = MAIN_WINDOW_WORKER_PANES[worker_index]
            return MAIN_SESSION, 0, pane_index

        extra_worker_index = worker_index - len(MAIN_WINDOW_WORKER_PANES)
        workers_per_extra = self.settings.workers_per_extra_window
        window_index = 1 + (extra_worker_index // workers_per_extra)
        pane_index = extra_worker_index % workers_per_extra
        return MAIN_SESSION, window_index, pane_index
