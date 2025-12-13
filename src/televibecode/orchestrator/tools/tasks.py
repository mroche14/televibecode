"""MCP tools for task management."""

from pathlib import Path

from televibecode.backlog import scan_backlog_directory, task_to_markdown
from televibecode.db import Database, TaskStatus


async def sync_backlog(
    db: Database,
    project_id: str,
) -> dict:
    """Sync tasks from project's backlog directory.

    Args:
        db: Database instance.
        project_id: Project to sync.

    Returns:
        Sync result with counts.
    """
    project = await db.get_project(project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found")

    if not project.backlog_enabled or not project.backlog_path:
        raise ValueError(f"Project '{project_id}' does not have backlog enabled")

    backlog_path = Path(project.backlog_path)
    if not backlog_path.exists():
        raise ValueError(f"Backlog path does not exist: {backlog_path}")

    # Parse tasks from backlog
    parsed_tasks = scan_backlog_directory(backlog_path, project_id)

    # Get existing tasks
    existing_tasks = await db.get_tasks_by_project(project_id)
    existing_ids = {t.task_id for t in existing_tasks}

    created = 0
    updated = 0
    unchanged = 0

    for task in parsed_tasks:
        if task.task_id in existing_ids:
            # Update existing task
            existing = await db.get_task(task.task_id)
            if existing:
                # Only update if changed
                if (
                    existing.title != task.title
                    or existing.status != task.status
                    or existing.priority != task.priority
                ):
                    existing.title = task.title
                    existing.description = task.description
                    existing.status = task.status
                    existing.priority = task.priority
                    existing.epic = task.epic
                    existing.assignee = task.assignee
                    existing.tags = task.tags
                    await db.update_task(existing)
                    updated += 1
                else:
                    unchanged += 1
        else:
            # Create new task
            await db.create_task(task)
            created += 1

    return {
        "project_id": project_id,
        "backlog_path": str(backlog_path),
        "found": len(parsed_tasks),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
    }


async def list_project_tasks(
    db: Database,
    project_id: str,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List tasks for a project.

    Args:
        db: Database instance.
        project_id: Project ID.
        status: Optional status filter.
        limit: Maximum tasks to return.

    Returns:
        List of task dictionaries.
    """
    if status:
        try:
            status_enum = TaskStatus(status)
        except ValueError:
            valid = [s.value for s in TaskStatus]
            raise ValueError(f"Invalid status '{status}'. Valid: {valid}") from None
        tasks = await db.get_tasks_by_project(project_id)
        tasks = [t for t in tasks if t.status == status_enum][:limit]
    else:
        tasks = await db.get_tasks_by_project(project_id)
        tasks = tasks[:limit]

    return [
        {
            "task_id": t.task_id,
            "title": t.title,
            "status": t.status.value,
            "priority": t.priority.value,
            "epic": t.epic,
            "session_id": t.session_id,
            "assignee": t.assignee,
        }
        for t in tasks
    ]


async def get_next_tasks(
    db: Database,
    project_id: str,
    limit: int = 5,
) -> list[dict]:
    """Get prioritized next tasks for a project.

    Args:
        db: Database instance.
        project_id: Project ID.
        limit: Maximum tasks to return.

    Returns:
        List of prioritized task dictionaries.
    """
    tasks = await db.get_pending_tasks(project_id, limit=limit)

    return [
        {
            "task_id": t.task_id,
            "title": t.title,
            "status": t.status.value,
            "priority": t.priority.value,
            "epic": t.epic,
            "description": t.description[:200] if t.description else None,
        }
        for t in tasks
    ]


async def claim_task(
    db: Database,
    task_id: str,
    session_id: str,
) -> dict:
    """Claim a task for a session.

    Args:
        db: Database instance.
        task_id: Task to claim.
        session_id: Session claiming the task.

    Returns:
        Result dictionary.
    """
    task = await db.get_task(task_id)
    if not task:
        raise ValueError(f"Task '{task_id}' not found")

    session = await db.get_session(session_id)
    if not session:
        raise ValueError(f"Session '{session_id}' not found")

    # Check if task is already claimed
    if task.session_id and task.session_id != session_id:
        raise ValueError(
            f"Task '{task_id}' already claimed by session '{task.session_id}'"
        )

    # Update task
    task.session_id = session_id
    task.branch = session.branch
    if task.status == TaskStatus.TODO:
        task.status = TaskStatus.IN_PROGRESS
    await db.update_task(task)

    # Update session
    if task_id not in session.attached_task_ids:
        session.attached_task_ids.append(task_id)
        await db.update_session(session)

    return {
        "task_id": task_id,
        "session_id": session_id,
        "title": task.title,
        "status": task.status.value,
        "message": f"Task '{task.title}' claimed by session {session_id}",
    }


async def update_task_status(
    db: Database,
    task_id: str,
    status: str,
) -> dict:
    """Update task status.

    Args:
        db: Database instance.
        task_id: Task to update.
        status: New status value.

    Returns:
        Result dictionary.
    """
    task = await db.get_task(task_id)
    if not task:
        raise ValueError(f"Task '{task_id}' not found")

    try:
        new_status = TaskStatus(status)
    except ValueError:
        valid = [s.value for s in TaskStatus]
        raise ValueError(f"Invalid status '{status}'. Valid: {valid}") from None

    old_status = task.status
    task.status = new_status
    await db.update_task(task)

    return {
        "task_id": task_id,
        "title": task.title,
        "old_status": old_status.value,
        "new_status": new_status.value,
        "message": f"Task status changed from {old_status.value} to {new_status.value}",
    }


async def get_task_detail(
    db: Database,
    task_id: str,
) -> dict | None:
    """Get detailed task information.

    Args:
        db: Database instance.
        task_id: Task ID.

    Returns:
        Task dictionary or None.
    """
    task = await db.get_task(task_id)
    if not task:
        return None

    return {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "epic": task.epic,
        "assignee": task.assignee,
        "tags": task.tags,
        "session_id": task.session_id,
        "branch": task.branch,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


async def write_task_to_backlog(
    db: Database,
    task_id: str,
) -> dict:
    """Write task back to backlog markdown file.

    Args:
        db: Database instance.
        task_id: Task to write.

    Returns:
        Result dictionary.
    """
    task = await db.get_task(task_id)
    if not task:
        raise ValueError(f"Task '{task_id}' not found")

    project = await db.get_project(task.project_id)
    if not project or not project.backlog_path:
        raise ValueError("Project backlog not configured")

    backlog_path = Path(project.backlog_path)
    if not backlog_path.exists():
        raise ValueError(f"Backlog path does not exist: {backlog_path}")

    # Generate filename
    safe_title = "".join(c if c.isalnum() or c in "-_ " else "" for c in task.title)
    safe_title = safe_title.replace(" ", "-").lower()[:50]
    filename = f"{task.task_id}-{safe_title}.md"

    # Write file
    file_path = backlog_path / filename
    content = task_to_markdown(task)
    file_path.write_text(content, encoding="utf-8")

    return {
        "task_id": task_id,
        "file_path": str(file_path),
        "message": f"Task written to {filename}",
    }
