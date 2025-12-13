# TeleVibeCode Operations Specification

## Failure Mode Analysis

### Component Failure Modes

| Component | Failure Mode | Detection | Impact | Recovery | RTO |
|-----------|--------------|-----------|--------|----------|-----|
| **Orchestrator MCP** | Process crash | Supervisor watchdog | All operations blocked | Auto-restart, state from SQLite | < 30s |
| **Orchestrator MCP** | Memory exhaustion | OOM killer / metrics | Process killed | Auto-restart, review limits | < 30s |
| **Runner** | Process hang | Job heartbeat timeout | Job stuck in "running" | SIGKILL, mark failed, notify | < 60s |
| **Runner** | Claude API failure | HTTP error codes | Jobs fail | Circuit breaker, retry with backoff | N/A |
| **Telegram Bot** | Network loss | Connection timeout | No user interaction | Auto-reconnect with backoff | < 60s |
| **Telegram Bot** | Rate limited | 429 response | Messages delayed | Exponential backoff | Self-healing |
| **SQLite DB** | Disk full | Write failure | State updates fail | Alert, cleanup old data | Manual |
| **SQLite DB** | Corruption | Integrity check fail | Data loss possible | Restore from backup | Manual |
| **Git worktree** | Creation failure | Git exit code | Session creation fails | Retry, then error to user | N/A |
| **Git worktree** | Disk full | Git error | Work cannot be saved | Alert, cleanup old worktrees | Manual |

### Degraded Operation Modes

```yaml
degraded_modes:
  claude_api_unavailable:
    detection: "Circuit breaker open on Claude API"
    behavior:
      - New jobs queued but not started
      - Existing running jobs will timeout
      - Status/list operations work normally
      - Telegram notifications continue
    user_message: "⚠️ Claude API temporarily unavailable. Jobs queued."
    recovery: "Circuit breaker half-open after timeout, test with single request"

  telegram_unavailable:
    detection: "Connection failures to Telegram API"
    behavior:
      - All operations work normally via MCP
      - Notifications queued in memory (max 1000)
      - Approvals blocked (require Telegram)
    user_message: null  # Can't reach user
    recovery: "Reconnect, flush notification queue"

  database_read_only:
    detection: "SQLite write failures"
    behavior:
      - Read operations work (list, get, status)
      - Write operations fail with error
      - Jobs cannot be created
    user_message: "⚠️ System in read-only mode. Writes disabled."
    recovery: "Fix disk issue, restart orchestrator"
```

---

## Circuit Breaker Configuration

### Claude Code / API

```yaml
circuit_breakers:
  claude_code:
    name: "Claude Code Execution"
    failure_threshold: 5        # Open after 5 consecutive failures
    success_threshold: 2        # Close after 2 successes in half-open
    timeout_seconds: 300        # Stay open for 5 minutes
    half_open_requests: 1       # Allow 1 test request

    failure_conditions:
      - exit_code: non-zero
        exclude_codes: [1]      # Exit 1 may be normal (lint errors, etc.)
      - timeout: true
      - signal: SIGKILL

    on_open:
      - log: "Circuit breaker OPEN for Claude Code"
      - metric: "circuit_breaker_state{name=claude_code} = 0"
      - notify_admin: true

    on_close:
      - log: "Circuit breaker CLOSED for Claude Code"
      - metric: "circuit_breaker_state{name=claude_code} = 1"

  telegram_api:
    name: "Telegram API"
    failure_threshold: 3
    success_threshold: 1
    timeout_seconds: 60
    half_open_requests: 1

    failure_conditions:
      - http_status: [500, 502, 503, 504]
      - connection_timeout: true
      - rate_limited: true  # 429

  git_operations:
    name: "Git Operations"
    failure_threshold: 3
    success_threshold: 1
    timeout_seconds: 30
    half_open_requests: 1

    failure_conditions:
      - exit_code: 128        # Git fatal errors
      - timeout: true
```

---

## Health Checks

### Liveness Probe

