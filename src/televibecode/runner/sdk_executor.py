"""SDK-based job executor using Claude Agent SDK.

This module provides an alternative executor implementation that uses the
official Claude Agent SDK instead of spawning subprocess. It provides:
- Native Python hooks for approval gating
- Clean interrupt support
- Structured message handling
- Session continuity support

See docs/sdk-analysis.md for comparison with subprocess approach.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        HookContext,
        HookMatcher,
        ResultMessage,
        SystemMessage,
        TextBlock,
        ToolResultBlock,
        ToolUseBlock,
    )

    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False
    # Define placeholder types for type hints when SDK not installed
    ClaudeSDKClient = Any
    ClaudeAgentOptions = Any
    HookMatcher = Any
    HookContext = Any

from televibecode.config import Settings
from televibecode.db import (
    Approval,
    ApprovalState,
    ApprovalType,
    Database,
    Job,
    JobStatus,
    Session,
    SessionState,
)
from televibecode.runner.context import get_enhanced_instruction
from televibecode.tracker import (
    AISpeechEvent,
    SessionEvent,
    SystemResultEvent,
    ToolResultEvent,
    ToolStartEvent,
)

log = structlog.get_logger()


# =============================================================================
# Approval Configuration (from specs requirements.md)
# =============================================================================

# Commands that never require approval (safe commands)
SHELL_WHITELIST = {
    "git status",
    "git diff",
    "git log",
    "git branch",
    "git show",
    "ls",
    "pwd",
    "cat",
    "head",
    "tail",
    "wc",
    "echo",
    "pytest",
    "npm test",
    "npm run lint",
    "npm run build",
    "uv run pytest",
    "uv run ruff",
    "uv run mypy",
    "python --version",
    "node --version",
    "which",
}

# Commands that always require approval (dangerous)
SHELL_DANGEROUS_PATTERNS = [
    "rm -rf",
    "rm -r /",
    "sudo",
    "chmod 777",
    "curl | bash",
    "wget | bash",
    "> /dev/",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",  # Fork bomb
]


def is_safe_command(command: str) -> bool:
    """Check if a shell command is in the safe whitelist.

    Args:
        command: Shell command to check.

    Returns:
        True if command is safe.
    """
    command_lower = command.lower().strip()

    # Check exact matches
    for safe in SHELL_WHITELIST:
        if command_lower == safe or command_lower.startswith(safe + " "):
            return True

    return False


def is_dangerous_command(command: str) -> bool:
    """Check if a shell command is dangerous.

    Args:
        command: Shell command to check.

    Returns:
        True if command is dangerous.
    """
    command_lower = command.lower()
    return any(pattern in command_lower for pattern in SHELL_DANGEROUS_PATTERNS)


def get_approval_type_for_tool(
    tool_name: str,
    tool_input: dict[str, Any],
) -> ApprovalType | None:
    """Determine if a tool use requires approval and what type.

    Args:
        tool_name: Name of the tool being used.
        tool_input: Tool input parameters.

    Returns:
        ApprovalType if approval required, None if auto-approved.
    """
    if tool_name == "Bash":
        command = tool_input.get("command", "")

        # Safe commands: auto-approve
        if is_safe_command(command):
            return None

        # Dangerous commands: always require approval
        if is_dangerous_command(command):
            return ApprovalType.SHELL_COMMAND

        # Git push: always require approval
        if "git push" in command.lower():
            return ApprovalType.GIT_PUSH

        # Other shell commands: require approval
        return ApprovalType.SHELL_COMMAND

    # File operations that might be dangerous
    if tool_name in ("Write", "Edit", "MultiEdit"):
        file_path = tool_input.get("file_path", "")

        # Sensitive files always need approval
        sensitive_patterns = [
            ".env",
            "credentials",
            "secret",
            "password",
            "private_key",
            ".ssh/",
            "/etc/",
        ]
        for pattern in sensitive_patterns:
            if pattern in file_path.lower():
                return ApprovalType.DANGEROUS_EDIT

        # Normal file writes: auto-approve (per specs)
        return None

    # Web operations
    if tool_name == "WebFetch":
        return ApprovalType.EXTERNAL_REQUEST

    return None


# =============================================================================
# Progress Tracking
# =============================================================================


@dataclass
class SDKJobProgress:
    """Progress information for a running SDK job."""

    job_id: str
    status: str = "starting"
    elapsed_seconds: int = 0
    files_touched: list[str] = field(default_factory=list)
    current_tool: str | None = None
    tool_count: int = 0
    message_count: int = 0
    last_message: str | None = None
    error: str | None = None
    waiting_approval: bool = False
    approval_tool: str | None = None
    approval_details: str | None = None

    def to_progress_text(self) -> str:
        """Format progress for display."""
        if self.waiting_approval:
            parts = ["⏳ *Waiting for approval*"]
            if self.approval_tool:
                parts.append(f"🔧 Tool: {self.approval_tool}")
            if self.approval_details:
                parts.append(f"📝 {self.approval_details[:100]}")
            return "\n".join(parts)

        # Progress bar based on activity
        activity = min(self.tool_count + self.message_count, 20)
        filled = activity
        empty = 20 - filled
        bar = f"[{'█' * filled}{'░' * empty}]"

        parts = [f"🔧 *Running...* {bar}"]

        if self.elapsed_seconds > 0:
            mins, secs = divmod(self.elapsed_seconds, 60)
            if mins > 0:
                parts.append(f"⏱️ {mins}m {secs}s")
            else:
                parts.append(f"⏱️ {secs}s")

        if self.current_tool:
            parts.append(f"🔨 {self.current_tool}")

        if self.files_touched:
            count = len(self.files_touched)
            parts.append(f"📝 {count} file{'s' if count != 1 else ''}")

        if self.last_message:
            msg = self.last_message[:80]
            if len(self.last_message) > 80:
                msg += "..."
            parts.append(f"💬 _{msg}_")

        return "\n".join(parts)


# =============================================================================
# Approval Request/Response Types
# =============================================================================


@dataclass
class ApprovalRequest:
    """Request for user approval."""

    approval_id: str
    job_id: str
    session_id: str
    project_id: str
    approval_type: ApprovalType
    tool_name: str
    tool_input: dict[str, Any]
    description: str


@dataclass
class ApprovalResponse:
    """Response to approval request."""

    approved: bool
    reason: str | None = None


# Type for approval callback
ApprovalCallback = Callable[[ApprovalRequest], Awaitable[ApprovalResponse]]


# =============================================================================
# SDK Job Executor
# =============================================================================


class SDKJobExecutor:
    """Execute jobs using Claude Agent SDK.

    This executor provides the same interface as JobExecutor but uses
    the official SDK instead of subprocess spawning.
    """

    def __init__(
        self,
        settings: Settings,
        db: Database,
        on_progress: Callable[[str, SDKJobProgress], None] | None = None,
        on_approval_needed: ApprovalCallback | None = None,
        on_event: Callable[[str, SessionEvent], None] | None = None,
        on_complete: Callable[[Job], None] | None = None,
    ):
        """Initialize the SDK executor.

        Args:
            settings: Application settings.
            db: Database instance.
            on_progress: Optional callback for progress updates.
            on_approval_needed: Optional callback for approval requests.
            on_event: Optional callback for tracker events.
            on_complete: Optional callback when job completes.
        """
        if not SDK_AVAILABLE:
            raise RuntimeError(
                "Claude Agent SDK not installed. "
                "Install with: pip install claude-agent-sdk"
            )

        self.settings = settings
        self.db = db
        self.on_progress = on_progress
        self.on_approval_needed = on_approval_needed
        self.on_event = on_event
        self.on_complete = on_complete
        self._running_clients: dict[str, ClaudeSDKClient] = {}
        self._job_progress: dict[str, SDKJobProgress] = {}
        self._pending_approvals: dict[str, asyncio.Event] = {}
        self._approval_results: dict[str, ApprovalResponse] = {}

    async def run_job(
        self,
        session: Session,
        instruction: str,
        raw_input: str | None = None,
    ) -> Job:
        """Create and queue a job for execution.

        Args:
            session: Session to run in.
            instruction: Instruction for Claude Code.
            raw_input: Original user input.

        Returns:
            Created Job object.
        """
        # Create job record
        job_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        log_filename = f"{job_id}_{timestamp}.log"
        log_path = self.settings.logs_dir / log_filename

        job = Job(
            job_id=job_id,
            session_id=session.session_id,
            project_id=session.project_id,
            instruction=instruction,
            raw_input=raw_input or instruction,
            status=JobStatus.QUEUED,
            log_path=str(log_path),
        )

        await self.db.create_job(job)

        # Update session state
        session.current_job_id = job_id
        session.state = SessionState.RUNNING
        await self.db.update_session(session)

        log.info(
            "job_created",
            job_id=job_id,
            session_id=session.session_id,
            instruction=instruction[:50],
            executor="sdk",
        )

        return job

    def _create_approval_hook(
        self,
        job: Job,
        session: Session,
    ) -> Callable[[dict, str | None, HookContext], Awaitable[dict]]:
        """Create a PreToolUse hook for approval gating.

        Args:
            job: Current job.
            session: Current session.

        Returns:
            Hook callback function.
        """

        async def approval_hook(
            input_data: dict[str, Any],
            tool_use_id: str | None,
            context: HookContext,
        ) -> dict[str, Any]:
            """Hook that checks tool usage and requests approval if needed."""
            tool_name = input_data.get("tool_name", "")
            tool_input = input_data.get("tool_input", {})

            # Check if approval is required
            approval_type = get_approval_type_for_tool(tool_name, tool_input)

            if approval_type is None:
                # Auto-approved
                return {}

            log.info(
                "approval_required",
                job_id=job.job_id,
                tool=tool_name,
                approval_type=approval_type.value,
            )

            # Update progress to show waiting
            progress = self._job_progress.get(job.job_id)
            if progress:
                progress.waiting_approval = True
                progress.approval_tool = tool_name
                if tool_name == "Bash":
                    progress.approval_details = tool_input.get("command", "")[:100]
                elif tool_name in ("Write", "Edit"):
                    progress.approval_details = tool_input.get("file_path", "")
                if self.on_progress:
                    self.on_progress(job.job_id, progress)

            # Update job status
            job.status = JobStatus.WAITING_APPROVAL
            job.approval_required = True
            job.approval_scope = approval_type.value
            job.approval_state = ApprovalState.PENDING
            await self.db.update_job(job)

            # Create approval request
            approval_id = str(uuid.uuid4())[:8]
            description = self._format_approval_description(
                tool_name, tool_input, approval_type
            )

            request = ApprovalRequest(
                approval_id=approval_id,
                job_id=job.job_id,
                session_id=session.session_id,
                project_id=session.project_id,
                approval_type=approval_type,
                tool_name=tool_name,
                tool_input=tool_input,
                description=description,
            )

            # Store approval in database
            approval = Approval(
                approval_id=approval_id,
                job_id=job.job_id,
                session_id=session.session_id,
                project_id=session.project_id,
                approval_type=approval_type,
                action_description=description,
                action_details={"tool_name": tool_name, "tool_input": tool_input},
                state=ApprovalState.PENDING,
            )
            await self.db.create_approval(approval)

            # Request approval via callback
            if self.on_approval_needed:
                # Create event to wait for response
                approval_event = asyncio.Event()
                self._pending_approvals[approval_id] = approval_event

                try:
                    # Call the approval callback (sends to Telegram)
                    response = await self.on_approval_needed(request)

                    # Store result
                    self._approval_results[approval_id] = response

                    # Update approval record
                    approval.state = (
                        ApprovalState.APPROVED
                        if response.approved
                        else ApprovalState.DENIED
                    )
                    approval.approved_at = datetime.now(timezone.utc)
                    await self.db.update_approval(approval)

                    # Update job
                    job.approval_state = approval.state
                    if response.approved:
                        job.status = JobStatus.RUNNING
                    else:
                        job.status = JobStatus.CANCELED
                        job.error = f"Approval denied: {response.reason or 'No reason'}"
                    await self.db.update_job(job)

                    # Update progress
                    if progress:
                        progress.waiting_approval = False
                        progress.approval_tool = None
                        progress.approval_details = None
                        if self.on_progress:
                            self.on_progress(job.job_id, progress)

                    if not response.approved:
                        return {
                            "hookSpecificOutput": {
                                "hookEventName": "PreToolUse",
                                "permissionDecision": "deny",
                                "permissionDecisionReason": response.reason
                                or "User denied approval",
                            }
                        }

                finally:
                    self._pending_approvals.pop(approval_id, None)
                    self._approval_results.pop(approval_id, None)

            return {}

        return approval_hook

    def _format_approval_description(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        approval_type: ApprovalType,
    ) -> str:
        """Format a human-readable description for approval request.

        Args:
            tool_name: Tool being used.
            tool_input: Tool input.
            approval_type: Type of approval needed.

        Returns:
            Formatted description.
        """
        if tool_name == "Bash":
            command = tool_input.get("command", "")
            if "git push" in command.lower():
                return f"Git push: `{command}`"
            return f"Shell command: `{command}`"

        if tool_name in ("Write", "Edit", "MultiEdit"):
            file_path = tool_input.get("file_path", "")
            return f"Edit sensitive file: `{file_path}`"

        if tool_name == "WebFetch":
            url = tool_input.get("url", "")
            return f"Fetch external URL: `{url}`"

        return f"{approval_type.value}: {tool_name}"

    def _create_logging_hook(
        self,
        job: Job,
        log_file,
    ) -> Callable[[dict, str | None, HookContext], Awaitable[dict]]:
        """Create a PostToolUse hook for logging.

        Args:
            job: Current job.
            log_file: Log file handle.

        Returns:
            Hook callback function.
        """

        async def logging_hook(
            input_data: dict[str, Any],
            tool_use_id: str | None,
            context: HookContext,
        ) -> dict[str, Any]:
            """Hook that logs tool usage."""
            tool_name = input_data.get("tool_name", "")
            tool_output = input_data.get("tool_output", {})

            # Update progress
            progress = self._job_progress.get(job.job_id)
            if progress:
                progress.current_tool = None

            # Log to file
            if log_file:
                timestamp = datetime.now(timezone.utc).isoformat()
                log_line = f"[{timestamp}] PostToolUse: {tool_name}\n"
                log_file.write(log_line)

                if tool_output:
                    import json

                    log_file.write(f"  Output: {json.dumps(tool_output)[:500]}\n")
                log_file.flush()

            return {}

        return logging_hook

    async def execute_job(self, job: Job) -> Job:
        """Execute a queued job using the SDK.

        Args:
            job: Job to execute.

        Returns:
            Updated Job object.
        """
        session = await self.db.get_session(job.session_id)
        if not session:
            job.status = JobStatus.FAILED
            job.error = "Session not found"
            await self.db.update_job(job)
            return job

        workspace_path = Path(session.workspace_path)
        if not workspace_path.exists():
            job.status = JobStatus.FAILED
            job.error = f"Workspace does not exist: {workspace_path}"
            await self.db.update_job(job)
            return job

        # Update job status
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        await self.db.update_job(job)

        # Initialize progress tracking
        progress = SDKJobProgress(job_id=job.job_id, status="running")
        self._job_progress[job.job_id] = progress
        start_time = datetime.now(timezone.utc)

        log.info(
            "job_started",
            job_id=job.job_id,
            workspace=str(workspace_path),
            executor="sdk",
        )

        # Open log file
        log_path = Path(job.log_path) if job.log_path else None
        log_file = None

        try:
            if log_path:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115

            # Build SDK options
            options = ClaudeAgentOptions(
                cwd=str(workspace_path),
                allowed_tools=[
                    "Read",
                    "Write",
                    "Edit",
                    "MultiEdit",
                    "Bash",
                    "BashOutput",
                    "KillBash",
                    "Glob",
                    "Grep",
                    "WebFetch",
                    "WebSearch",
                    "TodoWrite",
                    "Task",
                ],
                permission_mode="default",
                setting_sources=["project"],  # Load CLAUDE.md
                hooks={
                    "PreToolUse": [
                        HookMatcher(
                            matcher="Bash|Write|Edit|MultiEdit|WebFetch",
                            hooks=[self._create_approval_hook(job, session)],
                            timeout=3600,  # 1 hour for approval (per specs)
                        ),
                    ],
                    "PostToolUse": [
                        HookMatcher(
                            hooks=[self._create_logging_hook(job, log_file)],
                        ),
                    ],
                },
                env={
                    "TELEVIBE_JOB_ID": job.job_id,
                    "TELEVIBE_SESSION_ID": session.session_id,
                    "TELEVIBE_PROJECT_ID": session.project_id,
                    "TELEVIBE_BRANCH": session.branch,
                    "TELEVIBE_WORKSPACE": str(workspace_path),
                },
                max_turns=100,  # Reasonable limit
            )

            # Create and track client
            client = ClaudeSDKClient(options)
            self._running_clients[job.job_id] = client

            summary_lines: list[str] = []
            files_changed: list[str] = []
            last_progress_update = datetime.now(timezone.utc)

            try:
                async with client:
                    await client.query(job.instruction)

                    # Process responses
                    async for message in client.receive_response():
                        # Update elapsed time
                        now = datetime.now(timezone.utc)
                        progress.elapsed_seconds = int(
                            (now - start_time).total_seconds()
                        )

                        # Handle different message types
                        if isinstance(message, AssistantMessage):
                            for block in message.content:
                                if isinstance(block, TextBlock):
                                    text = block.text
                                    summary_lines.append(text[:200])
                                    progress.message_count += 1
                                    progress.last_message = text[:100]

                                    # Emit tracker event
                                    if self.on_event:
                                        event = AISpeechEvent(
                                            session_id=job.session_id,
                                            job_id=job.job_id,
                                            text=text,
                                        )
                                        self.on_event(job.job_id, event)

                                    if log_file:
                                        log_file.write(f"[Assistant] {text}\n")
                                        log_file.flush()

                                elif isinstance(block, ToolUseBlock):
                                    progress.tool_count += 1
                                    progress.current_tool = block.name

                                    # Emit tracker event
                                    if self.on_event:
                                        event = ToolStartEvent(
                                            session_id=job.session_id,
                                            job_id=job.job_id,
                                            tool_name=block.name,
                                            tool_use_id=block.id or "",
                                            tool_input=block.input or {},
                                        )
                                        self.on_event(job.job_id, event)

                                    if block.name in (
                                        "Write",
                                        "Edit",
                                        "MultiEdit",
                                    ):
                                        file_path = block.input.get("file_path")
                                        if file_path:
                                            if file_path not in files_changed:
                                                files_changed.append(file_path)
                                            if file_path not in progress.files_touched:
                                                progress.files_touched.append(file_path)

                                    if log_file:
                                        log_file.write(
                                            f"[ToolUse] {block.name}: "
                                            f"{str(block.input)[:200]}\n"
                                        )
                                        log_file.flush()

                                elif isinstance(block, ToolResultBlock):
                                    progress.current_tool = None

                                    # Emit tracker event
                                    if self.on_event:
                                        if block.content:
                                            content = str(block.content)
                                        else:
                                            content = ""
                                        is_err = getattr(block, 'is_error', False)
                                        event = ToolResultEvent(
                                            session_id=job.session_id,
                                            job_id=job.job_id,
                                            tool_use_id=block.tool_use_id or "",
                                            result=content,
                                            is_error=is_err,
                                        )
                                        self.on_event(job.job_id, event)

                                    if log_file:
                                        content = str(block.content)[:200]
                                        log_file.write(f"[ToolResult] {content}\n")
                                        log_file.flush()

                        elif isinstance(message, SystemMessage):
                            if log_file:
                                log_file.write(
                                    f"[System] {message.subtype}: {message.data}\n"
                                )
                                log_file.flush()

                        elif isinstance(message, ResultMessage):
                            # Emit result tracker event
                            if self.on_event:
                                subtype = "error" if message.is_error else "success"
                                err_msg = message.result if message.is_error else None
                                event = SystemResultEvent(
                                    session_id=job.session_id,
                                    job_id=job.job_id,
                                    subtype=subtype,
                                    is_error=message.is_error,
                                    error_message=err_msg,
                                    cost_usd=message.total_cost_usd,
                                    num_turns=message.num_turns or 0,
                                    duration_ms=int(progress.elapsed_seconds * 1000),
                                )
                                self.on_event(job.job_id, event)

                            # Final result
                            job.status = (
                                JobStatus.FAILED if message.is_error else JobStatus.DONE
                            )
                            if message.is_error and message.result:
                                job.error = message.result
                            progress.status = (
                                "done" if not message.is_error else "failed"
                            )

                            if log_file:
                                log_file.write(
                                    f"[Result] success={not message.is_error}, "
                                    f"turns={message.num_turns}, "
                                    f"cost=${message.total_cost_usd or 0:.4f}\n"
                                )
                                log_file.flush()

                        # Report progress periodically (every 3 seconds)
                        now = datetime.now(timezone.utc)
                        if (now - last_progress_update).total_seconds() >= 3:
                            if self.on_progress:
                                self.on_progress(job.job_id, progress)
                            last_progress_update = now

            except asyncio.CancelledError:
                job.status = JobStatus.CANCELED
                job.error = "Job was cancelled"
                progress.status = "cancelled"

            except Exception as e:
                job.status = JobStatus.FAILED
                job.error = str(e)
                progress.status = "failed"
                progress.error = str(e)
                log.error("job_error", job_id=job.job_id, error=str(e), executor="sdk")

            finally:
                self._running_clients.pop(job.job_id, None)

            # Update job with results
            job.result_summary = "\n".join(summary_lines[-5:])[:500]
            job.files_changed = files_changed if files_changed else None
            job.finished_at = datetime.now(timezone.utc)

            # Final progress update
            if self.on_progress:
                self.on_progress(job.job_id, progress)

        finally:
            self._job_progress.pop(job.job_id, None)
            if log_file:
                log_file.close()

        await self.db.update_job(job)

        # Update session state
        session = await self.db.get_session(job.session_id)
        if session:
            session.state = SessionState.IDLE
            session.current_job_id = None
            session.last_summary = job.result_summary
            await self.db.update_session(session)

        log.info(
            "job_completed",
            job_id=job.job_id,
            status=job.status.value,
            executor="sdk",
        )

        # Call completion callback
        if self.on_complete:
            self.on_complete(job)

        return job

    def get_job_progress(self, job_id: str) -> SDKJobProgress | None:
        """Get current progress for a job.

        Args:
            job_id: Job ID.

        Returns:
            SDKJobProgress or None if not running.
        """
        return self._job_progress.get(job_id)

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job via interrupt.

        Args:
            job_id: Job to cancel.

        Returns:
            True if job was cancelled.
        """
        client = self._running_clients.get(job_id)
        if client:
            try:
                await client.interrupt()
                log.info("job_interrupted", job_id=job_id, executor="sdk")
                return True
            except Exception as e:
                log.error(
                    "job_interrupt_failed", job_id=job_id, error=str(e), executor="sdk"
                )
        return False

    def get_running_job_ids(self) -> list[str]:
        """Get IDs of currently running jobs.

        Returns:
            List of job IDs.
        """
        return list(self._running_clients.keys())


