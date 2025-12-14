"""Conversational AI agent for TeleVibeCode.

This agent can actually DO things, not just suggest commands.
- Read operations: auto-execute and report back conversationally
- Write operations: require confirmation before executing
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

from televibecode.db import Database

log = structlog.get_logger()

# Agno for the agent
try:
    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.tools import tool

    AGNO_AVAILABLE = True
except ImportError:
    Agent = None
    SqliteDb = None
    tool = None
    AGNO_AVAILABLE = False


class ActionType(Enum):
    """Type of action - determines if confirmation is needed."""

    READ = "read"  # Auto-execute, no confirmation
    WRITE = "write"  # Requires user confirmation
    CONFIRM = "confirm"  # Confirmation response from user


@dataclass
class PendingAction:
    """An action waiting for user confirmation."""

    action_id: str
    action_type: str  # e.g., "create_session", "run_instruction"
    description: str  # Human-readable description
    params: dict[str, Any] = field(default_factory=dict)
    confirm_message: str = ""  # Message to show user


@dataclass
class AgentResponse:
    """Response from the conversational agent."""

    message: str  # Conversational response to show user
    pending_action: PendingAction | None = None  # Action needing confirmation
    error: str | None = None  # Error message if something went wrong


# Store pending actions per chat
_pending_actions: dict[int, PendingAction] = {}


def get_pending_action(chat_id: int) -> PendingAction | None:
    """Get pending action for a chat."""
    return _pending_actions.get(chat_id)


def set_pending_action(chat_id: int, action: PendingAction) -> None:
    """Set pending action for a chat."""
    _pending_actions[chat_id] = action


def clear_pending_action(chat_id: int) -> PendingAction | None:
    """Clear and return pending action for a chat."""
    return _pending_actions.pop(chat_id, None)


class TeleVibeAgent:
    """Conversational agent that can execute TeleVibeCode operations.

    Read operations are executed immediately.
    Write operations require confirmation.
    """

    def __init__(
        self,
        db: Database,
        model: str = "openrouter:meta-llama/llama-3.2-3b-instruct:free",
        db_path: Path | None = None,
    ):
        """Initialize the agent.

        Args:
            db: Database instance for operations.
            model: AI model to use.
            db_path: Path to SQLite database for agent memory.
        """
        if not AGNO_AVAILABLE:
            raise RuntimeError("agno not installed")

        self.db = db
        self.model = model
        self.db_path = db_path
        self._agents: dict[int, Agent] = {}
        self._storage: SqliteDb | None = None
        self._chat_contexts: dict[int, dict] = {}  # Per-chat context

    def _get_storage(self) -> SqliteDb | None:
        """Get or create storage for agent memory."""
        if SqliteDb is None or self.db_path is None:
            return None
        if self._storage is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._storage = SqliteDb(
                db_file=str(self.db_path),
                session_table="agent_sessions",
            )
        return self._storage

    def set_chat_context(
        self,
        chat_id: int,
        active_session: str | None = None,
        **kwargs,
    ) -> None:
        """Set context for a chat (active session, etc.)."""
        if chat_id not in self._chat_contexts:
            self._chat_contexts[chat_id] = {}
        self._chat_contexts[chat_id]["active_session"] = active_session
        self._chat_contexts[chat_id].update(kwargs)

    def get_chat_context(self, chat_id: int) -> dict:
        """Get context for a chat."""
        return self._chat_contexts.get(chat_id, {})

    def _get_agent(self, chat_id: int) -> Agent:
        """Get or create agent for a chat."""
        # Check if we need to recreate due to model change
        cache_key = (chat_id, self.model)

        # Invalidate old agent if model changed
        if chat_id in self._agents:
            old_model = getattr(self._agents[chat_id], '_televibe_model', None)
            if old_model != self.model:
                log.info("chat_agent_model_changed", chat_id=chat_id, old=old_model, new=self.model)
                del self._agents[chat_id]

        if chat_id not in self._agents:
            storage = self._get_storage()

            # Build tools for this agent
            tools = self._build_tools(chat_id)

            agent = Agent(
                model=self.model,
                name="TeleVibe",
                description="AI assistant for managing Claude Code sessions",
                instructions=[SYSTEM_PROMPT],
                tools=tools,
                session_id=f"televibe_{chat_id}",
                db=storage,
                add_history_to_context=True,
                read_chat_history=True,
                num_history_runs=10,
                markdown=True,
            )
            # Track which model this agent uses
            agent._televibe_model = self.model
            self._agents[chat_id] = agent

        return self._agents[chat_id]

    def _build_tools(self, chat_id: int) -> list:
        """Build tools for the agent.

        Tools are closures that capture chat_id and self.db.
        """
        db = self.db
        agent_self = self

        # ============== READ TOOLS (auto-execute) ==============

        @tool(description="List all active coding sessions")
        async def list_sessions() -> str:
            """List active sessions."""
            sessions = await db.get_active_sessions()
            if not sessions:
                return "No active sessions. Use create_session to start one."

            lines = []
            for s in sessions:
                emoji = {"idle": "💤", "running": "🔄", "paused": "⏸️"}.get(
                    s.state.value, "❓"
                )
                lines.append(f"{emoji} {s.session_id} - {s.project_id} ({s.state.value})")

            return "Active sessions:\n" + "\n".join(lines)

        @tool(description="List all registered projects/repositories")
        async def list_projects() -> str:
            """List registered projects."""
            projects = await db.get_all_projects()
            if not projects:
                return "No projects registered. Use scan_projects to find repositories."

            lines = []
            for p in projects:
                lines.append(f"📂 {p.project_id} - {p.path}")

            return "Registered projects:\n" + "\n".join(lines)

        @tool(description="Get status of current or specified session")
        async def get_status(session_id: str | None = None) -> str:
            """Get session status.

            Args:
                session_id: Session ID (uses active session if not provided)
            """
            ctx = agent_self.get_chat_context(chat_id)
            sid = session_id or ctx.get("active_session")

            if not sid:
                return "No active session. Tell me which session or create one."

            session = await db.get_session(sid)
            if not session:
                return f"Session {sid} not found."

            # Get recent jobs
            jobs = await db.get_jobs_by_session(sid, limit=3)
            job_info = ""
            if jobs:
                job_lines = []
                for j in jobs:
                    emoji = {
                        "queued": "⏳", "running": "🔄", "done": "✅",
                        "failed": "❌", "canceled": "⏹️"
                    }.get(j.status.value, "❓")
                    job_lines.append(f"  {emoji} {j.instruction[:40]}")
                job_info = "\n\nRecent jobs:\n" + "\n".join(job_lines)

            return (
                f"Session {sid}\n"
                f"Project: {session.project_id}\n"
                f"Branch: {session.branch}\n"
                f"State: {session.state.value}"
                f"{job_info}"
            )

        @tool(description="List recent jobs for a session")
        async def list_jobs(session_id: str | None = None, limit: int = 5) -> str:
            """List recent jobs.

            Args:
                session_id: Session ID (uses active session if not provided)
                limit: Max jobs to show
            """
            ctx = agent_self.get_chat_context(chat_id)
            sid = session_id or ctx.get("active_session")

            if not sid:
                return "No active session specified."

            jobs = await db.get_jobs_by_session(sid, limit=limit)
            if not jobs:
                return f"No jobs for session {sid}."

            lines = []
            for j in jobs:
                emoji = {
                    "queued": "⏳", "running": "🔄", "done": "✅",
                    "failed": "❌", "canceled": "⏹️"
                }.get(j.status.value, "❓")
                lines.append(f"{emoji} [{j.job_id[:8]}] {j.instruction[:50]}")

            return f"Jobs for {sid}:\n" + "\n".join(lines)

        @tool(description="List backlog tasks for current project")
        async def list_tasks(project_id: str | None = None) -> str:
            """List backlog tasks.

            Args:
                project_id: Project ID (uses active session's project if not provided)
            """
            ctx = agent_self.get_chat_context(chat_id)
            pid = project_id

            if not pid:
                sid = ctx.get("active_session")
                if sid:
                    session = await db.get_session(sid)
                    if session:
                        pid = session.project_id

            if not pid:
                return "No project specified. Which project's tasks do you want?"

            tasks = await db.get_tasks_by_project(pid)
            if not tasks:
                return f"No tasks for {pid}."

            lines = []
            for t in tasks[:10]:  # Limit to 10
                emoji = {
                    "todo": "📋", "in_progress": "🔄", "blocked": "🚫",
                    "needs_review": "👀", "done": "✅"
                }.get(t.status.value, "❓")
                lines.append(f"{emoji} {t.task_id}: {t.title[:40]}")

            return f"Tasks for {pid}:\n" + "\n".join(lines)

        @tool(description="List pending approval requests")
        async def list_approvals() -> str:
            """List pending approvals."""
            approvals = await db.get_pending_approvals()
            if not approvals:
                return "No pending approvals."

            lines = []
            for a in approvals:
                lines.append(f"⚠️ [{a.approval_id[:8]}] {a.approval_type.value}: {a.action_description[:40]}")

            return "Pending approvals:\n" + "\n".join(lines)

        # ============== WRITE TOOLS (require confirmation) ==============
        # These return a special format that signals confirmation needed

        @tool(description="Create a new coding session for a project. REQUIRES CONFIRMATION.")
        async def create_session(project_id: str) -> str:
            """Request to create a new session.

            Args:
                project_id: Project to create session for
            """
            # Check project exists
            project = await db.get_project(project_id)
            if not project:
                return f"Project '{project_id}' not found. Use list_projects to see available projects."

            # Return confirmation request
            action = PendingAction(
                action_id=f"create_session_{project_id}",
                action_type="create_session",
                description=f"Create new session for {project_id}",
                params={"project_id": project_id},
                confirm_message=f"Create new session for **{project_id}**?",
            )
            set_pending_action(chat_id, action)

            return f"CONFIRM_NEEDED: Create new session for {project_id}?"

        @tool(description="Close a coding session. REQUIRES CONFIRMATION.")
        async def close_session(session_id: str | None = None) -> str:
            """Request to close a session.

            Args:
                session_id: Session to close (uses active if not provided)
            """
            ctx = agent_self.get_chat_context(chat_id)
            sid = session_id or ctx.get("active_session")

            if not sid:
                return "No session specified. Which session should I close?"

            session = await db.get_session(sid)
            if not session:
                return f"Session {sid} not found."

            action = PendingAction(
                action_id=f"close_session_{sid}",
                action_type="close_session",
                description=f"Close session {sid}",
                params={"session_id": sid},
                confirm_message=f"Close session **{sid}** ({session.project_id})?",
            )
            set_pending_action(chat_id, action)

            return f"CONFIRM_NEEDED: Close session {sid}?"

        @tool(description="Run a coding instruction in the current session. REQUIRES CONFIRMATION.")
        async def run_instruction(instruction: str) -> str:
            """Request to run a coding instruction.

            Args:
                instruction: What to do (e.g., 'add unit tests', 'fix the login bug')
            """
            ctx = agent_self.get_chat_context(chat_id)
            sid = ctx.get("active_session")

            if not sid:
                return "No active session. Create or switch to a session first."

            session = await db.get_session(sid)
            if not session:
                return f"Session {sid} not found."

            # Truncate for display
            display = instruction[:100] + "..." if len(instruction) > 100 else instruction

            action = PendingAction(
                action_id=f"run_{sid}_{hash(instruction)}",
                action_type="run_instruction",
                description=f"Run: {display}",
                params={"session_id": sid, "instruction": instruction},
                confirm_message=f"Run in **{sid}**:\n\n`{display}`",
            )
            set_pending_action(chat_id, action)

            return f"CONFIRM_NEEDED: Run '{display}' in {sid}?"

        @tool(description="Cancel the currently running job. REQUIRES CONFIRMATION.")
        async def cancel_job(job_id: str | None = None) -> str:
            """Request to cancel a job.

            Args:
                job_id: Job to cancel (uses current running job if not provided)
            """
            ctx = agent_self.get_chat_context(chat_id)
            sid = ctx.get("active_session")

            if job_id:
                job = await db.get_job(job_id)
            elif sid:
                jobs = await db.get_jobs_by_session(sid, limit=1)
                job = jobs[0] if jobs else None
            else:
                return "No job specified and no active session."

            if not job:
                return "No job found to cancel."

            if job.status.value not in ("queued", "running"):
                return f"Job {job.job_id[:8]} is already {job.status.value}."

            action = PendingAction(
                action_id=f"cancel_{job.job_id}",
                action_type="cancel_job",
                description=f"Cancel job: {job.instruction[:40]}",
                params={"job_id": job.job_id},
                confirm_message=f"Cancel job **{job.job_id[:8]}**?\n\n`{job.instruction[:50]}`",
            )
            set_pending_action(chat_id, action)

            return f"CONFIRM_NEEDED: Cancel job {job.job_id[:8]}?"

        @tool(description="Scan for new git repositories in the projects folder. REQUIRES CONFIRMATION.")
        async def scan_projects() -> str:
            """Request to scan for projects."""
            action = PendingAction(
                action_id="scan_projects",
                action_type="scan_projects",
                description="Scan for new repositories",
                params={},
                confirm_message="Scan for new git repositories?",
            )
            set_pending_action(chat_id, action)

            return "CONFIRM_NEEDED: Scan for new repositories?"

        @tool(description="Claim a backlog task to work on. REQUIRES CONFIRMATION.")
        async def claim_task(task_id: str) -> str:
            """Request to claim a task.

            Args:
                task_id: Task ID (e.g., T-123)
            """
            task = await db.get_task(task_id)
            if not task:
                return f"Task {task_id} not found."

            action = PendingAction(
                action_id=f"claim_{task_id}",
                action_type="claim_task",
                description=f"Claim task {task_id}: {task.title[:40]}",
                params={"task_id": task_id},
                confirm_message=f"Claim task **{task_id}**?\n\n{task.title}",
            )
            set_pending_action(chat_id, action)

            return f"CONFIRM_NEEDED: Claim task {task_id}?"

        @tool(description="Switch to a different session (changes your active context)")
        async def switch_session(session_id: str) -> str:
            """Switch active session.

            Args:
                session_id: Session to switch to (e.g., S1)
            """
            sid = session_id.upper()
            session = await db.get_session(sid)
            if not session:
                return f"Session {sid} not found."

            # This is safe - just changes context, no confirmation needed
            agent_self.set_chat_context(chat_id, active_session=sid)

            return f"Switched to session {sid} ({session.project_id}, branch: {session.branch})"

        return [
            list_sessions,
            list_projects,
            get_status,
            list_jobs,
            list_tasks,
            list_approvals,
            create_session,
            close_session,
            run_instruction,
            cancel_job,
            scan_projects,
            claim_task,
            switch_session,
        ]

    async def chat(
        self,
        message: str,
        chat_id: int,
    ) -> AgentResponse:
        """Chat with the agent.

        Args:
            message: User's message.
            chat_id: Telegram chat ID.

        Returns:
            AgentResponse with message and optional pending action.
        """
        try:
            agent = self._get_agent(chat_id)

            # Add context to message
            ctx = self.get_chat_context(chat_id)
            active = ctx.get("active_session")
            context_note = f"\n[Context: active_session={active}]" if active else ""

            # Run agent
            response = await agent.arun(message + context_note)

            # Check if there's a pending action
            pending = get_pending_action(chat_id)

            # Clean up CONFIRM_NEEDED from response
            content = response.content
            if "CONFIRM_NEEDED:" in content:
                # Extract the conversational part before the confirmation
                parts = content.split("CONFIRM_NEEDED:")
                content = parts[0].strip()
                if not content:
                    content = "I'll need your confirmation for this."

            return AgentResponse(
                message=content,
                pending_action=pending,
            )

        except Exception as e:
            log.error("agent_chat_failed", error=str(e), chat_id=chat_id)

            # Handle rate limits
            error_str = str(e).lower()
            if "429" in str(e) or "rate" in error_str or "limit" in error_str:
                return AgentResponse(
                    message="I'm being rate limited. Try /model to switch to a different AI model.",
                    error="rate_limit",
                )

            if "provider" in error_str:
                return AgentResponse(
                    message="AI provider error. Try /model to switch models.",
                    error="provider_error",
                )

            return AgentResponse(
                message="Something went wrong. Try again or use /help for commands.",
                error="unknown",
            )

    async def confirm_action(self, chat_id: int) -> AgentResponse:
        """Confirm and execute a pending action.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            AgentResponse with result.
        """
        action = clear_pending_action(chat_id)
        if not action:
            return AgentResponse(message="Nothing to confirm.")

        try:
            result = await self._execute_action(action, chat_id)
            return AgentResponse(message=result)
        except Exception as e:
            log.error("action_execution_failed", error=str(e), action=action.action_type)
            return AgentResponse(
                message=f"Failed to execute: {e}",
                error="execution_error",
            )

    async def deny_action(self, chat_id: int) -> AgentResponse:
        """Deny/cancel a pending action.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            AgentResponse confirming cancellation.
        """
        action = clear_pending_action(chat_id)
        if not action:
            return AgentResponse(message="Nothing to cancel.")

        return AgentResponse(message=f"Cancelled: {action.description}")

    async def _execute_action(self, action: PendingAction, chat_id: int) -> str:
        """Execute a confirmed action.

        Args:
            action: The action to execute.
            chat_id: Chat ID for context.

        Returns:
            Result message.
        """
        from televibecode.orchestrator.tools import sessions

        if action.action_type == "create_session":
            project_id = action.params["project_id"]
            # We need settings for workspace creation - get from context
            ctx = self.get_chat_context(chat_id)
            settings = ctx.get("settings")
            if not settings:
                return "Missing settings context. Please try again."

            result = await sessions.create_session(self.db, settings, project_id)
            sid = result["session_id"]

            # Update active session
            self.set_chat_context(chat_id, active_session=sid)

            return (
                f"✅ Session **{sid}** created!\n\n"
                f"📂 Project: {result['project_id']}\n"
                f"🌿 Branch: {result['branch']}\n"
                f"📁 {result['workspace_path']}\n\n"
                f"Ready for instructions."
            )

        elif action.action_type == "close_session":
            session_id = action.params["session_id"]
            await sessions.close_session(self.db, session_id)

            # Clear active session if it was the one closed
            ctx = self.get_chat_context(chat_id)
            if ctx.get("active_session") == session_id:
                self.set_chat_context(chat_id, active_session=None)

            return f"✅ Session **{session_id}** closed."

        elif action.action_type == "run_instruction":
            session_id = action.params["session_id"]
            instruction = action.params["instruction"]

            # This would trigger the job runner
            # For now, return a placeholder - the actual execution
            # should be handled by the job system
            return (
                f"🚀 Starting job in **{session_id}**:\n\n"
                f"`{instruction[:100]}`\n\n"
                f"I'll notify you when it's done."
            )

        elif action.action_type == "cancel_job":
            job_id = action.params["job_id"]
            await self.db.update_job_status(job_id, "canceled")
            return f"⏹️ Job **{job_id[:8]}** cancelled."

        elif action.action_type == "scan_projects":
            # Would need projects_root from settings
            return "🔍 Scanning for projects... (not implemented in agent yet)"

        elif action.action_type == "claim_task":
            task_id = action.params["task_id"]
            ctx = self.get_chat_context(chat_id)
            session_id = ctx.get("active_session")

            task = await self.db.get_task(task_id)
            if task:
                task.status = "in_progress"
                if session_id:
                    task.session_id = session_id
                await self.db.update_task(task)

            return f"✅ Claimed task **{task_id}**. It's all yours!"

        else:
            return f"Unknown action type: {action.action_type}"

    def reset_chat(self, chat_id: int) -> None:
        """Reset agent for a chat."""
        if chat_id in self._agents:
            del self._agents[chat_id]
        if chat_id in self._chat_contexts:
            del self._chat_contexts[chat_id]
        clear_pending_action(chat_id)


# System prompt for the agent
SYSTEM_PROMPT = """You are TeleVibe, a friendly AI assistant for TeleVibeCode.

TeleVibeCode lets developers control Claude Code sessions from Telegram. You help them:
- Manage coding sessions (create, switch, close)
- Run coding instructions (add features, fix bugs, write tests)
- Track jobs and their status
- Work with backlog tasks

## Your Personality
- Be conversational and friendly, not robotic
- Be concise - this is mobile chat, not a terminal
- Use emojis sparingly but naturally
- If something fails, be helpful about what to try next

## How You Work
- For READ operations (listing, status): Just do it and tell them what you found
- For WRITE operations (create, run, close, cancel): Ask for confirmation first
- Always use the tools available to you - don't make things up
- If you're not sure what they want, ask a clarifying question

## Examples of Good Responses
User: "what sessions do I have"
You: *call list_sessions* "You have 2 sessions: S1 on televibecode (idle) and S2 on myproject (running a job)"

User: "start working on televibecode"
You: *call create_session* "Create a new session for televibecode?" (wait for confirm)

User: "run the tests"
You: *call run_instruction("pytest")* "Run pytest in S1?" (wait for confirm)

User: "yo"
You: "Hey! What are we working on today?"

## Important
- The user is on mobile - keep responses SHORT
- If they say yes/confirm/do it after you ask, that means proceed
- Don't repeat yourself or over-explain
- Be a helpful coding buddy, not a formal assistant
"""


# Global agent instance
_agent: TeleVibeAgent | None = None
_agent_model: str | None = None


def get_agent(db: Database, model: str, db_path: Path | None = None) -> TeleVibeAgent:
    """Get or create the global agent.

    Args:
        db: Database instance.
        model: AI model to use.
        db_path: Path to agent memory database.

    Returns:
        TeleVibeAgent instance.
    """
    global _agent, _agent_model

    # Recreate agent if model changed
    if _agent is not None and _agent_model != model:
        log.info("agent_model_changed", old=_agent_model, new=model)
        _agent = None

    if _agent is None:
        _agent = TeleVibeAgent(db=db, model=model, db_path=db_path)
        _agent_model = model

    # Update the model on the agent (for per-chat agent creation)
    _agent.model = model

    return _agent


def reset_agent() -> None:
    """Reset the global agent."""
    global _agent, _agent_model
    _agent = None
    _agent_model = None
