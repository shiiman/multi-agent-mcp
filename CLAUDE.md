# Multi-Agent MCP Server

An MCP (Model Context Protocol) server that enables parallel AI agent workflows using tmux and git worktree.

## Project Overview

This project provides an MCP server that allows Claude Code (or other AI CLIs) to manage multiple parallel agents, each running in separate tmux sessions with isolated git worktrees.

### Key Features

- **Multi-Agent Management**: Create and manage multiple AI agents with different roles (Owner, Admin, Worker)
- **Tmux Integration**: Each agent runs in an isolated tmux session
- **Git Worktree Support**: Parallel development with isolated working directories
- **AI CLI Selection**: Support for Claude Code, Codex, and Gemini CLI
- **Task Scheduling**: Priority-based task queue with dependency management
- **Health Monitoring**: Stall/tmux死活監視 + 自動復旧 + daemon運用
- **Cost Tracking**: API cost tracking integrated into Dashboard

## Project Structure

```text
multi-agent-mcp/
├── src/
│   ├── server.py                # MCP server entry point (FastMCP)
│   ├── context.py               # AppContext definition
│   ├── config/
│   │   ├── settings.py          # Pydantic Settings configuration
│   │   ├── templates.py         # Workspace templates
│   │   ├── template_loader.py   # Template loading with caching
│   │   ├── workflow_guides.py   # Role-based workflow guides
│   │   └── role_permissions.py  # Role-based permission definitions
│   ├── models/
│   │   ├── agent.py             # Agent, AgentRole, AgentStatus
│   │   ├── dashboard.py         # Dashboard, TaskInfo
│   │   ├── message.py           # Message, MessageType
│   │   └── workspace.py         # WorktreeInfo
│   ├── managers/
│   │   ├── tmux_manager.py      # Tmux session management
│   │   ├── tmux_workspace_mixin.py # Tmux workspace layout helpers
│   │   ├── tmux_shared.py       # Shared tmux utilities
│   │   ├── agent_manager.py     # Agent lifecycle management
│   │   ├── worktree_manager.py  # Git worktree management
│   │   ├── ai_cli_manager.py    # AI CLI selection and execution
│   │   ├── gtrconfig_manager.py # .gtrconfig detection/generation
│   │   ├── scheduler_manager.py # Task priority queue
│   │   ├── healthcheck_manager.py # Agent health monitoring
│   │   ├── healthcheck_daemon.py # Background monitor loop
│   │   ├── ipc_manager.py       # Inter-process communication
│   │   ├── dashboard_manager.py  # Dashboard state management
│   │   ├── dashboard_markdown_mixin.py # Dashboard Markdown rendering
│   │   ├── dashboard_rendering_mixin.py # Dashboard output rendering
│   │   ├── dashboard_sync_mixin.py # Dashboard sync/message helpers
│   │   ├── dashboard_tasks_mixin.py # Dashboard task file management
│   │   ├── dashboard_cost.py    # Cost calculation helpers
│   │   ├── memory_manager.py    # Persistent knowledge management
│   │   ├── persona_manager.py   # Task-based persona optimization
│   │   └── terminal/            # Terminal app implementations
│   │       ├── base.py          # Abstract base class
│   │       ├── ghostty.py       # Ghostty terminal support
│   │       ├── iterm2.py        # iTerm2 terminal support
│   │       └── terminal_app.py  # macOS Terminal.app support
│   └── tools/                   # MCP tool definitions (86 tools)
│       ├── __init__.py          # register_all_tools()
│       ├── helpers.py           # Compatibility exports + permission helpers
│       ├── helpers_git.py        # Git worktree root resolution helpers
│       ├── helpers_managers.py  # Manager initialization helpers
│       ├── helpers_registry.py  # Registry/config JSON helpers
│       ├── helpers_persistence.py # Agent persistence helpers
│       ├── session.py           # Session entry module (re-export)
│       ├── session_tools.py     # Session tools (4)
│       ├── session_env.py       # Session .env/template helpers
│       ├── session_state.py     # Session state helpers
│       ├── agent.py             # Agent entry module (re-export)
│       ├── agent_tools.py       # Agent tool registration entry
│       ├── agent_lifecycle_tools.py # Agent lifecycle tools (5)
│       ├── agent_batch_tools.py # Batch worker tools (1)
│       ├── agent_helpers.py     # Worker dispatch/task helpers
│       ├── command.py           # Command execution (5)
│       ├── cost_capture.py      # Claude actual cost capture
│       ├── worktree.py          # Git worktree (7)
│       ├── merge.py             # Merge completed task branches (1)
│       ├── ipc.py               # IPC/messaging (4)
│       ├── dashboard.py         # Dashboard/task tools (10)
│       ├── dashboard_cost_tools.py # Cost tools (4)
│       ├── gtrconfig.py         # Gtrconfig (3)
│       ├── template.py          # Templates (4)
│       ├── scheduler.py         # Scheduler (3)
│       ├── healthcheck.py       # Healthcheck (6)
│       ├── persona.py           # Persona (3)
│       ├── memory.py            # Project memory + archive (10)
│       ├── memory_global.py     # Global memory + archive (9)
│       ├── screenshot.py        # Screenshot management (4)
│       ├── model_profile.py     # Model profile (3)
│       └── task_templates.py    # Task template generation (helper module)
├── templates/                   # Templates for agents and scripts
│   ├── roles/                   # Role-based workflow guides (owner, admin, worker)
│   ├── tasks/                   # Task instruction templates
│   └── scripts/                 # Script templates
│       └── bash/                # Bash scripts (workspace_setup.sh)
├── tests/                       # Pytest test files
├── pyproject.toml
└── README.md
```

