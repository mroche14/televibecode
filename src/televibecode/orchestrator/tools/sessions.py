"""MCP tools for session management."""

import shutil
from pathlib import Path

from televibecode.config import Settings
from televibecode.db import Database, Session, SessionState
from televibecode.orchestrator.tools.git_ops import (
    GitOperations,
    generate_session_branch,
)


async def list_sessions(
    db: Database,
    project_id: str | None = None,
    include_closed: bool = False,
) -> list[dict]:
    """List sessions, optionally filtered by project.

    Args:
        db: Database instance.
        project_id: Optional project filter.
        include_closed: If True, include closing sessions.

    Returns:
        List of session dictionaries.
    """
    if project_id:
        sessions = await db.get_sessions_by_project(project_id)
    elif include_closed:
        sessions = await db.get_all_sessions()
    else:
        sessions = await db.get_active_sessions()

    return [
        {
            "session_id": s.session_id,
            "project_id": s.project_id,
            "display_name": s.display_name,
            "branch": s.branch,
            "state": s.state.value,
            "workspace_path": s.workspace_path,
            "current_job_id": s.current_job_id,
            "last_activity_at": s.last_activity_at.isoformat(),
        }
        for s in sessions
        if include_closed or s.state != SessionState.CLOSING
    ]


async def get_session(db: Database, session_id: str) -> dict | None:
    """Get a session by ID.

    Args:
        db: Database instance.
        session_id: Session identifier (e.g., S12).

    Returns:
        Session dictionary or None if not found.
    """
    session = await db.get_session(session_id)
    if not session:
        return None

    return {
        "session_id": session.session_id,
        "project_id": session.project_id,
        "display_name": session.display_name,
        "workspace_path": session.workspace_path,
        "branch": session.branch,
        "state": session.state.value,
        "superclaude_profile": session.superclaude_profile,
        "mcp_profile": session.mcp_profile,
        "attached_task_ids": session.attached_task_ids,
        "current_job_id": session.current_job_id,
        "last_summary": session.last_summary,
        "last_diff": session.last_diff,
        "open_pr": session.open_pr,
        "last_activity_at": session.last_activity_at.isoformat(),
        "created_at": session.created_at.isoformat(),
    }


