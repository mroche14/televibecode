# TeleVibeCode Data Models

## Entity Relationship Overview

```
┌─────────────┐       ┌─────────────┐
│   Project   │◄──────│   Session   │
└─────────────┘  1:N  └─────────────┘
      │                     │
      │ 1:N                 │ 1:N
      ▼                     ▼
┌─────────────┐       ┌─────────────┐
│    Task     │◄──────│     Job     │
└─────────────┘  N:1  └─────────────┘
```

## Core Concepts: Projects, Sessions, Branches, Worktrees, and Jobs

Understanding the relationship between these entities is **critical** to understanding TeleVibeCode.

### The Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                         PROJECT                                  │
│  (Git repository - the source of truth)                         │
│                                                                  │
│  • project_id: "my-web-app"                                     │
│  • path: "/home/user/projects/my-web-app"  ← Main repo          │
│  • default_branch: "main"                                       │
│  • Has the .git directory                                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ 1:N (max 10 per project)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         SESSION                                  │
│  (Isolated workspace = Git Worktree + Branch)                   │
│                                                                  │
│  • session_id: "my-web-app_20241214_153042"                     │
│  • project_id: "my-web-app" ──────────────► FK to Project       │
│  • branch: "televibe/my-web-app_20241214_153042"                │
│  • workspace_path: "~/.televibe/workspaces/my-web-app_..."      │
│  • state: idle | running | blocked | closing                    │
│                                                                  │
│  ⚠️  Each session has EXACTLY ONE branch and ONE worktree       │
│  ⚠️  No two active sessions can share the same branch           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ 1:N (sequential execution)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                           JOB                                    │
│  (Single Claude Code execution)                                 │
│                                                                  │
│  • job_id: "uuid-..."                                           │
│  • session_id: "my-web-app_20241214_..." ───► FK to Session     │
│  • instruction: "Fix the login bug"                             │
│  • status: queued | running | done | failed                     │
│                                                                  │
│  ⚠️  Only ONE job runs at a time per session                    │
│  ⚠️  Jobs execute in the session's worktree directory           │
└─────────────────────────────────────────────────────────────────┘
```

### Why Git Worktrees?

Git worktrees are the **isolation mechanism** that enables parallel work:

```
Main repository (Project):
~/projects/my-web-app/                    ← branch: main (protected)
          │
          │ git worktree add
          │
    ┌─────┴─────────────────────────────────────────┐
    │                                               │
    ▼                                               ▼
~/.televibe/workspaces/                     ~/.televibe/workspaces/
  my-web-app_20241214_153042/                 my-web-app_20241214_160000/

  Branch: televibe/...153042                  Branch: televibe/...160000
  ┌─────────────────────────┐                 ┌─────────────────────────┐
  │ Session S1              │                 │ Session S2              │
  │ • Full working copy     │                 │ • Full working copy     │
  │ • Independent commits   │                 │ • Independent commits   │
  │ • Isolated changes      │                 │ • Isolated changes      │
  │ • Own .git link         │                 │ • Own .git link         │
  └─────────────────────────┘                 └─────────────────────────┘

  Claude Code runs HERE                       Claude Code runs HERE
  Changes don't affect S2                     Changes don't affect S1
```

**Key benefits:**
- **True isolation**: Changes in S1 don't affect S2 or main
- **No branch switching**: Each worktree stays on its branch
- **Parallel execution**: Multiple sessions can run simultaneously
- **Clean merge path**: Each branch can be pushed/PR'd independently

### Session Lifecycle and Git State

```
┌──────────────────────────────────────────────────────────────────┐
│                     SESSION LIFECYCLE                             │
└──────────────────────────────────────────────────────────────────┘

1. CREATE SESSION (/new)
   ├─► Generate session_id: {project}_{YYYYMMDD_HHMMSS}
   ├─► Generate branch name: televibe/{session_id}
   ├─► Check: No other session uses this branch ⚠️
   ├─► Create worktree: git worktree add -b {branch} {workspace_path}
   └─► Session state: IDLE

2. RUN JOBS (/run)
   ├─► Create Job record
   ├─► Session state: RUNNING
   ├─► Execute Claude Code in workspace_path
   ├─► Claude makes commits on session's branch
   └─► Session state: IDLE (on completion)

3. CHECK STATUS (/status)
   ├─► Show commits ahead/behind main (drift)
   ├─► Show if branch is pushed to origin
   ├─► Show uncommitted changes in worktree
   └─► Show recent jobs

