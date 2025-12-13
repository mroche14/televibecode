# Multi-Session Coordination

## Overview

When running multiple "virtual coders" in parallel, sessions need ways to coordinate, share context, and hand off work. This document covers coordination patterns and implementation strategies.

## Session Topology

### Independent Sessions (Default)

Sessions work in isolation on separate branches:

```
Session S12 ──► feature-auth     (working on auth)
Session S15 ──► feature-payments (working on payments)
Session S7  ──► bugfix-api       (fixing bugs)
```

**Characteristics:**
- No shared state between sessions
- Git worktrees provide isolation
- Conflicts resolved at merge time
- Simplest model

### Coordinated Sessions

Sessions aware of each other, can reference shared context:

```
Session S12 ──► feature-auth
    │
    ├── knows about S15's payment types
    └── can request S15 to expose interface

Session S15 ──► feature-payments
    │
    └── knows about S12's auth context
```

**Use cases:**
- Feature A depends on Feature B's types/interfaces
- Need consistent patterns across features
- Cross-cutting concerns (logging, error handling)

### Hierarchical Sessions

Parent session orchestrates child sessions:

```
Session S1 (orchestrator)
    │
    ├── S12 ──► auth module
    ├── S15 ──► payments module
    └── S7  ──► tests
```

**Use cases:**
- Large features requiring multiple specialists
- Code review workflows
- Test-driven development with separate test writer

## Shared Context Mechanisms

### 1. Project-Level Context File

Maintain a shared context file in the repo:

**`.televibe/context.yaml`**:
```yaml
# Updated by sessions, read by all
interfaces:
  auth:
    session: S12
    exports:
      - name: AuthContext
        file: src/auth/context.py
        description: "Authentication context with user session"
      - name: require_auth
        file: src/auth/decorators.py
        description: "Decorator for protected routes"

  payments:
    session: S15
    exports:
      - name: PaymentProcessor
        file: src/payments/processor.py
        description: "Handles payment transactions"

decisions:
  - date: 2025-12-13
    session: S12
    decision: "Use JWT for session tokens"
    rationale: "Stateless, works with distributed backend"

  - date: 2025-12-13
    session: S15
    decision: "Use Stripe for payments"
    rationale: "Best API, good Python SDK"

todos_for_others:
  - from: S12
    to: S15
    message: "When auth is ready, payments will need to use require_auth decorator"

  - from: S15
    to: S12
    message: "Need user.payment_methods available in AuthContext"
```

**Integration:**
- Sessions read this file at job start
- Sessions update when they create/modify interfaces
- Middle AI can summarize for context injection

### 2. Orchestrator-Mediated Context

Orchestrator maintains cross-session state:

```python
class SessionContext:
    session_id: str
    project_id: str
    branch: str

    # What this session has produced
    exports: list[ExportedInterface]

    # What this session needs from others
    dependencies: list[Dependency]

    # Recent decisions
    decisions: list[Decision]

    # Messages to other sessions
    outbox: list[CrossSessionMessage]

class CrossSessionMessage:
    from_session: str
    to_session: Optional[str]  # None = broadcast
    message_type: str  # "interface_ready", "need_input", "fyi"
    content: str
    created_at: datetime
```

**MCP Tools:**

```python
# Session S12 declares an export
declare_export(
    session_id="S12",
    name="AuthContext",
    file="src/auth/context.py",
    description="...",
)

# Session S15 queries available interfaces
get_available_interfaces(project_id="project-a")
# Returns: [AuthContext, PaymentProcessor, ...]

# Session S15 requests something from S12
send_cross_session_message(
    from_session="S15",
    to_session="S12",
    message_type="need_input",
    content="Need user.payment_methods in AuthContext",
)

# Session S12 gets its inbox
get_inbox(session_id="S12")
# Returns: [message from S15]
```

### 3. Branch-Based Coordination

Use git branches for coordination:

```
main
 │
 ├── feature/auth (S12)
 │    └── Ready, merged types to main
 │
 └── feature/payments (S15)
      └── Rebased on main, has auth types
```

**Workflow:**
1. S12 finishes auth interfaces, creates PR
2. PR merged to main
3. S15 rebases on main, gets auth types
4. S15 can now use auth in payments

**Automation:**
```python
async def on_session_pr_merged(session: Session, pr: PullRequest):
    # Notify other sessions on same project
    other_sessions = await get_project_sessions(session.project_id)

    for other in other_sessions:
        if other.session_id == session.session_id:
            continue

        # Queue rebase job
        await run_instruction(
            other.session_id,
            f"Rebase on {session.project.default_branch} to get latest changes from {session.branch}"
        )
```

