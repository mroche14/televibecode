"""Message formatters for Telegram output."""

from datetime import datetime, timezone

from televibecode.db.models import Session, SessionState


def format_project_list(projects: list[dict]) -> str:
    """Format project list for display.

    Args:
        projects: List of project dictionaries.

    Returns:
        Formatted markdown string.
    """
    text = "*Projects*\n\n"

    for p in projects:
        # Project icon based on backlog status
        icon = "📂" if p.get("backlog_enabled") else "📁"

        text += f"{icon} `{p['project_id']}`\n"
        text += f"   {p['name']}\n"
        text += f"   📍 {_truncate_path(p['path'])}\n"
        text += f"   🌿 {p['default_branch']}\n\n"

    text += f"_Total: {len(projects)} project(s)_"
    return text


def format_session_list(sessions: list[Session], title: str = "Sessions") -> str:
    """Format session list for display.

    Args:
        sessions: List of Session objects.
        title: Title for the list.

    Returns:
        Formatted markdown string.
    """
    text = f"*{title}*\n\n"

    for s in sessions:
        state_icon = _session_state_icon(s.state)
        text += f"{state_icon} `{s.session_id}` ({s.project_id})\n"
        text += f"   🌿 {s.branch}\n"
        text += f"   ⏱️ {_relative_time(s.last_activity_at)}\n"

        if s.last_summary:
            if len(s.last_summary) > 50:
                summary = s.last_summary[:50] + "..."
            else:
                summary = s.last_summary
            text += f"   📝 {summary}\n"

        text += "\n"

    text += f"_Total: {len(sessions)} session(s)_"
    return text


def format_session_card(session: Session, project_name: str) -> str:
    """Format a single session as a card.

    Args:
        session: Session object.
        project_name: Name of the project.

    Returns:
        Formatted markdown string.
    """
    state_icon = _session_state_icon(session.state)

    text = f"📂 [{project_name}] 🔹 [{session.session_id}] 🌿 {session.branch}\n\n"
    text += f"*State*: {state_icon} {session.state.value}\n"
    text += f"*Last Activity*: {_relative_time(session.last_activity_at)}\n"

    if session.last_summary:
        text += f"\n*Last Summary*:\n{session.last_summary[:200]}"
        if len(session.last_summary) > 200:
            text += "..."

    if session.attached_task_ids:
        text += f"\n\n*Attached Tasks*: {', '.join(session.attached_task_ids)}"

    return text


def format_job_status(
    job_id: str,
    session_id: str,
    project_id: str,
    branch: str,
    status: str,
    instruction: str,
) -> str:
    """Format job status message.

    Args:
        job_id: Job identifier.
        session_id: Session identifier.
        project_id: Project identifier.
        branch: Branch name.
        status: Job status.
        instruction: Job instruction.

    Returns:
        Formatted markdown string.
    """
    icon = _job_status_icon(status)
    truncated = instruction[:80] + "..." if len(instruction) > 80 else instruction

    return f"{icon} {session_id} ({project_id}/{branch}): {truncated}"


def _session_state_icon(state: SessionState) -> str:
    """Get icon for session state."""
    icons = {
        SessionState.IDLE: "🟢",
        SessionState.RUNNING: "🔧",
        SessionState.BLOCKED: "⏸️",
        SessionState.CLOSING: "🔴",
    }
    return icons.get(state, "❓")


def _job_status_icon(status: str) -> str:
    """Get icon for job status."""
    icons = {
        "queued": "📋",
        "running": "🔧",
        "waiting_approval": "⚠️",
        "done": "✅",
        "failed": "❌",
        "canceled": "⏹️",
    }
    return icons.get(status, "❓")


def _truncate_path(path: str, max_len: int = 40) -> str:
    """Truncate path for display."""
    if len(path) <= max_len:
        return path

    # Try to show the end of the path
    parts = path.split("/")
    result = "/".join(parts[-2:])

    if len(result) > max_len:
        return "..." + result[-(max_len - 3) :]

    return ".../" + result


def _relative_time(dt: datetime) -> str:
    """Format datetime as relative time."""
    now = datetime.now(timezone.utc)
    diff = now - dt

    seconds = diff.total_seconds()

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes}m ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours}h ago"
    else:
        days = int(seconds / 86400)
        return f"{days}d ago"