```yaml
liveness:
  endpoint: "/health/live"
  interval_seconds: 10
  timeout_seconds: 5
  failure_threshold: 3

  checks:
    - name: "process_alive"
      type: "pid_check"

    - name: "event_loop_responsive"
      type: "async_ping"
      timeout_ms: 1000

  response:
    healthy:
      status: 200
      body: {"status": "alive"}

    unhealthy:
      status: 503
      body: {"status": "dead", "reason": "..."}
```

### Readiness Probe

```yaml
readiness:
  endpoint: "/health/ready"
  interval_seconds: 15
  timeout_seconds: 10
  failure_threshold: 2

  checks:
    - name: "database_connected"
      type: "sqlite_query"
      query: "SELECT 1"

    - name: "telegram_connected"
      type: "telegram_getMe"
      timeout_ms: 5000

    - name: "repos_accessible"
      type: "path_exists"
      path: "${REPOS_ROOT}"

  response:
    ready:
      status: 200
      body:
        status: "ready"
        checks:
          database: "ok"
          telegram: "ok"
          repos: "ok"

    not_ready:
      status: 503
      body:
        status: "not_ready"
        checks:
          database: "ok"
          telegram: "failed: connection refused"
          repos: "ok"
```

---

## Metrics Specification

### Core Metrics

```yaml
metrics:
  # Session metrics
  - name: televibe_sessions_total
    type: counter
    description: "Total sessions created"
    labels: [project_id]

  - name: televibe_sessions_active
    type: gauge
    description: "Currently active sessions"
    labels: [project_id, state]

  - name: televibe_session_duration_seconds
    type: histogram
    description: "Session lifetime duration"
    labels: [project_id]
    buckets: [60, 300, 900, 3600, 14400, 86400]

  # Job metrics
  - name: televibe_jobs_total
    type: counter
    description: "Total jobs processed"
    labels: [project_id, status]

  - name: televibe_jobs_active
    type: gauge
    description: "Currently running jobs"
    labels: [project_id]

  - name: televibe_job_duration_seconds
    type: histogram
    description: "Job execution duration"
    labels: [project_id, status]
    buckets: [10, 30, 60, 120, 300, 600, 1800, 3600]

  - name: televibe_job_queue_size
    type: gauge
    description: "Jobs waiting in queue"
    labels: [session_id]

  # Approval metrics
  - name: televibe_approvals_total
    type: counter
    description: "Total approval requests"
    labels: [scope, result]  # result: approved, denied, expired

  - name: televibe_approvals_pending
    type: gauge
    description: "Currently pending approvals"

  - name: televibe_approval_response_seconds
    type: histogram
    description: "Time to approve/deny"
    labels: [scope]
    buckets: [10, 30, 60, 300, 900, 3600]

  # Event metrics
  - name: televibe_events_total
    type: counter
    description: "Total events emitted"
    labels: [event_type]

  - name: televibe_event_delivery_seconds
    type: histogram
    description: "Time from emit to Telegram delivery"
    labels: [event_type]
    buckets: [0.1, 0.5, 1, 2, 5, 10]

  # Circuit breaker metrics
  - name: televibe_circuit_breaker_state
    type: gauge
    description: "Circuit breaker state (1=closed, 0.5=half-open, 0=open)"
    labels: [name]

  - name: televibe_circuit_breaker_failures_total
    type: counter
    description: "Circuit breaker failure count"
    labels: [name]

  # Resource metrics
  - name: televibe_workspace_disk_bytes
    type: gauge
    description: "Disk usage per workspace"
    labels: [session_id]

  - name: televibe_log_file_bytes
    type: gauge
    description: "Log file size per job"
    labels: [job_id]
```

### Prometheus Exposition