# =============================================================================
# Helper Functions (matching executor.py interface)
# =============================================================================


async def run_instruction_sdk(
    db: Database,
    settings: Settings,
    session_id: str,
    instruction: str,
    on_progress: Callable[[str, SDKJobProgress], None] | None = None,
    on_approval_needed: ApprovalCallback | None = None,
    on_event: Callable[[str, SessionEvent], None] | None = None,
    on_complete: Callable[[Job], None] | None = None,
) -> Job:
    """Run an instruction in a session using SDK executor.

    Args:
        db: Database instance.
        settings: Application settings.
        session_id: Session to run in.
        instruction: Instruction for Claude Code.
        on_progress: Optional progress callback.
        on_approval_needed: Optional approval callback.
        on_event: Optional callback for tracker events.
        on_complete: Optional callback when job completes.

    Returns:
        Job object.
    """
    session = await db.get_session(session_id)
    if not session:
        raise ValueError(f"Session '{session_id}' not found")

    if session.state == SessionState.RUNNING:
        raise ValueError(
            f"Session {session_id} already has a running job: {session.current_job_id}"
        )

    # Get project for context enhancement
    project = await db.get_project(session.project_id)
    if not project:
        raise ValueError(f"Project '{session.project_id}' not found")

    # Enhance instruction with session context
    enhanced_instruction = get_enhanced_instruction(instruction, session, project)

    executor = SDKJobExecutor(
        settings, db, on_progress, on_approval_needed, on_event, on_complete
    )
    # Store original instruction in raw_input, use enhanced for execution
    job = await executor.run_job(session, enhanced_instruction, raw_input=instruction)

    # Execute in background
    asyncio.create_task(executor.execute_job(job))

    return job


def is_sdk_available() -> bool:
    """Check if Claude Agent SDK is available.

    Returns:
        True if SDK is installed.
    """
    return SDK_AVAILABLE
