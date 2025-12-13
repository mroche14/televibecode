# TeleVibeCode Implementation Workflow

## Executive Summary

This workflow provides step-by-step implementation guidance for building TeleVibeCode across 6 phases. Each task includes file targets, dependencies, and verification criteria.

**Total Phases**: 6
**MVP**: Phases 1-4
**Production**: Phases 5-6

---

## Phase 1: Foundation

**Goal**: Core orchestrator + basic Telegram bot
**Milestone M1**: `/projects` works in Telegram

### 1.1 Dependencies & Structure

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 1.1.1 | Add core dependencies to pyproject.toml | `pyproject.toml` | `uv sync` succeeds |
| 1.1.2 | Create package directories | `src/televibecode/{db,orchestrator,telegram,runner}/` | Directories exist |
| 1.1.3 | Create `__init__.py` files | All subpackages | `uv run python -c "import televibecode"` works |

**Dependencies to add**:
```toml
dependencies = [
    "pydantic>=2.0",
    "aiosqlite>=0.20",
    "mcp[cli]>=1.0",
    "python-telegram-bot>=21.0",
    "gitpython>=3.1",
    "structlog>=24.0",
    "pyyaml>=6.0",
    "aiofiles>=24.0",
    "python-dotenv>=1.0",
    "agno",
]
```

### 1.2 Configuration System

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 1.2.1 | Create Pydantic settings model | `src/televibecode/config.py` | Model validates |
| 1.2.2 | Load from env + .env file | `src/televibecode/config.py` | `TELEGRAM_BOT_TOKEN` loads |
| 1.2.3 | Add startup validation | `src/televibecode/main.py` | Missing vars show helpful error |

**Config fields**:
- `TELEGRAM_BOT_TOKEN` (required)
- `AGNO_API_KEY` (required)
- `AGNO_PROVIDER` (required: gemini/anthropic/openai/openrouter)
- `AGNO_MODEL` (optional)
- `TELEVIBE_ROOT` (default: cwd)
- `LOG_LEVEL` (default: INFO)

### 1.3 Database Layer

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 1.3.1 | Create Pydantic models | `src/televibecode/db/models.py` | Types match data-models.md |
| 1.3.2 | Create DB connection manager | `src/televibecode/db/database.py` | Async connect works |
| 1.3.3 | Implement schema creation | `src/televibecode/db/database.py` | Tables created on init |
| 1.3.4 | Add Project CRUD | `src/televibecode/db/database.py` | Create/read/update/delete work |
| 1.3.5 | Add Session CRUD | `src/televibecode/db/database.py` | CRUD + state transitions |
| 1.3.6 | Add Task CRUD | `src/televibecode/db/database.py` | Basic operations |
| 1.3.7 | Add Job CRUD | `src/televibecode/db/database.py` | Status updates work |

**Pydantic Models** (from data-models.md):
```python
class Project(BaseModel):
    project_id: str
    name: str
    path: str
    remote_url: str | None = None
    default_branch: str = "main"
    backlog_enabled: bool = False
    backlog_path: str | None = None
    created_at: datetime
    updated_at: datetime

class SessionState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    BLOCKED = "blocked"
    CLOSING = "closing"

class Session(BaseModel):
    session_id: str  # S1, S12, etc.
    project_id: str
    workspace_path: str
    branch: str
    state: SessionState = SessionState.IDLE
    # ... other fields
```

### 1.4 Basic MCP Server

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 1.4.1 | Create FastMCP server skeleton | `src/televibecode/orchestrator/server.py` | Server initializes |
| 1.4.2 | Implement `list_projects` tool | `src/televibecode/orchestrator/tools/projects.py` | Returns project list |
| 1.4.3 | Implement `register_project` tool | `src/televibecode/orchestrator/tools/projects.py` | Adds project to DB |
| 1.4.4 | Implement `scan_projects` tool | `src/televibecode/orchestrator/tools/projects.py` | Finds git repos in root |
| 1.4.5 | Add MCP resources | `src/televibecode/orchestrator/server.py` | `projects://list` works |

**MCP Server Pattern**:
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("TeleVibeCode Orchestrator")