## Tech Stack

- **Python**: 3.10+
- **MCP**: FastMCP pattern
- **Pydantic**: v2 with ConfigDict
- **TOML**: tomli/tomli-w for .gtrconfig
- **Testing**: pytest with pytest-asyncio, pytest-cov
- **Linting**: ruff

## Development Commands

```bash
# Install dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_scheduler_manager.py

# Run tests with coverage report
uv run pytest --cov=src

# Lint code
uv run ruff check src/

# Format code
uv run ruff format src/

# Run the MCP server
uv run multi-agent-mcp
```

## Code Style Guidelines

### Python

- Use type hints for all function parameters and return values
- Use `|` syntax for union types (e.g., `str | None` instead of `Optional[str]`)
- Docstrings in Japanese with Google style format
- Line length: 100 characters max
- Import order: stdlib, third-party, local (managed by ruff)

### Pydantic Models

- Use `ConfigDict` instead of inner `Config` class
- Use `Field()` for field metadata and defaults
- Prefer `model_dump()` over `dict()` method

### Async Code

- Manager methods that interact with tmux are async
- Use `await` for all async operations
- Tests use `@pytest.mark.asyncio` decorator

### Testing

- Each manager has its own test file (`test_<manager_name>.py`)
- Use fixtures from `conftest.py`
- Test file naming: `test_<module_name>.py`
- Test class naming: `Test<ClassName>`
- Test method naming: `test_<method_name>_<scenario>`

## Architecture Notes

### Manager Pattern

All managers follow a consistent pattern:
- Constructor takes dependencies (other managers, settings)
- Public methods return typed results
- Private methods prefixed with `_`
- Each manager is responsible for a single domain

### MCP Tools

Tools are defined in `src/tools/` modules using FastMCP decorators:
- Entry modules can delegate to split modules (e.g., `session.py` -> `session_tools.py`)
- Agent tools are composed via `agent_tools.py` -> `agent_lifecycle_tools.py` / `agent_batch_tools.py`
- Tools are registered via `register_tools(mcp)` function in each module
- `src/tools/__init__.py` provides `register_all_tools(mcp)` to register all tools
- Return structured data (dict) for complex responses
- Error handling with descriptive messages

