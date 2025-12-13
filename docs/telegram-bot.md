# Telegram Bot Interface

## Overview

The Telegram bot is a thin UI layer on top of the Orchestrator MCP. All commands map directly to MCP tools.

## Message Format

### Session Context Tags

Every message related to a session includes visual tags:

```
📂 [project-a] 🔹 [S12] 🌿 feature-x
```

Components:
- 📂 `[project-id]` - Repository identifier
- 🔹 `[session-id]` - Session identifier (S1, S12, etc.)
- 🌿 `branch-name` - Git branch

### Job Status Prefixes

| Prefix | Meaning |
|--------|---------|
| 🔧 | Job running |
| ✅ | Job completed successfully |
| ❌ | Job failed |
| ⚠️ | Approval needed |
| ⏸️ | Job paused/blocked |
| 📋 | Status/info message |

### Examples

```
🔧 S12 (project-a/feature-x): Running "implement login form"

✅ S12 (project-a/feature-x): Completed
   3 files changed: src/auth/login.py, src/auth/forms.py, tests/test_login.py
   Summary: Added login form with email/password validation

⚠️ S12 (project-a/feature-x): Approval needed
   Action: git push origin feature-x
   [Approve] [Deny]
```

## Commands

### Project Commands

#### `/projects`
List all registered projects.

**MCP Call**: `list_projects()`

**Output**:
```
📂 Projects:

1. project-a (2 active sessions)
   ~/projects/project-a

2. project-b (0 active sessions)
   ~/projects/project-b

3. project-c (1 active session)
   ~/projects/project-c
```

#### `/project <name>`
Get project details.

**MCP Call**: `get_project(project_id)`

**Output**:
```
📂 project-a

Path: ~/projects/project-a
Remote: git@github.com:user/project-a.git
Default branch: main
Backlog: ✅ enabled (15 tasks)

Active sessions:
  🔹 S12 🌿 feature-x (idle)
  🔹 S15 🌿 bugfix-auth (running)
```

---

### Session Commands

#### `/sessions`
List all active sessions.

**MCP Call**: `list_sessions()`

**Output**:
```
🔹 Active Sessions:

S12 📂 project-a 🌿 feature-x
    State: idle | Last: 10m ago

S15 📂 project-a 🌿 bugfix-auth
    State: running | Job: "fix auth token refresh"

S7  📂 project-b 🌿 refactor-api
    State: blocked | Waiting: approval for push
```

#### `/new <project> [branch]`
Create a new session.

**MCP Call**: `create_session(project_id, branch)`

**Usage**:
```
/new project-a feature-payments
/new project-a  # uses default branch
```

**Output**:
```
✅ Session created

🔹 S16 📂 project-a 🌿 feature-payments
Workspace: <root>/.televibe/workspaces/project-a/S16/feature-payments

Ready for instructions. Reply to this message or use:
/run S16 <instruction>
```

#### `/use <session_id>`
Set active session for this chat.

**MCP Call**: `use_session(session_id)` + store in chat state

**Output**:
```
✅ Active session set to S12

📂 [project-a] 🔹 [S12] 🌿 feature-x

Your messages will now be sent to this session.
```

#### `/close <session_id>`
Close a session.

**MCP Call**: `close_session(session_id)`

**Output**:
```
✅ Session S12 closed

Worktree removed: <root>/.televibe/workspaces/project-a/S12/feature-x
Branch preserved: feature-x
```

---

### Task Commands

#### `/tasks <project>`
List tasks for a project.

**MCP Call**: `list_project_tasks(project_id)`

**Output**:
```
📋 Tasks for project-a:

TODO:
  T-125 [high] Implement password reset
  T-126 [medium] Add email verification
  T-127 [low] Improve error messages

IN PROGRESS:
  T-123 [high] Implement login form (S12)
  T-124 [medium] Fix auth token refresh (S15)

NEEDS REVIEW:
  T-120 [medium] Add logout endpoint
```

#### `/next <project> [count]`
Get next prioritized tasks.

**MCP Call**: `get_next_tasks(project_id, limit)`

**Output**:
```
📋 Next tasks for project-a:

1. T-125 [high] Implement password reset
   Epic: authentication

2. T-126 [medium] Add email verification
   Epic: authentication

3. T-127 [low] Improve error messages
   Epic: ux
```

#### `/claim <task_id> <session_id>`
Assign task to session.

**MCP Call**: `claim_task(task_id, session_id)`

**Output**:
```
✅ Task T-125 claimed by S12

📂 [project-a] 🔹 [S12] 🌿 feature-x
Now working on: Implement password reset
```

---

### Job Commands

#### `/run [session_id] <instruction>`
Queue a job.

**MCP Call**: `run_instruction(session_id, instruction)`

**Usage**:
```
/run implement the login form with validation
/run S12 implement the login form with validation
```

**Output**:
```
🔧 Job queued

📂 [project-a] 🔹 [S12] 🌿 feature-x
Instruction: implement the login form with validation
Job ID: 550e8400-e29b-41d4-a716-446655440000

Status updates will follow...
```

#### `/status [session_id]`
Get current job status.

