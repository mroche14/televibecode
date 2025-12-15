"""MCP tools for session management."""

import shutil
from pathlib import Path

from televibecode.config import Settings
from televibecode.db import Database, Session, SessionState
from televibecode.db.models import ExecutionMode
from televibecode.orchestrator.tools.git_ops import GitOperations


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
            "execution_mode": s.execution_mode.value,
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
        "execution_mode": session.execution_mode.value,
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
    execution_mode: ExecutionMode = ExecutionMode.WORKTREE,
) -> dict:
    """Create a new session.

    Args:
        db: Database instance.
        settings: Application settings.
        project_id: Project to create session for.
        branch: Optional branch name (auto-generated if not provided for worktree).
        display_name: Optional display name for the session.
        execution_mode: WORKTREE (isolated worktree) or DIRECT (project folder).

    Returns:
        Created session dictionary.

    Raises:
        ValueError: If project not found or creation fails.
    """
    # Get project
    project = await db.get_project(project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found")

    # Generate session ID: project_YYYYMMDD_HHMMSS
    from datetime import datetime

    now = datetime.now()
    session_id = f"{project_id}_{now.strftime('%Y%m%d_%H%M%S')}"

    git_ops = GitOperations(project.path)

    if execution_mode == ExecutionMode.DIRECT:
        # Direct mode: run in project folder directly
        workspace_path = Path(project.path)

        # Get current branch from the project
        if not branch:
            branch = git_ops.get_current_branch()

        # Check for existing direct sessions on same project
        existing_sessions = await db.get_sessions_by_project(project_id)
        for existing in existing_sessions:
            if (
                existing.execution_mode == ExecutionMode.DIRECT
                and existing.state != SessionState.CLOSING
            ):
                raise ValueError(
                    f"Project '{project_id}' already has an active direct session "
                    f"'{existing.session_id}'. Close it first or use worktree mode."
                )

        # Create session in database
        session = Session(
            session_id=session_id,
            project_id=project_id,
            display_name=display_name,
            workspace_path=str(workspace_path),
            branch=branch,
            state=SessionState.IDLE,
            execution_mode=ExecutionMode.DIRECT,
        )

        await db.create_session(session)

        return {
            "session_id": session.session_id,
            "project_id": project_id,
            "project_name": project.name,
            "display_name": display_name,
            "branch": branch,
            "workspace_path": str(workspace_path),
            "execution_mode": "direct",
            "state": session.state.value,
            "message": (
                f"Session {session_id} created in direct mode for {project.name} "
                f"(running in project folder)"
            ),
        }

    # Worktree mode (default): create isolated git worktree
    # Generate branch name if not provided
    if not branch:
        branch = f"televibe/{session_id}"

    # Check for duplicate branch sessions
    existing_sessions = await db.get_sessions_by_project(project_id)
    for existing in existing_sessions:
        if existing.branch == branch and existing.state != SessionState.CLOSING:
            raise ValueError(
                f"Branch '{branch}' is already in use by session "
                f"'{existing.session_id}'. Close that session first or "
                "use a different branch."
            )

    # Set up worktree path
    workspace_path = settings.workspaces_dir / session_id
    if workspace_path.exists():
        raise ValueError(f"Workspace path already exists: {workspace_path}")

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
        execution_mode=ExecutionMode.WORKTREE,
    )

    await db.create_session(session)

    return {
        "session_id": session.session_id,
        "project_id": project_id,
        "project_name": project.name,
        "display_name": display_name,
        "branch": branch,
        "workspace_path": str(workspace_path),
        "execution_mode": "worktree",
        "state": session.state.value,
        "message": (
            f"Session {session_id} created for {project.name} on branch {branch}"
        ),
    }


