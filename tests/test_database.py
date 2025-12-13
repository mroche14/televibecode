"""Tests for the database layer."""

import pytest

from televibecode.db import (
    Approval,
    ApprovalState,
    ApprovalType,
    Database,
    Job,
    JobStatus,
    Project,
    Session,
    SessionState,
    Task,
    TaskPriority,
    TaskStatus,
)


@pytest.fixture
async def db():
    """Create an in-memory database for testing."""
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def sample_project(db: Database) -> Project:
    """Create a sample project."""
    project = Project(
        project_id="test-project",
        name="Test Project",
        path="/tmp/test-project",
        remote_url="https://github.com/test/test-project",
        default_branch="main",
    )
    await db.create_project(project)
    return project


@pytest.fixture
async def sample_session(db: Database, sample_project: Project) -> Session:
    """Create a sample session."""
    session = Session(
        session_id="S1",
        project_id=sample_project.project_id,
        display_name="Test Session",
        workspace_path="/tmp/workspaces/S1",
        branch="televibe/S1",
        state=SessionState.IDLE,
    )
    await db.create_session(session)
    return session


class TestProjectCRUD:
    """Test project CRUD operations."""

    async def test_create_project(self, db: Database):
        """Test creating a project."""
        project = Project(
            project_id="my-project",
            name="My Project",
            path="/home/user/my-project",
            default_branch="main",
        )
        result = await db.create_project(project)
        assert result.project_id == "my-project"

    async def test_get_project(self, db: Database, sample_project: Project):
        """Test retrieving a project."""
        project = await db.get_project(sample_project.project_id)
        assert project is not None
        assert project.name == "Test Project"

    async def test_get_nonexistent_project(self, db: Database):
        """Test retrieving a nonexistent project."""
        project = await db.get_project("nonexistent")
        assert project is None

    async def test_get_all_projects(self, db: Database, sample_project: Project):
        """Test listing all projects."""
        projects = await db.get_all_projects()
        assert len(projects) == 1
        assert projects[0].project_id == sample_project.project_id

    async def test_update_project(self, db: Database, sample_project: Project):
        """Test updating a project."""
        sample_project.name = "Updated Name"
        await db.update_project(sample_project)

        project = await db.get_project(sample_project.project_id)
        assert project.name == "Updated Name"

    async def test_delete_project(self, db: Database, sample_project: Project):
        """Test deleting a project."""
        await db.delete_project(sample_project.project_id)
        project = await db.get_project(sample_project.project_id)
        assert project is None


class TestSessionCRUD:
    """Test session CRUD operations."""

    async def test_create_session(self, db: Database, sample_project: Project):
        """Test creating a session."""
        session = Session(
            session_id="S2",
            project_id=sample_project.project_id,
            workspace_path="/tmp/workspaces/S2",
            branch="televibe/S2",
        )
        result = await db.create_session(session)
        assert result.session_id == "S2"

    async def test_get_session(self, db: Database, sample_session: Session):
        """Test retrieving a session."""
        session = await db.get_session(sample_session.session_id)
        assert session is not None
        assert session.display_name == "Test Session"

    async def test_get_active_sessions(self, db: Database, sample_session: Session):
        """Test listing active sessions."""
        sessions = await db.get_active_sessions()
        assert len(sessions) == 1

    async def test_update_session_state(self, db: Database, sample_session: Session):
        """Test updating session state."""
        result = await db.update_session_state(
            sample_session.session_id, SessionState.RUNNING
        )
        assert result is True

        session = await db.get_session(sample_session.session_id)
        assert session.state == SessionState.RUNNING

    async def test_get_next_session_number(self, db: Database, sample_project: Project):
        """Test getting next session number."""
        # First session
        num1 = await db.get_next_session_number()
        assert num1 == 1

        # Create a session
        session = Session(
            session_id="S1",
            project_id=sample_project.project_id,
            workspace_path="/tmp/workspaces/S1",
            branch="televibe/S1",
        )
        await db.create_session(session)

        # Next session should be 2
        num2 = await db.get_next_session_number()
        assert num2 == 2


class TestTaskCRUD:
    """Test task CRUD operations."""

    async def test_create_task(self, db: Database, sample_project: Project):
        """Test creating a task."""
        task = Task(
            task_id="T-001",
            project_id=sample_project.project_id,
            title="Implement feature",
            description="Add new feature",
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
        )
        result = await db.create_task(task)
        assert result.task_id == "T-001"

    async def test_get_task(self, db: Database, sample_project: Project):
        """Test retrieving a task."""
        task = Task(
            task_id="T-002",
            project_id=sample_project.project_id,
            title="Fix bug",
            status=TaskStatus.TODO,
        )
        await db.create_task(task)

        retrieved = await db.get_task("T-002")
        assert retrieved is not None
        assert retrieved.title == "Fix bug"

    async def test_get_tasks_by_project(self, db: Database, sample_project: Project):
        """Test getting tasks by project."""
        for i in range(3):
            task = Task(
                task_id=f"T-{i:03d}",
                project_id=sample_project.project_id,
                title=f"Task {i}",
            )
            await db.create_task(task)

        tasks = await db.get_tasks_by_project(sample_project.project_id)
        assert len(tasks) == 3

    async def test_get_pending_tasks(self, db: Database, sample_project: Project):
        """Test getting pending tasks with priority ordering."""
        # Create tasks with different priorities
        high = Task(
            task_id="T-HIGH",
            project_id=sample_project.project_id,
            title="High priority",
            priority=TaskPriority.HIGH,
        )
        low = Task(
            task_id="T-LOW",
            project_id=sample_project.project_id,
            title="Low priority",
            priority=TaskPriority.LOW,
        )
        await db.create_task(high)
        await db.create_task(low)

        pending = await db.get_pending_tasks(sample_project.project_id)
        assert len(pending) == 2
        # High priority should be first
        assert pending[0].priority == TaskPriority.HIGH