**MCP Call**: `get_session(session_id)` + `list_jobs(session_id, status=['running'])`

**Output**:
```
📋 Status for S12

📂 [project-a] 🔹 [S12] 🌿 feature-x
State: running

Current job:
🔧 "implement login form with validation"
   Started: 2 minutes ago
   Progress: Editing src/auth/login.py...
```

#### `/summary [session_id]`
Get session summary.

**MCP Call**: `get_session(session_id)`

**Output**:
```
📋 Summary for S12

📂 [project-a] 🔹 [S12] 🌿 feature-x

Last job: ✅ Completed
  Instruction: implement login form with validation
  Duration: 3m 45s
  Files changed:
    - src/auth/login.py (new)
    - src/auth/forms.py (modified)
    - tests/test_login.py (new)

Git status:
  Branch: feature-x (+2 commits ahead of main)
  Changed: 3 files, +245 -12 lines

Tasks:
  - T-123 [in_progress] Implement login form
```

#### `/tail [session_id] [lines]`
Get recent job logs.

**MCP Call**: `get_job_logs(job_id, tail)`

**Output**:
```
📜 Logs for S12 (last 20 lines):

[10:32:15] Reading src/auth/forms.py...
[10:32:16] Analyzing existing form patterns...
[10:32:18] Creating login form component...
[10:32:25] Writing src/auth/login.py...
[10:32:30] Running linter...
[10:32:32] All checks passed
[10:32:33] Job completed successfully
```

#### `/cancel [job_id]`
Cancel a running job.

**MCP Call**: `cancel_job(job_id)`

---

### Approval Commands

#### `/approvals`
List pending approvals.

**MCP Call**: `list_pending_approvals()`

**Output**:
```
⚠️ Pending Approvals:

1. S12 (project-a/feature-x)
   Action: git push origin feature-x
   Requested: 5 minutes ago
   [Approve] [Deny]

2. S15 (project-a/bugfix-auth)
   Action: Run: npm run deploy
   Requested: 2 minutes ago
   [Approve] [Deny]
```

#### Inline Approval Buttons

When approval is needed, the bot sends a message with inline buttons:

```
⚠️ S12 (project-a/feature-x): Approval needed

Action: git push origin feature-x
Reason: Push to remote repository

Changes to push:
  - 2 commits
  - 3 files changed

[✅ Approve] [❌ Deny]
```

Button callbacks:
- `approve:<job_id>` → `approve_job(job_id)`
- `deny:<job_id>` → `deny_job(job_id)`

---

## Reply-to Routing

### Session Cards

When the bot sends session-related messages, they include embedded metadata for reply routing.

**Card Structure**:
```
📂 [project-a] 🔹 [S12] 🌿 feature-x

[Session content here...]

───────────────
Reply to send instructions to this session
```

**Reply Handling**:
1. User replies to a session card
2. Bot extracts session_id from the original message
3. Bot calls `run_instruction(session_id, reply_text)`

### Natural Language Support

The Middle AI layer can parse natural language:

| User says | Interpreted as |
|-----------|----------------|
| "fix the auth bug" | `run_instruction(active_session, "fix the auth bug")` |
| "what's next on project-a?" | `get_next_tasks("project-a")` |
| "switch to the payments feature" | `use_session(<session on payments branch>)` |
| "show me all sessions" | `list_sessions()` |
| "start working on T-125" | `claim_task("T-125", active_session) + run_instruction(...)` |

---

## Bot State

### Per-Chat State

```json
{
  "chat_id": 123456789,
  "active_session_id": "S12",
  "last_project_id": "project-a",
  "notification_level": "all",  // all | errors | approvals
  "reply_routing": {
    "message_id_123": "S12",
    "message_id_456": "S15"
  }
}
```

### Notification Preferences

```
/notifications all       # All updates
/notifications errors    # Only errors and approvals
/notifications approvals # Only approvals
/notifications off       # Disable (use /status to check manually)
```

---

## Error Handling

### Error Message Format

```
❌ Error

Command: /run implement feature
Session: S12

Error: Session is currently running another job.
       Use /cancel to stop it, or wait for completion.

Suggestion: Use /status to check current job progress.
```

### Common Errors

| Error | Response |
|-------|----------|
| Session not found | "Session S99 not found. Use /sessions to list." |
| Project not found | "Project 'foo' not found. Use /projects to list." |
| Session busy | "Session S12 is running a job. Wait or /cancel." |
| No active session | "No active session. Use /use <id> or /new <project>." |
| Approval timeout | "Approval request expired. Job canceled." |

---

## Webhook Setup

### Telegram Bot Configuration

1. Create bot via @BotFather
2. Get bot token
3. Set webhook:

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-server.com/telegram/webhook"}'
```

### Command Registration

Register commands with BotFather:

```
projects - List all projects
sessions - List active sessions
new - Create new session
use - Set active session
close - Close a session
tasks - List project tasks
next - Get next tasks
run - Run instruction
status - Get session status
summary - Get session summary
tail - View job logs
cancel - Cancel running job
approvals - List pending approvals
notifications - Set notification level
help - Show help
```