```python
# Endpoint: /metrics
# Format: Prometheus text exposition format

# Example output:
"""
# HELP televibe_sessions_active Currently active sessions
# TYPE televibe_sessions_active gauge
televibe_sessions_active{project_id="myapp",state="idle"} 2
televibe_sessions_active{project_id="myapp",state="running"} 1
televibe_sessions_active{project_id="other",state="idle"} 1

# HELP televibe_jobs_total Total jobs processed
# TYPE televibe_jobs_total counter
televibe_jobs_total{project_id="myapp",status="done"} 45
televibe_jobs_total{project_id="myapp",status="failed"} 3
televibe_jobs_total{project_id="myapp",status="canceled"} 2

# HELP televibe_job_duration_seconds Job execution duration
# TYPE televibe_job_duration_seconds histogram
televibe_job_duration_seconds_bucket{project_id="myapp",status="done",le="60"} 10
televibe_job_duration_seconds_bucket{project_id="myapp",status="done",le="300"} 35
televibe_job_duration_seconds_bucket{project_id="myapp",status="done",le="+Inf"} 45
televibe_job_duration_seconds_sum{project_id="myapp",status="done"} 5420
televibe_job_duration_seconds_count{project_id="myapp",status="done"} 45
"""
```

---

## Alerting Rules

```yaml
alerts:
  # Critical alerts (page immediately)
  - name: OrchestratorDown
    condition: 'up{job="televibe-orchestrator"} == 0'
    for: 1m
    severity: critical
    summary: "TeleVibeCode orchestrator is down"
    description: "Orchestrator has been unreachable for 1 minute"

  - name: DatabaseCorruption
    condition: 'televibe_health_check{check="database"} == 0'
    for: 0s
    severity: critical
    summary: "Database health check failed"
    description: "SQLite database may be corrupted"

  # Warning alerts (notify, don't page)
  - name: JobStuckRunning
    condition: |
      (time() - televibe_job_start_timestamp) > 3600
      and televibe_jobs_active > 0
    for: 5m
    severity: warning
    summary: "Job running longer than 1 hour"
    description: "Job {{ $labels.job_id }} has been running for over 1 hour"

  - name: HighApprovalBacklog
    condition: 'televibe_approvals_pending > 5'
    for: 30m
    severity: warning
    summary: "Many pending approvals"
    description: "{{ $value }} approvals pending for 30+ minutes"

  - name: CircuitBreakerOpen
    condition: 'televibe_circuit_breaker_state == 0'
    for: 5m
    severity: warning
    summary: "Circuit breaker open"
    description: "Circuit breaker {{ $labels.name }} has been open for 5 minutes"

  - name: DiskSpaceLow
    condition: 'node_filesystem_avail_bytes{mountpoint="/projects"} < 5e9'
    for: 10m
    severity: warning
    summary: "Low disk space on /projects"
    description: "Less than 5GB available on projects volume"

  - name: HighJobFailureRate
    condition: |
      rate(televibe_jobs_total{status="failed"}[1h])
      / rate(televibe_jobs_total[1h]) > 0.2
    for: 15m
    severity: warning
    summary: "High job failure rate"
    description: "More than 20% of jobs failing in the last hour"

  # Info alerts (log only)
  - name: SessionLongIdle
    condition: |
      (time() - televibe_session_last_activity_timestamp) > 86400
      and televibe_sessions_active > 0
    for: 0s
    severity: info
    summary: "Session idle for 24+ hours"
    description: "Session {{ $labels.session_id }} has been idle for over 24 hours"
```

---

## Backup and Recovery

### SQLite Backup Strategy

```yaml
backup:
  type: "sqlite"
  schedule: "0 */6 * * *"  # Every 6 hours
  retention_days: 30

  procedure:
    1. Acquire database read lock
    2. Copy state.db to backup location
    3. Verify backup integrity (PRAGMA integrity_check)
    4. Release lock
    5. Compress backup (gzip)
    6. Upload to remote storage (optional)

  storage:
    local_path: "/projects/orchestrator/backups"
    remote: "s3://bucket/televibe/backups"  # Optional

  naming: "state-{timestamp}.db.gz"
  # Example: state-2025-12-13T06-00-00.db.gz
```

### Recovery Procedure

