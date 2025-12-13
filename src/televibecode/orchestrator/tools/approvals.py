"""MCP tools for approval management."""

import uuid
from datetime import datetime, timezone

from televibecode.db import (
    Approval,
    ApprovalState,
    ApprovalType,
    Database,
    JobStatus,
    SessionState,
)


async def create_approval(
    db: Database,
    job_id: str,
    approval_type: str,
    action_description: str,
    action_details: dict | None = None,
) -> dict:
    """Create an approval request for a job.

    Args:
        db: Database instance.
        job_id: Job requiring approval.
        approval_type: Type of action (shell_command, git_push, etc.).
        action_description: Human-readable description.
        action_details: Optional additional details.

    Returns:
        Created approval dictionary.
    """
    job = await db.get_job(job_id)
    if not job:
        raise ValueError(f"Job '{job_id}' not found")

    # Validate approval type
    try:
        atype = ApprovalType(approval_type)
    except ValueError:
        valid = [t.value for t in ApprovalType]
        raise ValueError(f"Invalid approval type. Valid: {valid}") from None

    # Create approval
    approval = Approval(
        approval_id=str(uuid.uuid4())[:8],
        job_id=job_id,
        session_id=job.session_id,
        project_id=job.project_id,
        approval_type=atype,
        action_description=action_description,
        action_details=action_details,
    )

    await db.create_approval(approval)

    # Update job status
    job.status = JobStatus.WAITING_APPROVAL
    job.approval_required = True
    job.approval_scope = approval_type
    await db.update_job(job)

    # Update session state
    session = await db.get_session(job.session_id)
    if session:
        session.state = SessionState.BLOCKED
        await db.update_session(session)

    return {
        "approval_id": approval.approval_id,
        "job_id": job_id,
        "session_id": job.session_id,
        "approval_type": approval_type,
        "action_description": action_description,
        "state": "pending",
        "message": f"Approval request created: {action_description}",
    }


async def list_pending_approvals(
    db: Database,
    session_id: str | None = None,
) -> list[dict]:
    """List pending approvals.

    Args:
        db: Database instance.
        session_id: Optional session filter.

    Returns:
        List of pending approval dictionaries.
    """
    if session_id:
        all_approvals = await db.get_approvals_by_session(session_id)
        approvals = [a for a in all_approvals if a.state == ApprovalState.PENDING]
    else:
        approvals = await db.get_pending_approvals()

    return [
        {
            "approval_id": a.approval_id,
            "job_id": a.job_id,
            "session_id": a.session_id,
            "project_id": a.project_id,
            "approval_type": a.approval_type.value,
            "action_description": a.action_description,
            "action_details": a.action_details,
            "created_at": a.created_at.isoformat(),
        }
        for a in approvals
    ]


async def get_approval_detail(
    db: Database,
    approval_id: str,
) -> dict | None:
    """Get detailed approval information.

    Args:
        db: Database instance.
        approval_id: Approval ID.

    Returns:
        Approval dictionary or None.
    """
    approval = await db.get_approval(approval_id)
    if not approval:
        return None

    # Get job info
    job = await db.get_job(approval.job_id)
    job_info = {
        "instruction": job.instruction if job else None,
        "status": job.status.value if job else None,
    }

    return {
        "approval_id": approval.approval_id,
        "job_id": approval.job_id,
        "session_id": approval.session_id,
        "project_id": approval.project_id,
        "approval_type": approval.approval_type.value,
        "action_description": approval.action_description,
        "action_details": approval.action_details,
        "state": approval.state.value,
        "approved_by": approval.approved_by,
        "approved_at": approval.approved_at.isoformat()
        if approval.approved_at
        else None,
        "created_at": approval.created_at.isoformat(),
        "job": job_info,
    }


async def approve_action(
    db: Database,
    approval_id: str,
    approved_by: str,
) -> dict:
    """Approve a pending action.

    Args:
        db: Database instance.
        approval_id: Approval to approve.
        approved_by: User who approved.

    Returns:
        Result dictionary.
    """
    approval = await db.get_approval(approval_id)
    if not approval:
        raise ValueError(f"Approval '{approval_id}' not found")

    if approval.state != ApprovalState.PENDING:
        raise ValueError(f"Approval is already {approval.state.value}, cannot approve")

    # Approve
    approval.state = ApprovalState.APPROVED
    approval.approved_by = approved_by
    approval.approved_at = datetime.now(timezone.utc)
    await db.update_approval(approval)

    # Update job
    job = await db.get_job(approval.job_id)
    if job:
        job.approval_state = ApprovalState.APPROVED
        # Job remains in waiting_approval until the executor resumes it
        await db.update_job(job)

    return {
        "approval_id": approval_id,
        "job_id": approval.job_id,
        "state": "approved",
        "approved_by": approved_by,
        "message": f"Action approved by {approved_by}",
    }


async def deny_action(
    db: Database,
    approval_id: str,
    denied_by: str,
    reason: str | None = None,
) -> dict:
    """Deny a pending action.

    Args:
        db: Database instance.
        approval_id: Approval to deny.
        denied_by: User who denied.
        reason: Optional denial reason.

    Returns:
        Result dictionary.
    """
    approval = await db.get_approval(approval_id)
    if not approval:
        raise ValueError(f"Approval '{approval_id}' not found")

    if approval.state != ApprovalState.PENDING:
        raise ValueError(f"Approval is already {approval.state.value}, cannot deny")

    # Deny
    approval.state = ApprovalState.DENIED
    approval.approved_by = denied_by
    approval.approved_at = datetime.now(timezone.utc)
    await db.update_approval(approval)

    # Update job - mark as failed/canceled
    job = await db.get_job(approval.job_id)
    if job:
        job.status = JobStatus.CANCELED
        job.approval_state = ApprovalState.DENIED
        job.error = f"Denied by {denied_by}" + (f": {reason}" if reason else "")
        job.finished_at = datetime.now(timezone.utc)
        await db.update_job(job)

    # Update session state back to idle
    session = await db.get_session(approval.session_id)
    if session:
        session.state = SessionState.IDLE
        session.current_job_id = None
        await db.update_session(session)

    return {
        "approval_id": approval_id,
        "job_id": approval.job_id,
        "state": "denied",
        "denied_by": denied_by,
        "reason": reason,
        "message": f"Action denied by {denied_by}",
    }


def format_approval_message(approval: dict) -> str:
    """Format an approval request for Telegram display.

    Args:
        approval: Approval dictionary.

    Returns:
        Formatted markdown string.
    """
    type_icons = {
        "shell_command": "🖥️",
        "file_write": "📝",
        "git_push": "⬆️",
        "deploy": "🚀",
        "dangerous_edit": "⚠️",
        "external_request": "🌐",
    }

    icon = type_icons.get(approval.get("approval_type", ""), "❓")
    atype = approval.get("approval_type", "unknown").replace("_", " ").title()

    text = "*⚠️ Approval Required*\n\n"
    text += f"{icon} *Type*: {atype}\n"
    text += f"📂 Session: `{approval.get('session_id')}`\n"
    text += f"🔹 Job: `{approval.get('job_id')}`\n\n"
    text += f"*Action*:\n_{approval.get('action_description', 'N/A')}_\n\n"

    details = approval.get("action_details")
    if details and isinstance(details, dict):
        if "command" in details:
            text += f"*Command*:\n`{details['command']}`\n\n"
        if "file_path" in details:
            text += f"*File*: `{details['file_path']}`\n\n"

    return text
