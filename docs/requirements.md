# TeleVibeCode Requirements Specification

## Non-Functional Requirements

### Performance Requirements

| Requirement | Target | Measurement |
|-------------|--------|-------------|
| **NFR-PERF-001** Job queue response | < 500ms | Time from API call to "queued" confirmation |
| **NFR-PERF-002** Session creation | < 5s | Time from API call to "idle" state |
| **NFR-PERF-003** Event delivery | < 1s | Time from event emission to Telegram delivery |
| **NFR-PERF-004** Concurrent sessions | >= 10 | Per orchestrator instance |
| **NFR-PERF-005** Concurrent jobs | >= 3 | Configurable via `runner.max_concurrent_jobs` |

### Reliability Requirements

| Requirement | Target | Measurement |
|-------------|--------|-------------|
| **NFR-REL-001** Orchestrator uptime | 99.5% | Excluding planned maintenance |
| **NFR-REL-002** Data durability | No loss | SQLite with WAL mode, periodic backups |
| **NFR-REL-003** Graceful degradation | Required | System functional if Claude API unavailable |
| **NFR-REL-004** Recovery time | < 30s | From crash to operational |

### Security Requirements

| Requirement | Description |
|-------------|-------------|
| **NFR-SEC-001** | Telegram bot tokens stored in environment variables, never in config files |
| **NFR-SEC-002** | Approval required for shell commands by default |
| **NFR-SEC-003** | Git push always requires explicit approval |
| **NFR-SEC-004** | Workspace isolation via git worktrees prevents cross-session access |
| **NFR-SEC-005** | Telegram chat ID whitelist (optional, empty = allow all) |

---

## Acceptance Criteria by MCP Tool

### Project Tools

#### `register_project`

| Criterion | Specification |
|-----------|---------------|
| **Valid input** | Path exists, contains `.git` directory |
| **Success** | Returns project object with generated `project_id` |
| **Duplicate** | If path already registered, returns existing project |
| **Invalid path** | Error: "Path does not exist: {path}" |
| **Not a repo** | Error: "Path is not a git repository: {path}" |

#### `create_session`

| Criterion | Specification |
|-----------|---------------|
| **Valid input** | project_id exists, branch is valid git branch name |
| **Success** | Session created with state "idle", worktree exists |
| **Branch exists** | Uses existing branch, creates worktree from it |
| **Branch new** | Creates branch from base_branch (or default_branch) |
| **Project not found** | Error: "Project not found: {project_id}" |
| **Branch conflict** | Error: "Branch has active session: {existing_session_id}" |
| **Worktree failure** | Error: "Failed to create worktree: {git_error}" |

### Job Tools

#### `run_instruction`

| Criterion | Specification |
|-----------|---------------|
| **Valid input** | session_id exists, instruction is non-empty string < 10000 chars |
| **Success** | Job created with status "queued", job_id returned |
| **Session busy** | Job queued, position in queue returned |
| **Session not found** | Error: "Session not found: {session_id}" |
| **Session closing** | Error: "Session is closing, cannot accept jobs" |
| **Empty instruction** | Error: "Instruction cannot be empty" |
| **Instruction too long** | Error: "Instruction exceeds 10000 character limit" |

---

## Timeout Handling Specification

### Job Timeout

```yaml
timeout:
  default_seconds: 3600  # 1 hour
  max_seconds: 14400     # 4 hours
  grace_period_seconds: 30

behavior:
  on_timeout:
    1. Send SIGTERM to Claude Code process
    2. Wait grace_period_seconds for clean exit
    3. If still running, send SIGKILL
    4. Set job.status = "failed"
    5. Set job.error = "Job exceeded timeout of {timeout}s"
    6. Preserve workspace state (do not clean up)
    7. Emit event "job.failed" with error_type = "timeout"
    8. Set session.state = "idle"

  partial_work:
    - All file changes remain in workspace
    - Log file preserved (may be truncated)
    - Git status available via session
    - User can resume with new job or close session
```

### Approval Timeout

```yaml
approval_timeout:
  default_seconds: 3600  # 1 hour
  max_seconds: 86400     # 24 hours

behavior:
  on_timeout:
    1. Set job.status = "canceled"
    2. Set job.approval_state = "expired"
    3. Set job.error = "Approval request expired after {timeout}s"
    4. Emit event "job.canceled" with reason = "approval_timeout"
    5. Set session.state = "idle"
    6. Notify user via Telegram: "⏱️ Approval expired for job in {session_id}"
```

