# TeleVibeCode Data Models

## Entity Relationship

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
