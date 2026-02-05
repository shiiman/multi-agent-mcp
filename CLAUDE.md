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
- **Health Monitoring**: Heartbeat-based agent health checks with auto-recovery
- **Metrics Collection**: Track task completion, duration, and success rates
- **Cost Estimation**: Estimate API costs across different AI providers

## Project Structure

```
multi-agent-mcp/
├── src/
│   ├── server.py              # MCP server entry point (FastMCP, ~70 lines)
│   ├── context.py             # AppContext definition
│   ├── config/
│   │   ├── settings.py        # Pydantic Settings configuration
│   │   ├── templates.py       # Workspace templates
│   │   ├── template_loader.py # Template loading with caching
│   │   └── workflow_guides.py # Role-based workflow guides
│   ├── models/
│   │   ├── agent.py           # Agent, AgentRole, AgentStatus
│   │   ├── dashboard.py       # Dashboard, TaskInfo
│   │   ├── message.py         # Message, MessageType
│   │   └── workspace.py       # WorktreeInfo
│   ├── managers/
│   │   ├── tmux_manager.py    # Tmux session management
│   │   ├── agent_manager.py   # Agent lifecycle management
│   │   ├── worktree_manager.py # Git worktree management
│   │   ├── ai_cli_manager.py  # AI CLI selection and execution
│   │   ├── gtrconfig_manager.py # .gtrconfig detection/generation
│   │   ├── scheduler_manager.py # Task priority queue
│   │   ├── healthcheck_manager.py # Agent health monitoring
│   │   ├── metrics_manager.py # Statistics collection
│   │   ├── cost_manager.py    # API cost tracking
│   │   ├── ipc_manager.py     # Inter-process communication
│   │   ├── dashboard_manager.py # Dashboard state management
│   │   ├── memory_manager.py  # Persistent knowledge management
│   │   ├── persona_manager.py # Task-based persona optimization
│   │   └── terminal/          # Terminal app implementations
│   │       ├── base.py        # Abstract base class
│   │       ├── ghostty.py     # Ghostty terminal support
│   │       ├── iterm2.py      # iTerm2 terminal support
│   │       └── terminal_app.py # macOS Terminal.app support
│   └── tools/                 # MCP tool definitions (89 tools)
│       ├── __init__.py        # register_all_tools()
│       ├── helpers.py         # Common helper functions
│       ├── session.py         # Session management (4 tools)
│       ├── agent.py           # Agent management (6 tools)
│       ├── command.py         # Command execution (5 tools)
│       ├── worktree.py        # Git worktree (7 tools)
│       ├── ipc.py             # IPC/messaging (5 tools)
│       ├── dashboard.py       # Dashboard/task management (10 tools)
│       ├── gtrconfig.py       # Gtrconfig (3 tools)
│       ├── template.py        # Templates (4 tools)
│       ├── scheduler.py       # Scheduler (3 tools)
│       ├── healthcheck.py     # Healthcheck (5 tools)
│       ├── metrics.py         # Metrics (4 tools)
│       ├── cost.py            # Cost management (4 tools)
│       ├── persona.py         # Persona (3 tools)
│       ├── memory.py          # Memory management (19 tools)
│       ├── screenshot.py      # Screenshot management (4 tools)
│       ├── model_profile.py   # Model profile (3 tools)
│       └── task_templates.py  # Task template generation (helper module)
├── templates/                 # Templates for agents and scripts
│   ├── roles/                 # Role-based workflow guides (owner, admin, worker)
│   ├── tasks/                 # Task instruction templates (admin_task, admin_task_no_worktree, worker_task)
│   └── scripts/               # Script templates
│       └── bash/              # Bash scripts (workspace_setup.sh)
├── tests/                     # Pytest test files
├── pyproject.toml
└── README.md
```

## Tech Stack

- **Python**: 3.10+
- **MCP**: FastMCP pattern
- **Pydantic**: v2 with ConfigDict
- **TOML**: tomli/tomli-w for .gtrconfig
- **Testing**: pytest with pytest-asyncio
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
- Each category has its own module (e.g., `session.py`, `agent.py`)
- Tools are registered via `register_tools(mcp)` function in each module
- `src/tools/__init__.py` provides `register_all_tools(mcp)` to register all tools
- Return structured data (dict) for complex responses
- Error handling with descriptive messages

### Agent Roles

- **Owner**: Orchestrates the entire workflow, creates tasks
- **Admin**: Manages workers, handles complex decisions
- **Worker**: Executes individual tasks

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MCP_MAX_WORKERS` | Maximum number of worker agents | 6 |
| `MCP_TMUX_PREFIX` | Prefix for tmux session names | multi-agent-mcp |
| `MCP_ENABLE_WORKTREE` | Enable git worktree for workers | true |
| `MCP_COST_WARNING_THRESHOLD_USD` | Cost warning threshold | 10.0 |
| `MCP_HEALTHCHECK_INTERVAL_SECONDS` | Healthcheck interval (no response = unhealthy) | 60 |
| `MCP_MODEL_PROFILE_ACTIVE` | Current model profile | standard |
| `MCP_MODEL_PROFILE_STANDARD_CLI` | Standard profile AI CLI | claude |
| `MCP_MODEL_PROFILE_STANDARD_ADMIN_MODEL` | Standard profile Admin model | claude-opus-4-20250514 |
| `MCP_MODEL_PROFILE_STANDARD_WORKER_MODEL` | Standard profile Worker model | claude-sonnet-4-20250514 |
| `MCP_MODEL_PROFILE_STANDARD_MAX_WORKERS` | Standard profile max workers | 6 |
| `MCP_MODEL_PROFILE_STANDARD_THINKING_MULTIPLIER` | Standard thinking multiplier | 1.0 |
| `MCP_MODEL_PROFILE_PERFORMANCE_CLI` | Performance profile AI CLI | claude |
| `MCP_MODEL_PROFILE_PERFORMANCE_ADMIN_MODEL` | Performance profile Admin model | claude-opus-4-20250514 |
| `MCP_MODEL_PROFILE_PERFORMANCE_WORKER_MODEL` | Performance profile Worker model | claude-opus-4-20250514 |
| `MCP_MODEL_PROFILE_PERFORMANCE_MAX_WORKERS` | Performance profile max workers | 16 |
| `MCP_MODEL_PROFILE_PERFORMANCE_THINKING_MULTIPLIER` | Performance thinking multiplier | 2.0 |
| `MCP_PROJECT_ROOT` | Project root for .env loading | - |
| `MCP_OWNER_THINKING_TOKENS` | Owner thinking tokens | 0 |
| `MCP_ADMIN_THINKING_TOKENS` | Admin thinking tokens | 1000 |
| `MCP_WORKER_THINKING_TOKENS` | Worker thinking tokens | 10000 |
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