@mcp.tool()
async def list_projects() -> list[dict]:
    """List all registered projects."""
    db = get_database()
    return await db.get_all_projects()

@mcp.resource("projects://list")
async def projects_resource() -> str:
    projects = await list_projects()
    return json.dumps(projects)
```

### 1.5 Basic Telegram Bot

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 1.5.1 | Create bot initialization | `src/televibecode/telegram/bot.py` | Bot starts with token |
| 1.5.2 | Add `/help` command | `src/televibecode/telegram/handlers.py` | Returns help text |
| 1.5.3 | Add `/projects` command | `src/televibecode/telegram/handlers.py` | Lists projects via MCP |
| 1.5.4 | Add error handling wrapper | `src/televibecode/telegram/bot.py` | Errors don't crash bot |
| 1.5.5 | Wire up polling | `src/televibecode/main.py` | `televibecode serve` runs |

**Telegram Handler Pattern**:
```python
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

async def projects_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    projects = await orchestrator.list_projects()
    if not projects:
        await update.message.reply_text("No projects registered.")
        return

    text = "📂 **Projects**\n\n"
    for p in projects:
        text += f"• `{p['project_id']}` - {p['name']}\n"

    await update.message.reply_text(text, parse_mode="Markdown")
```

### 1.6 CLI Entry Point

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 1.6.1 | Create CLI with argparse/click | `src/televibecode/main.py` | `--help` works |
| 1.6.2 | Add `serve` subcommand | `src/televibecode/main.py` | Starts bot + MCP |
| 1.6.3 | Add `--root` option | `src/televibecode/main.py` | Sets projects root |
| 1.6.4 | Initialize `.televibe/` on startup | `src/televibecode/main.py` | Creates state.db |

**Phase 1 Complete When**:
- [ ] `uv run televibecode serve --root ~/projects` starts
- [ ] Telegram `/projects` command returns list
- [ ] SQLite database persists data
- [ ] Missing env vars show helpful errors

---

## Phase 2: Session Management

**Goal**: Full session lifecycle + git worktrees
**Milestone M2**: Create and switch sessions

### 2.1 Git Operations

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 2.1.1 | Create git wrapper module | `src/televibecode/git_ops.py` | Module imports |
| 2.1.2 | Implement `create_worktree()` | `src/televibecode/git_ops.py` | Creates worktree |
| 2.1.3 | Implement `remove_worktree()` | `src/televibecode/git_ops.py` | Removes cleanly |
| 2.1.4 | Implement `list_worktrees()` | `src/televibecode/git_ops.py` | Lists all |
| 2.1.5 | Implement `get_branch_status()` | `src/televibecode/git_ops.py` | Returns ahead/behind |
| 2.1.6 | Add worktree conflict handling | `src/televibecode/git_ops.py` | Handles existing paths |

**Git Worktree Pattern**:
```python
from git import Repo

def create_worktree(repo_path: str, worktree_path: str, branch: str, create_branch: bool = True):
    repo = Repo(repo_path)
    if create_branch:
        repo.git.worktree("add", "-b", branch, worktree_path)
    else:
        repo.git.worktree("add", worktree_path, branch)
    return worktree_path
```

### 2.2 Session MCP Tools

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 2.2.1 | Implement `list_sessions` | `src/televibecode/orchestrator/tools/sessions.py` | Returns sessions |
| 2.2.2 | Implement `create_session` | `src/televibecode/orchestrator/tools/sessions.py` | Creates worktree + DB entry |
| 2.2.3 | Implement `get_session` | `src/televibecode/orchestrator/tools/sessions.py` | Returns details |
| 2.2.4 | Implement `close_session` | `src/televibecode/orchestrator/tools/sessions.py` | Cleans up worktree |
| 2.2.5 | Add session state transitions | `src/televibecode/db/database.py` | idle→running→idle |

**Session ID Generation**:
```python
async def generate_session_id(db: Database) -> str:
    """Generate next session ID like S1, S2, S12."""
    max_id = await db.get_max_session_number()
    return f"S{max_id + 1}"
