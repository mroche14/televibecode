# Orchestrator MCP Specification

## Overview

The Orchestrator MCP is the central brain of TeleVibeCode. It's installed as a Python package and runs as a server pointed at a **projects root** directory containing user repositories.

```bash
televibecode serve --root ~/projects
```

## Server Configuration

### Manifest (mcp.json)

```json
{
  "name": "televibecode-orchestrator",
  "version": "0.1.0",
  "description": "Orchestrator for managing Claude Code sessions across multiple projects",
  "protocol_version": "2024-11-05",
  "capabilities": {
    "tools": true,
    "resources": true
  }
}
```

### Configuration (config.yaml)

Located at `<projects-root>/.televibe/config.yaml`:

```yaml
# Orchestrator configuration
server:
  host: "127.0.0.1"
  port: 3100

# All paths relative to projects_root (set via --root CLI arg)
# Everything goes in .televibe/ - these defaults rarely need changing
paths:
  televibe_dir: ".televibe"                   # <root>/.televibe/
  workspaces_dir: ".televibe/workspaces"      # <root>/.televibe/workspaces/
  state_db: ".televibe/state.db"              # <root>/.televibe/state.db
  logs_dir: ".televibe/logs"                  # <root>/.televibe/logs/

defaults:
  superclaude_profile: "default"
  session_id_prefix: "S"
  auto_backlog_sync: true

runner:
  claude_command: "claude"
  timeout_seconds: 3600
  max_concurrent_jobs: 3

approval:
  require_for_writes: false
  require_for_shell: true
  require_for_push: true
  require_for_deploy: true

telegram:
  enabled: true
  bot_token_env: "TELEGRAM_BOT_TOKEN"
  allowed_chat_ids: []  # empty = allow all
```

## MCP Tools

### Project Tools

#### `list_projects`

List all registered projects.

**Parameters**: None

**Returns**:
```json
{
  "projects": [
    {
      "project_id": "project-a",
      "name": "Project A",
      "path": "~/projects/project-a",
      "default_branch": "main",
      "backlog_enabled": true,
      "active_sessions": 2
    }
  ]
}
```

#### `get_project`

Get details for a specific project.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `project_id` | string | yes | Project identifier |

**Returns**:
```json
{
  "project": {
    "project_id": "project-a",
    "name": "Project A",
    "path": "~/projects/project-a",
    "remote_url": "git@github.com:user/project-a.git",
    "default_branch": "main",
    "backlog_enabled": true,
    "backlog_path": "~/projects/project-a/backlog"
  }
}
```

#### `register_project`

Register a new project (existing repo).

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `path` | string | yes | Absolute path to git repo |
| `name` | string | no | Display name (defaults to folder name) |
| `project_id` | string | no | Custom ID (defaults to slugified name) |

**Returns**:
```json
{
  "project": { ... },
  "message": "Project registered successfully"
}
```

#### `scan_projects`

Scan repos directory and register all found repositories.

**Parameters**: None

**Returns**:
```json
{
  "found": 5,
  "registered": 3,
  "already_registered": 2,
  "projects": [ ... ]
}
```

---

### Session Tools

#### `list_sessions`

List all sessions, optionally filtered.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `project_id` | string | no | Filter by project |
| `state` | string | no | Filter by state |
| `limit` | number | no | Max results (default: 20) |

**Returns**:
```json
{
  "sessions": [
    {
      "session_id": "S12",
      "project_id": "project-a",
      "display_name": "Feature X",
      "branch": "feature-x",
      "state": "idle",
      "last_activity_at": "2025-12-13T10:30:00Z"
    }
  ]
}
```

#### `create_session`