4. CLOSE SESSION (/close)
   ├─► Show branch status (commits, pushed?)
   ├─► User chooses:
   │   ├─► 🗑️ Delete branch (lose unpushed work)
   │   ├─► 📌 Keep branch (can resume later)
   │   └─► ☁️ Push first (backup to origin)
   ├─► Remove worktree: git worktree remove {workspace_path}
   ├─► Optionally delete branch: git branch -D {branch}
   └─► Delete session from database
```

### Constraints and Safeguards

| Constraint | Enforcement | Rationale |
|------------|-------------|-----------|
| Max 10 sessions per project | `create_session()` | Prevent resource exhaustion |
| Max 50 total active sessions | `create_session()` | System-wide limit |
| One branch per session | Database model | 1:1 relationship |
| No duplicate branches | `create_session()` | Prevent worktree conflicts |
| Sequential job execution | Session state machine | Prevent race conditions |
| Branch status on close | `/close` command | Prevent accidental data loss |

### Data Flow Example

```
User sends: "Fix the auth bug in my-web-app"
                    │
                    ▼
            ┌───────────────┐
            │  Telegram Bot │
            └───────┬───────┘
                    │
                    ▼
            ┌───────────────┐
            │  Orchestrator │  ← Finds or creates session
            └───────┬───────┘
                    │
                    ▼
        ┌───────────────────────┐
        │  Session: S1          │
        │  Branch: televibe/... │
        │  Workspace: ~/.tel... │
        └───────────┬───────────┘
                    │
                    ▼
            ┌───────────────┐
            │  Job Created  │  ← instruction: "Fix the auth bug"
            └───────┬───────┘
                    │
                    ▼
        ┌───────────────────────┐
        │  Runner               │
        │  cwd = workspace_path │  ← Claude runs HERE
        │  claude -p "Fix..."   │
        └───────────┬───────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │  Claude Code          │
        │  • Reads/writes files │  ← In worktree only
        │  • Makes commits      │  ← On session's branch
        │  • Updates workspace  │
        └───────────────────────┘
```

### File System Layout

```
~/projects/                           # --root directory
├── .televibe/                        # TeleVibeCode artifacts
│   ├── state.db                      # SQLite database
│   ├── logs/                         # Job execution logs
│   │   └── job-{uuid}.jsonl
│   └── workspaces/                   # Git worktrees (sessions)
│       ├── my-web-app_20241214_153042/     ← Session S1
│       │   ├── .git                  # Worktree link file
│       │   ├── src/
│       │   └── package.json
│       └── my-api_20241214_160000/         ← Session S2
│           ├── .git
│           └── ...
│
├── my-web-app/                       # Original project (untouched)
│   ├── .git/                         # Main git directory
│   │   └── worktrees/                # Git's worktree tracking
│   │       ├── my-web-app_20241214_153042/
│   │       └── ...
│   ├── src/
│   └── package.json
│
└── my-api/                           # Another project
    └── ...
```

## Project (Repository)

Represents a git repository managed by the orchestrator.

| Field | Type | Description |
|-------|------|-------------|
| `project_id` | string | Unique identifier (slug) |
| `name` | string | Display name |
| `path` | string | Absolute path to repo (e.g., `~/projects/my-web-app`) |
| `remote_url` | string? | Git remote URL |
| `default_branch` | string | Default branch (main/master) |
| `backlog_enabled` | boolean | Whether Backlog.md is initialized |
| `backlog_path` | string? | Path to backlog directory |
| `created_at` | datetime | Creation timestamp |
| `updated_at` | datetime | Last update timestamp |

### JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "project_id": { "type": "string", "pattern": "^[a-z0-9-]+$" },
    "name": { "type": "string" },
    "path": { "type": "string" },
    "remote_url": { "type": ["string", "null"] },
    "default_branch": { "type": "string", "default": "main" },
    "backlog_enabled": { "type": "boolean", "default": false },
    "backlog_path": { "type": ["string", "null"] },
    "created_at": { "type": "string", "format": "date-time" },
    "updated_at": { "type": "string", "format": "date-time" }
  },
  "required": ["project_id", "name", "path"]
}
```

## Session

