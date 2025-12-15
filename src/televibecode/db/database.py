"""Async SQLite database operations for TeleVibeCode."""

import contextlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from televibecode.db.models import (
    Approval,
    ApprovalState,
    ApprovalType,
    ExecutionMode,
    Job,
    JobStatus,
    Project,
    Session,
    SessionState,
    Task,
    TaskPriority,
    TaskStatus,
)

SCHEMA = """
-- Projects table
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    remote_url TEXT,
    default_branch TEXT DEFAULT 'main',
    backlog_enabled INTEGER DEFAULT 0,
    backlog_path TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Sessions table
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    display_name TEXT,
    workspace_path TEXT NOT NULL UNIQUE,
    branch TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'idle',
    execution_mode TEXT NOT NULL DEFAULT 'worktree',
    superclaude_profile TEXT,
    mcp_profile TEXT,
    attached_task_ids TEXT DEFAULT '[]',
    current_job_id TEXT,
    last_summary TEXT,
    last_diff TEXT,
    open_pr TEXT,
    last_activity_at TEXT DEFAULT (datetime('now')),
    created_at TEXT DEFAULT (datetime('now'))
);

-- Tasks table
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'todo',
    epic TEXT,
    priority TEXT DEFAULT 'medium',
    session_id TEXT REFERENCES sessions(session_id),
    branch TEXT,
    assignee TEXT,
    tags TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Jobs table
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    instruction TEXT NOT NULL,
    raw_input TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    approval_required INTEGER DEFAULT 0,
    approval_scope TEXT,
    approval_state TEXT,
    log_path TEXT,
    result_summary TEXT,
    files_changed TEXT,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT,
    finished_at TEXT
);

-- Approvals table
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    approval_type TEXT NOT NULL,
    action_description TEXT NOT NULL,
    action_details TEXT,
    state TEXT NOT NULL DEFAULT 'pending',
    approved_by TEXT,
    approved_at TEXT,
    telegram_message_id INTEGER,
    telegram_chat_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

-- User preferences table (for Telegram users)
CREATE TABLE IF NOT EXISTS user_preferences (
    chat_id INTEGER PRIMARY KEY,
    ai_model_id TEXT,
    ai_provider TEXT,
    active_session_id TEXT,
    notifications_enabled INTEGER DEFAULT 1,
    tracker_preset TEXT DEFAULT 'normal',
    tracker_config TEXT DEFAULT '{}',
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_state ON sessions(state);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_approvals_job ON approvals(job_id);
CREATE INDEX IF NOT EXISTS idx_approvals_state ON approvals(state);
"""


