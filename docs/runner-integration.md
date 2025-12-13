# Runner & Claude Code Integration

## Overview

The Runner is responsible for executing Claude Code + SuperClaude within session workspaces. This document covers the integration patterns, permission handling, and structured output capture.

## Execution Modes

### Mode 1: Job Mode (Primary)

Single instruction execution with explicit start/end.

```
Runner receives: run_instruction(session_id, instruction)
Runner executes: claude -p "<instruction>" in workspace
Runner captures: stdout/stderr, exit code, file changes
```

**Characteristics:**
- Stateless from Claude's perspective (new conversation each job)
- Clear boundaries (job starts, runs, ends)
- Easy to track and log
- No conversation continuity

**Best for:**
- Discrete tasks: "implement X", "fix Y", "refactor Z"
- Tasks with clear success criteria
- Automated workflows

### Mode 2: Session Mode (Interactive)

Persistent Claude session with message passing.

```
Runner maintains: Long-running claude process per session
Runner receives: send_message(session_id, message)
Runner passes:   Message to stdin of running process
Runner captures: Streaming responses
```

**Characteristics:**
- Conversation continuity within session
- Claude remembers previous context
- More natural for iterative work
- Harder to manage lifecycle

**Best for:**
- Exploratory work: "investigate X, then based on what you find..."
- Multi-step refinement
- Complex debugging sessions

### Hybrid Approach (Recommended)

Use **Job Mode** as the default, with optional "continuation" flag:

```python
class Job:
    instruction: str
    continue_from: Optional[str]  # Previous job_id for context
    include_context: bool = False  # Include session's recent history
```

When `include_context=True`, Runner prepends context:
```
Previous work in this session:
- Job 1: "implement login form" → completed, 3 files changed
- Job 2: "add validation" → completed, updated src/auth/forms.py

Current instruction: "add password strength indicator"
```

## Claude Code Invocation

### Command Construction

```python
def build_claude_command(job: Job, session: Session) -> list[str]:
    cmd = ["claude"]

    # Core flags
    cmd.extend(["-p", job.instruction])

    # Output format (if available)
    cmd.extend(["--output-format", "stream-json"])

    # Permission handling (see below)
    if session.auto_approve_writes:
        cmd.append("--dangerously-skip-permissions")

    # SuperClaude integration
    if session.superclaude_profile:
        # SuperClaude is configured via .claude/ files, not CLI flags
        # Ensure workspace has correct .claude/settings.json
        pass

    return cmd
```

### Environment Variables

```python
def build_environment(job: Job, session: Session, project: Project) -> dict:
    return {
        # Standard
        **os.environ,

        # TeleVibeCode context
        "TELEVIBE_PROJECT_ID": project.project_id,
        "TELEVIBE_SESSION_ID": session.session_id,
        "TELEVIBE_JOB_ID": job.job_id,
        "TELEVIBE_BRANCH": session.branch,

        # Paths
        "TELEVIBE_WORKSPACE": session.workspace_path,
        "TELEVIBE_ORCHESTRATOR": config.orchestrator_url,

        # For hooks (see below)
        "TELEVIBE_APPROVAL_ENDPOINT": f"{config.orchestrator_url}/approve",
    }
```

### Working Directory

Always execute in the session's workspace (git worktree):

```python
process = await asyncio.create_subprocess_exec(
    *cmd,
    cwd=session.workspace_path,  # Critical!
    env=env,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.STDOUT,
)
```

## Permission & Approval Handling

### Strategy 1: Pre-flight Approval

Ask for blanket approval before job starts:

```
⚠️ S12 (project-a/feature-x): New job

Instruction: "implement password reset with email"

This may involve:
- Creating/modifying files
- Running shell commands
- Accessing external services

[▶️ Run with approval] [▶️ Run auto-approve writes] [❌ Cancel]
```

**Pros:** Simple, one approval per job
**Cons:** No granular control, may over-approve

### Strategy 2: Claude Code Hooks (Recommended)

Use Claude Code's hook system to intercept actions:

**.claude/settings.local.json** (in workspace):
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|Bash",
        "command": "televibe-hook check-approval"
      }
    ]
  }
}
```

**televibe-hook** script:
```bash
#!/bin/bash
# Called by Claude Code before tool use
# Receives tool info via stdin or env

