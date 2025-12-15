"""Message formatters for Telegram output.

This module provides safe markdown formatting utilities for Telegram messages.

IMPORTANT: Always use these helpers for user-provided content to prevent
markdown parsing errors:

- `escape_markdown(text)` - Escapes special chars (_*[]`)
- `safe_inline(text)` - For text inside _italics_ or *bold* (also strips newlines)
- `safe_code(text)` - For text inside `backticks` (escapes backticks)

Example:
    # For regular text with potential special chars:
    f"Project: {escape_markdown(project_name)}"

    # For italic/bold content (will be wrapped in _..._ or *...*):
    f"_{safe_inline(description)}_"

    # For inline code:
    f"`{safe_code(session_id)}`"
"""

from datetime import datetime, timezone

from televibecode.db.models import Session, SessionState


def escape_markdown(text: str) -> str:
    """Escape Telegram markdown special characters.

    Use this for any user-provided text that will be displayed in a message
    with parse_mode="Markdown". This prevents characters like _ or * from
    being interpreted as formatting.

    Args:
        text: Text to escape. Can be None or empty.

    Returns:
        Escaped text safe for Telegram markdown. Returns empty string for None.

    Example:
        f"Branch: {escape_markdown(branch_name)}"
        f"Session `{escape_markdown(session_id)}` created"
    """
    if not text:
        return text or ""
    # Escape markdown special characters
    for char in ["_", "*", "[", "]", "`"]:
        text = text.replace(char, "\\" + char)
    return text


def safe_inline(text: str, max_len: int | None = None) -> str:
    """Prepare text for use inside inline formatting (_italic_ or *bold*).

    This function:
    1. Replaces newlines with spaces (newlines break inline formatting)
    2. Optionally truncates to max_len
    3. Escapes markdown special characters

    IMPORTANT: Use this whenever text will be wrapped in underscores or asterisks:
        f"_{safe_inline(description)}_"
        f"*{safe_inline(title)}*"

    Args:
        text: Text to prepare. Can be None or empty.
        max_len: Optional maximum length (truncates with "..." if exceeded).

    Returns:
        Text safe for inline markdown formatting.

    Example:
        # For italic description:
        f"_{safe_inline(job.instruction, max_len=100)}_"

        # For bold title:
        f"*{safe_inline(task.title)}*"
    """
    if not text:
        return text or ""

    # Replace newlines with spaces (critical for inline formatting)
    text = text.replace("\n", " ").replace("\r", " ")

    # Collapse multiple spaces
    while "  " in text:
        text = text.replace("  ", " ")

    # Truncate if needed
    if max_len and len(text) > max_len:
        text = text[: max_len - 3].rstrip() + "..."

    # Escape markdown characters
    return escape_markdown(text)


def safe_code(text: str, max_len: int | None = None) -> str:
    """Prepare text for use inside backticks (`code`).

    This function escapes backticks and optionally truncates.
    Newlines are preserved in code blocks.

    Args:
        text: Text to prepare. Can be None or empty.
        max_len: Optional maximum length.

    Returns:
        Text safe for inline code formatting.

    Example:
        f"Session: `{safe_code(session_id)}`"
    """
    if not text:
        return text or ""

    # Escape backticks
    text = text.replace("`", "\\`")

    # Truncate if needed
    if max_len and len(text) > max_len:
        text = text[: max_len - 3] + "..."

    return text


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
        # Escape branch and project_id to avoid markdown issues
        branch_escaped = escape_markdown(s.branch)
        project_escaped = escape_markdown(s.project_id)
        text += f"{state_icon} `{s.session_id}` ({project_escaped})\n"
        text += f"   🌿 {branch_escaped}\n"
        text += f"   ⏱️ {_relative_time(s.last_activity_at)}\n"

        if s.last_summary:
            if len(s.last_summary) > 50:
                summary = s.last_summary[:50] + "..."
            else:
                summary = s.last_summary
            text += f"   📝 {escape_markdown(summary)}\n"

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
    branch_escaped = escape_markdown(session.branch)
    project_escaped = escape_markdown(project_name)

    text = f"📂 {project_escaped} 🔹 {session.session_id} 🌿 {branch_escaped}\n\n"
    text += f"*State*: {state_icon} {session.state.value}\n"
    text += f"*Last Activity*: {_relative_time(session.last_activity_at)}\n"

    if session.last_summary:
        summary = escape_markdown(session.last_summary[:200])
        text += f"\n*Last Summary*:\n{summary}"
        if len(session.last_summary) > 200:
            text += "..."

    if session.attached_task_ids:
        tasks = ", ".join(session.attached_task_ids)
        text += f"\n\n*Attached Tasks*: {escape_markdown(tasks)}"

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
    # Escape all user-provided content
    branch_escaped = escape_markdown(branch)
    project_escaped = escape_markdown(project_id)
    instruction_escaped = escape_markdown(truncated)

    return (
        f"{icon} {session_id} ({project_escaped}/{branch_escaped}): "
        f"{instruction_escaped}"
    )


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