---

## Approval Scope Enumeration

```python
class ApprovalScope(str, Enum):
    """Complete enumeration of actions requiring approval."""

    # File operations
    WRITE = "write"           # Create or modify files
    DELETE_FILE = "delete_file"  # Delete files

    # Shell operations
    SHELL = "shell"           # Execute shell commands
    SHELL_SUDO = "shell_sudo" # Execute privileged commands

    # Git operations
    PUSH = "push"             # Push to remote repository
    FORCE_PUSH = "force_push" # Force push (--force)
    DELETE_BRANCH = "delete_branch"  # Delete git branch

    # Deployment operations
    DEPLOY = "deploy"         # Deployment commands
    DEPLOY_PROD = "deploy_prod"  # Production deployment

    # External operations
    EXTERNAL_API = "external_api"  # Calls to external APIs
    NETWORK = "network"       # Network operations (curl, wget, etc.)
```

### Default Approval Configuration

```yaml
approval:
  # File operations
  require_for_write: false        # Allow file writes without approval
  require_for_delete_file: true   # Require approval for file deletion

  # Shell operations
  require_for_shell: true         # Require approval for shell commands
  require_for_shell_sudo: true    # Always require for privileged

  # Git operations
  require_for_push: true          # Require approval for push
  require_for_force_push: true    # Always require for force push
  require_for_delete_branch: true # Require approval for branch deletion

  # Deployment
  require_for_deploy: true        # Require approval for deployment
  require_for_deploy_prod: true   # Always require for production

  # External
  require_for_external_api: false # Allow external API calls
  require_for_network: true       # Require approval for network ops

  # Whitelist (never require approval)
  shell_whitelist:
    - "git status"
    - "git diff"
    - "git log"
    - "ls"
    - "pwd"
    - "cat"
    - "head"
    - "tail"
    - "wc"
    - "pytest"
    - "npm test"
    - "npm run lint"
```

---

## Error Handling Specification

### Error Response Format

```json
{
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "Session not found: S99",
    "details": {
      "session_id": "S99",
      "suggestion": "Use list_sessions() to see available sessions"
    }
  }
}
```

### Error Code Enumeration

| Code | HTTP-equiv | Description |
|------|------------|-------------|
| `PROJECT_NOT_FOUND` | 404 | Project ID does not exist |
| `SESSION_NOT_FOUND` | 404 | Session ID does not exist |
| `JOB_NOT_FOUND` | 404 | Job ID does not exist |
| `TASK_NOT_FOUND` | 404 | Task ID does not exist |
| `INVALID_PATH` | 400 | Path does not exist or is inaccessible |
| `NOT_A_REPOSITORY` | 400 | Path is not a git repository |
| `BRANCH_CONFLICT` | 409 | Branch already has active session |
| `SESSION_BUSY` | 409 | Session is running/blocked, cannot perform action |
| `SESSION_CLOSING` | 409 | Session is closing, cannot accept new work |
| `INSTRUCTION_EMPTY` | 400 | Instruction cannot be empty |
| `INSTRUCTION_TOO_LONG` | 400 | Instruction exceeds character limit |
| `APPROVAL_REQUIRED` | 403 | Action requires approval |
| `APPROVAL_DENIED` | 403 | Approval was denied |
| `APPROVAL_EXPIRED` | 408 | Approval request timed out |
| `TIMEOUT` | 408 | Operation timed out |
| `GIT_ERROR` | 500 | Git operation failed |
| `RUNNER_ERROR` | 500 | Job execution failed |
| `INTERNAL_ERROR` | 500 | Unexpected internal error |

---

## Capacity Limits

| Resource | Default Limit | Configurable | Notes |
|----------|---------------|--------------|-------|
| Projects per orchestrator | 100 | Yes | Limited by disk space |
| Active sessions per project | 10 | Yes | Git worktree limit |
| Total active sessions | 50 | Yes | Memory/process limit |
| Concurrent running jobs | 3 | Yes | CPU/API limit |
| Job queue per session | 10 | Yes | Prevent queue buildup |
| Instruction length | 10,000 chars | Yes | Reasonable prompt size |
| Log file size | 100 MB | Yes | Truncate if exceeded |
| Workspace disk usage | 10 GB | Yes | Per session |
| Event history retention | 30 days | Yes | For replay/audit |

### Behavior at Limits