```

### 2.3 Telegram Session Commands

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 2.3.1 | Add `/sessions` command | `src/televibecode/telegram/handlers.py` | Lists sessions |
| 2.3.2 | Add `/new <project> [branch]` | `src/televibecode/telegram/handlers.py` | Creates session |
| 2.3.3 | Add `/use <session>` | `src/televibecode/telegram/handlers.py` | Sets active |
| 2.3.4 | Add `/close <session>` | `src/televibecode/telegram/handlers.py` | Closes session |
| 2.3.5 | Implement per-chat state | `src/televibecode/telegram/state.py` | Tracks active session |

**Per-Chat State**:
```python
class ChatState:
    def __init__(self):
        self._active_sessions: dict[int, str] = {}  # chat_id -> session_id

    def get_active(self, chat_id: int) -> str | None:
        return self._active_sessions.get(chat_id)

    def set_active(self, chat_id: int, session_id: str):
        self._active_sessions[chat_id] = session_id
```

### 2.4 Session Cards

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 2.4.1 | Create session card formatter | `src/televibecode/telegram/formatters.py` | Formats nicely |
| 2.4.2 | Add context tags | `src/televibecode/telegram/formatters.py` | Shows 📂 🔹 🌿 |
| 2.4.3 | Include state emoji | `src/televibecode/telegram/formatters.py` | Shows state icon |

**Session Card Format**:
```
📂 [my-app] 🔹 [S12] 🌿 feature-auth
State: 🟢 idle
Branch: feature-auth (2 ahead)
Last: "Implemented login form" (5 min ago)
```

**Phase 2 Complete When**:
- [ ] `/new my-app feature-x` creates worktree
- [ ] `/use S12` switches active session
- [ ] `/close S12` removes worktree
- [ ] Session state persists across restarts

---

## Phase 3: Task System

**Goal**: Backlog.md integration
**Milestone M3**: View and claim backlog tasks

### 3.1 Backlog.md Parser

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 3.1.1 | Create markdown parser | `src/televibecode/backlog/parser.py` | Parses YAML front-matter |
| 3.1.2 | Extract task fields | `src/televibecode/backlog/parser.py` | Gets id, title, status |
| 3.1.3 | Handle nested directories | `src/televibecode/backlog/parser.py` | Finds all .md files |
| 3.1.4 | Handle parse errors gracefully | `src/televibecode/backlog/parser.py` | Logs warnings |

**Backlog.md Format**:
```markdown
---
id: T-123
title: Implement user authentication
status: todo
priority: high
epic: auth
---

## Description

