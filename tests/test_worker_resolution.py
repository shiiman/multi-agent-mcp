"""worker_resolution の特性テスト。

healthcheck_manager と agent_helpers に重複していた Worker 解決ロジックを
src/managers/worker_resolution.py へ統合した際の挙動を固定する安全網。
MagicMock と実 Settings を併用し、統合後の 3 関数を網羅する。
"""

from datetime import datetime
from unittest.mock import MagicMock

from src.config.settings import AICli
from src.managers.worker_resolution import (
    resolve_agent_cli_name,
    resolve_worker_model_for_cli,
    resolve_worker_number_from_slot,
)
from src.models.agent import Agent, AgentRole, AgentStatus


def _make_worker_agent(
    agent_id: str = "worker-001",
    session_name: str = "test",
    window_index: int | None = 0,
    pane_index: int | None = 1,
) -> Agent:
    """テスト用 Worker エージェントを生成する。"""
    now = datetime.now()
    return Agent(
        id=agent_id,
        role=AgentRole.WORKER,
        status=AgentStatus.IDLE,
        tmux_session=f"{session_name}:{window_index}.{pane_index}",
        session_name=session_name,
        window_index=window_index,
        pane_index=pane_index,
        working_dir="/tmp",
        created_at=now,
        last_activity=now,
    )


def _make_owner_agent() -> Agent:
    """テスト用 Owner エージェントを生成する。"""
    now = datetime.now()
    return Agent(
        id="owner-001",
        role=AgentRole.OWNER,
        status=AgentStatus.IDLE,
        tmux_session=None,
        working_dir="/tmp",
        created_at=now,
        last_activity=now,
    )


class TestResolveWorkerNumberFromSlot:
    """resolve_worker_number_from_slot のテスト。"""

    def test_main_window_returns_pane_index(self, settings):
        """window0 では pane_index がそのまま Worker 番号になる。"""
        assert resolve_worker_number_from_slot(settings, 0, 1) == 1
        assert resolve_worker_number_from_slot(settings, 0, 6) == 6

    def test_extra_window_first_slot(self, settings):
        """追加ウィンドウ(window1)の先頭 pane は 7 を返す。"""
        # 計算式: 6 + ((1 - 1) * workers_per_extra) + 0 + 1 = 7
        assert resolve_worker_number_from_slot(settings, 1, 0) == 7

    def test_extra_window_calculation(self, settings):
        """追加ウィンドウの計算式が実コードと一致する。"""
        wpe = settings.workers_per_extra_window
        # window1, pane2: 6 + 0 + 2 + 1 = 9
        assert resolve_worker_number_from_slot(settings, 1, 2) == 9
        # window2, pane0: 6 + (1 * wpe) + 0 + 1
        assert resolve_worker_number_from_slot(settings, 2, 0) == 6 + wpe + 1
        # window2, pane3: 6 + (1 * wpe) + 3 + 1
        assert resolve_worker_number_from_slot(settings, 2, 3) == 6 + wpe + 4