async def create_session(
    db: Database,
    settings: Settings,
    project_id: str,
    branch: str | None = None,
    display_name: str | None = None,
) -> dict:
    """Create a new session with a git worktree.

    Args:
        db: Database instance.
        settings: Application settings.
        project_id: Project to create session for.
        branch: Optional branch name (auto-generated if not provided).
        display_name: Optional display name for the session.

    Returns:
        Created session dictionary.

    Raises:
        ValueError: If project not found or creation fails.
    """
    # Get project
    project = await db.get_project(project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found")

    # Generate session ID
    session_number = await db.get_next_session_number()
    session_id = f"S{session_number}"

    # Generate branch name if not provided
    if not branch:
        branch = generate_session_branch(project_id, session_number, display_name)

    # Set up worktree path
    workspace_path = settings.workspaces_dir / session_id
    if workspace_path.exists():
        raise ValueError(f"Workspace path already exists: {workspace_path}")

    # Create git worktree
    git_ops = GitOperations(project.path)

    # Check if branch exists
    branch_exists = git_ops.branch_exists(branch)

    try:
        git_ops.create_worktree(
            worktree_path=workspace_path,
            branch=branch,
            create_branch=not branch_exists,
            base_branch=project.default_branch,
        )
    except Exception as e:
        raise ValueError(f"Failed to create worktree: {e}") from e

    # Create session in database
    session = Session(
        session_id=session_id,
        project_id=project_id,
        display_name=display_name,
        workspace_path=str(workspace_path),
        branch=branch,
        state=SessionState.IDLE,
    )

    await db.create_session(session)

    return {
        "session_id": session.session_id,
        "project_id": project_id,
        "project_name": project.name,
        "display_name": display_name,
        "branch": branch,
        "workspace_path": str(workspace_path),
        "state": session.state.value,
        "message": (
            f"Session {session_id} created for {project.name} on branch {branch}"
        ),
    }


async def close_session(
    db: Database,
    session_id: str,
    force: bool = False,
) -> dict:
    """Close a session and clean up its worktree.

    Args:
        db: Database instance.
        session_id: Session to close.
        force: If True, force close even with uncommitted changes.

    Returns:
        Result dictionary.

    Raises:
        ValueError: If session not found or has running jobs.
    """
    session = await db.get_session(session_id)
    if not session:
        raise ValueError(f"Session '{session_id}' not found")

    # Check for running jobs
    if session.state == SessionState.RUNNING and not force:
        raise ValueError(
            f"Session {session_id} has a running job. "
            "Wait for it to complete or use force=True."
        )

    # Get project for git operations
    project = await db.get_project(session.project_id)
    if not project:
        # Project was deleted, just clean up the session
        workspace_path = Path(session.workspace_path)
        if workspace_path.exists():
            shutil.rmtree(workspace_path)
        await db.delete_session(session_id)
        return {
            "session_id": session_id,
            "closed": True,
            "note": "Project no longer exists, session cleaned up",
        }

    # Remove worktree
    workspace_path = Path(session.workspace_path)
    worktree_removed = False

    if workspace_path.exists():
        git_ops = GitOperations(project.path)
        try:
            git_ops.remove_worktree(workspace_path, force=force)
            worktree_removed = True
        except Exception:
            # Fall back to manual removal
            if force:
                shutil.rmtree(workspace_path)
                worktree_removed = True

    # Update session state
    session.state = SessionState.CLOSING
    await db.update_session(session)

    # Delete session from database
    await db.delete_session(session_id)

    return {
        "session_id": session_id,
        "project_id": session.project_id,
        "branch": session.branch,
        "closed": True,
        "worktree_removed": worktree_removed,
        "message": f"Session {session_id} closed",
    }


async def update_session_state(
    db: Database,
    session_id: str,
    state: str,
) -> dict:
    """Update session state.

    Args:
        db: Database instance.
        session_id: Session to update.
        state: New state (idle, running, blocked, closing).

    Returns:
        Result dictionary.
    """
    try:
        new_state = SessionState(state)
    except ValueError:
        valid = [s.value for s in SessionState]
        raise ValueError(f"Invalid state '{state}'. Valid: {valid}") from None

    success = await db.update_session_state(session_id, new_state)
    if not success:
        raise ValueError(f"Session '{session_id}' not found")

    return {
        "session_id": session_id,
        "state": state,
        "updated": True,
    }


async def get_session_status(
    db: Database,
    session_id: str,
) -> dict:
    """Get detailed session status including git status.

    Args:
        db: Database instance.
        session_id: Session to check.

    Returns:
        Status dictionary with session and git info.
    """
    session = await db.get_session(session_id)
    if not session:
        raise ValueError(f"Session '{session_id}' not found")

    project = await db.get_project(session.project_id)
    if not project:
        raise ValueError(f"Project '{session.project_id}' not found")

    # Get git status
    workspace_path = Path(session.workspace_path)
    git_status = None

    if workspace_path.exists():
        try:
            git_ops = GitOperations(session.workspace_path)
            git_status = git_ops.get_branch_status()
        except Exception as e:
            git_status = {"error": str(e)}

    # Get recent jobs
    jobs = await db.get_jobs_by_session(session_id, limit=5)
    recent_jobs = []
    for j in jobs:
        instr = j.instruction
        if len(instr) > 50:
            instr = instr[:50] + "..."
        recent_jobs.append(
            {
                "job_id": j.job_id,
                "status": j.status.value,
                "instruction": instr,
                "created_at": j.created_at.isoformat(),
            }
        )

    return {
        "session_id": session_id,
        "project_id": session.project_id,
        "project_name": project.name,
        "display_name": session.display_name,
        "branch": session.branch,
        "state": session.state.value,
        "workspace_path": session.workspace_path,
        "git_status": git_status,
        "recent_jobs": recent_jobs,
        "current_job_id": session.current_job_id,
        "last_summary": session.last_summary,
        "attached_tasks": session.attached_task_ids,
    }


async def attach_task(
    db: Database,
    session_id: str,
    task_id: str,
) -> dict:
    """Attach a task to a session.

    Args:
        db: Database instance.
        session_id: Session to attach to.
        task_id: Task to attach.

    Returns:
        Result dictionary.
    """
    session = await db.get_session(session_id)
    if not session:
        raise ValueError(f"Session '{session_id}' not found")

    task = await db.get_task(task_id)
    if not task:
        raise ValueError(f"Task '{task_id}' not found")

    if task_id in session.attached_task_ids:
        return {
            "session_id": session_id,
            "task_id": task_id,
            "attached": False,
            "note": "Task already attached",
        }

    session.attached_task_ids.append(task_id)
    await db.update_session(session)

    # Also update task with session reference
    task.session_id = session_id
    task.branch = session.branch
    await db.update_task(task)

    return {
        "session_id": session_id,
        "task_id": task_id,
        "attached": True,
        "message": f"Task {task_id} attached to session {session_id}",
    }


async def detach_task(
    db: Database,
    session_id: str,
    task_id: str,
) -> dict:
    """Detach a task from a session.

    Args:
        db: Database instance.
        session_id: Session to detach from.
        task_id: Task to detach.

    Returns:
        Result dictionary.
    """
    session = await db.get_session(session_id)
    if not session:
        raise ValueError(f"Session '{session_id}' not found")

    if task_id not in session.attached_task_ids:
        return {
            "session_id": session_id,
            "task_id": task_id,
            "detached": False,
            "note": "Task not attached to this session",
        }

    session.attached_task_ids.remove(task_id)
    await db.update_session(session)

    # Also clear task's session reference
    task = await db.get_task(task_id)
    if task and task.session_id == session_id:
        task.session_id = None
        await db.update_task(task)

    return {
        "session_id": session_id,
        "task_id": task_id,
        "detached": True,
        "message": f"Task {task_id} detached from session {session_id}",
    }