### Agent Roles

- **Owner**: Orchestrates the entire workflow, creates tasks
- **Admin**: Manages workers, handles complex decisions
- **Worker**: Executes individual tasks

## Multi-Agent Architecture Rules

### IPC Notification (EVENT-DRIVEN)

- Admin↔Worker communication is EVENT-DRIVEN via tmux `send_keys_to_pane()`.
- When a message is sent, `src/tools/ipc.py` automatically sends `[IPC] 新しいメッセージ` via tmux to the receiver's pane.
- Admin/Worker react to IPC notifications — NO polling loops (`while True: read_messages()` is FORBIDDEN).
- Owner without tmux pane receives macOS native notification instead.
- Healthcheck polling is the ONLY exception (checking agent liveness).

### Agent State Management

- Agent data is persisted to `agents.json` file via `save_agent_to_file()` / `load_agents_from_file()` in `src/tools/helpers.py`.
- AgentManager holds in-memory cache but file is the source of truth across MCP instances.
- `sync_agents_from_file()` synchronizes file → memory before cross-instance operations.
- On terminate: change `status` to `TERMINATED` — NEVER delete the agent resource.
- On IPC busy state: implement lock/wait mechanism — NEVER skip notifications.

### Dashboard Persistence

- Dashboard uses YAML Front Matter + Markdown format (`dashboard.md`).
- NO in-memory caching — reads/writes file on every operation for multi-process safety.
- `src/managers/dashboard_manager.py` handles all Dashboard I/O.

### Testing Rules

- ALWAYS run `uv run pytest` after making changes.
- NEVER leave failing tests — fix immediately before moving to other work.
- If tests fail, debug and fix before reporting success.
- Verify fixes don't break existing tests.

### Code Accuracy

