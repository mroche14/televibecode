# Technology Reference Guide

This document provides implementation details and patterns for all key technologies used in TeleVibeCode.

## Table of Contents

1. [python-telegram-bot v21+](#python-telegram-bot-v21)
2. [Agno Framework](#agno-framework)
3. [MCP Python SDK](#mcp-python-sdk)
4. [aiosqlite](#aiosqlite)
5. [Claude Code SDK](#claude-code-sdk)
6. [GitPython & Worktrees](#gitpython--worktrees)

---

## python-telegram-bot v21+

**Package**: `python-telegram-bot>=21.0`

### Async Handler Pattern

All handlers in v21 use async/await:

```python
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hello!")

app = Application.builder().token("TOKEN").build()
app.add_handler(CommandHandler("start", start))
app.run_polling()
```

### ConversationHandler

For multi-step interactions (like session creation):

```python
from telegram.ext import ConversationHandler, MessageHandler, filters

SELECTING_PROJECT, SELECTING_BRANCH = range(2)

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("new", start_new_session)],
    states={
        SELECTING_PROJECT: [MessageHandler(filters.TEXT, select_project)],
        SELECTING_BRANCH: [MessageHandler(filters.TEXT, select_branch)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)
```

### Inline Keyboard Buttons (Approvals)

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def send_approval_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{job_id}"),
            InlineKeyboardButton("❌ Deny", callback_data=f"deny:{job_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⚠️ Job requires approval:\n`git push origin main`",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Must acknowledge to prevent timeout

    action, job_id = query.data.split(":")
    if action == "approve":
        # Process approval
        await query.edit_message_text(f"✅ Job {job_id} approved!")
    else:
        await query.edit_message_text(f"❌ Job {job_id} denied.")
```

### Resources

- [Official Docs](https://docs.python-telegram-bot.org/en/v21.10/)
- [ConversationHandler](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.conversationhandler.html)
- [InlineKeyboardButton](https://docs.python-telegram-bot.org/en/v21.9/telegram.inlinekeyboardbutton.html)

---

## Agno Framework

**Package**: `agno`

Agno is a high-performance, model-agnostic framework for building AI agents. Used for the intermediate intelligence layer in TeleVibeCode.

### Installation

```bash
pip install agno
# or
uv add agno
```

### Basic Agent Setup

```python
from agno.agent import Agent
from agno.models.google import Gemini
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat

# Gemini (recommended free tier)
agent = Agent(
    name="TeleVibe Parser",
    model=Gemini(id="gemini-2.0-flash"),
    instructions="Parse user messages and extract intent.",
)

# Or use Anthropic
agent = Agent(model=Claude(id="claude-sonnet-4-5"))

# Or use OpenAI
agent = Agent(model=OpenAIChat(id="gpt-4o"))
```

### Multi-Provider Configuration

```python
import os
from agno.agent import Agent

def get_agent():
    provider = os.getenv("AGNO_PROVIDER", "gemini")
    model_id = os.getenv("AGNO_MODEL")

    if provider == "gemini":
        from agno.models.google import Gemini
        model = Gemini(id=model_id or "gemini-2.0-flash")
    elif provider == "anthropic":
        from agno.models.anthropic import Claude
        model = Claude(id=model_id or "claude-sonnet-4-5")
    elif provider == "openai":
        from agno.models.openai import OpenAIChat
        model = OpenAIChat(id=model_id or "gpt-4o-mini")
    elif provider == "openrouter":
        from agno.models.openrouter import OpenRouter
        model = OpenRouter(id=model_id or "grok-beta")

    return Agent(model=model)
```

### Key Features

- **Performance**: ~3μs agent instantiation, ~6.6KB memory per agent
- **Providers**: 23+ LLM providers supported
- **Built-in**: Memory, knowledge bases, guardrails, tools

### Resources

- [GitHub](https://github.com/agno-agi/agno)
- [Documentation](https://docs.agno.com/)
- [Quickstart](https://docs.agno.com/get-started/quickstart)

---

## MCP Python SDK

**Package**: `mcp[cli]>=1.0`

The Model Context Protocol SDK for building MCP servers that expose tools, resources, and prompts.

### Installation

```bash
uv add "mcp[cli]"
# or
pip install "mcp[cli]"
```

### FastMCP Server

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("TeleVibeCode Orchestrator")

@mcp.tool()
async def list_projects() -> list[dict]:
    """List all registered projects."""
    # Implementation
    return [{"id": "proj-1", "name": "my-app"}]

@mcp.tool()
async def run_instruction(session_id: str, instruction: str) -> dict:
    """Queue an instruction for execution in a session."""
    # Implementation
    return {"job_id": "job-123", "status": "queued"}

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

### Tools with Context

```python
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("Orchestrator")

@mcp.tool()
async def long_running_task(ctx: Context, param: str) -> str:
    """Task with progress reporting."""
    await ctx.report_progress(progress=0, total=100)
    # ... work ...
    await ctx.report_progress(progress=50, total=100)
    # ... more work ...
    await ctx.report_progress(progress=100, total=100)
    return "Complete"
```

### Resources (Read-Only Data)

```python
@mcp.resource("projects://list")
async def get_projects_resource() -> str:
    """Expose projects as a readable resource."""
    projects = await db.get_all_projects()
    return json.dumps(projects)

@mcp.resource("sessions://active")
async def get_active_sessions() -> str:
    """List active sessions."""
    sessions = await db.get_active_sessions()
    return json.dumps(sessions)
```

### Structured Output with Pydantic

```python
from pydantic import BaseModel

class JobResult(BaseModel):
    job_id: str
    status: str
    message: str

@mcp.tool()
async def get_job_status(job_id: str) -> JobResult:
    """Get status of a job."""
    job = await db.get_job(job_id)
    return JobResult(
        job_id=job.id,
        status=job.status,
        message=job.result_summary or ""
    )
```

### Resources

- [GitHub](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Specification](https://modelcontextprotocol.io/)
- [FastMCP Guide](https://modelcontextprotocol.github.io/python-sdk/)

---

## aiosqlite

**Package**: `aiosqlite>=0.20`

Async SQLite wrapper for non-blocking database operations.

### Installation

```bash
uv add aiosqlite
```

### Basic Usage

```python
import aiosqlite

async def query_example():
    async with aiosqlite.connect("state.db") as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
```

### WAL Mode & Performance Pragmas

```python
async def init_database(db_path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(db_path)

    # Enable WAL mode for better concurrency
    await db.execute("PRAGMA journal_mode = WAL")

    # Performance optimizations
    await db.execute("PRAGMA synchronous = NORMAL")
    await db.execute("PRAGMA cache_size = 10000")
    await db.execute("PRAGMA temp_store = MEMORY")
    await db.execute("PRAGMA foreign_keys = ON")

    return db
```

### Connection Manager Pattern

```python
from contextlib import asynccontextmanager

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self):
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._init_pragmas()

    async def _init_pragmas(self):
        await self._connection.execute("PRAGMA journal_mode = WAL")
        await self._connection.execute("PRAGMA foreign_keys = ON")

    async def close(self):
        if self._connection:
            await self._connection.close()

    @asynccontextmanager
    async def transaction(self):
        async with self._connection.cursor() as cursor:
            try:
                yield cursor
                await self._connection.commit()
            except Exception:
                await self._connection.rollback()
                raise
```

### Concurrency Notes

- SQLite has single-writer limitation
- Use WAL mode for concurrent reads during writes
- For high write concurrency, consider connection pooling with `aiosqlitepool`

### Resources

- [GitHub](https://github.com/omnilib/aiosqlite)
- [API Reference](https://aiosqlite.omnilib.dev/en/stable/api.html)
- [aiosqlitepool](https://github.com/slaily/aiosqlitepool) (connection pooling)

---

## Claude Code SDK

**Package**: `claude-code-sdk`

Python SDK for integrating Claude Code CLI into applications.

### Installation

```bash
pip install claude-code-sdk
# Requires: Python 3.10+, Node.js, Claude Code CLI
```

### Basic Subprocess Execution

```python
import asyncio
import json

async def run_claude_instruction(
    instruction: str,
    workspace: str
) -> dict:
    """Run Claude Code with streaming JSON output."""
    proc = await asyncio.create_subprocess_exec(
        "claude",
        "-p", instruction,
        "--output-format", "stream-json",
        cwd=workspace,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        return {
            "status": "failed",
            "error": stderr.decode()
        }

    # Parse streaming JSON (newline-delimited)
    messages = []
    for line in stdout.decode().strip().split("\n"):
        if line:
            messages.append(json.loads(line))

    return {
        "status": "success",
        "messages": messages
    }
```

### Using the SDK (Preferred)

```python
from claude_code_sdk import ClaudeSDKClient

async def run_with_sdk(instruction: str, workspace: str):
    client = ClaudeSDKClient(working_directory=workspace)

    async for message in client.stream(instruction):
        if message.type == "text":
            print(message.content)
        elif message.type == "tool_use":
            print(f"Using tool: {message.tool_name}")
        elif message.type == "error":
            print(f"Error: {message.error}")
```

### Output Formats

| Format | Use Case |
|--------|----------|
| `text` | Human-readable output |
| `json` | Single JSON response |
| `stream-json` | Real-time streaming, newline-delimited JSON |

### Error Types

- `ClaudeSDKError` - Base error
- `CLINotFoundError` - Claude Code not installed
- `CLIConnectionError` - Connection issues
- `ProcessError` - Process failed
- `CLIJSONDecodeError` - JSON parsing issues

### Resources

- [GitHub](https://github.com/anthropics/claude-code)
- [PyPI](https://pypi.org/project/claude-code-sdk/)
- [SDK Reference](https://docs.claude.com/en/docs/claude-code/sdk/sdk-python)
- [Best Practices](https://www.anthropic.com/engineering/claude-code-best-practices)

---

## GitPython & Worktrees

**Package**: `gitpython>=3.1`

Git repository management with Python. Note: GitPython lacks native worktree API but supports it via git command execution.

### Installation

```bash
uv add gitpython
```

### Basic Repository Operations

```python
from git import Repo

# Open existing repo
repo = Repo("/path/to/project")

# Get current branch
current_branch = repo.active_branch.name

# Check for uncommitted changes
is_dirty = repo.is_dirty()

# Get remote URL
remote_url = repo.remotes.origin.url
```

### Worktree Management

GitPython doesn't have high-level worktree API, use `repo.git.worktree()`:

```python
from git import Repo
import os

class WorktreeManager:
    def __init__(self, repo_path: str, worktrees_base: str):
        self.repo = Repo(repo_path)
        self.worktrees_base = worktrees_base

    def create_worktree(
        self,
        session_id: str,
        branch: str,
        create_branch: bool = True
    ) -> str:
        """Create a new worktree for a session."""
        worktree_path = os.path.join(
            self.worktrees_base,
            session_id,
            branch
        )

        os.makedirs(os.path.dirname(worktree_path), exist_ok=True)

        if create_branch:
            # Create new branch and worktree
            self.repo.git.worktree("add", "-b", branch, worktree_path)
        else:
            # Use existing branch
            self.repo.git.worktree("add", worktree_path, branch)

        return worktree_path

    def remove_worktree(self, worktree_path: str):
        """Remove a worktree."""
        self.repo.git.worktree("remove", worktree_path, "--force")

    def list_worktrees(self) -> list[dict]:
        """List all worktrees."""
        output = self.repo.git.worktree("list", "--porcelain")
        worktrees = []
        current = {}

        for line in output.split("\n"):
            if line.startswith("worktree "):
                if current:
                    worktrees.append(current)
                current = {"path": line[9:]}
            elif line.startswith("HEAD "):
                current["head"] = line[5:]
            elif line.startswith("branch "):
                current["branch"] = line[7:]

        if current:
            worktrees.append(current)

        return worktrees

    def prune_worktrees(self):
        """Remove stale worktree entries."""
        self.repo.git.worktree("prune")
```

### Session Workspace Pattern

```python
async def create_session_workspace(
    project_path: str,
    session_id: str,
    branch: str,
    workspaces_root: str
) -> str:
    """Create isolated workspace for a session."""
    manager = WorktreeManager(project_path, workspaces_root)

    # Check if branch exists
    repo = Repo(project_path)
    branch_exists = branch in [ref.name for ref in repo.refs]

    workspace_path = manager.create_worktree(
        session_id=session_id,
        branch=branch,
        create_branch=not branch_exists
    )

    return workspace_path
```

### Resources

- [GitPython Docs](https://gitpython.readthedocs.io/en/stable/)
- [Git Worktree Docs](https://git-scm.com/docs/git-worktree)
- [GitPython Worktree Issue #719](https://github.com/gitpython-developers/GitPython/issues/719)

---

## Dependency Summary

```toml
# pyproject.toml
[project]
dependencies = [
    "python-telegram-bot>=21.0",
    "agno",
    "mcp[cli]>=1.0",
    "aiosqlite>=0.20",
    "gitpython>=3.1",
    "pydantic>=2.0",
    "structlog>=24.0",
    "pyyaml>=6.0",
    "aiofiles>=24.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
    "mypy>=1.13",
]
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from @BotFather |
| `AGNO_API_KEY` | Yes | API key for LLM provider |
| `AGNO_PROVIDER` | Yes | `gemini`, `anthropic`, `openai`, `openrouter` |
| `AGNO_MODEL` | No | Model ID override |
