"""Job executor for Claude Code processes."""

import asyncio
import contextlib
import json
import os
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog

from televibecode.config import Settings
from televibecode.db import Database, Job, JobStatus, Session, SessionState
from televibecode.runner.context import get_enhanced_instruction
from televibecode.tracker import SessionEvent, parse_stream_events

log = structlog.get_logger()


@dataclass
class JobProgress:
    """Progress information for a running job."""

    job_id: str
    status: str = "starting"
    elapsed_seconds: int = 0
    files_touched: list[str] = field(default_factory=list)
    current_tool: str | None = None
    tool_count: int = 0
    message_count: int = 0
    last_message: str | None = None
    error: str | None = None

    def to_progress_text(self) -> str:
        """Format progress for display."""
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


class JobExecutor:
    """Executes Claude Code jobs in session workspaces."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        on_progress: Callable[[str, JobProgress], None] | None = None,
        on_event: Callable[[str, SessionEvent], None] | None = None,
    ):
        """Initialize the executor.

        Args:
            settings: Application settings.
            db: Database instance.
            on_progress: Optional callback for progress updates.
            on_event: Optional callback for session events (for tracker).
        """
        self.settings = settings
        self.db = db
        self.on_progress = on_progress
        self.on_event = on_event
        self._running_jobs: dict[str, asyncio.subprocess.Process] = {}
        self._job_progress: dict[str, JobProgress] = {}

    async def run_job(
        self,
        session: Session,
        instruction: str,
        raw_input: str | None = None,
    ) -> Job:
        """Run a job in a session's workspace.

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
        )

        return job

    async def execute_job(self, job: Job) -> Job:
        """Execute a queued job.

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
        progress = JobProgress(job_id=job.job_id, status="running")
        self._job_progress[job.job_id] = progress
        start_time = datetime.now(timezone.utc)

        log.info(
            "job_started",
            job_id=job.job_id,
            workspace=str(workspace_path),
        )

        # Build command
        cmd = [
            "claude",
            "-p",
            job.instruction,
            "--output-format",
            "stream-json",
        ]

        # Set up environment (inherit PATH to find claude CLI)
        env = {
            "HOME": str(Path.home()),
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "CLAUDE_CODE_ENTRYPOINT": "televibecode",
        }

        # Open log file using context manager
        log_path = Path(job.log_path) if job.log_path else None

        with contextlib.ExitStack() as stack:
            log_file = None
            if log_path:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_file = stack.enter_context(
                    open(log_path, "w", encoding="utf-8")  # noqa: SIM115
                )

            try:
                # Start process
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(workspace_path),
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )

                self._running_jobs[job.job_id] = proc

                # Stream output
                summary_lines = []
                files_changed = []
                last_progress_update = datetime.now(timezone.utc)

                async for line in self._stream_output(proc, log_file):
                    # Update elapsed time
                    now = datetime.now(timezone.utc)
                    progress.elapsed_seconds = int((now - start_time).total_seconds())

                    # Parse and emit tracker events
                    if self.on_event:
                        for session_event in parse_stream_events(line, job.job_id):
                            self.on_event(job.job_id, session_event)

                    # Try to parse JSON events for progress tracking
                    try:
                        event = json.loads(line)
                        event_type = event.get("type")

                        if event_type == "assistant":
                            message = event.get("message", {})
                            content_list = message.get("content", [])
                            for content in content_list:
                                if content.get("type") == "text":
                                    text = content.get("text", "")
                                    if text:
                                        summary_lines.append(text[:200])
                                        progress.message_count += 1
                                        progress.last_message = text[:100]
                                elif content.get("type") == "tool_use":
                                    tool_name = content.get("name", "")
                                    progress.tool_count += 1
                                    progress.current_tool = tool_name

                                    if tool_name in ("Write", "Edit", "MultiEdit"):
                                        tool_input = content.get("input", {})
                                        file_path = tool_input.get("file_path")
                                        if file_path and file_path not in files_changed:
                                            files_changed.append(file_path)
                                        if (
                                            file_path
                                            and file_path not in progress.files_touched
                                        ):
                                            progress.files_touched.append(file_path)

                        elif event_type == "user":
                            # Tool results
                            progress.current_tool = None

                        # Report progress periodically (every 3 seconds)
                        now = datetime.now(timezone.utc)
                        if (now - last_progress_update).total_seconds() >= 3:
                            if self.on_progress:
                                self.on_progress(job.job_id, progress)
                            last_progress_update = now

                    except json.JSONDecodeError:
                        # Plain text output
                        if line.strip():
                            summary_lines.append(line.strip()[:200])

                # Wait for completion
                return_code = await proc.wait()

                # Update job with results
                if return_code == 0:
                    job.status = JobStatus.DONE
                    job.result_summary = "\n".join(summary_lines[-5:])[:500]
                    progress.status = "done"
                else:
                    job.status = JobStatus.FAILED
                    job.error = f"Process exited with code {return_code}"
                    progress.status = "failed"
                    progress.error = job.error

                job.files_changed = files_changed if files_changed else None
                job.finished_at = datetime.now(timezone.utc)

                # Final progress update
                if self.on_progress:
                    self.on_progress(job.job_id, progress)

            except asyncio.CancelledError:
                job.status = JobStatus.CANCELED
                job.error = "Job was cancelled"
                job.finished_at = datetime.now(timezone.utc)
                progress.status = "cancelled"

            except Exception as e:
                job.status = JobStatus.FAILED
                job.error = str(e)
                job.finished_at = datetime.now(timezone.utc)
                progress.status = "failed"
                progress.error = str(e)
                log.error("job_error", job_id=job.job_id, error=str(e))

            finally:
                self._running_jobs.pop(job.job_id, None)
                self._job_progress.pop(job.job_id, None)

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
        )

        return job

    def get_job_progress(self, job_id: str) -> JobProgress | None:
        """Get current progress for a job.

        Args:
            job_id: Job ID.

        Returns:
            JobProgress or None if not running.
        """
        return self._job_progress.get(job_id)

    async def _stream_output(
        self,
        proc: asyncio.subprocess.Process,
        log_file=None,
    ) -> AsyncIterator[str]:
        """Stream output from process.

        Args:
            proc: Running subprocess.
            log_file: Optional file to write logs.

        Yields:
            Output lines.
        """
        if not proc.stdout:
            return

        while True:
            line = await proc.stdout.readline()
            if not line:
                break

            decoded = line.decode("utf-8", errors="replace").rstrip()

            if log_file:
                log_file.write(decoded + "\n")
                log_file.flush()

            yield decoded

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job.

        Args:
            job_id: Job to cancel.

        Returns:
            True if job was cancelled.
        """
        proc = self._running_jobs.get(job_id)
        if proc:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except TimeoutError:
                proc.kill()

            return True

        return False

    def get_running_job_ids(self) -> list[str]:
        """Get IDs of currently running jobs.

        Returns:
            List of job IDs.
        """
        return list(self._running_jobs.keys())


