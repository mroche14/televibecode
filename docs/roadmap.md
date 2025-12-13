# Implementation Roadmap

## Phase Overview

```
Phase 1: Foundation     →  Core orchestrator + basic Telegram        ✅ DONE
Phase 2: Session Mgmt   →  Full session lifecycle + worktrees
Phase 3: Task System    →  Backlog.md integration
Phase 4: Job Execution  →  Claude Code runner + streaming
Phase 5: Approvals      →  Gated actions + inline buttons
Phase 6: Polish         →  Middle AI + natural language
```

---

## Phase 1: Foundation ✅

### Goals
- Project structure and dependencies
- SQLite database with core models
- Basic Orchestrator MCP skeleton
- Telegram bot with command routing

### Tasks

#### 1.1 Project Setup
- [x] Initialize UV Python project
- [x] Add core dependencies:
  - `mcp` - MCP protocol SDK
  - `python-telegram-bot` - Telegram integration
  - `aiosqlite` - Async SQLite
  - `pydantic` - Data validation
  - `structlog` - Logging
  - `agno` - AI layer
- [x] Create package structure

#### 1.2 Database Layer
- [x] Implement SQLite schema (from data-models.md)
- [x] Create async CRUD operations for:
  - Projects
  - Sessions
  - Tasks
  - Jobs
- [x] WAL mode and performance pragmas

#### 1.3 Configuration
- [x] Pydantic settings model
- [x] Environment variable support
- [x] Startup validation with helpful errors
- [x] Path resolution for projects/repos/workspaces

#### 1.4 Basic MCP Server
- [x] Initialize FastMCP server skeleton
- [x] Implement `list_projects` tool
- [x] Implement `register_project` tool
- [x] Implement `scan_projects` tool
- [x] Add MCP resources (projects, sessions, jobs, approvals)

#### 1.5 Basic Telegram Bot
- [x] Bot initialization with token
- [x] Polling mode for development
- [x] `/projects` command
- [x] `/scan` command
- [x] `/sessions` command
- [x] `/help` command
- [x] Error handling wrapper
- [x] Per-chat state manager

### Deliverables ✅
- Running orchestrator that can scan and list projects
- Telegram bot responding to `/projects`, `/scan`, `/sessions`, `/help`
- SQLite database persisting project data

---

## Phase 2: Session Management

### Goals
- Full session lifecycle
- Git worktree management
- Session state machine
- **Message context tracking for reply routing**

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
- [ ] `/sessions` - list all (with inline keyboard for quick switch)
- [ ] `/new <project> [branch]` - create session
- [ ] `/use <session_id>` - set active
- [ ] `/close <session_id>` - close session
- [ ] Per-chat active session storage

#### 2.4 Message Context Store (NEW)
- [ ] Store message_id → session context mapping
- [ ] Track: session_id, project_id, job_id, message_type
- [ ] Prune old entries (keep last 1000)
- [ ] Retrieve context when user replies to bot message

#### 2.5 Reply-To Session Routing (NEW)
- [ ] Detect when user replies to a bot message
- [ ] Look up original message context
- [ ] Auto-route to correct session (even if other messages in between)
- [ ] Fall back to active session if no context found

#### 2.6 Session Cards
- [ ] Format session info with context tags:
  ```
  📂 [project] 🔹 [S12] 🌿 feature-x
  ```
- [ ] Embed session context in every bot message
- [ ] Store context with every sent message
- [ ] Reply routing based on message context

#### 2.7 Session Switcher Keyboard (NEW)
- [ ] Inline keyboard with active sessions
- [ ] Quick switch via button tap
- [ ] Show state icon (🟢 idle, 🔧 running, ⏸️ blocked)

### Deliverables
- Create sessions with isolated worktrees
- Switch between sessions from Telegram
- **Reply to any bot message → routes to correct session**
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
- [ ] `/tasks <project>` - list tasks (with inline buttons)
- [ ] `/next <project>` - prioritized next
- [ ] `/claim <task> <session>` - assign

#### 3.5 Task Quick Actions (NEW)
- [ ] Inline keyboard on task list:
  - [Claim] [View] [Skip]
- [ ] Task status update buttons
- [ ] Link task to current session with one tap

### Deliverables
- Tasks synced from Backlog.md
- Query and update tasks via Telegram
- Tasks linked to sessions
- **Quick task actions via inline buttons**

---

## Phase 4: Job Execution

### Goals
- Claude Code execution in sessions
- Log streaming and capture
- Job lifecycle management
- **Live progress updates with message editing**

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

#### 4.5 Typing Indicator (NEW)
- [ ] Show "typing..." while job queued/starting
- [ ] Keep typing indicator alive during long operations
- [ ] Cancel typing when job completes or sends update

#### 4.6 Live Progress Updates (NEW)
- [ ] Send initial status message
- [ ] Edit message with progress (every 5-10 seconds)
- [ ] Progress bar format: `[████░░░░░░] 40%`
- [ ] Show elapsed time
- [ ] Final edit with completion status

#### 4.7 Job Status Reactions (NEW)
- [ ] React to user's instruction message:
  - 👀 when job starts
  - ✅ when job completes
  - ❌ when job fails
- [ ] Provides quick visual feedback

