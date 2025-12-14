"""Pydantic models for TeleVibeCode entities."""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class SessionState(str, Enum):
    """Session state enumeration."""

    IDLE = "idle"
    RUNNING = "running"
    BLOCKED = "blocked"
    CLOSING = "closing"


class TaskStatus(str, Enum):
    """Task status enumeration."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    NEEDS_REVIEW = "needs_review"
    DONE = "done"


class TaskPriority(str, Enum):
    """Task priority enumeration."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class JobStatus(str, Enum):
    """Job status enumeration."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


class ApprovalState(str, Enum):
    """Approval state enumeration."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class Project(BaseModel):
    """Represents a git repository managed by the orchestrator."""

    project_id: str = Field(..., pattern=r"^[a-z0-9-]+$")
    name: str
    path: str
    remote_url: str | None = None
    default_branch: str = "main"
    backlog_enabled: bool = False
    backlog_path: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class Session(BaseModel):
    """Represents an active Claude Code workspace on a specific branch."""

    session_id: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$")
    project_id: str
    display_name: str | None = None
    workspace_path: str
    branch: str
    state: SessionState = SessionState.IDLE
    superclaude_profile: str | None = None
    mcp_profile: str | None = None
    attached_task_ids: list[str] = Field(default_factory=list)
    current_job_id: str | None = None
    last_summary: str | None = None
    last_diff: str | None = None
    open_pr: str | None = None
    last_activity_at: datetime = Field(default_factory=_utc_now)
    created_at: datetime = Field(default_factory=_utc_now)


class Task(BaseModel):
    """Represents a backlog item (from Backlog.md or similar)."""

    task_id: str
    project_id: str
    title: str
    description: str | None = None
    status: TaskStatus = TaskStatus.TODO
    epic: str | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    session_id: str | None = None
    branch: str | None = None
    assignee: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class Job(BaseModel):
    """Represents a unit of work executed in a session."""

    job_id: str
    session_id: str
    project_id: str
    instruction: str
    raw_input: str
    status: JobStatus = JobStatus.QUEUED
    approval_required: bool = False
    approval_scope: str | None = None
    approval_state: ApprovalState | None = None
    log_path: str | None = None
    result_summary: str | None = None
    files_changed: list[str] | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ApprovalType(str, Enum):
    """Type of action requiring approval."""

    SHELL_COMMAND = "shell_command"
    FILE_WRITE = "file_write"
    GIT_PUSH = "git_push"
    DEPLOY = "deploy"
    DANGEROUS_EDIT = "dangerous_edit"
    EXTERNAL_REQUEST = "external_request"


class Approval(BaseModel):
    """Represents an approval request for a gated action."""

    approval_id: str
    job_id: str
    session_id: str
    project_id: str
    approval_type: ApprovalType
    action_description: str
    action_details: dict | None = None
    state: ApprovalState = ApprovalState.PENDING
    approved_by: str | None = None
    approved_at: datetime | None = None
    telegram_message_id: int | None = None
    telegram_chat_id: int | None = None
    created_at: datetime = Field(default_factory=_utc_now)