Represents an active Claude Code workspace on a specific branch.

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Unique identifier (e.g., "S12") |
| `project_id` | string | FK to Project |
| `display_name` | string? | Human-readable name |
| `workspace_path` | string | Absolute path to git worktree |
| `branch` | string | Git branch name |
| `state` | enum | `idle`, `running`, `blocked`, `closing` |
| `superclaude_profile` | string? | SuperClaude config/mode to use |
| `mcp_profile` | string? | Additional MCP server configuration |
| `attached_task_ids` | string[] | Backlog task IDs being worked on |
| `current_job_id` | string? | Currently executing job |
| `last_summary` | string? | Last job summary |
| `last_diff` | string? | Last git diff summary |
| `open_pr` | string? | Open PR URL if any |
| `last_activity_at` | datetime | Last activity timestamp |
| `created_at` | datetime | Creation timestamp |

### Session States

```
┌───────┐     create      ┌───────┐
│       │ ───────────────►│       │
│ (new) │                 │ idle  │◄─────────────────┐
│       │                 │       │                  │
└───────┘                 └───┬───┘                  │
                              │ run_instruction      │ job_complete
                              ▼                      │
                         ┌────────┐                  │
                         │running │──────────────────┘
                         └───┬────┘
                             │ approval_needed
                             ▼
                         ┌────────┐
                         │blocked │
                         └───┬────┘
                             │ approve/deny
                             ▼
                         ┌────────┐
                         │ idle   │
                         └────────┘
```

### JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "session_id": { "type": "string", "pattern": "^S[0-9]+$" },
    "project_id": { "type": "string" },
    "display_name": { "type": ["string", "null"] },
    "workspace_path": { "type": "string" },
    "branch": { "type": "string" },
    "state": {
      "type": "string",
      "enum": ["idle", "running", "blocked", "closing"]
    },
    "superclaude_profile": { "type": ["string", "null"] },
    "mcp_profile": { "type": ["string", "null"] },
    "attached_task_ids": {
      "type": "array",
      "items": { "type": "string" }
    },
    "current_job_id": { "type": ["string", "null"] },
    "last_summary": { "type": ["string", "null"] },
    "last_diff": { "type": ["string", "null"] },
    "open_pr": { "type": ["string", "null"] },
    "last_activity_at": { "type": "string", "format": "date-time" },
    "created_at": { "type": "string", "format": "date-time" }
  },
  "required": ["session_id", "project_id", "workspace_path", "branch", "state"]
}
```

## Task

Represents a backlog item (from Backlog.md or similar).

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Unique identifier (e.g., "T-123") |
| `project_id` | string | FK to Project |
| `title` | string | Task title |
| `description` | string? | Task description/body |
| `status` | enum | `todo`, `in_progress`, `blocked`, `needs_review`, `done` |
| `epic` | string? | Parent epic/feature |
| `priority` | enum | `low`, `medium`, `high`, `critical` |
| `session_id` | string? | Session currently working on this |
| `branch` | string? | Associated git branch |
| `assignee` | string? | `agent:<name>` or `human:<name>` |
| `tags` | string[] | Labels/tags |
| `created_at` | datetime | Creation timestamp |
| `updated_at` | datetime | Last update timestamp |

### Task Status Flow

```
todo ──► in_progress ──► needs_review ──► done
              │                │
              ▼                ▼
           blocked ◄───────────┘
```

### JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "task_id": { "type": "string" },
    "project_id": { "type": "string" },
    "title": { "type": "string" },
    "description": { "type": ["string", "null"] },
    "status": {
      "type": "string",
      "enum": ["todo", "in_progress", "blocked", "needs_review", "done"]
    },
    "epic": { "type": ["string", "null"] },
    "priority": {
      "type": "string",
      "enum": ["low", "medium", "high", "critical"],
      "default": "medium"
    },
    "session_id": { "type": ["string", "null"] },
    "branch": { "type": ["string", "null"] },
    "assignee": { "type": ["string", "null"] },
    "tags": { "type": "array", "items": { "type": "string" } },
    "created_at": { "type": "string", "format": "date-time" },
    "updated_at": { "type": "string", "format": "date-time" }
  },
  "required": ["task_id", "project_id", "title", "status"]
}
```

## Job

