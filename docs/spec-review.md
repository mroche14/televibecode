# TeleVibeCode Specification Review

## Expert Panel Analysis

**Review Date**: 2025-12-13
**Specifications Reviewed**: architecture.md, data-models.md, orchestrator-mcp.md, telegram-bot.md, runner-integration.md, multi-session.md, event-streaming.md
**Panel**: Wiegers (Requirements), Adzic (Specification by Example), Fowler (Architecture), Nygard (Production Systems), Newman (Distributed Systems), Crispin (Testing)

---

## Quality Assessment

| Dimension | Score | Notes |
|-----------|-------|-------|
| **Overall Specification Quality** | 7.8/10 | Comprehensive but gaps in non-functional requirements |
| **Requirements Clarity** | 7.5/10 | Good structure, needs measurable criteria |
| **Architecture Clarity** | 8.5/10 | Well-defined layers and boundaries |
| **Testability** | 6.5/10 | Missing acceptance criteria and test scenarios |
| **Operational Readiness** | 6.0/10 | Needs failure modes and monitoring specs |
| **Completeness** | 7.5/10 | Core flows covered, edge cases sparse |

---

## Expert Commentary

### Karl Wiegers - Requirements Engineering

**Strengths:**
- Clear separation of entities (Project, Session, Task, Job) with well-defined relationships
- State machines for Session and Job provide unambiguous lifecycle
- JSON schemas provide validation constraints

**Critical Issues:**

❌ **REQ-001**: No measurable acceptance criteria for core operations
> "The specification says 'run instruction in session' but doesn't define what success looks like. What's the expected response time? What constitutes a valid instruction? How do we validate the job completed correctly?"

**Recommendation**: Add acceptance criteria table:
```yaml
run_instruction:
  response_time: "Job queued confirmation within 500ms"
  validation: "Instruction must be non-empty string under 10000 characters"
  success_criteria: "Claude Code exits with code 0, summary extracted from logs"
  failure_criteria: "Exit code non-zero OR timeout exceeded OR process killed"
```

❌ **REQ-002**: Timeout values not specified
> "The config shows `timeout_seconds: 3600` but there's no specification for what happens when timeout occurs. Is the job marked failed? Is the process killed? What about partial work?"

**Recommendation**: Add timeout handling specification:
```yaml
timeout_behavior:
  action: "SIGTERM followed by SIGKILL after 30s grace period"
  job_status: "failed"
  error_message: "Job exceeded timeout of {timeout_seconds}s"
  cleanup: "Preserve partial work in workspace, log truncated"
```

⚠️ **REQ-003**: Approval scope not fully enumerated
> "The spec mentions 'write, run, push' but the config also has 'deploy'. What other approval scopes exist? This should be a closed enumeration."

**Recommendation**: Define complete approval scope enum:
```python
class ApprovalScope(Enum):
    WRITE = "write"       # File creation/modification
    SHELL = "shell"       # Shell command execution
    PUSH = "push"         # Git push to remote
    DEPLOY = "deploy"     # Deployment operations
    DELETE = "delete"     # File/branch deletion
    EXTERNAL = "external" # External API calls
```

---

### Gojko Adzic - Specification by Example

**Strengths:**
- Good high-level flow descriptions
- Message format examples are concrete

**Critical Issues:**

❌ **SPEC-001**: No Given/When/Then scenarios for critical paths
> "The specification describes what the system does but lacks executable examples. How would QA validate this works?"

**Recommendation**: Add behavior scenarios:

```gherkin
Feature: Session Creation

Scenario: Create session on existing branch
  Given project "project-a" exists with branch "feature-x"
  When I call create_session(project_id="project-a", branch="feature-x")
  Then a new session "S{N}" is created
  And workspace_path is "/projects/workspaces/project-a/S{N}/feature-x"
  And state is "idle"
  And a git worktree exists at workspace_path

Scenario: Create session on new branch
  Given project "project-a" exists with default_branch "main"
  And branch "feature-new" does not exist
  When I call create_session(project_id="project-a", branch="feature-new")
  Then branch "feature-new" is created from "main"
  And a new session is created with that branch

Scenario: Create session fails if project doesn't exist
  Given project "nonexistent" does not exist
  When I call create_session(project_id="nonexistent", branch="any")
  Then error "Project not found: nonexistent" is returned
  And no session is created
```

❌ **SPEC-002**: Job execution scenarios missing
> "What happens when a job is running and user sends another instruction? What if the same branch is used by two sessions?"

**Recommendation**: Add conflict scenarios:

```gherkin
Scenario: Instruction while job running
  Given session "S12" has a job in "running" state
  When I call run_instruction(session_id="S12", instruction="new task")
  Then the job is queued after current job
  And response indicates position in queue

Scenario: Two sessions on same branch (should fail)
  Given session "S12" exists on project-a/feature-x
  When I call create_session(project_id="project-a", branch="feature-x")
  Then error "Branch already has active session: S12" is returned
```

⚠️ **SPEC-003**: Edge cases not specified
> "What's the maximum number of concurrent sessions? What happens when disk space runs out? What if git worktree creation fails?"

---

### Martin Fowler - Software Architecture

**Strengths:**
- Clean layer separation (Layer 0-3)
- Single API surface principle (Orchestrator MCP)
- Good use of git worktrees for isolation

**Critical Issues:**

❌ **ARCH-001**: Middle AI Layer is underspecified
> "The architecture diagram shows 'Middle AI Layer (optional)' but this is actually critical for natural language routing. It's not optional if you want the described UX."

**Recommendation**: Elevate Middle AI to required component with clear interface:
```python
class MiddleAILayer(Protocol):
    async def classify_intent(self, message: str) -> Intent:
        """Classify user intent: question, task, status, switch"""
        ...

    async def extract_entities(self, message: str) -> Entities:
        """Extract project, session, task references"""
        ...

    async def normalize_instruction(self, message: str, context: SessionContext) -> str:
        """Convert natural language to actionable instruction"""
        ...

    async def route_to_session(self, message: str, chat_state: ChatState) -> Session:
        """Determine target session for message"""
        ...
```

❌ **ARCH-002**: Session Manager vs Orchestrator boundary unclear
> "Both seem to manage session state. Who owns the session lifecycle? Who handles worktree creation?"

**Recommendation**: Clarify responsibilities:
```
Orchestrator MCP:
  - Owns database state
  - Exposes MCP tools
  - Coordinates between components
  - Does NOT directly manage git or processes

Session Manager:
  - Owns git worktree lifecycle
  - Manages workspace files
  - Reports state changes to Orchestrator
  - Does NOT persist state

Runner:
  - Owns Claude Code process lifecycle
  - Captures logs and output
  - Reports job progress to Orchestrator
  - Does NOT manage state
```

⚠️ **ARCH-003**: Event bus coupling
> "The event streaming doc shows both in-process and Redis options. The core spec should pick one as default and define the interface clearly."

---

### Michael Nygard - Production Systems (Release It!)

**Strengths:**
- Approval gating prevents accidental damage
- Log capture for debugging

**Critical Issues:**

❌ **OPS-001**: No failure mode analysis
> "What happens when each component fails? The spec doesn't describe degraded operation modes."

**Recommendation**: Add failure mode table:

| Component | Failure Mode | Detection | Impact | Recovery |
|-----------|--------------|-----------|--------|----------|
| Orchestrator MCP | Process crash | Supervisor watchdog | All operations blocked | Auto-restart, recover state from SQLite |
| Runner | Process hang | Heartbeat timeout | Job stuck | SIGKILL, mark job failed, notify user |
| Telegram Bot | Network loss | Connection timeout | No user interaction | Reconnect with backoff, queue messages |
| SQLite DB | Corruption | Integrity check | Data loss | Restore from backup, replay events |
| Git worktree | Disk full | Space check | Session creation fails | Alert, cleanup old worktrees |

❌ **OPS-002**: No circuit breaker patterns
> "If Claude Code starts failing repeatedly (API issues, rate limits), the system will keep hammering it. Need backoff and circuit breaking."

**Recommendation**: Add circuit breaker config:
```yaml
circuit_breaker:
  claude_code:
    failure_threshold: 5          # Open circuit after 5 failures
    reset_timeout_seconds: 300    # Try again after 5 minutes
    half_open_requests: 1         # Test with single request

  telegram:
    failure_threshold: 3
    reset_timeout_seconds: 60

  git_operations:
    failure_threshold: 3
    reset_timeout_seconds: 30
```

❌ **OPS-003**: No monitoring or alerting specifications
> "How do operators know if the system is healthy? Where are the metrics?"

**Recommendation**: Add observability requirements:
```yaml
metrics:
  - name: televibe_sessions_active
    type: gauge
    labels: [project_id, state]

  - name: televibe_jobs_total
    type: counter
    labels: [project_id, status]

  - name: televibe_job_duration_seconds
    type: histogram
    labels: [project_id]

  - name: televibe_approvals_pending
    type: gauge

alerts:
  - name: JobStuckRunning
    condition: "televibe_job_duration_seconds > 3600"
    severity: warning

  - name: HighApprovalBacklog
    condition: "televibe_approvals_pending > 10"
    severity: warning

  - name: OrchestratorDown
    condition: "up{job='televibe-orchestrator'} == 0"
    severity: critical
```