- Verify architectural claims against the actual codebase before documenting.
- Do NOT leave misleading comments (e.g., describing polling when the system is event-driven).
- If you find stale artifacts from previous sessions, flag the discrepancy.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MCP_MCP_DIR` | MCP working directory name | .multi-agent-mcp |
| `MCP_MAX_WORKERS` | Maximum number of worker agents | 6 |
| `MCP_ENABLE_WORKTREE` | Enable git worktree for workers | true |
| `MCP_WINDOW_NAME_MAIN` | Main tmux window name (Admin + Worker 1-6) | main |
| `MCP_WINDOW_NAME_WORKER_PREFIX` | Prefix for extra worker windows | workers- |
| `MCP_COST_WARNING_THRESHOLD_USD` | Cost warning threshold | 10.0 |
| `MCP_HEALTHCHECK_INTERVAL_SECONDS` | Healthcheck monitor interval (seconds) | 60 |
| `MCP_HEALTHCHECK_STALL_TIMEOUT_SECONDS` | Stall detection timeout (seconds) | 600 |
| `MCP_HEALTHCHECK_MAX_RECOVERY_ATTEMPTS` | Max recovery attempts per worker/task | 3 |
| `MCP_HEALTHCHECK_IDLE_STOP_CONSECUTIVE` | Consecutive idle detections to auto-stop daemon | 3 |
| `MCP_DEFAULT_TERMINAL` | Default terminal app | auto |
| `MCP_MODEL_PROFILE_ACTIVE` | Current model profile | standard |
| `MCP_MODEL_PROFILE_STANDARD_CLI` | Standard profile AI CLI | claude |
| `MCP_MODEL_PROFILE_STANDARD_ADMIN_MODEL` | Standard profile Admin model | opus |
| `MCP_MODEL_PROFILE_STANDARD_WORKER_MODEL` | Standard profile Worker model | sonnet |
| `MCP_MODEL_PROFILE_STANDARD_MAX_WORKERS` | Standard profile max workers | 6 |
| `MCP_MODEL_PROFILE_STANDARD_ADMIN_THINKING_TOKENS` | Standard Admin thinking tokens | 4000 |
| `MCP_MODEL_PROFILE_STANDARD_WORKER_THINKING_TOKENS` | Standard Worker thinking tokens | 4000 |
| `MCP_MODEL_PROFILE_PERFORMANCE_CLI` | Performance profile AI CLI | claude |
| `MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_MODEL` | Performance profile Admin model | opus |
| `MCP_MODEL_PROFILE_PERFORMANCE_WORKER_MODEL` | Performance profile Worker model | opus |
| `MCP_MODEL_PROFILE_PERFORMANCE_MAX_WORKERS` | Performance profile max workers | 16 |
| `MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_THINKING_TOKENS` | Performance Admin thinking tokens | 30000 |
| `MCP_MODEL_PROFILE_PERFORMANCE_WORKER_THINKING_TOKENS` | Performance Worker thinking tokens | 4000 |
| `MCP_PROJECT_ROOT` | Project root for .env loading | - |
| `MCP_CLI_DEFAULT_CLAUDE_ADMIN_MODEL` | Claude CLI Admin default model | opus |
| `MCP_CLI_DEFAULT_CLAUDE_WORKER_MODEL` | Claude CLI Worker default model | sonnet |
| `MCP_CLI_DEFAULT_CODEX_ADMIN_MODEL` | Codex CLI Admin default model | gpt-5.3-codex |
| `MCP_CLI_DEFAULT_CODEX_WORKER_MODEL` | Codex CLI Worker default model | gpt-5.3-codex |
| `MCP_CLI_DEFAULT_GEMINI_ADMIN_MODEL` | Gemini CLI Admin default model | gemini-3-pro |
| `MCP_CLI_DEFAULT_GEMINI_WORKER_MODEL` | Gemini CLI Worker default model | gemini-3-flash |
| `MCP_WORKER_CLI_MODE` | Worker CLI mode (`uniform` / `per-worker`) | uniform |
| `MCP_WORKER_CLI_UNIFORM` | Uniform Worker CLI value | claude |
| `MCP_WORKER_MODEL_MODE` | Worker model mode (`uniform` / `per-worker`) | uniform |
| `MCP_WORKER_MODEL_UNIFORM` | Uniform Worker model value (falls back to profile worker model) | - |
| `MCP_QUALITY_CHECK_MAX_ITERATIONS` | Max quality check iterations | 5 |
| `MCP_QUALITY_CHECK_SAME_ISSUE_LIMIT` | Same issue repeat limit | 3 |
| `MCP_MEMORY_MAX_ENTRIES` | Max memory entries | 1000 |
| `MCP_MEMORY_TTL_DAYS` | Memory entry TTL in days | 90 |

## Common Patterns

### Adding a New Manager

1. Create `src/managers/<name>_manager.py`
2. Add to `src/managers/__init__.py`
3. Create fixture in `tests/conftest.py`
4. Create `tests/test_<name>_manager.py`
5. Add MCP tools in `server.py`

### Adding a New MCP Tool

1. Choose the appropriate module in `src/tools/` (or create a new one)
2. Define the tool function inside `register_tools(mcp)` using `@mcp.tool()` decorator
3. Add proper type hints and docstring
4. Return structured dict for complex responses
5. If creating a new module, add import and call in `src/tools/__init__.py`

Example tool module structure:

```python
# src/tools/example.py
from mcp.server.fastmcp import Context, FastMCP
from src.context import AppContext

def register_tools(mcp: FastMCP) -> None:
    """Register example tools."""

    @mcp.tool()
    async def example_tool(param: str, ctx: Context = None) -> dict:
        """Tool description."""
        app_ctx: AppContext = ctx.request_context.lifespan_context
        # Implementation
        return {"success": True, "result": "..."}
```