## Handoff Patterns

### Pattern 1: Sequential Handoff

One session completes, hands off to next:

```
S12 (implement) ──► S15 (review) ──► S7 (test)
```

**Implementation:**
```python
class WorkflowStage:
    stage_id: str
    session_id: str
    instruction: str
    next_stage: Optional[str]
    on_complete: str  # "handoff" | "merge" | "notify"

class Workflow:
    workflow_id: str
    project_id: str
    stages: list[WorkflowStage]
    current_stage: int

async def advance_workflow(workflow: Workflow):
    current = workflow.stages[workflow.current_stage]
    next_stage = workflow.stages[workflow.current_stage + 1]

    # Create handoff context
    handoff = {
        "from_session": current.session_id,
        "from_branch": get_session(current.session_id).branch,
        "summary": get_session(current.session_id).last_summary,
        "files_changed": get_last_job_files(current.session_id),
    }

    # Start next stage
    await run_instruction(
        next_stage.session_id,
        f"""
        Continuing work from {current.session_id}:
        Branch: {handoff['from_branch']}
        Summary: {handoff['summary']}

        Your task: {next_stage.instruction}
        """
    )

    workflow.current_stage += 1
```

### Pattern 2: Parallel Work, Sync Points

Multiple sessions work in parallel, sync at defined points:

```
        ┌─► S12 (auth) ───┐
        │                 │
Start ──┼─► S15 (payments)┼──► Sync ──► Integration
        │                 │
        └─► S7 (ui) ──────┘
```

**Implementation:**
```python
class SyncPoint:
    sync_id: str
    workflow_id: str
    required_sessions: list[str]
    completed_sessions: list[str]
    on_complete: str  # instruction for integration session

async def session_completed_stage(session_id: str, sync_point: SyncPoint):
    sync_point.completed_sessions.append(session_id)

    if set(sync_point.completed_sessions) >= set(sync_point.required_sessions):
        # All sessions ready, trigger integration
        await trigger_integration(sync_point)

async def trigger_integration(sync_point: SyncPoint):
    # Create integration branch
    integration_session = await create_session(
        project_id=sync_point.project_id,
        branch="integration/sync-" + sync_point.sync_id,
    )

    # Merge all completed branches
    branches = [
        get_session(s).branch
        for s in sync_point.completed_sessions
    ]

    await run_instruction(
        integration_session.session_id,
        f"""
        Integrate the following branches:
        {', '.join(branches)}

        Then: {sync_point.on_complete}
        """
    )
```

### Pattern 3: Request-Response

Sessions request help from specialized sessions:

```
S12 (feature dev) ──request──► S20 (security review)
                  ◄──response──
```

**Implementation:**
```python
class SessionRequest:
    request_id: str
    from_session: str
    to_session: str
    request_type: str  # "review", "help", "implement"
    context: str
    status: str  # "pending", "accepted", "completed", "declined"
    response: Optional[str]

# S12 requests security review
await create_request(
    from_session="S12",
    to_session="S20",  # Security specialist session
    request_type="review",
    context="Please review auth implementation for security issues",
)

# S20 receives and processes
requests = await get_pending_requests(session_id="S20")
for req in requests:
    # Run review job
    result = await run_instruction(
        "S20",
        f"Review the code in {get_session(req.from_session).branch}: {req.context}"
    )

    # Send response
    await complete_request(
        request_id=req.request_id,
        response=result.summary,
    )

# S12 gets response
responses = await get_request_responses(session_id="S12")
```

## Conflict Resolution

### Detection

Monitor for potential conflicts:

```python
async def check_conflicts(session: Session) -> list[Conflict]:
    conflicts = []

    # Check git conflicts with other branches
    other_sessions = await get_project_sessions(session.project_id)
    for other in other_sessions:
        if other.session_id == session.session_id:
            continue

        # Check if branches have diverged
        merge_base = await git_merge_base(
            session.workspace_path,
            session.branch,
            other.branch,
        )

        if has_conflicts(session.branch, other.branch, merge_base):
            conflicts.append(Conflict(
                session_a=session.session_id,
                session_b=other.session_id,
                files=get_conflicting_files(...),
            ))

    return conflicts
```

### Resolution Strategies

**Strategy 1: First-come-first-served**
```python
# Whoever merges first wins
# Other session must rebase and resolve
```

**Strategy 2: Designated integrator**
```python
# Special session handles all merges
# Other sessions never merge directly
```

