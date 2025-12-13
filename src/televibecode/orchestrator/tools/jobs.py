"""MCP tools for job management."""

from datetime import datetime, timezone

from televibecode.config import Settings
from televibecode.db import Database, JobStatus, SessionState
from televibecode.runner import (
    get_job_logs as _get_job_logs,
)
from televibecode.runner import (
    get_job_summary as _get_job_summary,
)
from televibecode.runner import (
    list_session_jobs as _list_session_jobs,
)
from televibecode.runner import (
    run_instruction as _run_instruction,
)


async def run_instruction(
    db: Database,
    settings: Settings,
    session_id: str,
    instruction: str,
) -> dict:
    """Run an instruction in a session.

    Args:
        db: Database instance.
        settings: Application settings.
        session_id: Session to run in.
        instruction: Instruction for Claude Code.

    Returns:
        Created job dictionary.
    """
    job = await _run_instruction(db, settings, session_id, instruction)

    return {
        "job_id": job.job_id,
        "session_id": job.session_id,
        "project_id": job.project_id,
        "status": job.status.value,
        "instruction": job.instruction[:100] + "..."
        if len(job.instruction) > 100
        else job.instruction,
        "created_at": job.created_at.isoformat(),
        "message": f"Job {job.job_id} started in session {session_id}",
    }


async def get_job(
    db: Database,
    job_id: str,
) -> dict | None:
    """Get a job by ID.

    Args:
        db: Database instance.
        job_id: Job ID.

    Returns:
        Job dictionary or None.
    """
    return await _get_job_summary(db, job_id)


async def list_jobs(
    db: Database,
    session_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List jobs.

    Args:
        db: Database instance.
        session_id: Optional session filter.
        status: Optional status filter.
        limit: Maximum jobs to return.

    Returns:
        List of job dictionaries.
    """
    if session_id:
        jobs = await _list_session_jobs(db, session_id, limit=limit)
    else:
        # Get all recent jobs from database
        all_jobs = []
        all_sessions = await db.get_all_sessions()
        for session in all_sessions:
            session_jobs = await db.get_jobs_by_session(session.session_id, limit=limit)
            all_jobs.extend(session_jobs)

        # Sort by created_at and limit
        all_jobs.sort(key=lambda j: j.created_at, reverse=True)
        jobs = [
            {
                "job_id": j.job_id,
                "session_id": j.session_id,
                "status": j.status.value,
                "instruction": j.instruction[:50] + "..."
                if len(j.instruction) > 50
                else j.instruction,
                "created_at": j.created_at.isoformat(),
            }
            for j in all_jobs[:limit]
        ]

    if status:
        try:
            status_enum = JobStatus(status)
            jobs = [j for j in jobs if j.get("status") == status_enum.value]
        except ValueError:
            pass

    return jobs


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
    return await _get_job_logs(db, job_id, tail=tail)


async def cancel_job(
    db: Database,
    job_id: str,
) -> dict:
    """Cancel a running job.

    Args:
        db: Database instance.
        job_id: Job to cancel.

    Returns:
        Result dictionary.
    """
    job = await db.get_job(job_id)
    if not job:
        raise ValueError(f"Job '{job_id}' not found")

    if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
        raise ValueError(f"Job '{job_id}' is not running (status: {job.status.value})")

    # Update status
    job.status = JobStatus.CANCELED
    job.error = "Cancelled by user"
    job.finished_at = datetime.now(timezone.utc)
    await db.update_job(job)

    # Update session
    session = await db.get_session(job.session_id)
    if session:
        session.state = SessionState.IDLE
        session.current_job_id = None
        await db.update_session(session)

    return {
        "job_id": job_id,
        "status": "canceled",
        "message": f"Job {job_id} has been cancelled",
    }


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
    return await _get_job_summary(db, job_id)


async def list_running_jobs(db: Database) -> list[dict]:
    """List all currently running jobs.

    Args:
        db: Database instance.

    Returns:
        List of running job dictionaries.
    """
    all_sessions = await db.get_all_sessions()
    running = []

    for session in all_sessions:
        if session.current_job_id:
            job = await db.get_job(session.current_job_id)
            if job and job.status == JobStatus.RUNNING:
                running.append(
                    {
                        "job_id": job.job_id,
                        "session_id": job.session_id,
                        "project_id": job.project_id,
                        "instruction": job.instruction[:50] + "..."
                        if len(job.instruction) > 50
                        else job.instruction,
                        "started_at": job.started_at.isoformat()
                        if job.started_at
                        else None,
                    }
                )

    return running
