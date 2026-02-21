# Multi-Agent MCP - Agent Instructions

This file provides instructions for AI agents (Admin/Worker) spawned by the Multi-Agent MCP server.
For full project documentation, see CLAUDE.md.

## Role Responsibilities

- **Owner**: Orchestrates the workflow, creates tasks, monitors progress
- **Admin**: Manages workers, handles complex decisions, coordinates tasks
- **Worker**: Executes individual tasks in isolated environments

## Critical Rules

### IPC Communication (EVENT-DRIVEN)

- Admin↔Worker communication is EVENT-DRIVEN via tmux `send_keys_to_pane()`.
- React to `[IPC] 新しいメッセージ` notifications — NO polling loops.
- `while True: read_messages()` is **FORBIDDEN**.

### Agent State

- Agent data persists to `agents.json` — file is the source of truth.
- On terminate: set `status` to `TERMINATED` — NEVER delete agent resources.
- Use `sync_agents_from_file()` before cross-instance operations.

### Dashboard

- Dashboard uses YAML Front Matter + Markdown (`dashboard.md`).
- Multi-process safe: reads/writes file on every operation.

## Development Commands

```bash
uv run pytest           # Run tests
uv run ruff check src/  # Lint
uv run ruff format src/ # Format
```

## Code Style

- Type hints for all function parameters and return values
- `str | None` syntax (not `Optional[str]`)
- Docstrings in Japanese (Google style)
- Line length: 100 characters max

## Testing Rules

- ALWAYS run `uv run pytest` after changes.
- NEVER leave failing tests — fix before moving on.
- Verify fixes don't break existing tests.

## Code Accuracy

- Verify architectural claims against actual code before documenting.
- Do NOT leave misleading comments.
- Flag stale artifacts from previous sessions.