**Strategy 3: File ownership**
```python
# Each session "owns" certain files/directories
# Conflicts only possible when ownership overlaps

file_ownership = {
    "src/auth/*": "S12",
    "src/payments/*": "S15",
    "src/shared/*": None,  # Shared, needs coordination
}
```

**Strategy 4: Lock-based**
```python
# Session requests lock on files before editing
async def acquire_file_lock(session_id: str, files: list[str]) -> bool:
    for file in files:
        existing_lock = await get_lock(file)
        if existing_lock and existing_lock.session_id != session_id:
            return False  # File locked by another session

    # Acquire locks
    for file in files:
        await create_lock(file, session_id)

    return True
```

## Session Specialization

### Role-Based Sessions

Create sessions with specialized configurations:

```python
SESSION_ROLES = {
    "implementer": {
        "superclaude_profile": "implementer",
        "description": "Writes new code, implements features",
        "allowed_actions": ["write", "run_tests"],
    },
    "reviewer": {
        "superclaude_profile": "reviewer",
        "description": "Reviews code, suggests improvements",
        "allowed_actions": ["read", "comment"],
    },
    "tester": {
        "superclaude_profile": "tester",
        "description": "Writes and runs tests",
        "allowed_actions": ["write_tests", "run_tests"],
    },
    "refactorer": {
        "superclaude_profile": "refactorer",
        "description": "Improves code quality",
        "allowed_actions": ["refactor", "run_tests"],
    },
    "security": {
        "superclaude_profile": "security",
        "description": "Security review and hardening",
        "allowed_actions": ["read", "security_scan", "comment"],
    },
}

async def create_specialized_session(
    project_id: str,
    branch: str,
    role: str,
) -> Session:
    role_config = SESSION_ROLES[role]

    session = await create_session(
        project_id=project_id,
        branch=branch,
        superclaude_profile=role_config["superclaude_profile"],
    )

    session.role = role
    session.allowed_actions = role_config["allowed_actions"]

    return session
```

### Team Composition

For complex features, spawn a team:

```python
async def create_feature_team(
    project_id: str,
    feature_name: str,
    roles: list[str] = ["implementer", "reviewer", "tester"],
) -> list[Session]:
    sessions = []

    for role in roles:
        session = await create_specialized_session(
            project_id=project_id,
            branch=f"feature/{feature_name}",
            role=role,
        )
        sessions.append(session)

    # Link sessions as a team
    team_id = generate_team_id()
    for session in sessions:
        session.team_id = team_id

    return sessions
```

## Orchestrator Intelligence

### Session Recommendation

Suggest which session should handle a task:

```python
async def recommend_session(
    project_id: str,
    instruction: str,
) -> tuple[Session, str]:
    """Returns (session, reasoning)"""

    # Classify instruction type
    task_type = classify_task(instruction)  # "implement", "review", "test", etc.

    # Get active sessions
    sessions = await get_project_sessions(project_id)

    # Find best match
    for session in sessions:
        if session.role == task_type:
            return session, f"Using {session.role} session {session.session_id}"

    # Check if task relates to existing session's work
    for session in sessions:
        if instruction_relates_to_session(instruction, session):
            return session, f"Relates to {session.session_id}'s work on {session.branch}"

    # Default: create new session or use first available
    if sessions:
        return sessions[0], "Using default session"

    # No sessions, suggest creation
    return None, f"Create new session with role: {task_type}"
```

### Automatic Coordination

Orchestrator can inject coordination automatically:

```python
async def enhance_instruction(
    session: Session,
    instruction: str,
) -> str:
    """Add context from other sessions"""

    enhancements = []

    # Get relevant exports from other sessions
    exports = await get_relevant_exports(session.project_id, instruction)
    if exports:
        enhancements.append(
            "Available interfaces from other sessions:\n" +
            "\n".join(f"- {e.name}: {e.description}" for e in exports)
        )

    # Get pending messages for this session
    messages = await get_inbox(session.session_id)
    if messages:
        enhancements.append(
            "Messages from other sessions:\n" +
            "\n".join(f"- {m.from_session}: {m.content}" for m in messages)
        )

    # Get recent decisions
    decisions = await get_recent_decisions(session.project_id, limit=5)
    if decisions:
        enhancements.append(
            "Recent team decisions:\n" +
            "\n".join(f"- {d.decision}" for d in decisions)
        )

    if enhancements:
        return f"""
Context:
{chr(10).join(enhancements)}

---

Task: {instruction}
"""
    return instruction
```
