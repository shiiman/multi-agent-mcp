"""Claude statusLine から実測コストを取り込むヘルパー。"""

from __future__ import annotations

import re
from typing import Any

from src.models.agent import Agent, AgentRole
from src.tools.agent_helpers import resolve_worker_number_from_slot
from src.tools.helpers import ensure_dashboard_manager
from src.tools.model_profile import get_current_profile_settings


def extract_claude_statusline_cost(output: str) -> tuple[float, str] | None:
    """Claude の statusLine からコスト値を抽出する。"""
    patterns = (
        r"💰\s*\$\s*([0-9]+(?:\.[0-9]+)?)",
        r"(?:cost|Cost|COST)[^$\n]*\$\s*([0-9]+(?:\.[0-9]+)?)",
        r"\$\s*([0-9]+(?:\.[0-9]+)?)\s*(?:cost|Cost|COST)",
    )
    for line in reversed(output.splitlines()):
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                try:
                    return float(match.group(1)), line.strip()
                except ValueError:
                    continue
    return None


async def capture_claude_actual_cost_for_agent(
    app_ctx: Any,
    agent: Agent,
    task_id: str | None = None,
    capture_lines: int = 80,
) -> dict[str, Any] | None:
    """対象エージェントの pane から Claude 実測コストを取り込む。"""
    agent_cli = agent.ai_cli or app_ctx.ai_cli.get_default_cli()
    cli_value = agent_cli.value if hasattr(agent_cli, "value") else str(agent_cli)
    if cli_value != "claude":
        return None
    if agent.session_name is None or agent.window_index is None or agent.pane_index is None:
        return None

    output = await app_ctx.tmux.capture_pane_by_index(
        agent.session_name,
        agent.window_index,
        agent.pane_index,
        capture_lines,
    )
    parsed = extract_claude_statusline_cost(output)
    if not parsed:
        return None

    actual_cost_usd, status_line = parsed
    dashboard = ensure_dashboard_manager(app_ctx)
    latest_calls = dashboard.get_dashboard().cost.calls[-50:]
    already_recorded = any(
        c.agent_id == agent.id and c.status_line == status_line for c in latest_calls
    )
    if already_recorded:
        return {
            "updated": False,
            "actual_cost_usd": actual_cost_usd,
            "status_line": status_line,
            "task_id": task_id or agent.current_task,
        }

    profile_settings = get_current_profile_settings(app_ctx)
    if str(agent.role) == AgentRole.ADMIN.value:
        model = profile_settings.get("admin_model")
    else:
        worker_no = resolve_worker_number_from_slot(
            app_ctx.settings,
            agent.window_index,
            agent.pane_index,
        )
        model_default = profile_settings.get("worker_model")
        model = app_ctx.settings.get_worker_model(worker_no, model_default)

    dashboard.record_api_call(
        ai_cli="claude",
        model=model,
        estimated_tokens=app_ctx.settings.estimated_tokens_per_call,
        agent_id=agent.id,
        task_id=task_id or agent.current_task,
        actual_cost_usd=actual_cost_usd,
        status_line=status_line,
        cost_source="actual",
    )

    return {
        "updated": True,
        "actual_cost_usd": actual_cost_usd,
        "status_line": status_line,
        "task_id": task_id or agent.current_task,
    }