⚠️ **OPS-004**: No backup/restore procedures
> "SQLite database is the source of truth. What's the backup strategy? How do you restore?"

---

### Sam Newman - Distributed Systems

**Strengths:**
- Stateless Telegram bot design
- MCP protocol provides clean API evolution path

**Critical Issues:**

⚠️ **DIST-001**: State synchronization between components
> "Session Manager and Orchestrator both reference session state. How do you handle race conditions?"

**Recommendation**: Define consistency model:
```
Consistency Model: Orchestrator is authoritative

1. All state changes go through Orchestrator MCP
2. Session Manager reads state, never writes directly
3. Runner reports via events, Orchestrator updates state
4. Optimistic locking on session state changes:
   - Include `version` field in Session
   - Updates must provide current version
   - Conflict returns error, client retries
```

⚠️ **DIST-002**: No API versioning strategy
> "MCP tools will evolve. How do you handle backward compatibility?"

**Recommendation**: Add versioning:
```json
{
  "protocol_version": "2024-11-05",
  "api_version": "v1",
  "deprecated_tools": [],
  "removed_in_v2": ["legacy_tool_name"]
}
```

---

### Lisa Crispin - Agile Testing

**Critical Issues:**

❌ **TEST-001**: No test strategy defined
> "What types of tests are needed? Who writes them? What's the coverage target?"

**Recommendation**: Add test requirements:
```yaml
test_strategy:
  unit_tests:
    coverage_target: 80%
    focus:
      - Data model validation
      - State machine transitions
      - Event serialization

  integration_tests:
    coverage_target: 70%
    focus:
      - MCP tool end-to-end
      - Git worktree operations
      - Database CRUD

  e2e_tests:
    scenarios:
      - "User creates session from Telegram, runs job, approves push"
      - "Multiple sessions on same project, no conflicts"
      - "System recovers after restart mid-job"

  load_tests:
    scenarios:
      - "10 concurrent sessions across 5 projects"
      - "100 jobs queued, processed within SLA"
```

❌ **TEST-002**: No acceptance criteria for user stories
> "Each MCP tool needs acceptance criteria that QA can validate."

---

## Consolidated Recommendations

### Critical (Must Fix Before Implementation)

| ID | Category | Issue | Recommendation |
|----|----------|-------|----------------|
| C1 | Requirements | No timeout handling spec | Define timeout behavior, cleanup, error messages |
| C2 | Requirements | Missing acceptance criteria | Add success/failure criteria for each MCP tool |
| C3 | Architecture | Middle AI Layer underspec | Define as required component with interface |
| C4 | Operations | No failure mode analysis | Document degraded modes and recovery |
| C5 | Testing | No test strategy | Define unit/integration/e2e requirements |

### Major (Should Fix Before Beta)

| ID | Category | Issue | Recommendation |
|----|----------|-------|----------------|
| M1 | Specification | No behavior scenarios | Add Given/When/Then for critical paths |
| M2 | Architecture | Component boundaries fuzzy | Clarify Orchestrator vs Session Manager |
| M3 | Operations | No monitoring specs | Define metrics, alerts, dashboards |
| M4 | Operations | No circuit breakers | Add failure protection patterns |
| M5 | Testing | No acceptance criteria | Add per-tool validation criteria |

### Minor (Nice to Have)

| ID | Category | Issue | Recommendation |
|----|----------|-------|----------------|
| N1 | Specification | Edge cases sparse | Document limits, error conditions |
| N2 | Operations | No backup strategy | Define SQLite backup/restore |
| N3 | Distribution | No API versioning | Add version fields and deprecation |

---

## Expert Consensus

The panel agrees on these key points:

1. **Strong foundation**: The layered architecture and entity model are well-designed
2. **Operationalization gap**: The spec needs more work on failure handling, monitoring, and recovery
3. **Testability needs work**: Add scenarios, acceptance criteria, and test strategy
4. **Clarify the "Middle AI"**: This is actually central to the UX, not optional

---

## Next Steps

1. **Immediate**: Add timeout and failure handling specs
2. **This week**: Write Given/When/Then scenarios for happy paths
3. **Before coding**: Define test strategy and acceptance criteria
4. **During implementation**: Add metrics and health checks incrementally