async def run_instruction(
    db: Database,
    settings: Settings,
    session_id: str,
    instruction: str,
    on_progress: Callable[[str, JobProgress], None] | None = None,
    on_event: Callable[[str, SessionEvent], None] | None = None,
    on_complete: Callable[[Job], None] | None = None,
) -> Job:
    """Run an instruction in a session.

    Args:
        db: Database instance.
        settings: Application settings.
        session_id: Session to run in.
        instruction: Instruction for Claude Code.
        on_progress: Optional progress callback (receives job_id, JobProgress).
        on_event: Optional event callback for tracker (receives job_id, SessionEvent).
        on_complete: Optional callback when job completes (receives Job).

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

    executor = JobExecutor(settings, db, on_progress, on_event)
    # Store original instruction in raw_input, use enhanced for execution
    job = await executor.run_job(session, enhanced_instruction, raw_input=instruction)

    # Execute in background with completion callback
    async def execute_with_callback():
        completed_job = await executor.execute_job(job)
        if on_complete:
            on_complete(completed_job)

    asyncio.create_task(execute_with_callback())

    return job


async def get_job_logs(
    db: Database,
    job_id: str,
    tail: int = 50,
) -> dict:
    """Get logs for a job.

    Args:
        db: Database instance.
        job_id: Job ID.
        tail: Number of lines from end.

    Returns:
        Dictionary with log info and content.
    """
    job = await db.get_job(job_id)
    if not job:
        raise ValueError(f"Job '{job_id}' not found")

    logs = ""
    if job.log_path:
        log_path = Path(job.log_path)
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8", errors="replace")
            lines = content.strip().split("\n")
            logs = "\n".join(lines[-tail:]) if tail and len(lines) > tail else content

    return {
        "job_id": job_id,
        "status": job.status.value,
        "log_path": job.log_path,
        "tail": tail,
        "logs": logs,
    }


async def list_session_jobs(
    db: Database,
    session_id: str,
    limit: int = 10,
) -> list[dict]:
    """List jobs for a session.

    Args:
        db: Database instance.
        session_id: Session ID.
        limit: Maximum jobs to return.

    Returns:
        List of job dictionaries.
    """
    jobs = await db.get_jobs_by_session(session_id, limit=limit)

    return [
        {
            "job_id": j.job_id,
            "status": j.status.value,
            "instruction": j.instruction[:50] + "..."
            if len(j.instruction) > 50
            else j.instruction,
            "created_at": j.created_at.isoformat(),
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            "files_changed": j.files_changed,
            "error": j.error,
        }
        for j in jobs
    ]


async def get_job_summary(
    db: Database,
    job_id: str,
) -> dict | None:
    """Get job summary.

    Args:
        db: Database instance.
        job_id: Job ID.

    Returns:
        Job summary dictionary or None.
    """
    job = await db.get_job(job_id)
    if not job:
        return None

    return {
        "job_id": job.job_id,
        "session_id": job.session_id,
        "project_id": job.project_id,
        "status": job.status.value,
        "instruction": job.instruction,
        "result_summary": job.result_summary,
        "files_changed": job.files_changed,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