class TestResolveAgentCliName:
    """resolve_agent_cli_name のテスト。"""

    def test_worker_pinned_prefers_agent_cli(self):
        """pin 済み Worker は slot/.env より agent.ai_cli を優先する。"""
        agent = _make_worker_agent()
        agent.ai_cli = AICli.CURSOR
        agent.ai_cli_pinned = True

        app_ctx = MagicMock()
        app_ctx.settings.get_worker_cli.return_value = AICli.CODEX

        assert resolve_agent_cli_name(agent, app_ctx) == "cursor"

    def test_worker_resolves_from_slot(self):
        """pin なし Worker は slot から CLI を再解決する。"""
        agent = _make_worker_agent()
        agent.ai_cli = AICli.CLAUDE  # agents.json 由来の残骸を想定

        app_ctx = MagicMock()
        app_ctx.settings.get_worker_cli.return_value = AICli.CODEX

        assert resolve_agent_cli_name(agent, app_ctx) == "codex"

    def test_worker_slot_resolution_failure_falls_back_to_agent_cli(self):
        """slot 解決が失敗したら agent.ai_cli へフォールバックする。"""
        agent = _make_worker_agent()
        agent.ai_cli = AICli.CLAUDE

        app_ctx = MagicMock()
        # get_worker_cli が ValueError を投げると agent.ai_cli へ戻る
        app_ctx.settings.get_worker_cli.side_effect = ValueError("range error")

        assert resolve_agent_cli_name(agent, app_ctx) == "claude"

    def test_worker_without_slot_uses_agent_cli(self):
        """window/pane 未確定 Worker は agent.ai_cli を使用する。"""
        agent = _make_worker_agent(window_index=None, pane_index=None)
        agent.ai_cli = AICli.AGY

        app_ctx = MagicMock()

        assert resolve_agent_cli_name(agent, app_ctx) == "agy"

    def test_non_worker_uses_agent_cli(self):
        """非 Worker は slot 解決せず agent.ai_cli を返す。"""
        agent = _make_owner_agent()
        agent.ai_cli = AICli.CLAUDE

        app_ctx = MagicMock()

        assert resolve_agent_cli_name(agent, app_ctx) == "claude"
        # 非 Worker では Worker CLI 解決を呼ばない
        app_ctx.settings.get_worker_cli.assert_not_called()

    def test_non_worker_fallback_to_default(self):
        """agent.ai_cli が未設定ならデフォルト CLI を返す。"""
        agent = _make_owner_agent()
        agent.ai_cli = None

        app_ctx = MagicMock()
        app_ctx.ai_cli.get_default_cli.return_value = AICli.CLAUDE

        assert resolve_agent_cli_name(agent, app_ctx) == "claude"

    def test_role_as_enum_value_string_is_treated_as_worker(self):
        """role が文字列("worker")でも Worker として扱う。

        Agent は ``use_enum_values=True`` のため role は内部的に文字列 "worker"
        を保持する。Enum/文字列双方を許容する比較が機能することを固定する。
        """
        agent = _make_worker_agent()
        agent.role = AgentRole.WORKER.value  # "worker"
        assert agent.role == AgentRole.WORKER.value
        agent.ai_cli = AICli.CLAUDE

        app_ctx = MagicMock()
        app_ctx.settings.get_worker_cli.return_value = AICli.CODEX

        assert resolve_agent_cli_name(agent, app_ctx) == "codex"

    def test_role_as_enum_is_treated_as_worker(self):
        """role を Enum(AgentRole.WORKER)で代入しても Worker として扱う。"""
        agent = _make_worker_agent()
        agent.role = AgentRole.WORKER
        # str Enum なので Enum/文字列いずれの比較でも一致する
        assert agent.role == AgentRole.WORKER
        agent.ai_cli = AICli.CLAUDE

        app_ctx = MagicMock()
        app_ctx.settings.get_worker_cli.return_value = AICli.CODEX

        assert resolve_agent_cli_name(agent, app_ctx) == "codex"


class TestResolveWorkerModelForCli:
    """resolve_worker_model_for_cli のテスト。"""

    def test_returns_none_when_slot_unresolved(self):
        """window/pane が None なら None を返す(healthcheck 版の None ガード)。"""
        agent = _make_worker_agent(window_index=None, pane_index=None)
        app_ctx = MagicMock()
        profile_settings = {"worker_model": "gpt-5.5"}

        assert resolve_worker_model_for_cli(app_ctx, agent, profile_settings) is None

    def test_returns_none_when_only_window_unresolved(self):
        """window のみ None でも None を返す。"""
        agent = _make_worker_agent(window_index=None, pane_index=1)
        app_ctx = MagicMock()

        assert resolve_worker_model_for_cli(app_ctx, agent, {"worker_model": "gpt-5.5"}) is None

    def test_normal_resolution(self, settings):
        """通常解決: slot から worker 番号 → モデルを解決する。"""
        agent = _make_worker_agent(window_index=0, pane_index=1)
        agent.ai_cli = AICli.CODEX
        agent.ai_cli_pinned = True

        app_ctx = MagicMock()
        app_ctx.settings = settings
        profile_settings = {"worker_model": "gpt-5.5"}

        result = resolve_worker_model_for_cli(app_ctx, agent, profile_settings)
        # codex + gpt-5.5 は互換のためそのまま返る
        assert result == "gpt-5.5"

    def test_resolution_with_explicit_cli_name(self, settings):
        """agent_cli_name を明示指定した場合はそれを使う。"""
        agent = _make_worker_agent(window_index=0, pane_index=1)

        app_ctx = MagicMock()
        app_ctx.settings = settings
        profile_settings = {"worker_model": "gpt-5.5"}

        # claude を明示指定 → gpt-5.5 は claude と非互換なので claude デフォルトへ
        result = resolve_worker_model_for_cli(
            app_ctx, agent, profile_settings, agent_cli_name="claude"
        )
        assert result == settings.get_cli_default_models()["claude"]["worker"]