TOOL_NAME="$CLAUDE_TOOL_NAME"
TOOL_INPUT="$CLAUDE_TOOL_INPUT"

# Check with orchestrator
RESULT=$(curl -s -X POST "$TELEVIBE_APPROVAL_ENDPOINT" \
  -H "Content-Type: application/json" \
  -d "{
    \"job_id\": \"$TELEVIBE_JOB_ID\",
    \"tool\": \"$TOOL_NAME\",
    \"input\": $TOOL_INPUT
  }")

if [ "$RESULT" = "approved" ]; then
  exit 0  # Allow
elif [ "$RESULT" = "denied" ]; then
  echo "Action denied by user" >&2
  exit 1  # Block
else
  # Pending - wait for approval
  echo "Waiting for approval..." >&2
  # Poll or wait for webhook
  while true; do
    sleep 2
    RESULT=$(curl -s "$TELEVIBE_APPROVAL_ENDPOINT/$TELEVIBE_JOB_ID/status")
    if [ "$RESULT" = "approved" ]; then
      exit 0
    elif [ "$RESULT" = "denied" ]; then
      exit 1
    fi
  done
fi
```

**Pros:** Granular control, real-time approval
**Cons:** More complex, hook script required per workspace

### Strategy 3: Post-hoc Review

Let Claude run freely, review changes before commit/push:

```python
async def on_job_complete(job: Job, session: Session):
    # Get diff
    diff = await git_diff(session.workspace_path)

    if requires_review(diff):
        job.status = "waiting_approval"
        emit_event("job.review_needed", {
            "job_id": job.job_id,
            "diff": diff,
            "files_changed": get_changed_files(diff),
        })
        # Wait for approval before allowing next job
```

**Pros:** Non-blocking during execution
**Cons:** May need to revert changes if denied

### Recommended Approach

Combine strategies based on action type:

| Action | Strategy |
|--------|----------|
| Read files | Auto-approve |
| Write/Edit files | Hook-based or post-hoc |
| Safe shell commands (ls, git status) | Auto-approve |
| Risky shell commands | Hook-based with approval |
| Git push | Always require explicit approval |
| External API calls | Hook-based |

## Output Capture

### Stream Formats

**Plain text** (default):
```
Reading file src/auth/login.py...
Creating new file src/auth/reset.py...
Writing password reset implementation...
Done. 2 files created, 1 modified.
```

**Stream JSON** (if Claude supports --output-format stream-json):
```json
{"type": "tool_start", "tool": "Read", "input": {"path": "src/auth/login.py"}}
{"type": "tool_end", "tool": "Read", "success": true}
{"type": "tool_start", "tool": "Write", "input": {"path": "src/auth/reset.py"}}
{"type": "text", "content": "Creating password reset module..."}
{"type": "tool_end", "tool": "Write", "success": true}
{"type": "complete", "summary": "2 files created, 1 modified"}
```

### Log Capture

```python
async def capture_output(process, job: Job) -> AsyncGenerator[str, None]:
    log_path = f"{config.logs_dir}/{job.job_id}.log"

    async with aiofiles.open(log_path, "w") as log_file:
        async for line in process.stdout:
            decoded = line.decode("utf-8")

            # Write to log file
            await log_file.write(decoded)
            await log_file.flush()

            # Parse if JSON
            event = parse_line(decoded)

            # Emit event for real-time streaming
            yield event

    job.log_path = log_path
```

### Structured Event Extraction

```python
def parse_line(line: str) -> dict:
    # Try JSON first
    try:
        data = json.loads(line)
        return {
            "type": "structured",
            "event": data.get("type"),
            "data": data,
        }
    except json.JSONDecodeError:
        pass

    # Pattern matching for plain text
    patterns = [
        (r"Reading file (.+)\.\.\.", "file_read"),
        (r"Writing (?:to )?(.+)\.\.\.", "file_write"),
        (r"Running: (.+)", "shell_command"),
        (r"Error: (.+)", "error"),
        (r"Done\. (.+)", "complete"),
    ]

    for pattern, event_type in patterns:
        if match := re.match(pattern, line):
            return {
                "type": "parsed",
                "event": event_type,
                "data": match.groups(),
                "raw": line,
            }

    return {"type": "raw", "line": line}