Create a new session with git worktree.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `project_id` | string | yes | Target project |
| `branch` | string | yes | Branch name (created if doesn't exist) |
| `display_name` | string | no | Human-readable name |
| `superclaude_profile` | string | no | SuperClaude config to use |
| `base_branch` | string | no | Branch to create from (default: project's default_branch) |

**Returns**:
```json
{
  "session": {
    "session_id": "S15",
    "project_id": "project-a",
    "workspace_path": "<root>/.televibe/workspaces/project-a/S15/feature-x",
    "branch": "feature-x",
    "state": "idle"
  },
  "message": "Session created with worktree"
}
```

#### `get_session`

Get session details.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | yes | Session identifier |

**Returns**: Full session object with current job, tasks, summaries.

#### `close_session`

Close a session and clean up worktree.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | yes | Session to close |
| `force` | boolean | no | Force close even if running |
| `delete_branch` | boolean | no | Also delete the git branch |

**Returns**:
```json
{
  "message": "Session S12 closed",
  "worktree_removed": true,
  "branch_deleted": false
}
```

---

### Task Tools

#### `list_project_tasks`

List tasks for a project.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `project_id` | string | yes | Project identifier |
| `status` | string | no | Filter by status |
| `epic` | string | no | Filter by epic |
| `limit` | number | no | Max results |

**Returns**:
```json
{
  "tasks": [
    {
      "task_id": "T-123",
      "title": "Implement auth flow",
      "status": "todo",
      "priority": "high",
      "epic": "authentication"
    }
  ]
}
```

#### `get_next_tasks`

Get prioritized next tasks for a project.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `project_id` | string | yes | Project identifier |
| `limit` | number | no | How many tasks (default: 3) |
| `epic` | string | no | Focus on specific epic |

**Returns**: Prioritized list of unclaimed todo tasks.

#### `claim_task`

Assign a task to a session.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `task_id` | string | yes | Task to claim |
| `session_id` | string | yes | Session claiming it |

**Returns**:
```json
{
  "task": { ... },
  "message": "Task T-123 claimed by session S12"
}
```

#### `update_task_status`

Update task status.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `task_id` | string | yes | Task to update |
| `status` | string | yes | New status |
| `session_id` | string | no | Session making the update |

**Returns**: Updated task object.

#### `sync_backlog`

Sync tasks from Backlog.md files.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `project_id` | string | yes | Project to sync |

**Returns**:
```json
{
  "synced": 15,
  "added": 2,
  "updated": 3,
  "removed": 0
}
```

---

### Job Tools

#### `run_instruction`

Queue a job for execution.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | yes | Target session |
| `instruction` | string | yes | What to do |
| `raw_input` | string | no | Original user text |
| `task_ids` | string[] | no | Related tasks |

**Returns**:
```json
{
  "job": {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "session_id": "S12",
    "status": "queued",
    "instruction": "Implement login form with validation"
  }
}
```

#### `get_job`

Get job details and status.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `job_id` | string | yes | Job identifier |

**Returns**: Full job object with logs summary.

#### `list_jobs`

List jobs with filters.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | no | Filter by session |
| `status` | string[] | no | Filter by status(es) |
| `limit` | number | no | Max results |

**Returns**: Array of job summaries.

#### `cancel_job`

Cancel a queued or running job.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `job_id` | string | yes | Job to cancel |
| `reason` | string | no | Cancellation reason |

**Returns**: Updated job object.

#### `get_job_logs`

Get job execution logs.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `job_id` | string | yes | Job identifier |
| `tail` | number | no | Last N lines only |

**Returns**:
```json
{
  "job_id": "...",
  "log_path": "<root>/.televibe/logs/job-xxx.log",
  "content": "...",
  "truncated": false
}
```

---

### Approval Tools

#### `list_pending_approvals`

List all jobs waiting for approval.

**Parameters**: None

**Returns**:
```json
{
  "pending": [
    {
      "job_id": "...",
      "session_id": "S12",
      "project_id": "project-a",
      "approval_scope": "push",
      "instruction": "Push changes to remote",
      "created_at": "..."
    }
  ]
}
```

#### `approve_job`

Approve a pending job.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `job_id` | string | yes | Job to approve |
| `scope` | string | no | Limit approval scope |

**Returns**:
```json
{
  "job": { ... },
  "message": "Job approved, resuming execution"
}
```

#### `deny_job`

Deny a pending job.

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `job_id` | string | yes | Job to deny |
| `reason` | string | no | Denial reason |

**Returns**:
```json
{
  "job": { ... },
  "message": "Job denied and canceled"
}
```

---

## MCP Resources

### `projects://list`

Read-only resource listing all projects.

### `sessions://active`

Read-only resource listing active sessions with current state.

### `jobs://running`

Read-only resource listing currently running jobs.

### `approvals://pending`

Read-only resource listing pending approvals.

---

## Events (Notifications)

The orchestrator emits notifications for real-time updates:

| Event | Description |
|-------|-------------|
| `session.created` | New session created |
| `session.state_changed` | Session state transition |
| `session.closed` | Session closed |
| `job.queued` | Job added to queue |
| `job.started` | Job execution started |
| `job.progress` | Job progress update |
| `job.approval_needed` | Job waiting for approval |
| `job.completed` | Job finished successfully |
| `job.failed` | Job failed with error |
| `task.status_changed` | Task status updated |

### Event Payload Example

```json
{
  "event": "job.completed",
  "timestamp": "2025-12-13T10:30:00Z",
  "data": {
    "job_id": "...",
    "session_id": "S12",
    "project_id": "project-a",
    "branch": "feature-x",
    "result_summary": "Implemented login form, 3 files changed",
    "files_changed": ["src/auth/login.py", "src/auth/forms.py", "tests/test_login.py"]
  }
}
```

---

## Runner Implementation

### Job Execution Flow

```python
async def run_job(job: Job, session: Session):
    # 1. Update state
    job.status = "running"
    job.started_at = now()
    session.state = "running"

    # 2. Prepare environment
    env = {
        "CLAUDE_PROJECT": session.project_id,
        "CLAUDE_SESSION": session.session_id,
        "CLAUDE_BRANCH": session.branch,
    }

    # 3. Build command
    cmd = [
        "claude",
        "--dangerously-skip-permissions",  # or use hooks for approval
        "-p", job.instruction,
    ]

    # 4. Execute in workspace
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=session.workspace_path,
        env={**os.environ, **env},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    # 5. Stream and capture logs
    log_path = f"<root>/.televibe/logs/{job.job_id}.log"
    async with aiofiles.open(log_path, "w") as log:
        async for line in process.stdout:
            await log.write(line.decode())
            emit_event("job.progress", {"job_id": job.job_id, "line": line})

    # 6. Finalize
    await process.wait()
    job.status = "done" if process.returncode == 0 else "failed"
    job.finished_at = now()
    job.log_path = log_path
    session.state = "idle"

    emit_event("job.completed" if job.status == "done" else "job.failed", {...})
```

### Approval Hook Integration

For approval gating, use Claude Code hooks or wrap commands:

```python
async def check_approval_needed(job: Job, action: str) -> bool:
    config = load_config()
    if action == "write" and config.approval.require_for_writes:
        return True
    if action == "shell" and config.approval.require_for_shell:
        return True
    if action == "push" and config.approval.require_for_push:
        return True
    return False

async def request_approval(job: Job, scope: str):
    job.status = "waiting_approval"
    job.approval_scope = scope
    job.approval_state = "pending"
    emit_event("job.approval_needed", {...})
    # Telegram bot will show approval buttons
```