class TestJobCRUD:
    """Test job CRUD operations."""

    async def test_create_job(self, db: Database, sample_session: Session):
        """Test creating a job."""
        job = Job(
            job_id="job-001",
            session_id=sample_session.session_id,
            project_id=sample_session.project_id,
            instruction="Add tests",
            raw_input="Add tests for the database module",
        )
        result = await db.create_job(job)
        assert result.job_id == "job-001"

    async def test_get_job(self, db: Database, sample_session: Session):
        """Test retrieving a job."""
        job = Job(
            job_id="job-002",
            session_id=sample_session.session_id,
            project_id=sample_session.project_id,
            instruction="Fix bug",
            raw_input="Fix the authentication bug",
        )
        await db.create_job(job)

        retrieved = await db.get_job("job-002")
        assert retrieved is not None
        assert retrieved.instruction == "Fix bug"

    async def test_get_jobs_by_session(self, db: Database, sample_session: Session):
        """Test getting jobs by session."""
        for i in range(5):
            job = Job(
                job_id=f"job-{i:03d}",
                session_id=sample_session.session_id,
                project_id=sample_session.project_id,
                instruction=f"Task {i}",
                raw_input=f"Do task {i}",
            )
            await db.create_job(job)

        jobs = await db.get_jobs_by_session(sample_session.session_id, limit=3)
        assert len(jobs) == 3

    async def test_get_running_jobs(self, db: Database, sample_session: Session):
        """Test getting running jobs."""
        job = Job(
            job_id="running-job",
            session_id=sample_session.session_id,
            project_id=sample_session.project_id,
            instruction="Long task",
            raw_input="Run long task",
            status=JobStatus.RUNNING,
        )
        await db.create_job(job)

        running = await db.get_running_jobs()
        assert len(running) == 1
        assert running[0].job_id == "running-job"


class TestApprovalCRUD:
    """Test approval CRUD operations."""

    async def test_create_approval(self, db: Database, sample_session: Session):
        """Test creating an approval."""
        # First create a job
        job = Job(
            job_id="job-approval",
            session_id=sample_session.session_id,
            project_id=sample_session.project_id,
            instruction="Deploy",
            raw_input="Deploy to production",
        )
        await db.create_job(job)

        approval = Approval(
            approval_id="approval-001",
            job_id=job.job_id,
            session_id=sample_session.session_id,
            project_id=sample_session.project_id,
            approval_type=ApprovalType.DEPLOY,
            action_description="Deploy to production server",
        )
        result = await db.create_approval(approval)
        assert result.approval_id == "approval-001"

    async def test_get_pending_approvals(self, db: Database, sample_session: Session):
        """Test getting pending approvals."""
        # Create job and approval
        job = Job(
            job_id="job-pending",
            session_id=sample_session.session_id,
            project_id=sample_session.project_id,
            instruction="Push",
            raw_input="Git push",
        )
        await db.create_job(job)

        approval = Approval(
            approval_id="approval-pending",
            job_id=job.job_id,
            session_id=sample_session.session_id,
            project_id=sample_session.project_id,
            approval_type=ApprovalType.GIT_PUSH,
            action_description="Push changes to remote",
        )
        await db.create_approval(approval)

        pending = await db.get_pending_approvals()
        assert len(pending) == 1

    async def test_approve_approval(self, db: Database, sample_session: Session):
        """Test approving an approval."""
        job = Job(
            job_id="job-to-approve",
            session_id=sample_session.session_id,
            project_id=sample_session.project_id,
            instruction="Shell",
            raw_input="Run shell command",
        )
        await db.create_job(job)

        approval = Approval(
            approval_id="approval-to-approve",
            job_id=job.job_id,
            session_id=sample_session.session_id,
            project_id=sample_session.project_id,
            approval_type=ApprovalType.SHELL_COMMAND,
            action_description="Run rm -rf",
        )
        await db.create_approval(approval)

        result = await db.approve("approval-to-approve", "admin")
        assert result is not None
        assert result.state == ApprovalState.APPROVED
        assert result.approved_by == "admin"

    async def test_deny_approval(self, db: Database, sample_session: Session):
        """Test denying an approval."""
        job = Job(
            job_id="job-to-deny",
            session_id=sample_session.session_id,
            project_id=sample_session.project_id,
            instruction="Dangerous",
            raw_input="Do dangerous thing",
        )
        await db.create_job(job)

        approval = Approval(
            approval_id="approval-to-deny",
            job_id=job.job_id,
            session_id=sample_session.session_id,
            project_id=sample_session.project_id,
            approval_type=ApprovalType.DANGEROUS_EDIT,
            action_description="Delete all files",
        )
        await db.create_approval(approval)

        result = await db.deny("approval-to-deny", "admin")
        assert result is not None
        assert result.state == ApprovalState.DENIED
