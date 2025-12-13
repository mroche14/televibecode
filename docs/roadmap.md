# Implementation Roadmap

## Phase Overview

```
Phase 1: Foundation     →  Core orchestrator + basic Telegram
Phase 2: Session Mgmt   →  Full session lifecycle + worktrees
Phase 3: Task System    →  Backlog.md integration
Phase 4: Job Execution  →  Claude Code runner + streaming
Phase 5: Approvals      →  Gated actions + inline buttons
Phase 6: Polish         →  Middle AI + natural language
```

---

## Phase 1: Foundation

### Goals
- Project structure and dependencies
- SQLite database with core models
- Basic Orchestrator MCP skeleton
- Telegram bot with command routing

### Tasks

#### 1.1 Project Setup
- [x] Initialize UV Python project
- [ ] Add core dependencies:
  - `mcp` - MCP protocol SDK
  - `python-telegram-bot` - Telegram integration
  - `aiosqlite` - Async SQLite
  - `pydantic` - Data validation
  - `structlog` - Logging
- [ ] Create package structure:
  ```
  src/televibecode/
  ├── __init__.py
  ├── main.py              # Entry point
  ├── config.py            # Configuration loading
  ├── db/
  │   ├── __init__.py
  │   ├── models.py        # Pydantic models
  │   └── database.py      # SQLite operations
  ├── orchestrator/
  │   ├── __init__.py
  │   ├── server.py        # MCP server
  │   └── tools/           # MCP tool handlers
  ├── telegram/
  │   ├── __init__.py
  │   ├── bot.py           # Bot setup
  │   └── handlers.py      # Command handlers
  └── runner/
      ├── __init__.py
      └── executor.py      # Job execution
  ```

#### 1.2 Database Layer
- [ ] Implement SQLite schema (from data-models.md)
- [ ] Create async CRUD operations for:
  - Projects
  - Sessions
  - Tasks
  - Jobs
- [ ] Add migration system (simple version table)

#### 1.3 Configuration
- [ ] Create config.yaml schema
- [ ] Environment variable support
- [ ] Path resolution for projects/repos/workspaces

#### 1.4 Basic MCP Server
- [ ] Initialize MCP server skeleton
- [ ] Implement `list_projects` tool
- [ ] Implement `register_project` tool
- [ ] Implement `scan_projects` tool
- [ ] Add stdio transport

#### 1.5 Basic Telegram Bot
- [ ] Bot initialization with token
- [ ] Webhook setup (or polling for dev)
- [ ] `/projects` command
- [ ] `/help` command
- [ ] Error handling wrapper

### Deliverables
- Running orchestrator that can scan and list projects
- Telegram bot responding to `/projects` and `/help`
- SQLite database persisting project data

---

## Phase 2: Session Management

### Goals
- Full session lifecycle
- Git worktree management
- Session state machine

### Tasks

#### 2.1 Git Operations
- [ ] Implement git wrapper module:
  - `create_worktree(repo_path, worktree_path, branch)`
  - `remove_worktree(worktree_path)`
  - `create_branch(repo_path, branch, base)`
  - `get_branch_status(worktree_path)`
- [ ] Handle worktree conflicts and cleanup

#### 2.2 Session MCP Tools
- [ ] `list_sessions`
- [ ] `create_session` with worktree creation
- [ ] `get_session`
- [ ] `close_session` with cleanup
- [ ] Session state transitions

#### 2.3 Telegram Session Commands
- [ ] `/sessions` - list all
- [ ] `/new <project> [branch]` - create session
- [ ] `/use <session_id>` - set active
- [ ] `/close <session_id>` - close session
- [ ] Per-chat active session storage

#### 2.4 Session Cards
- [ ] Format session info with tags
- [ ] Reply-to metadata embedding
- [ ] Reply routing to correct session

### Deliverables
- Create sessions with isolated worktrees
- Switch between sessions from Telegram
- Close sessions with proper cleanup

---

## Phase 3: Task System

### Goals
- Backlog.md integration
- Task CRUD via MCP
- Task-session linking

### Tasks

#### 3.1 Backlog.md Parser
- [ ] Parse markdown files with YAML front-matter
- [ ] Extract task fields:
  - id, title, status, priority, epic, assignee
- [ ] Handle nested backlog directories

#### 3.2 Task Sync
- [ ] Initial sync on project registration
- [ ] `sync_backlog` tool
- [ ] Detect changes (file watcher or on-demand)
- [ ] Write back task updates to markdown

#### 3.3 Task MCP Tools
- [ ] `list_project_tasks`
- [ ] `get_next_tasks`
- [ ] `claim_task`
- [ ] `update_task_status`

#### 3.4 Telegram Task Commands
- [ ] `/tasks <project>` - list tasks
- [ ] `/next <project>` - prioritized next
- [ ] `/claim <task> <session>` - assign

### Deliverables
- Tasks synced from Backlog.md
- Query and update tasks via Telegram
- Tasks linked to sessions

