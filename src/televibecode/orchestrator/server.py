"""MCP server for TeleVibeCode orchestrator."""

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from televibecode.db import Database

# Global database reference (set during server creation)
_db: Database | None = None
_root: Path | None = None


def create_mcp_server(db: Database, root: Path) -> FastMCP:
    """Create and configure the MCP server.

    Args:
        db: Database instance.
        root: Projects root directory.

    Returns:
        Configured FastMCP server.
    """
    global _db, _root
    _db = db
    _root = root

    mcp = FastMCP("TeleVibeCode Orchestrator")

    # Register tools
    _register_project_tools(mcp)
    _register_session_tools(mcp)
    _register_task_tools(mcp)
    _register_job_tools(mcp)
    _register_approval_tools(mcp)
    _register_resources(mcp)

    return mcp


def _register_project_tools(mcp: FastMCP) -> None:
    """Register project management tools."""
    from televibecode.orchestrator.tools import projects

    @mcp.tool()
    async def list_projects() -> str:
        """List all registered projects.

        Returns a JSON array of projects with id, name, path, and status.
        """
        result = await projects.list_projects(_db)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_project(project_id: str) -> str:
        """Get details for a specific project.

        Args:
            project_id: The project identifier (slug).

        Returns project details or error message.
        """
        result = await projects.get_project(_db, project_id)
        if not result:
            return json.dumps({"error": f"Project '{project_id}' not found"})
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def register_project(
        path: str,
        name: str | None = None,
        project_id: str | None = None,
    ) -> str:
        """Register a git repository as a project.

        Args:
            path: Absolute path to the repository.
            name: Display name (optional, defaults to directory name).
            project_id: Project identifier (optional, defaults to slugified name).

        Returns registration result or error.
        """
        try:
            result = await projects.register_project(_db, path, name, project_id)
            return json.dumps(result, indent=2)
        except ValueError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def scan_projects() -> str:
        """Scan the projects root directory for git repositories.

        Automatically registers any git repositories found in the root directory.
        Already registered projects are skipped.

        Returns summary of scan results.
        """
        result = await projects.scan_projects(_db, _root)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def unregister_project(project_id: str) -> str:
        """Unregister a project.

        Args:
            project_id: The project identifier to remove.

        Note: Projects with active sessions cannot be unregistered.
        """
        try:
            result = await projects.unregister_project(_db, project_id)
            return json.dumps(result, indent=2)
        except ValueError as e:
            return json.dumps({"error": str(e)})


def _register_session_tools(mcp: FastMCP) -> None:
    """Register session management tools."""
    from televibecode.orchestrator.tools import sessions

    @mcp.tool()
    async def list_sessions(project_id: str | None = None) -> str:
        """List active sessions.

        Args:
            project_id: Filter by project (optional).

        Returns JSON array of sessions.
        """
        result = await sessions.list_sessions(_db, project_id)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_session(session_id: str) -> str:
        """Get details for a specific session.

        Args:
            session_id: The session identifier (e.g., S12).

        Returns session details or error message.
        """
        result = await sessions.get_session(_db, session_id)
        if not result:
            return json.dumps({"error": f"Session '{session_id}' not found"})
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_session_status(session_id: str) -> str:
        """Get detailed status for a session including git status.

        Args:
            session_id: The session identifier.

        Returns status details or error.
        """
        try:
            result = await sessions.get_session_status(_db, session_id)
            return json.dumps(result, indent=2)
        except ValueError as e:
            return json.dumps({"error": str(e)})