```yaml
recovery:
  from_backup:
    steps:
      1. Stop orchestrator process
      2. Move current state.db to state.db.corrupted
      3. Decompress backup
      4. Copy backup to state.db
      5. Run integrity check
      6. Start orchestrator
      7. Verify sessions and jobs recovered

  state_reconstruction:
    description: "Rebuild state from git repos if backup unavailable"
    steps:
      1. Scan /projects/repos for repositories
      2. Register each as project
      3. Scan /projects/workspaces for worktrees
      4. Recreate session records for each worktree
      5. Jobs history is lost (only current state recoverable)

  workspace_recovery:
    description: "Recover workspace after disk failure"
    steps:
      1. Close affected session in database
      2. Delete corrupted worktree directory
      3. Create new session on same branch
      4. Git worktree will be recreated from repo
```

---

## Logging Specification

### Log Format

```json
{
  "timestamp": "2025-12-13T10:30:45.123Z",
  "level": "info",
  "logger": "televibe.runner",
  "message": "Job started",
  "context": {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "session_id": "S12",
    "project_id": "myapp",
    "instruction_preview": "implement login form..."
  },
  "trace_id": "abc123",
  "span_id": "def456"
}
```

### Log Levels

| Level | Usage |
|-------|-------|
| `debug` | Detailed debugging, disabled in production |
| `info` | Normal operations (job start, complete, session create) |
| `warning` | Recoverable issues (timeout, retry, circuit breaker) |
| `error` | Failures requiring attention (job failed, API error) |
| `critical` | System-level failures (database error, process crash) |

### Log Retention

```yaml
logging:
  orchestrator_logs:
    path: "/projects/orchestrator/logs/orchestrator.log"
    rotation: "daily"
    retention_days: 30
    max_size_mb: 100

  job_logs:
    path: "/projects/orchestrator/logs/jobs/{job_id}.log"
    retention_days: 7
    max_size_mb: 100
    on_exceed: "truncate"

  audit_logs:
    path: "/projects/orchestrator/logs/audit.log"
    retention_days: 90
    events:
      - "session.created"
      - "session.closed"
      - "job.approval_needed"
      - "job.approved"
      - "job.denied"
      - "project.registered"
```

---

## Operational Runbooks

### Runbook: Job Stuck in Running State

```yaml
runbook:
  name: "Job Stuck Running"
  trigger: "Job running > 1 hour or user report"

  diagnosis:
    1. Check job status:
       command: "sqlite3 state.db 'SELECT * FROM jobs WHERE job_id = ?'"
    2. Check process:
       command: "ps aux | grep claude"
    3. Check logs:
       command: "tail -100 /projects/orchestrator/logs/jobs/{job_id}.log"

  resolution:
    if_process_hung:
      1. "kill -TERM {pid}"
      2. "sleep 30"
      3. "kill -KILL {pid}"  # If still running
      4. Update job status: "UPDATE jobs SET status='failed', error='Manual termination' WHERE job_id=?"
      5. Update session: "UPDATE sessions SET state='idle' WHERE session_id=?"

    if_waiting_network:
      1. Check network connectivity
      2. If API rate limited, wait for circuit breaker
      3. If network down, cancel job and notify user

  notification:
    - User via Telegram: "Job {job_id} was terminated after getting stuck"
```

### Runbook: Orchestrator Won't Start

```yaml
runbook:
  name: "Orchestrator Start Failure"
  trigger: "Supervisor reports repeated restarts"

  diagnosis:
    1. Check logs:
       command: "journalctl -u televibe -n 100"
    2. Check database:
       command: "sqlite3 state.db 'PRAGMA integrity_check'"
    3. Check disk space:
       command: "df -h /projects"
    4. Check permissions:
       command: "ls -la /projects/orchestrator"

  resolution:
    if_database_corrupt:
      1. Restore from backup (see recovery procedure)

    if_disk_full:
      1. Clear old logs: "find /projects/orchestrator/logs -mtime +7 -delete"
      2. Clear old backups: "find /projects/orchestrator/backups -mtime +30 -delete"
      3. Remove stale worktrees: "git worktree prune" in each repo

    if_permission_denied:
      1. Check user running orchestrator
      2. Fix permissions: "chown -R televibe:televibe /projects"

  escalation:
    - If unresolved in 30 minutes, page on-call
```
