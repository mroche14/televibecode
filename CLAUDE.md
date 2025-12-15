# CLAUDE.md - TeleVibeCode Project Guide

## Project Overview

TeleVibeCode is a remote orchestration harness for managing multiple Claude Code + SuperClaude sessions via Telegram. It enables developers to control parallel AI coding sessions from their mobile devices with project management, task tracking, approval gating, and real-time monitoring.

**Repository**: https://github.com/mroche14/televibecode

## Tech Stack

- **Language**: Python 3.12+
- **Package Manager**: uv (not pip)
- **Database**: SQLite with aiosqlite (async)
- **API Pattern**: MCP (Model Context Protocol) - no REST API
- **Bot Framework**: python-telegram-bot
- **Data Validation**: Pydantic v2
- **Testing**: pytest + pytest-asyncio
- **Linting/Formatting**: ruff
- **Type Checking**: mypy

## Quick Commands

```bash
# Install dependencies
uv sync

# Run the server
uv run televibecode serve --root ~/projects

# Run tests
uv run pytest

# Lint and format
uv run ruff check .
uv run ruff format .

# Type check
uv run mypy src/
```

## Project Structure

```
src/televibecode/
├── __init__.py          # Package init (version)
├── main.py              # CLI entry point
├── config.py            # Configuration loading
├── db/
│   ├── models.py        # Pydantic data models
│   └── database.py      # SQLite async CRUD
├── ai/
│   ├── models.py        # AI provider/model registry (Gemini, OpenRouter, Groq, Cerebras)
│   ├── tool_tester.py   # Empirical tool calling tests
│   ├── agent.py         # Conversational AI agent
│   └── transcription.py # Voice transcription (Groq Whisper)
├── orchestrator/
│   ├── server.py        # MCP server
│   └── tools/           # MCP tool handlers
├── telegram/
│   ├── bot.py           # Bot setup
│   ├── handlers.py      # Command handlers
│   └── state.py         # Per-chat state management
└── runner/
    ├── executor.py      # Job execution (subprocess)
    └── sdk_executor.py  # Job execution (Claude Agent SDK)
```

## Architecture

**Core Principle**: Telegram only talks to the Orchestrator MCP.

```
Telegram Bot <-> Orchestrator MCP <-> Sessions / Repos / Tasks / Claude Code
```

**Layers**:
- Layer 0: Claude Code CLI + SuperClaude Framework
- Layer 1: Orchestrator MCP + Telegram Bot + Runner
- Layer 2: Backlog.md task management per repo
- Layer 3: Multi-agent orchestration

**Data Layout**:
```
~/projects/                    # User's existing projects
├── .televibe/                 # TeleVibeCode artifacts
│   ├── state.db              # SQLite database
│   ├── config.yaml           # Configuration
│   ├── logs/                 # Job logs
│   └── workspaces/           # Git worktrees per session
├── project-a/                # Unmodified user repos
└── project-b/
```

## AI Providers

TeleVibeCode supports multiple AI providers for natural language processing:

| Provider | Env Variable | Use Case |
|----------|--------------|----------|
| **Gemini** | `GEMINI_API_KEY` | Recommended default, long context |
| **OpenRouter** | `OPENROUTER_API_KEY` | Access to many free models |
| **Groq** | `GROQ_API_KEY` | Ultra-fast inference + voice transcription |
| **Cerebras** | `CEREBRAS_API_KEY` | Fastest inference available |

Models are fetched dynamically from each provider's API. Use `/models` in Telegram to:
- View all available models with tool support indicators (🔧)
- Filter by provider: 💎 Gemini, 🌐 OpenRouter, ⚡ Groq, 🧠 Cerebras
- Run tool tests (🧪) to verify function calling support
- Refresh model lists (🔄) from APIs

Tool test results are cached in `~/.televibe/tool_test_results.json`.

## Code Style

- **Line length**: 88 characters
- **Ruff rules**: E, F, I, UP, B, SIM (errors, flake8, isort, upgrade, bugbear, simplify)
- **Async-first**: All I/O operations use async/await
- **Type hints**: Required on all public functions
- **Docstrings**: Google style for public APIs

## Core Entities