---

## Phase 4: Job Execution

### Goals
- Claude Code execution in sessions
- Log streaming and capture
- Job lifecycle management

### Tasks

#### 4.1 Runner Implementation
- [ ] Job queue per session
- [ ] Process spawning with:
  - Correct working directory
  - Environment variables
  - SuperClaude configuration
- [ ] Async log streaming
- [ ] Exit code handling

#### 4.2 Log Management
- [ ] Write logs to files
- [ ] Structured log parsing (if available)
- [ ] Summary extraction
- [ ] Log rotation/cleanup

#### 4.3 Job MCP Tools
- [ ] `run_instruction`
- [ ] `get_job`
- [ ] `list_jobs`
- [ ] `cancel_job`
- [ ] `get_job_logs`

#### 4.4 Telegram Job Commands
- [ ] `/run [session] <instruction>`
- [ ] `/status [session]`
- [ ] `/summary [session]`
- [ ] `/tail [session] [lines]`
- [ ] `/cancel [job_id]`

#### 4.5 Real-time Updates
- [ ] Job start notification
- [ ] Progress updates (periodic or on events)
- [ ] Completion notification with summary
- [ ] Failure notification with error

### Deliverables
- Execute Claude Code jobs from Telegram
- Stream logs and status updates
- View job history and summaries

---

## Phase 5: Approval System

### Goals
- Gated high-impact actions
- Inline approval buttons
- Configurable policies

### Tasks

#### 5.1 Approval Detection
- [ ] Hook into Claude Code permission system (or wrapper)
- [ ] Detect approval-required actions:
  - File writes (optional)
  - Shell commands
  - Git push
  - Deployments
- [ ] Pause job execution on approval needed

#### 5.2 Approval MCP Tools
- [ ] `list_pending_approvals`
- [ ] `approve_job`
- [ ] `deny_job`

#### 5.3 Telegram Approval UI
- [ ] Approval needed message format
- [ ] Inline keyboard buttons [Approve] [Deny]
- [ ] Callback query handlers
- [ ] Approval timeout handling

#### 5.4 Policy Configuration
- [ ] Config options for each action type
- [ ] Per-project overrides
- [ ] Trusted commands whitelist

### Deliverables
- Pause on sensitive actions
- Approve/deny from Telegram inline buttons
- Configurable approval policies

---

## Phase 6: Polish & Intelligence

### Goals
- Middle AI layer for natural language
- Improved UX and error handling
- Performance and reliability

### Tasks

#### 6.1 Middle AI Layer
- [ ] Intent classification:
  - question vs task vs status vs switch
- [ ] Entity extraction:
  - project names, session IDs, task IDs
- [ ] Instruction normalization
- [ ] Session routing suggestions

#### 6.2 Natural Language Support
- [ ] "fix the auth bug" → run instruction
- [ ] "what's next?" → get next tasks
- [ ] "switch to payments" → use session
- [ ] Ambiguity resolution

#### 6.3 UX Improvements
- [ ] Better error messages with suggestions
- [ ] Command autocomplete hints
- [ ] Notification preferences
- [ ] Message threading

#### 6.4 Reliability
- [ ] Graceful shutdown handling
- [ ] Session recovery on restart
- [ ] Job retry on failure
- [ ] Health monitoring

#### 6.5 Documentation & Testing
- [ ] User documentation
- [ ] Developer documentation
- [ ] Unit tests for core modules
- [ ] Integration tests

### Deliverables
- Natural language understanding
- Polished user experience
- Production-ready reliability

---

## Dependencies

```toml
[project.dependencies]
# Core
pydantic = ">=2.0"
structlog = ">=24.0"
pyyaml = ">=6.0"
aiofiles = ">=24.0"

# Database
aiosqlite = ">=0.20"

# MCP
mcp = ">=1.0"

# Telegram
python-telegram-bot = ">=21.0"

# Git operations
gitpython = ">=3.1"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
    "mypy>=1.13",
]
```

---

## Milestones

| Milestone | Phase | Key Deliverable |
|-----------|-------|-----------------|
| M1: First Response | 1 | `/projects` works in Telegram |
| M2: First Session | 2 | Create and switch sessions |
| M3: First Task | 3 | View and claim backlog tasks |
| M4: First Job | 4 | Run Claude Code from Telegram |
| M5: First Approval | 5 | Approve git push inline |
| M6: First NL | 6 | "fix the bug" works naturally |

---

## Success Criteria

### MVP (Phases 1-4)
- [ ] Can create sessions on any project from Telegram
- [ ] Can run instructions and see results
- [ ] Can track tasks and link to sessions
- [ ] Works reliably for single-user usage

### Production (Phases 5-6)
- [ ] Approval gating prevents accidents
- [ ] Natural language reduces friction
- [ ] Handles multiple concurrent sessions
- [ ] Survives restarts gracefully