Implement OAuth2 authentication flow...
```

### 3.2 Task Sync

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 3.2.1 | Initial sync on project register | `src/televibecode/backlog/sync.py` | Tasks imported |
| 3.2.2 | Implement `sync_backlog` tool | `src/televibecode/orchestrator/tools/tasks.py` | Refreshes tasks |
| 3.2.3 | Write back task updates | `src/televibecode/backlog/sync.py` | Updates .md files |
| 3.2.4 | Handle task conflicts | `src/televibecode/backlog/sync.py` | DB vs file |

### 3.3 Task MCP Tools

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 3.3.1 | Implement `list_project_tasks` | `src/televibecode/orchestrator/tools/tasks.py` | Filters by project |
| 3.3.2 | Implement `get_next_tasks` | `src/televibecode/orchestrator/tools/tasks.py` | Priority sorted |
| 3.3.3 | Implement `claim_task` | `src/televibecode/orchestrator/tools/tasks.py` | Links to session |
| 3.3.4 | Implement `update_task_status` | `src/televibecode/orchestrator/tools/tasks.py` | Updates DB + file |

### 3.4 Telegram Task Commands

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 3.4.1 | Add `/tasks <project>` | `src/televibecode/telegram/handlers.py` | Lists tasks |
| 3.4.2 | Add `/next <project>` | `src/televibecode/telegram/handlers.py` | Shows prioritized |
| 3.4.3 | Add `/claim <task> <session>` | `src/televibecode/telegram/handlers.py` | Assigns task |
| 3.4.4 | Format task cards | `src/televibecode/telegram/formatters.py` | Pretty output |

**Phase 3 Complete When**:
- [ ] Tasks sync from Backlog.md on project register
- [ ] `/tasks my-app` shows task list
- [ ] `/claim T-123 S12` links task to session
- [ ] Task status updates persist to .md files

---

## Phase 4: Job Execution

**Goal**: Claude Code runner + streaming
**Milestone M4**: Run Claude Code from Telegram

### 4.1 Runner Implementation

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 4.1.1 | Create job queue per session | `src/televibecode/runner/queue.py` | FIFO queue works |
| 4.1.2 | Create process spawner | `src/televibecode/runner/executor.py` | Spawns Claude Code |
| 4.1.3 | Configure environment | `src/televibecode/runner/executor.py` | Sets cwd, env vars |
| 4.1.4 | Stream stdout/stderr | `src/televibecode/runner/executor.py` | Async streaming |
| 4.1.5 | Handle exit codes | `src/televibecode/runner/executor.py` | Success/failure |
| 4.1.6 | Implement concurrency limit | `src/televibecode/runner/executor.py` | Max 3 concurrent |

**Runner Pattern**:
```python
async def execute_job(job: Job, workspace: str) -> JobResult:
    proc = await asyncio.create_subprocess_exec(
        "claude",
        "-p", job.instruction,
        "--output-format", "stream-json",
        cwd=workspace,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async for line in proc.stdout:
        # Parse streaming JSON
        await emit_progress(job.job_id, line)

    await proc.wait()
    return JobResult(
        status="done" if proc.returncode == 0 else "failed",
        exit_code=proc.returncode
    )
```

### 4.2 Log Management

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 4.2.1 | Write logs to files | `src/televibecode/runner/logs.py` | Creates log file |
| 4.2.2 | Parse structured output | `src/televibecode/runner/logs.py` | Extracts events |
| 4.2.3 | Extract summary | `src/televibecode/runner/logs.py` | Gets final summary |
| 4.2.4 | Implement log rotation | `src/televibecode/runner/logs.py` | Cleans old logs |

**Log Path**: `.televibe/logs/{session_id}/{job_id}.log`

### 4.3 Job MCP Tools

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 4.3.1 | Implement `run_instruction` | `src/televibecode/orchestrator/tools/jobs.py` | Queues job |
| 4.3.2 | Implement `get_job` | `src/televibecode/orchestrator/tools/jobs.py` | Returns status |
| 4.3.3 | Implement `list_jobs` | `src/televibecode/orchestrator/tools/jobs.py` | Filters by session |
| 4.3.4 | Implement `cancel_job` | `src/televibecode/orchestrator/tools/jobs.py` | Kills process |
| 4.3.5 | Implement `get_job_logs` | `src/televibecode/orchestrator/tools/jobs.py` | Returns log content |

### 4.4 Telegram Job Commands

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 4.4.1 | Add `/run [session] <instruction>` | `src/televibecode/telegram/handlers.py` | Queues job |
| 4.4.2 | Add `/status [session]` | `src/televibecode/telegram/handlers.py` | Shows job status |
| 4.4.3 | Add `/summary [session]` | `src/televibecode/telegram/handlers.py` | Shows last summary |
| 4.4.4 | Add `/tail [session] [lines]` | `src/televibecode/telegram/handlers.py` | Shows log tail |
| 4.4.5 | Add `/cancel [job_id]` | `src/televibecode/telegram/handlers.py` | Cancels job |

### 4.5 Real-time Updates

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 4.5.1 | Send job start notification | `src/televibecode/telegram/notifications.py` | User sees start |
| 4.5.2 | Send periodic progress | `src/televibecode/telegram/notifications.py` | Updates during |
| 4.5.3 | Send completion notification | `src/televibecode/telegram/notifications.py` | Shows result |
| 4.5.4 | Send failure with error | `src/televibecode/telegram/notifications.py` | Shows error |

**Notification Format**:
```
🔧 S12 (my-app/feature-x): Running "implement login form"
...
✅ S12 (my-app/feature-x): Completed
📝 3 files changed: src/auth.py, src/login.tsx, tests/test_auth.py
```

**Phase 4 Complete When**:
- [ ] `/run implement the login form` executes Claude Code
- [ ] Job progress streams to Telegram
- [ ] `/status` shows running job
- [ ] `/summary` shows last result
- [ ] Logs persist to `.televibe/logs/`

---

## Phase 5: Approval System

**Goal**: Gated high-impact actions
**Milestone M5**: Approve git push inline

### 5.1 Approval Detection

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 5.1.1 | Create approval scope enum | `src/televibecode/db/models.py` | Scopes defined |
| 5.1.2 | Parse Claude Code hooks | `src/televibecode/runner/approvals.py` | Detects approval need |
| 5.1.3 | Pause job on approval | `src/televibecode/runner/executor.py` | Job enters waiting |
| 5.1.4 | Resume on approval | `src/televibecode/runner/executor.py` | Job continues |

**Approval Scopes**:
- `write` - File modifications
- `delete_file` - File deletions
- `shell` - Shell command execution
- `shell_sudo` - Sudo commands
- `push` - Git push
- `force_push` - Force push
- `deploy` - Deployment commands

### 5.2 Approval MCP Tools

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 5.2.1 | Implement `list_pending_approvals` | `src/televibecode/orchestrator/tools/approvals.py` | Returns pending |
| 5.2.2 | Implement `approve_job` | `src/televibecode/orchestrator/tools/approvals.py` | Approves + resumes |
| 5.2.3 | Implement `deny_job` | `src/televibecode/orchestrator/tools/approvals.py` | Denies + cancels |

### 5.3 Telegram Approval UI

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 5.3.1 | Create approval message format | `src/televibecode/telegram/formatters.py` | Shows action details |
| 5.3.2 | Add inline keyboard buttons | `src/televibecode/telegram/approvals.py` | [Approve] [Deny] |
| 5.3.3 | Handle callback queries | `src/televibecode/telegram/approvals.py` | Processes clicks |
| 5.3.4 | Update message on action | `src/televibecode/telegram/approvals.py` | Shows result |
| 5.3.5 | Handle approval timeout | `src/televibecode/telegram/approvals.py` | Auto-deny after X |

**Approval Message**:
```
⚠️ S12 (my-app/feature-x): Approval needed

Action: git push origin feature-x
Scope: push

[✅ Approve] [❌ Deny]
```

### 5.4 Policy Configuration

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 5.4.1 | Add approval config | `src/televibecode/config.py` | Per-scope settings |
| 5.4.2 | Add per-project overrides | `src/televibecode/config.py` | Project config |
| 5.4.3 | Add trusted commands whitelist | `src/televibecode/config.py` | Allowed without approval |

**Default Policy**:
```yaml
approvals:
  default:
    write: false      # No approval for writes
    shell: true       # Require for shell
    push: true        # Require for push
    deploy: true      # Require for deploy

  whitelist:
    - "git status"
    - "git diff"
    - "git log"
    - "pytest"
    - "npm test"
```

**Phase 5 Complete When**:
- [ ] Shell commands pause for approval
- [ ] `git push` shows inline buttons
- [ ] Approve button resumes job
- [ ] Deny button cancels job
- [ ] Policy config controls behavior

---

## Phase 6: Polish & Intelligence

**Goal**: Middle AI + natural language
**Milestone M6**: "fix the bug" works naturally

### 6.1 Middle AI Layer (Agno)

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 6.1.1 | Create Agno agent | `src/televibecode/ai/agent.py` | Agent initializes |
| 6.1.2 | Implement intent classification | `src/televibecode/ai/intents.py` | Detects intent type |
| 6.1.3 | Implement entity extraction | `src/televibecode/ai/entities.py` | Extracts project, session, task |
| 6.1.4 | Implement instruction normalization | `src/televibecode/ai/normalize.py` | Cleans instructions |
| 6.1.5 | Add session routing suggestions | `src/televibecode/ai/routing.py` | Suggests best session |

**Intent Types**:
- `run_instruction` - Execute a coding task
- `query_status` - Ask about job/session status
- `switch_session` - Change active session
- `list_items` - List projects/sessions/tasks
- `manage_session` - Create/close session
- `approval` - Approve/deny action

**Agno Integration**:
```python
from agno.agent import Agent
from agno.models.google import Gemini

intent_agent = Agent(
    name="TeleVibe Intent Parser",
    model=Gemini(id="gemini-2.0-flash"),
    instructions="""
    Parse user messages and extract:
    - intent: run_instruction | query_status | switch_session | ...
    - entities: {project, session, task, instruction}
    - confidence: 0.0-1.0

    Return JSON only.
    """
)
```

### 6.2 Natural Language Support

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 6.2.1 | Route NL to intent parser | `src/televibecode/telegram/nl.py` | Non-commands parsed |
| 6.2.2 | "fix the auth bug" → run | `src/televibecode/ai/handlers.py` | Triggers job |
| 6.2.3 | "what's next?" → get tasks | `src/televibecode/ai/handlers.py` | Lists tasks |
| 6.2.4 | "switch to payments" → use | `src/televibecode/ai/handlers.py` | Switches session |
| 6.2.5 | Ambiguity resolution | `src/televibecode/ai/handlers.py` | Asks clarification |

**Example Mappings**:
```
User: "fix the auth bug"
→ Intent: run_instruction
→ Entities: {instruction: "fix the auth bug"}
→ Action: /run fix the auth bug

User: "what's happening with S12?"
→ Intent: query_status
→ Entities: {session: "S12"}
→ Action: /status S12

User: "switch to payments"
→ Intent: switch_session
→ Entities: {session_hint: "payments"}
→ Action: Find session with "payments" in name/branch, /use it
```

### 6.3 UX Improvements

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 6.3.1 | Better error messages | `src/televibecode/telegram/errors.py` | Helpful suggestions |
| 6.3.2 | Command autocomplete hints | `src/televibecode/telegram/bot.py` | Set bot commands |
| 6.3.3 | Notification preferences | `src/televibecode/telegram/preferences.py` | Toggle verbosity |
| 6.3.4 | Message threading | `src/televibecode/telegram/threading.py` | Group by session |

### 6.4 Reliability

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 6.4.1 | Graceful shutdown | `src/televibecode/main.py` | SIGTERM handled |
| 6.4.2 | Session recovery | `src/televibecode/runner/recovery.py` | Resumes on restart |
| 6.4.3 | Job retry on failure | `src/televibecode/runner/retry.py` | Configurable retries |
| 6.4.4 | Health monitoring | `src/televibecode/health.py` | Health endpoint |

### 6.5 Documentation & Testing

| Step | Task | Files | Verify |
|------|------|-------|--------|
| 6.5.1 | User documentation | `docs/user-guide.md` | Complete guide |
| 6.5.2 | Developer documentation | `docs/developer-guide.md` | API docs |
| 6.5.3 | Unit tests | `tests/test_*.py` | Core modules tested |
| 6.5.4 | Integration tests | `tests/integration/` | End-to-end flows |

**Phase 6 Complete When**:
- [ ] "fix the bug in auth" runs instruction
- [ ] Error messages suggest solutions
- [ ] Bot survives restarts gracefully
- [ ] Test coverage > 70%

---

## Dependency Graph

```
Phase 1 ─┬─► Phase 2 ─┬─► Phase 3 ─┬─► Phase 4 ─┬─► Phase 5 ─┬─► Phase 6
         │            │            │            │            │
    Foundation   Sessions     Tasks        Jobs      Approvals    Polish
         │            │            │            │            │
         └────────────┴────────────┴────────────┴────────────┘
                              MVP (1-4)              Production (5-6)
```

## Quick Reference

| Phase | Key Files | Test Command |
|-------|-----------|--------------|
| 1 | `config.py`, `db/`, `orchestrator/server.py`, `telegram/bot.py` | `/projects` returns list |
| 2 | `git_ops.py`, `orchestrator/tools/sessions.py`, `telegram/handlers.py` | `/new app feature` creates worktree |
| 3 | `backlog/parser.py`, `orchestrator/tools/tasks.py` | `/tasks app` shows tasks |
| 4 | `runner/executor.py`, `orchestrator/tools/jobs.py` | `/run implement X` executes |
| 5 | `runner/approvals.py`, `telegram/approvals.py` | Inline buttons work |
| 6 | `ai/agent.py`, `ai/intents.py` | "fix the bug" works |