#### 4.8 Real-time Updates
- [ ] Job start notification (edit message)
- [ ] Progress updates (periodic message edits)
- [ ] Completion notification with summary
- [ ] Failure notification with error

### Deliverables
- Execute Claude Code jobs from Telegram
- **Live progress via message editing**
- **Typing indicator during processing**
- **Reaction feedback on messages**
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

#### 5.3 Telegram Approval UI (ENHANCED)
- [ ] Approval needed message format with details
- [ ] Inline keyboard buttons:
  ```
  [✅ Approve] [❌ Deny]
  [📋 View Details] [🔗 View Diff]
  ```
- [ ] Callback query handlers with `query.answer()`
- [ ] Edit message to show result after action
- [ ] Approval timeout handling with auto-deny option

#### 5.4 Approval Confirmation (NEW)
- [ ] After approve: edit message to `✅ Approved by @user`
- [ ] After deny: edit message to `❌ Denied by @user`
- [ ] Show who approved and when
- [ ] Optional: require confirmation for dangerous actions

#### 5.5 Policy Configuration
- [ ] Config options for each action type
- [ ] Per-project overrides
- [ ] Trusted commands whitelist

### Deliverables
- Pause on sensitive actions
- **Rich approval UI with inline buttons**
- **Visual feedback after approval/denial**
- Configurable approval policies

---

## Phase 6: Polish & Intelligence

### Goals
- Middle AI layer for natural language
- Improved UX and error handling
- Performance and reliability

### Tasks

#### 6.1 Middle AI Layer (Agno)
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
- [ ] Ambiguity resolution with ForceReply

#### 6.3 ForceReply for Clarification (NEW)
- [ ] Use ForceReply when ambiguous input
- [ ] Input placeholder: "Which session? S1, S2, or S3..."
- [ ] Clear prompts for missing info
- [ ] Remember context for follow-up

#### 6.4 Bot Commands Menu (NEW)
- [ ] Register commands with `set_my_commands`
- [ ] Autocomplete in Telegram client
- [ ] Grouped by category:
  - Projects: /projects, /scan
  - Sessions: /sessions, /new, /use, /close
  - Jobs: /run, /status, /summary, /cancel
  - Tasks: /tasks, /next, /claim

#### 6.5 Task Prioritization Poll (NEW)
- [ ] `/prioritize <project>` - create poll
- [ ] Poll with top 5 pending tasks
- [ ] Multiple choice voting
- [ ] Update task priorities based on votes

#### 6.6 UX Improvements
- [ ] Better error messages with suggestions
- [ ] Command autocomplete hints (via bot commands menu)
- [ ] Notification preferences (silent/normal/verbose)
- [ ] Message threading for long conversations

#### 6.7 Media & Rich Content (NEW)
- [ ] Send screenshots as photo albums
- [ ] Send log files as documents
- [ ] Diff preview with syntax highlighting (as document)

#### 6.8 Reliability
- [ ] Graceful shutdown handling
- [ ] Session recovery on restart
- [ ] Job retry on failure
- [ ] Health monitoring

#### 6.9 Documentation & Testing
- [ ] User documentation
- [ ] Developer documentation
- [ ] Unit tests for core modules
- [ ] Integration tests

### Deliverables
- Natural language understanding
- **ForceReply for clarification**
- **Bot commands menu with autocomplete**
- **Task polls for prioritization**
- Polished user experience
- Production-ready reliability

---

## Telegram UI Features Summary

| Feature | Phase | Implementation |
|---------|-------|----------------|
| Inline Keyboards | 2, 3, 5 | Session switcher, task actions, approvals |
| Reply-To Context | 2 | Message context store, auto-routing |
| Message Editing | 4 | Live job progress updates |
| Typing Indicator | 4 | Show activity during processing |
| Reactions | 4 | Quick status feedback (✅❌👀) |
| ForceReply | 6 | Clarification prompts |
| Bot Commands | 6 | Autocomplete menu |
| Polls | 6 | Task prioritization |
| Callback Query | 2, 3, 5 | All inline button handlers |

---

## Dependencies

```toml
[project.dependencies]
# Core
pydantic = ">=2.0"
pydantic-settings = ">=2.0"
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

# AI Layer
agno = "*"

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
| M1: First Response | 1 ✅ | `/projects` works in Telegram |
| M2: First Session | 2 | Create and switch sessions |
| M2.5: Reply Routing | 2 | Reply to message → correct session |
| M3: First Task | 3 | View and claim backlog tasks |
| M4: First Job | 4 | Run Claude Code from Telegram |
| M4.5: Live Progress | 4 | See progress updates in real-time |
| M5: First Approval | 5 | Approve git push inline |
| M6: First NL | 6 | "fix the bug" works naturally |

---

## Success Criteria

### MVP (Phases 1-4)
- [x] Can scan and list projects from Telegram
- [ ] Can create sessions on any project from Telegram
- [ ] **Reply to any bot message routes to correct session**
- [ ] Can run instructions and see results
- [ ] **See live progress updates**
- [ ] Can track tasks and link to sessions
- [ ] Works reliably for single-user usage

### Production (Phases 5-6)
- [ ] Approval gating prevents accidents
- [ ] **Rich approval UI with inline buttons**
- [ ] Natural language reduces friction
- [ ] **ForceReply for clarification**
- [ ] Handles multiple concurrent sessions
- [ ] Survives restarts gracefully