> **📖 See [docs/data-models.md](docs/data-models.md#core-concepts-projects-sessions-branches-worktrees-and-jobs) for detailed entity relationships.**

| Entity | ID Format | Description |
|--------|-----------|-------------|
| Project | slug | Git repository (e.g., `my-web-app`) |
| Session | project_timestamp | Git worktree + branch (e.g., `my-web-app_20241214_153042`) |
| Task | T-123 | Backlog item from Backlog.md |
| Job | UUID | Single Claude Code execution in a session |

**Critical relationships:**
- **Project → Session**: 1:N (max 10 sessions per project)
- **Session → Branch/Worktree**: 1:1 (each session has exactly one branch)
- **Session → Job**: 1:N (jobs run sequentially, one at a time)
- Sessions use **git worktrees** for isolation - changes in one session don't affect others

## Key Patterns

### Async Database Operations
```python
async with aiosqlite.connect(db_path) as db:
    db.row_factory = aiosqlite.Row
    async with db.execute(query, params) as cursor:
        rows = await cursor.fetchall()
```

### MCP Tool Structure
```python
@mcp.tool()
async def tool_name(param: str) -> ToolResult:
    """Tool description."""
    # Implementation
    return ToolResult(content=[TextContent(text="result")])
```

### Job Execution
```python
proc = await asyncio.create_subprocess_exec(
    "claude", "-p", instruction, "--output-format", "stream-json",
    cwd=workspace_path,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

## Important Files

- `docs/architecture.md` - System design and layers
- `docs/data-models.md` - Entity schemas and SQLite DDL
- `docs/orchestrator-mcp.md` - MCP tool specifications (20+ tools)
- `docs/telegram-bot.md` - Commands and UX patterns
- `docs/requirements.md` - NFRs and acceptance criteria
- `docs/roadmap.md` - 6-phase development plan

## Development Guidelines

1. **Async everywhere**: Never use blocking I/O in the main event loop
2. **MCP-first**: All operations exposed as MCP tools, not REST
3. **Git worktree isolation**: Each session gets its own worktree
4. **Approval gating**: Dangerous operations (shell, push, deploy) require approval
5. **Structured logging**: Use structlog for all logging
6. **Error handling**: Jobs should fail gracefully with clear error messages

## Configuration Guidelines

When adding new configurable settings:

1. **Telegram-first configuration**: All user-facing config should be controllable via Telegram commands, not just environment variables. Users should be able to adjust settings without restarting the bot.

2. **Database storage for preferences**: Per-chat settings should be stored in the `user_preferences` table using the appropriate columns. Use JSON for complex nested configs.

3. **Default presets**: For multi-option configs (like tracker display), provide named presets (minimal, normal, verbose) that users can switch between easily.

4. **Careful additions**: Before adding new config options:
   - Consider if it's truly user-facing (needs Telegram UI) vs deployment-only (env var is fine)
   - Ensure sensible defaults that work without configuration
   - Document the option in the relevant Telegram command's help text
   - Add database migration if extending user_preferences schema

5. **Config locations**:
   - **Environment variables (.env)**: API keys, security settings, deployment config
   - **user_preferences table**: Per-chat preferences (model, tracker config, display settings)
   - **TrackerConfig/presets**: Complex structured settings with sensible defaults

## SuperClaude Commands

Use `/sc` commands proactively when relevant, even if not explicitly requested:

| When to use | Command |
|-------------|---------|
| Implementing features | `/sc:implement` |
| Building/compiling | `/sc:build` |
| Running tests | `/sc:test` |
| Code quality review | `/sc:analyze` |
| Debugging issues | `/sc:troubleshoot` |
| Git operations | `/sc:git` |
| Refactoring/cleanup | `/sc:cleanup` or `/sc:improve` |
| Generating docs | `/sc:document` |
| Explaining code | `/sc:explain` |
| Planning architecture | `/sc:design` |
| Breaking down tasks | `/sc:workflow` or `/sc:spawn` |
| Estimating work | `/sc:estimate` |
| Exploring requirements | `/sc:brainstorm` |

**Useful flags**:
- `--think` / `--think-hard` / `--ultrathink` - deeper analysis
- `--delegate auto` - parallel processing for large operations
- `--validate` - risk assessment before execution
- `--safe-mode` - conservative execution for critical operations

Match commands to intent, not just explicit requests.

## Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=televibecode

# Run specific test file
uv run pytest tests/test_database.py

# Run async tests
uv run pytest -v tests/test_async.py
```

## Current Status

**Phase**: Early implementation (Phase 1 - Foundation)

**Completed**: Architecture specs, data models, project structure

**In Progress**: Core database layer, MCP server skeleton

## Constraints

- Concurrent jobs limit: 3
- Max sessions per project: 10
- Total active sessions: 50
- Instruction length: 10,000 chars
- Job log size: 100 MB