Represents a unit of work executed in a session.

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | Unique identifier (UUID) |
| `session_id` | string | FK to Session |
| `project_id` | string | FK to Project (denormalized) |
| `instruction` | string | Normalized instruction for Claude |
| `raw_input` | string | Original user input |
| `status` | enum | `queued`, `running`, `waiting_approval`, `done`, `failed`, `canceled` |
| `approval_required` | boolean | Whether approval is needed |
| `approval_scope` | string? | What needs approval (write, run, push) |
| `approval_state` | enum? | `pending`, `approved`, `denied` |
| `log_path` | string? | Path to log file |
| `result_summary` | string? | Summary of results |
| `files_changed` | string[]? | List of modified files |
| `error` | string? | Error message if failed |
| `created_at` | datetime | Creation timestamp |
| `started_at` | datetime? | Execution start |
| `finished_at` | datetime? | Execution end |

### Job Status Flow

```
queued ──► running ──┬──► done
              │      │
              │      └──► failed
              ▼
      waiting_approval ──┬──► running (approved)
                         └──► canceled (denied)
```

### JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "job_id": { "type": "string", "format": "uuid" },
    "session_id": { "type": "string" },
    "project_id": { "type": "string" },
    "instruction": { "type": "string" },
    "raw_input": { "type": "string" },
    "status": {
      "type": "string",
      "enum": ["queued", "running", "waiting_approval", "done", "failed", "canceled"]
    },
    "approval_required": { "type": "boolean", "default": false },
    "approval_scope": { "type": ["string", "null"] },
    "approval_state": {
      "type": ["string", "null"],
      "enum": ["pending", "approved", "denied", null]
    },
    "log_path": { "type": ["string", "null"] },
    "result_summary": { "type": ["string", "null"] },
    "files_changed": {
      "type": ["array", "null"],
      "items": { "type": "string" }
    },
    "error": { "type": ["string", "null"] },
    "created_at": { "type": "string", "format": "date-time" },
    "started_at": { "type": ["string", "null"], "format": "date-time" },
    "finished_at": { "type": ["string", "null"], "format": "date-time" }
  },
  "required": ["job_id", "session_id", "project_id", "instruction", "raw_input", "status"]
}
```

## SQLite Schema

```sql
-- Projects table
CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    remote_url TEXT,
    default_branch TEXT DEFAULT 'main',
    backlog_enabled INTEGER DEFAULT 0,
    backlog_path TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Sessions table
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    display_name TEXT,
    workspace_path TEXT NOT NULL UNIQUE,
    branch TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'idle',
    superclaude_profile TEXT,
    mcp_profile TEXT,
    attached_task_ids TEXT DEFAULT '[]',  -- JSON array
    current_job_id TEXT,
    last_summary TEXT,
    last_diff TEXT,
    open_pr TEXT,
    last_activity_at TEXT DEFAULT (datetime('now')),
    created_at TEXT DEFAULT (datetime('now'))
);

-- Tasks table (cache of Backlog.md, synced)
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'todo',
    epic TEXT,
    priority TEXT DEFAULT 'medium',
    session_id TEXT REFERENCES sessions(session_id),
    branch TEXT,
    assignee TEXT,
    tags TEXT DEFAULT '[]',  -- JSON array
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Jobs table
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    instruction TEXT NOT NULL,
    raw_input TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    approval_required INTEGER DEFAULT 0,
    approval_scope TEXT,
    approval_state TEXT,
    log_path TEXT,
    result_summary TEXT,
    files_changed TEXT,  -- JSON array
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT,
    finished_at TEXT
);

-- User preferences table (for Telegram users)
CREATE TABLE user_preferences (
    chat_id INTEGER PRIMARY KEY,
    ai_model_id TEXT,
    ai_provider TEXT,
    active_session_id TEXT,
    notifications_enabled INTEGER DEFAULT 1,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX idx_sessions_project ON sessions(project_id);
CREATE INDEX idx_sessions_state ON sessions(state);
CREATE INDEX idx_tasks_project ON tasks(project_id);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_session ON tasks(session_id);
CREATE INDEX idx_jobs_session ON jobs(session_id);
CREATE INDEX idx_jobs_status ON jobs(status);
```

## User Preferences

Stores per-user settings for Telegram users. Persists across bot restarts.

| Field | Type | Description |
|-------|------|-------------|
| `chat_id` | integer | Telegram chat ID (primary key) |
| `ai_model_id` | string? | Selected AI model ID |
| `ai_provider` | string? | Model provider ("openrouter" or "gemini") |
| `active_session_id` | string? | Last active session |
| `notifications_enabled` | boolean | Whether notifications are enabled |
| `updated_at` | datetime | Last update timestamp |
