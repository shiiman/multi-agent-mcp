"""tmux セッション初期化のオーケストレーション。"""

from __future__ import annotations

import asyncio
import logging

from src.managers.pane_layout_planner import PaneLayoutPlanner

logger = logging.getLogger(__name__)


class SessionBootstrapper:
    """tmux ワークスペース構築手順をまとめる。"""

    def __init__(self, manager, planner: PaneLayoutPlanner) -> None:
        self._manager = manager
        self._planner = planner

    async def create_main_session(self, working_dir: str) -> bool:
        """メインセッションを初期化する。"""
        project_name = self._manager._get_project_name(working_dir)
        session_name = project_name

        if await self._manager.session_exists(project_name):
            await self._manager._configure_session_options(session_name)
            await self._manager._normalize_window_indices(session_name)
            logger.info(
                "メインセッション %s は既に存在します（インデックス正規化済み）",
                session_name,
            )
            return True

        if not await self._manager._create_main_session_window(session_name, working_dir):
            return False
        if not await self._manager._configure_session_options(session_name):
            return False
        if not await self._manager._normalize_window_indices(session_name):
            return False
        if not await self.split_main_window_layout(session_name):
            return False

        logger.info("メインセッション作成完了: %s", session_name)
        return True

    async def split_main_window_layout(self, session_name: str) -> bool:
        """メインウィンドウのレイアウトを構築する。"""
        target = f"{session_name}:{self._manager.settings.window_name_main}"
        for command in self._planner.plan_main_window_splits(target):
            code, _, stderr = await self._manager._run(*command.args)
            if code != 0:
                logger.error("%s: %s", command.error_prefix, stderr)
                return False
        return True

    async def split_into_grid(
        self,
        session: str,
        window: int,
        rows: int = 2,
        cols: int = 3,
    ) -> bool:
        """指定ウィンドウをグリッド分割する。"""
        target = f"{session}:{window}"
        for command in self._planner.plan_grid_splits(target, rows, cols):
            code, _, stderr = await self._manager._run(*command.args)
            if code != 0:
                logger.error("%s: %s", command.error_prefix, stderr)
                return False

        code, _, _ = await self._manager._run("select-layout", "-t", target, "even-horizontal")
        if code != 0:
            logger.warning("列幅均等化に失敗、続行します")

        logger.debug("グリッド分割完了: %s (%s×%s)", target, rows, cols)
        return True

    async def add_extra_worker_window(
        self,
        project_name: str,
        window_index: int,
        rows: int = 2,
        cols: int = 6,
    ) -> bool:
        """追加 Worker ウィンドウを作成する。"""
        window_name = self._planner.get_extra_window_name(window_index)

        lock = getattr(self._manager, "_extra_worker_window_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._manager._extra_worker_window_lock = lock

        async with lock:
            windows = await self._manager.list_windows(project_name)
            existing_indices = {w["index"] for w in windows}
            if window_index in existing_indices:
                logger.info("ウィンドウ %s は既に存在します", window_index)
                return True

            if not await self._manager._create_named_window(
                project_name, window_name, "追加Workerウィンドウ作成エラー"
            ):
                return False

            window_target = f"{project_name}:{window_name}"
            await self._manager._run(
                "set-window-option",
                "-t",
                window_target,
                "pane-base-index",
                "0",
            )

            success = await self.split_into_grid(project_name, window_index, rows, cols)
            if not success:
                return False

            logger.info("追加Workerウィンドウ作成完了: %s:%s", project_name, window_name)
            return True
