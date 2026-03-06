"""AppContext の live view 挙動テスト。"""

from unittest.mock import MagicMock

from src.context import AppContext


class TestAppContextGroupViews:
    """AppContext のグループ API が stale にならないことをテストする。"""

    def test_top_level_updates_are_visible_through_group_views(self, settings):
        """トップレベル属性の差し替えがグループ経由でも見えること。"""
        tmux = MagicMock()
        ai_cli = MagicMock()
        ctx = AppContext(settings=settings, tmux=tmux, ai_cli=ai_cli)

        new_dashboard = MagicMock()
        new_healthcheck = MagicMock()
        new_memory = MagicMock()
        new_agents = {"worker-001": MagicMock()}

        ctx.dashboard_manager = new_dashboard
        ctx.healthcheck_manager = new_healthcheck
        ctx.memory_manager = new_memory
        ctx.agents = new_agents

        assert ctx.workflow.dashboard_manager is new_dashboard
        assert ctx.monitoring.healthcheck_manager is new_healthcheck
        assert ctx.optional.memory_manager is new_memory
        assert ctx.core.agents is new_agents

    def test_group_view_updates_write_back_to_top_level(self, settings):
        """グループ経由の更新が AppContext 本体へ反映されること。"""
        tmux = MagicMock()
        ai_cli = MagicMock()
        ctx = AppContext(settings=settings, tmux=tmux, ai_cli=ai_cli)

        new_ipc = MagicMock()
        new_persona = MagicMock()
        new_tmux = MagicMock()

        ctx.workflow.ipc_manager = new_ipc
        ctx.optional.persona_manager = new_persona
        ctx.core.tmux = new_tmux
        ctx.monitoring.healthcheck_idle_cycles = 7

        assert ctx.ipc_manager is new_ipc
        assert ctx.persona_manager is new_persona
        assert ctx.tmux is new_tmux
        assert ctx.healthcheck_idle_cycles == 7

    def test_group_view_objects_are_stable_live_views(self, settings):
        """グループオブジェクト自体は安定しつつ、参照先は最新値を返すこと。"""
        tmux = MagicMock()
        ai_cli = MagicMock()
        ctx = AppContext(settings=settings, tmux=tmux, ai_cli=ai_cli)

        workflow_view = ctx.workflow
        optional_view = ctx.optional

        first_dashboard = MagicMock()
        second_dashboard = MagicMock()
        first_memory = MagicMock()
        second_memory = MagicMock()

        ctx.dashboard_manager = first_dashboard
        ctx.memory_manager = first_memory
        assert workflow_view.dashboard_manager is first_dashboard
        assert optional_view.memory_manager is first_memory

        ctx.dashboard_manager = second_dashboard
        ctx.memory_manager = second_memory
        assert workflow_view is ctx.workflow
        assert optional_view is ctx.optional
        assert workflow_view.dashboard_manager is second_dashboard
        assert optional_view.memory_manager is second_memory