async def get_session_branch_status(
    db: Database,
    session_id: str,
) -> dict:
    """Get branch status for a session (for close confirmation).

    Args:
        db: Database instance.
        session_id: Session to check.

    Returns:
        Dictionary with branch status info.
    """
    session = await db.get_session(session_id)
    if not session:
        raise ValueError(f"Session '{session_id}' not found")

    project = await db.get_project(session.project_id)
    if not project:
        return {
            "session_id": session_id,
            "branch": session.branch,
            "project_missing": True,
        }

    # Get branch drift info
    workspace_path = Path(session.workspace_path)
    if not workspace_path.exists():
        return {
            "session_id": session_id,
            "branch": session.branch,
            "workspace_missing": True,
        }

    git_ops = GitOperations(project.path)

    # Get working directory status
    work_status = git_ops.get_branch_status(workspace_path)

    # Get drift from main
    drift = git_ops.get_branch_drift(session.branch, worktree_path=workspace_path)

    return {
        "session_id": session_id,
        "project_id": session.project_id,
        "project_name": project.name,
        "branch": session.branch,
        "has_uncommitted": work_status.get("has_changes", False),
        "uncommitted_count": (
            work_status.get("staged", 0)
            + work_status.get("unstaged", 0)
            + work_status.get("untracked", 0)
        ),
        "ahead_of_main": drift.get("ahead_of_base", 0),
        "behind_main": drift.get("behind_base", 0),
        "is_pushed": drift.get("is_pushed", False),
        "last_commit": drift.get("last_commit", ""),
        "base_branch": drift.get("base_branch", "main"),
    }


async def close_session(
    db: Database,
    session_id: str,
    force: bool = False,
    delete_branch: bool = False,
) -> dict:
    """Close a session and clean up its worktree (if applicable).

    Args:
        db: Database instance.
        session_id: Session to close.
        force: If True, force close even with uncommitted changes.
        delete_branch: If True, also delete the git branch (worktree mode only).

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
        # Only remove workspace if worktree mode
        if session.execution_mode == ExecutionMode.WORKTREE:
            workspace_path = Path(session.workspace_path)
            if workspace_path.exists():
                shutil.rmtree(workspace_path)
        await db.delete_session(session_id)
        return {
            "session_id": session_id,
            "closed": True,
            "note": "Project no longer exists, session cleaned up",
        }

    worktree_removed = False
    branch_deleted = False

    # Only handle worktree cleanup for worktree mode
    if session.execution_mode == ExecutionMode.WORKTREE:
        # Remove worktree
        workspace_path = Path(session.workspace_path)

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

        # Optionally delete the branch (only for worktree sessions)
        if delete_branch and project:
            git_ops = GitOperations(project.path)
            try:
                git_ops.delete_branch(session.branch, force=force)
                branch_deleted = True
            except Exception:
                # Branch deletion failed, but session still closes
                pass

    # Update session state
    session.state = SessionState.CLOSING
    await db.update_session(session)

    # Delete session from database
    await db.delete_session(session_id)

    return {
        "session_id": session_id,
        "project_id": session.project_id,
        "branch": session.branch,
        "execution_mode": session.execution_mode.value,
        "closed": True,
        "worktree_removed": worktree_removed,
        "branch_deleted": branch_deleted,
        "message": f"Session {session_id} closed",
    }


async def push_session_branch(
    db: Database,
    session_id: str,
) -> dict:
    """Push the session's branch to origin.

    Args:
        db: Database instance.
        session_id: Session whose branch to push.

    Returns:
        Dictionary with push result.
    """
    session = await db.get_session(session_id)
    if not session:
        raise ValueError(f"Session '{session_id}' not found")

    project = await db.get_project(session.project_id)
    if not project:
        raise ValueError(f"Project '{session.project_id}' not found")

    git_ops = GitOperations(project.path)
    result = git_ops.push_branch(session.branch)

    return {
        "session_id": session_id,
        "branch": session.branch,
        "pushed": result.get("pushed", False),
        "error": result.get("error"),
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
        "execution_mode": session.execution_mode.value,
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