def _register_task_tools(mcp: FastMCP) -> None:
    """Register task management tools."""
    from televibecode.orchestrator.tools import tasks

    @mcp.tool()
    async def list_tasks(
        project_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> str:
        """List tasks for a project.

        Args:
            project_id: Project to list tasks for.
            status: Optional status filter (todo, in_progress, blocked, etc.).
            limit: Maximum tasks to return.

        Returns JSON array of tasks.
        """
        try:
            result = await tasks.list_project_tasks(_db, project_id, status, limit)
            return json.dumps(result, indent=2)
        except ValueError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_next_tasks(project_id: str, limit: int = 5) -> str:
        """Get prioritized next tasks for a project.

        Args:
            project_id: Project ID.
            limit: Maximum tasks to return.

        Returns prioritized tasks ready for work.
        """
        result = await tasks.get_next_tasks(_db, project_id, limit)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def claim_task(task_id: str, session_id: str) -> str:
        """Claim a task for a session.

        Args:
            task_id: Task to claim (e.g., T-123).
            session_id: Session claiming the task (e.g., S12).

        Returns claim result or error.
        """
        try:
            result = await tasks.claim_task(_db, task_id, session_id)
            return json.dumps(result, indent=2)
        except ValueError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def update_task_status(task_id: str, status: str) -> str:
        """Update task status.

        Args:
            task_id: Task to update.
            status: New status (todo, in_progress, blocked, needs_review, done).

        Returns update result or error.
        """
        try:
            result = await tasks.update_task_status(_db, task_id, status)
            return json.dumps(result, indent=2)
        except ValueError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def sync_backlog(project_id: str) -> str:
        """Sync tasks from project's backlog directory.

        Args:
            project_id: Project to sync backlog for.

        Returns sync results with counts.
        """
        try:
            result = await tasks.sync_backlog(_db, project_id)
            return json.dumps(result, indent=2)
        except ValueError as e:
            return json.dumps({"error": str(e)})


def _register_job_tools(mcp: FastMCP) -> None:
    """Register job execution tools."""
    from televibecode.orchestrator.tools import jobs

    @mcp.tool()
    async def list_jobs(
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> str:
        """List jobs.

        Args:
            session_id: Filter by session (optional).
            status: Filter by status (optional).
            limit: Maximum jobs to return.

        Returns JSON array of jobs.
        """
        result = await jobs.list_jobs(_db, session_id, status, limit)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_job(job_id: str) -> str:
        """Get details for a specific job.

        Args:
            job_id: The job identifier.

        Returns job details or error.
        """
        result = await jobs.get_job(_db, job_id)
        if not result:
            return json.dumps({"error": f"Job '{job_id}' not found"})
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_job_logs(job_id: str, tail: int = 50) -> str:
        """Get logs for a job.

        Args:
            job_id: The job identifier.
            tail: Number of lines from end.

        Returns log content or error.
        """
        try:
            result = await jobs.get_job_logs(_db, job_id, tail)
            return json.dumps(result, indent=2)
        except ValueError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def cancel_job(job_id: str) -> str:
        """Cancel a running job.

        Args:
            job_id: The job to cancel.

        Returns cancellation result or error.
        """
        try:
            result = await jobs.cancel_job(_db, job_id)
            return json.dumps(result, indent=2)
        except ValueError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def list_running_jobs() -> str:
        """List all currently running jobs.

        Returns JSON array of running jobs.
        """
        result = await jobs.list_running_jobs(_db)
        return json.dumps(result, indent=2)


def _register_approval_tools(mcp: FastMCP) -> None:
    """Register approval management tools."""
    from televibecode.orchestrator.tools import approvals

    @mcp.tool()
    async def list_pending_approvals(session_id: str | None = None) -> str:
        """List pending approvals.

        Args:
            session_id: Filter by session (optional).

        Returns JSON array of pending approvals.
        """
        result = await approvals.list_pending_approvals(_db, session_id)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_approval(approval_id: str) -> str:
        """Get details for a specific approval.

        Args:
            approval_id: The approval identifier.

        Returns approval details or error.
        """
        result = await approvals.get_approval_detail(_db, approval_id)
        if not result:
            return json.dumps({"error": f"Approval '{approval_id}' not found"})
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def approve_action(approval_id: str, approved_by: str) -> str:
        """Approve a pending action.

        Args:
            approval_id: The approval to approve.
            approved_by: User approving the action.

        Returns approval result or error.
        """
        try:
            result = await approvals.approve_action(_db, approval_id, approved_by)
            return json.dumps(result, indent=2)
        except ValueError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def deny_action(
        approval_id: str, denied_by: str, reason: str | None = None
    ) -> str:
        """Deny a pending action.

        Args:
            approval_id: The approval to deny.
            denied_by: User denying the action.
            reason: Optional denial reason.

        Returns denial result or error.
        """
        try:
            result = await approvals.deny_action(_db, approval_id, denied_by, reason)
            return json.dumps(result, indent=2)
        except ValueError as e:
            return json.dumps({"error": str(e)})


def _register_resources(mcp: FastMCP) -> None:
    """Register MCP resources."""
    from televibecode.orchestrator.tools import projects

    @mcp.resource("projects://list")
    async def projects_resource() -> str:
        """Read-only resource: list of all projects."""
        result = await projects.list_projects(_db)
        return json.dumps(result)

    @mcp.resource("sessions://active")
    async def sessions_resource() -> str:
        """Read-only resource: list of active sessions."""
        sessions = await _db.get_active_sessions()
        return json.dumps(
            [
                {
                    "session_id": s.session_id,
                    "project_id": s.project_id,
                    "branch": s.branch,
                    "state": s.state.value,
                }
                for s in sessions
            ]
        )

    @mcp.resource("jobs://running")
    async def running_jobs_resource() -> str:
        """Read-only resource: list of running jobs."""
        jobs = await _db.get_running_jobs()
        return json.dumps(
            [
                {
                    "job_id": j.job_id,
                    "session_id": j.session_id,
                    "instruction": j.instruction[:100],
                    "started_at": j.started_at.isoformat() if j.started_at else None,
                }
                for j in jobs
            ]
        )

    @mcp.resource("approvals://pending")
    async def pending_approvals_resource() -> str:
        """Read-only resource: list of jobs awaiting approval."""
        jobs = await _db.get_pending_approval_jobs()
        return json.dumps(
            [
                {
                    "job_id": j.job_id,
                    "session_id": j.session_id,
                    "instruction": j.instruction[:100],
                    "approval_scope": j.approval_scope,
                }
                for j in jobs
            ]
        )