```

## Result Extraction

After job completion, extract structured results:

```python
async def extract_results(job: Job, session: Session) -> JobResult:
    workspace = session.workspace_path

    # Git diff for changes
    diff_output = await run_git(workspace, ["diff", "--stat"])
    full_diff = await run_git(workspace, ["diff"])

    # Changed files
    status = await run_git(workspace, ["status", "--porcelain"])
    files_changed = parse_git_status(status)

    # Try to extract summary from log
    summary = await extract_summary_from_log(job.log_path)

    return JobResult(
        job_id=job.job_id,
        success=job.exit_code == 0,
        files_changed=files_changed,
        diff_stat=diff_output,
        diff_full=full_diff,
        summary=summary,
        error=job.error if not job.success else None,
    )
```

## SuperClaude Integration

SuperClaude is configured via `.claude/` directory in each workspace.

### Workspace Setup

When creating a session:

```python
async def setup_superclaude(session: Session, profile: str):
    workspace = session.workspace_path
    claude_dir = Path(workspace) / ".claude"
    claude_dir.mkdir(exist_ok=True)

    # Copy profile settings
    profile_path = config.superclaude_profiles / f"{profile}.json"
    if profile_path.exists():
        shutil.copy(profile_path, claude_dir / "settings.json")

    # Add TeleVibeCode hooks
    settings = load_json(claude_dir / "settings.json")
    settings.setdefault("hooks", {})
    settings["hooks"]["PreToolUse"] = [
        {
            "matcher": "Bash|Write|Edit",
            "command": "televibe-hook check-approval"
        }
    ]
    save_json(claude_dir / "settings.json", settings)
```

### Profile Examples

**default.json** - Balanced, approval-gated:
```json
{
  "permissions": {
    "allow_read": true,
    "allow_write": false,
    "allow_bash": false
  }
}
```

**trusted.json** - Auto-approve writes, gate shell:
```json
{
  "permissions": {
    "allow_read": true,
    "allow_write": true,
    "allow_bash": false
  }
}
```

**autonomous.json** - Full auto-approve (dangerous):
```json
{
  "permissions": {
    "allow_read": true,
    "allow_write": true,
    "allow_bash": true
  }
}
```

## Error Handling

### Execution Errors

```python
async def handle_execution_error(job: Job, error: Exception):
    job.status = "failed"
    job.error = str(error)
    job.finished_at = now()

    # Classify error
    if isinstance(error, asyncio.TimeoutError):
        job.error_type = "timeout"
    elif isinstance(error, PermissionError):
        job.error_type = "permission"
    elif "SIGKILL" in str(error):
        job.error_type = "killed"
    else:
        job.error_type = "unknown"

    emit_event("job.failed", {
        "job_id": job.job_id,
        "error": job.error,
        "error_type": job.error_type,
    })
```

### Recovery Strategies

| Error Type | Recovery |
|------------|----------|
| Timeout | Cancel job, notify user, optionally retry |
| Permission denied | Request approval, resume if granted |
| Process killed | Log, clean up, notify user |
| Git conflict | Pause session, require manual resolution |

## Concurrency

### Per-Session Queue

Each session has a single job queue - one job at a time per session:

```python
class SessionRunner:
    def __init__(self, session: Session):
        self.session = session
        self.current_job: Optional[Job] = None
        self.queue: asyncio.Queue[Job] = asyncio.Queue()

    async def run(self):
        while True:
            job = await self.queue.get()
            self.current_job = job
            try:
                await self.execute(job)
            finally:
                self.current_job = None
                self.queue.task_done()
```

### Cross-Session Parallelism

Multiple sessions can run jobs in parallel:

```python
class OrchestratorRunner:
    def __init__(self):
        self.session_runners: dict[str, SessionRunner] = {}
        self.max_concurrent = config.runner.max_concurrent_jobs
        self.semaphore = asyncio.Semaphore(self.max_concurrent)

    async def run_job(self, session_id: str, job: Job):
        runner = self.get_or_create_runner(session_id)
        async with self.semaphore:
            await runner.queue.put(job)
```