```yaml
limits:
  sessions_per_project:
    value: 10
    on_exceed: "error"
    message: "Project has reached maximum sessions (10). Close existing sessions first."

  concurrent_jobs:
    value: 3
    on_exceed: "queue"
    message: "Job queued. {position} jobs ahead in global queue."

  job_queue_per_session:
    value: 10
    on_exceed: "reject"
    message: "Session job queue full (10). Wait for jobs to complete."

  log_file_size:
    value: "100MB"
    on_exceed: "truncate"
    message: null  # Silent truncation, note in log

  workspace_disk:
    value: "10GB"
    on_exceed: "error"
    message: "Workspace disk limit exceeded. Clean up or close session."
```

---

## Behavior Scenarios (Gherkin)

### Session Lifecycle

```gherkin
Feature: Session Lifecycle

  Scenario: Create session on existing branch
    Given project "myapp" exists with branch "feature-login"
    When I call create_session(project_id="myapp", branch="feature-login")
    Then response contains session_id matching "S\d+"
    And response.session.state is "idle"
    And response.session.workspace_path exists on filesystem
    And git worktree is valid at workspace_path

  Scenario: Create session on new branch
    Given project "myapp" exists with default_branch "main"
    And branch "feature-new" does not exist
    When I call create_session(project_id="myapp", branch="feature-new")
    Then response contains session_id
    And branch "feature-new" exists in repository
    And branch "feature-new" was created from "main"

  Scenario: Cannot create session if branch has active session
    Given project "myapp" exists
    And session "S5" exists on branch "feature-x"
    When I call create_session(project_id="myapp", branch="feature-x")
    Then error code is "BRANCH_CONFLICT"
    And error message contains "S5"

  Scenario: Close session cleans up worktree
    Given session "S5" exists with workspace "/projects/workspaces/myapp/S5/feature-x"
    When I call close_session(session_id="S5")
    Then response.worktree_removed is true
    And path "/projects/workspaces/myapp/S5" does not exist
    And session "S5" is removed from database
```

### Job Execution

```gherkin
Feature: Job Execution

  Scenario: Run instruction queues job
    Given session "S5" exists with state "idle"
    When I call run_instruction(session_id="S5", instruction="fix the bug")
    Then response.job.status is "queued"
    And response.job.job_id is a valid UUID
    And session state changes to "running" when job starts

  Scenario: Run instruction while job running
    Given session "S5" has a job in "running" state
    When I call run_instruction(session_id="S5", instruction="another task")
    Then response.job.status is "queued"
    And response.queue_position is 1

  Scenario: Job completion updates session
    Given session "S5" has job "J1" in "running" state
    When job "J1" completes successfully
    Then job "J1" status is "done"
    And job "J1" has result_summary
    And job "J1" has files_changed
    And session "S5" state is "idle"
    And event "job.completed" is emitted

  Scenario: Job timeout handling
    Given session "S5" has job "J1" in "running" state
    And job "J1" has been running for 3601 seconds
    When timeout check runs
    Then SIGTERM is sent to job process
    And after 30 seconds, SIGKILL is sent if still running
    And job "J1" status is "failed"
    And job "J1" error contains "timeout"
    And session "S5" state is "idle"
    And workspace is preserved
```

### Approval Flow

```gherkin
Feature: Approval Flow

  Scenario: Job requires approval for push
    Given session "S5" has job "J1" running
    And approval is required for "push"
    When job attempts git push
    Then job "J1" status changes to "waiting_approval"
    And job "J1" approval_scope is "push"
    And event "job.approval_needed" is emitted
    And Telegram shows approval buttons

  Scenario: Approve pending job
    Given job "J1" has status "waiting_approval"
    When I call approve_job(job_id="J1")
    Then job "J1" status changes to "running"
    And job "J1" approval_state is "approved"
    And job execution resumes

  Scenario: Deny pending job
    Given job "J1" has status "waiting_approval"
    When I call deny_job(job_id="J1", reason="Not ready for push")
    Then job "J1" status is "canceled"
    And job "J1" approval_state is "denied"
    And session state is "idle"
    And event "job.canceled" is emitted with reason

  Scenario: Approval timeout
    Given job "J1" has status "waiting_approval"
    And approval was requested 3601 seconds ago
    When approval timeout check runs
    Then job "J1" status is "canceled"
    And job "J1" approval_state is "expired"
    And Telegram notification sent about expiration
```