class Database:
    """Async SQLite database manager."""

    def __init__(self, db_path: Path):
        """Initialize database manager.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Connect to database and initialize schema."""
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row

        # Enable WAL mode and other pragmas
        await self._connection.execute("PRAGMA journal_mode = WAL")
        await self._connection.execute("PRAGMA foreign_keys = ON")
        await self._connection.execute("PRAGMA synchronous = NORMAL")

        # Create schema
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()

        # Run migrations for existing databases
        await self._run_migrations()

    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def _run_migrations(self) -> None:
        """Run database migrations for schema updates."""
        # Add tracker columns to user_preferences if missing
        try:
            async with self.conn.execute(
                "SELECT tracker_preset FROM user_preferences LIMIT 1"
            ):
                pass
        except Exception:
            # Column doesn't exist, add it
            await self.conn.execute(
                "ALTER TABLE user_preferences ADD COLUMN tracker_preset TEXT DEFAULT 'normal'"
            )
            await self.conn.execute(
                "ALTER TABLE user_preferences ADD COLUMN tracker_config TEXT DEFAULT '{}'"
            )
            await self.conn.commit()

        # Add execution_mode column to sessions if missing
        try:
            async with self.conn.execute(
                "SELECT execution_mode FROM sessions LIMIT 1"
            ):
                pass
        except Exception:
            # Column doesn't exist, add it
            await self.conn.execute(
                "ALTER TABLE sessions ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'worktree'"
            )
            await self.conn.commit()

    @property
    def conn(self) -> aiosqlite.Connection:
        """Get active connection."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        return self._connection

    # =========================================================================
    # Project CRUD
    # =========================================================================

    async def create_project(self, project: Project) -> Project:
        """Create a new project."""
        await self.conn.execute(
            """
            INSERT INTO projects (
                project_id, name, path, remote_url, default_branch,
                backlog_enabled, backlog_path, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project.project_id,
                project.name,
                project.path,
                project.remote_url,
                project.default_branch,
                1 if project.backlog_enabled else 0,
                project.backlog_path,
                project.created_at.isoformat(),
                project.updated_at.isoformat(),
            ),
        )
        await self.conn.commit()
        return project

    async def get_project(self, project_id: str) -> Project | None:
        """Get a project by ID."""
        async with self.conn.execute(
            "SELECT * FROM projects WHERE project_id = ?",
            (project_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_project(row)
            return None

    async def get_project_by_path(self, path: str) -> Project | None:
        """Get a project by path."""
        async with self.conn.execute(
            "SELECT * FROM projects WHERE path = ?",
            (path,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_project(row)
            return None

    async def get_all_projects(self) -> list[Project]:
        """Get all projects."""
        async with self.conn.execute("SELECT * FROM projects ORDER BY name") as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_project(row) for row in rows]

    async def update_project(self, project: Project) -> Project:
        """Update an existing project."""
        project.updated_at = datetime.now(timezone.utc)
        await self.conn.execute(
            """
            UPDATE projects SET
                name = ?, path = ?, remote_url = ?, default_branch = ?,
                backlog_enabled = ?, backlog_path = ?, updated_at = ?
            WHERE project_id = ?
            """,
            (
                project.name,
                project.path,
                project.remote_url,
                project.default_branch,
                1 if project.backlog_enabled else 0,
                project.backlog_path,
                project.updated_at.isoformat(),
                project.project_id,
            ),
        )
        await self.conn.commit()
        return project

    async def delete_project(self, project_id: str) -> bool:
        """Delete a project."""
        cursor = await self.conn.execute(
            "DELETE FROM projects WHERE project_id = ?",
            (project_id,),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    def _row_to_project(self, row: aiosqlite.Row) -> Project:
        """Convert database row to Project model."""
        return Project(
            project_id=row["project_id"],
            name=row["name"],
            path=row["path"],
            remote_url=row["remote_url"],
            default_branch=row["default_branch"],
            backlog_enabled=bool(row["backlog_enabled"]),
            backlog_path=row["backlog_path"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # =========================================================================
    # Session CRUD
    # =========================================================================

    async def create_session(self, session: Session) -> Session:
        """Create a new session."""
        await self.conn.execute(
            """
            INSERT INTO sessions (
                session_id, project_id, display_name, workspace_path, branch,
                state, execution_mode, superclaude_profile, mcp_profile,
                attached_task_ids, current_job_id, last_summary, last_diff,
                open_pr, last_activity_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                session.project_id,
                session.display_name,
                session.workspace_path,
                session.branch,
                session.state.value,
                session.execution_mode.value,
                session.superclaude_profile,
                session.mcp_profile,
                json.dumps(session.attached_task_ids),
                session.current_job_id,
                session.last_summary,
                session.last_diff,
                session.open_pr,
                session.last_activity_at.isoformat(),
                session.created_at.isoformat(),
            ),
        )
        await self.conn.commit()
        return session

    async def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        async with self.conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_session(row)
            return None

    async def get_sessions_by_project(self, project_id: str) -> list[Session]:
        """Get all sessions for a project."""
        async with self.conn.execute(
            "SELECT * FROM sessions WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_session(row) for row in rows]

    async def get_all_sessions(self) -> list[Session]:
        """Get all sessions."""
        async with self.conn.execute(
            "SELECT * FROM sessions ORDER BY last_activity_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_session(row) for row in rows]

    async def get_active_sessions(self) -> list[Session]:
        """Get sessions that are not closing."""
        async with self.conn.execute(
            """
            SELECT * FROM sessions
            WHERE state != 'closing'
            ORDER BY last_activity_at DESC
            """
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_session(row) for row in rows]

    async def update_session(self, session: Session) -> Session:
        """Update an existing session."""
        session.last_activity_at = datetime.now(timezone.utc)
        await self.conn.execute(
            """
            UPDATE sessions SET
                display_name = ?, workspace_path = ?, branch = ?, state = ?,
                execution_mode = ?, superclaude_profile = ?, mcp_profile = ?,
                attached_task_ids = ?, current_job_id = ?, last_summary = ?,
                last_diff = ?, open_pr = ?, last_activity_at = ?
            WHERE session_id = ?
            """,
            (
                session.display_name,
                session.workspace_path,
                session.branch,
                session.state.value,
                session.execution_mode.value,
                session.superclaude_profile,
                session.mcp_profile,
                json.dumps(session.attached_task_ids),
                session.current_job_id,
                session.last_summary,
                session.last_diff,
                session.open_pr,
                session.last_activity_at.isoformat(),
                session.session_id,
            ),
        )
        await self.conn.commit()
        return session

    async def update_session_state(self, session_id: str, state: SessionState) -> bool:
        """Update session state."""
        cursor = await self.conn.execute(
            """
            UPDATE sessions SET state = ?, last_activity_at = ?
            WHERE session_id = ?
            """,
            (state.value, datetime.now(timezone.utc).isoformat(), session_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        cursor = await self.conn.execute(
            "DELETE FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def get_next_session_number(self) -> int:
        """Get next session number for ID generation."""
        async with self.conn.execute(
            "SELECT MAX(CAST(SUBSTR(session_id, 2) AS INTEGER)) FROM sessions"
        ) as cursor:
            row = await cursor.fetchone()
            max_num = row[0] if row and row[0] else 0
            return max_num + 1

    def _row_to_session(self, row: aiosqlite.Row) -> Session:
        """Convert database row to Session model."""
        return Session(
            session_id=row["session_id"],
            project_id=row["project_id"],
            display_name=row["display_name"],
            workspace_path=row["workspace_path"],
            branch=row["branch"],
            state=SessionState(row["state"]),
            execution_mode=ExecutionMode(row["execution_mode"] or "worktree"),
            superclaude_profile=row["superclaude_profile"],
            mcp_profile=row["mcp_profile"],
            attached_task_ids=json.loads(row["attached_task_ids"] or "[]"),
            current_job_id=row["current_job_id"],
            last_summary=row["last_summary"],
            last_diff=row["last_diff"],
            open_pr=row["open_pr"],
            last_activity_at=datetime.fromisoformat(row["last_activity_at"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # =========================================================================
    # Task CRUD
    # =========================================================================

    async def create_task(self, task: Task) -> Task:
        """Create a new task."""
        await self.conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, title, description, status, epic,
                priority, session_id, branch, assignee, tags,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                task.project_id,
                task.title,
                task.description,
                task.status.value,
                task.epic,
                task.priority.value,
                task.session_id,
                task.branch,
                task.assignee,
                json.dumps(task.tags),
                task.created_at.isoformat(),
                task.updated_at.isoformat(),
            ),
        )
        await self.conn.commit()
        return task

    async def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        async with self.conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?",
            (task_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_task(row)
            return None

    async def get_tasks_by_project(self, project_id: str) -> list[Task]:
        """Get all tasks for a project."""
        async with self.conn.execute(
            """
            SELECT * FROM tasks
            WHERE project_id = ?
            ORDER BY priority DESC, created_at
            """,
            (project_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    async def get_pending_tasks(self, project_id: str, limit: int = 10) -> list[Task]:
        """Get pending tasks for a project, ordered by priority."""
        async with self.conn.execute(
            """
            SELECT * FROM tasks
            WHERE project_id = ? AND status IN ('todo', 'in_progress')
            ORDER BY
                CASE priority
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                END,
                created_at
            LIMIT ?
            """,
            (project_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    async def update_task(self, task: Task) -> Task:
        """Update an existing task."""
        task.updated_at = datetime.now(timezone.utc)
        await self.conn.execute(
            """
            UPDATE tasks SET
                title = ?, description = ?, status = ?, epic = ?, priority = ?,
                session_id = ?, branch = ?, assignee = ?, tags = ?, updated_at = ?
            WHERE task_id = ?
            """,
            (
                task.title,
                task.description,
                task.status.value,
                task.epic,
                task.priority.value,
                task.session_id,
                task.branch,
                task.assignee,
                json.dumps(task.tags),
                task.updated_at.isoformat(),
                task.task_id,
            ),
        )
        await self.conn.commit()
        return task

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        cursor = await self.conn.execute(
            "DELETE FROM tasks WHERE task_id = ?",
            (task_id,),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    def _row_to_task(self, row: aiosqlite.Row) -> Task:
        """Convert database row to Task model."""
        return Task(
            task_id=row["task_id"],
            project_id=row["project_id"],
            title=row["title"],
            description=row["description"],
            status=TaskStatus(row["status"]),
            epic=row["epic"],
            priority=TaskPriority(row["priority"]),
            session_id=row["session_id"],
            branch=row["branch"],
            assignee=row["assignee"],
            tags=json.loads(row["tags"] or "[]"),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # =========================================================================
    # Job CRUD
    # =========================================================================

    async def create_job(self, job: Job) -> Job:
        """Create a new job."""
        await self.conn.execute(
            """
            INSERT INTO jobs (
                job_id, session_id, project_id, instruction, raw_input,
                status, approval_required, approval_scope, approval_state,
                log_path, result_summary, files_changed, error,
                created_at, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.session_id,
                job.project_id,
                job.instruction,
                job.raw_input,
                job.status.value,
                1 if job.approval_required else 0,
                job.approval_scope,
                job.approval_state.value if job.approval_state else None,
                job.log_path,
                job.result_summary,
                json.dumps(job.files_changed) if job.files_changed else None,
                job.error,
                job.created_at.isoformat(),
                job.started_at.isoformat() if job.started_at else None,
                job.finished_at.isoformat() if job.finished_at else None,
            ),
        )
        await self.conn.commit()
        return job

    async def get_job(self, job_id: str) -> Job | None:
        """Get a job by ID."""
        async with self.conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?",
            (job_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_job(row)
            return None

    async def get_jobs_by_session(self, session_id: str, limit: int = 20) -> list[Job]:
        """Get jobs for a session."""
        async with self.conn.execute(
            """
            SELECT * FROM jobs WHERE session_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (session_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    async def get_running_jobs(self) -> list[Job]:
        """Get all currently running jobs."""
        async with self.conn.execute(
            "SELECT * FROM jobs WHERE status = 'running'"
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    async def get_pending_approval_jobs(self) -> list[Job]:
        """Get jobs waiting for approval."""
        async with self.conn.execute(
            "SELECT * FROM jobs WHERE status = 'waiting_approval'"
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    async def update_job(self, job: Job) -> Job:
        """Update an existing job."""
        await self.conn.execute(
            """
            UPDATE jobs SET
                status = ?, approval_required = ?, approval_scope = ?,
                approval_state = ?, log_path = ?, result_summary = ?,
                files_changed = ?, error = ?, started_at = ?, finished_at = ?
            WHERE job_id = ?
            """,
            (
                job.status.value,
                1 if job.approval_required else 0,
                job.approval_scope,
                job.approval_state.value if job.approval_state else None,
                job.log_path,
                job.result_summary,
                json.dumps(job.files_changed) if job.files_changed else None,
                job.error,
                job.started_at.isoformat() if job.started_at else None,
                job.finished_at.isoformat() if job.finished_at else None,
                job.job_id,
            ),
        )
        await self.conn.commit()
        return job

    async def update_job_status(self, job_id: str, status: JobStatus) -> bool:
        """Update job status."""
        updates: dict[str, Any] = {"status": status.value}

        if status == JobStatus.RUNNING:
            updates["started_at"] = datetime.now(timezone.utc).isoformat()
        elif status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELED):
            updates["finished_at"] = datetime.now(timezone.utc).isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        cursor = await self.conn.execute(
            f"UPDATE jobs SET {set_clause} WHERE job_id = ?",
            (*updates.values(), job_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    def _row_to_job(self, row: aiosqlite.Row) -> Job:
        """Convert database row to Job model."""
        return Job(
            job_id=row["job_id"],
            session_id=row["session_id"],
            project_id=row["project_id"],
            instruction=row["instruction"],
            raw_input=row["raw_input"],
            status=JobStatus(row["status"]),
            approval_required=bool(row["approval_required"]),
            approval_scope=row["approval_scope"],
            approval_state=ApprovalState(row["approval_state"])
            if row["approval_state"]
            else None,
            log_path=row["log_path"],
            result_summary=row["result_summary"],
            files_changed=json.loads(row["files_changed"])
            if row["files_changed"]
            else None,
            error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"])
            if row["started_at"]
            else None,
            finished_at=datetime.fromisoformat(row["finished_at"])
            if row["finished_at"]
            else None,
        )

    # =========================================================================
    # Approval CRUD
    # =========================================================================

    async def create_approval(self, approval: Approval) -> Approval:
        """Create a new approval request."""
        await self.conn.execute(
            """
            INSERT INTO approvals (
                approval_id, job_id, session_id, project_id, approval_type,
                action_description, action_details, state, approved_by,
                approved_at, telegram_message_id, telegram_chat_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval.approval_id,
                approval.job_id,
                approval.session_id,
                approval.project_id,
                approval.approval_type.value,
                approval.action_description,
                json.dumps(approval.action_details)
                if approval.action_details
                else None,
                approval.state.value,
                approval.approved_by,
                approval.approved_at.isoformat() if approval.approved_at else None,
                approval.telegram_message_id,
                approval.telegram_chat_id,
                approval.created_at.isoformat(),
            ),
        )
        await self.conn.commit()
        return approval

    async def get_approval(self, approval_id: str) -> Approval | None:
        """Get an approval by ID."""
        async with self.conn.execute(
            "SELECT * FROM approvals WHERE approval_id = ?",
            (approval_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_approval(row)
            return None

    async def get_approval_by_job(self, job_id: str) -> Approval | None:
        """Get pending approval for a job."""
        async with self.conn.execute(
            "SELECT * FROM approvals WHERE job_id = ? AND state = 'pending'",
            (job_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_approval(row)
            return None

    async def get_pending_approvals(self) -> list[Approval]:
        """Get all pending approvals."""
        async with self.conn.execute(
            "SELECT * FROM approvals WHERE state = 'pending' ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_approval(row) for row in rows]

    async def get_approvals_by_session(self, session_id: str) -> list[Approval]:
        """Get approvals for a session."""
        async with self.conn.execute(
            "SELECT * FROM approvals WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_approval(row) for row in rows]

    async def update_approval(self, approval: Approval) -> Approval:
        """Update an approval."""
        await self.conn.execute(
            """
            UPDATE approvals SET
                state = ?, approved_by = ?, approved_at = ?,
                telegram_message_id = ?, telegram_chat_id = ?
            WHERE approval_id = ?
            """,
            (
                approval.state.value,
                approval.approved_by,
                approval.approved_at.isoformat() if approval.approved_at else None,
                approval.telegram_message_id,
                approval.telegram_chat_id,
                approval.approval_id,
            ),
        )
        await self.conn.commit()
        return approval

    async def approve(self, approval_id: str, approved_by: str) -> Approval | None:
        """Approve an approval request."""
        approval = await self.get_approval(approval_id)
        if not approval:
            return None

        approval.state = ApprovalState.APPROVED
        approval.approved_by = approved_by
        approval.approved_at = datetime.now(timezone.utc)
        return await self.update_approval(approval)

    async def deny(self, approval_id: str, denied_by: str) -> Approval | None:
        """Deny an approval request."""
        approval = await self.get_approval(approval_id)
        if not approval:
            return None

        approval.state = ApprovalState.DENIED
        approval.approved_by = denied_by
        approval.approved_at = datetime.now(timezone.utc)
        return await self.update_approval(approval)

    def _row_to_approval(self, row: aiosqlite.Row) -> Approval:
        """Convert database row to Approval model."""
        return Approval(
            approval_id=row["approval_id"],
            job_id=row["job_id"],
            session_id=row["session_id"],
            project_id=row["project_id"],
            approval_type=ApprovalType(row["approval_type"]),
            action_description=row["action_description"],
            action_details=json.loads(row["action_details"])
            if row["action_details"]
            else None,
            state=ApprovalState(row["state"]),
            approved_by=row["approved_by"],
            approved_at=datetime.fromisoformat(row["approved_at"])
            if row["approved_at"]
            else None,
            telegram_message_id=row["telegram_message_id"],
            telegram_chat_id=row["telegram_chat_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # =========================================================================
    # User Preferences
    # =========================================================================

    async def get_user_preferences(
        self, chat_id: int
    ) -> dict[str, Any] | None:
        """Get user preferences by Telegram chat ID.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            Dict with preferences or None if not found.
        """
        async with self.conn.execute(
            "SELECT * FROM user_preferences WHERE chat_id = ?",
            (chat_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                # Parse tracker_config JSON
                tracker_config = {}
                if row["tracker_config"]:
                    with contextlib.suppress(json.JSONDecodeError):
                        tracker_config = json.loads(row["tracker_config"])

                return {
                    "chat_id": row["chat_id"],
                    "ai_model_id": row["ai_model_id"],
                    "ai_provider": row["ai_provider"],
                    "active_session_id": row["active_session_id"],
                    "notifications_enabled": bool(row["notifications_enabled"]),
                    "tracker_preset": row["tracker_preset"] or "normal",
                    "tracker_config": tracker_config,
                }
            return None

    async def set_user_ai_model(
        self, chat_id: int, model_id: str, provider: str
    ) -> None:
        """Set user's preferred AI model.

        Args:
            chat_id: Telegram chat ID.
            model_id: Model ID.
            provider: Provider name ("openrouter" or "gemini").
        """
        now = datetime.now(timezone.utc).isoformat()
        await self.conn.execute(
            """
            INSERT INTO user_preferences (chat_id, ai_model_id, ai_provider, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                ai_model_id = excluded.ai_model_id,
                ai_provider = excluded.ai_provider,
                updated_at = excluded.updated_at
            """,
            (chat_id, model_id, provider, now),
        )
        await self.conn.commit()

    async def set_user_active_session(
        self, chat_id: int, session_id: str | None
    ) -> None:
        """Set user's active session.

        Args:
            chat_id: Telegram chat ID.
            session_id: Session ID or None to clear.
        """
        now = datetime.now(timezone.utc).isoformat()
        await self.conn.execute(
            """
            INSERT INTO user_preferences (chat_id, active_session_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                active_session_id = excluded.active_session_id,
                updated_at = excluded.updated_at
            """,
            (chat_id, session_id, now),
        )
        await self.conn.commit()

    async def set_user_notifications(
        self, chat_id: int, enabled: bool
    ) -> None:
        """Set user's notification preference.

        Args:
            chat_id: Telegram chat ID.
            enabled: Whether notifications are enabled.
        """
        now = datetime.now(timezone.utc).isoformat()
        await self.conn.execute(
            """
            INSERT INTO user_preferences (chat_id, notifications_enabled, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                notifications_enabled = excluded.notifications_enabled,
                updated_at = excluded.updated_at
            """,
            (chat_id, 1 if enabled else 0, now),
        )
        await self.conn.commit()

    async def get_tracker_config(
        self, chat_id: int
    ) -> tuple[str, dict[str, Any]]:
        """Get tracker config for a chat.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            Tuple of (preset_name, config_overrides).
        """
        async with self.conn.execute(
            "SELECT tracker_preset, tracker_config FROM user_preferences WHERE chat_id = ?",
            (chat_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                preset = row["tracker_preset"] or "normal"
                config = {}
                if row["tracker_config"]:
                    with contextlib.suppress(json.JSONDecodeError):
                        config = json.loads(row["tracker_config"])
                return preset, config
            return "normal", {}

    async def set_tracker_preset(
        self, chat_id: int, preset: str
    ) -> None:
        """Set tracker preset for a chat.

        Args:
            chat_id: Telegram chat ID.
            preset: Preset name.
        """
        now = datetime.now(timezone.utc).isoformat()
        await self.conn.execute(
            """
            INSERT INTO user_preferences (chat_id, tracker_preset, tracker_config, updated_at)
            VALUES (?, ?, '{}', ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                tracker_preset = excluded.tracker_preset,
                tracker_config = '{}',
                updated_at = excluded.updated_at
            """,
            (chat_id, preset, now),
        )
        await self.conn.commit()

    async def update_tracker_config(
        self, chat_id: int, key: str, value: Any
    ) -> None:
        """Update a single tracker config setting.

        Args:
            chat_id: Telegram chat ID.
            key: Config key.
            value: Config value.
        """
        # Get current config
        _, current_config = await self.get_tracker_config(chat_id)
        current_config[key] = value
        config_json = json.dumps(current_config)

        now = datetime.now(timezone.utc).isoformat()
        await self.conn.execute(
            """
            INSERT INTO user_preferences (chat_id, tracker_config, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                tracker_config = excluded.tracker_config,
                updated_at = excluded.updated_at
            """,
            (chat_id, config_json, now),
        )
        await self.conn.commit()

    async def set_tracker_config(
        self, chat_id: int, config: dict[str, Any]
    ) -> None:
        """Set full tracker config for a chat.

        Args:
            chat_id: Telegram chat ID.
            config: Full config dict.
        """
        config_json = json.dumps(config)
        now = datetime.now(timezone.utc).isoformat()
        await self.conn.execute(
            """
            INSERT INTO user_preferences (chat_id, tracker_config, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                tracker_config = excluded.tracker_config,
                updated_at = excluded.updated_at
            """,
            (chat_id, config_json, now),
        )
        await self.conn.commit()
