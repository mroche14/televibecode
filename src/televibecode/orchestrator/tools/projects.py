"""MCP tools for project management."""

import contextlib
import re
from pathlib import Path

from git import InvalidGitRepositoryError, Repo

from televibecode.db import Database, Project


def slugify(name: str) -> str:
    """Convert name to URL-friendly slug."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


async def list_projects(db: Database) -> list[dict]:
    """List all registered projects.

    Returns:
        List of project dictionaries.
    """
    projects = await db.get_all_projects()
    return [
        {
            "project_id": p.project_id,
            "name": p.name,
            "path": p.path,
            "default_branch": p.default_branch,
            "backlog_enabled": p.backlog_enabled,
        }
        for p in projects
    ]


async def get_project(db: Database, project_id: str) -> dict | None:
    """Get a project by ID.

    Args:
        db: Database instance.
        project_id: Project identifier.

    Returns:
        Project dictionary or None if not found.
    """
    project = await db.get_project(project_id)
    if not project:
        return None

    return {
        "project_id": project.project_id,
        "name": project.name,
        "path": project.path,
        "remote_url": project.remote_url,
        "default_branch": project.default_branch,
        "backlog_enabled": project.backlog_enabled,
        "backlog_path": project.backlog_path,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


async def register_project(
    db: Database,
    path: str,
    name: str | None = None,
    project_id: str | None = None,
) -> dict:
    """Register a project (git repository).

    Args:
        db: Database instance.
        path: Absolute path to repository.
        name: Display name (defaults to directory name).
        project_id: Project ID (defaults to slugified name).

    Returns:
        Created project dictionary.

    Raises:
        ValueError: If path is not a valid git repository.
    """
    repo_path = Path(path).expanduser().resolve()

    if not repo_path.exists():
        raise ValueError(f"Path does not exist: {repo_path}")

    # Validate it's a git repo
    try:
        repo = Repo(repo_path)
    except InvalidGitRepositoryError as e:
        raise ValueError(f"Not a git repository: {repo_path}") from e

    # Determine name and ID
    if not name:
        name = repo_path.name

    if not project_id:
        project_id = slugify(name)

    # Check for duplicates
    existing = await db.get_project(project_id)
    if existing:
        raise ValueError(f"Project with ID '{project_id}' already exists")

    existing_path = await db.get_project_by_path(str(repo_path))
    if existing_path:
        raise ValueError(f"Project at path '{repo_path}' already registered")

    # Get remote URL if available
    remote_url = None
    with contextlib.suppress(Exception):
        if repo.remotes:
            remote_url = repo.remotes.origin.url

    # Get default branch
    default_branch = "main"
    with contextlib.suppress(Exception):
        default_branch = repo.active_branch.name

    # Check for backlog
    backlog_enabled = False
    backlog_path = None
    for backlog_dir in ["backlog", "Backlog", ".backlog"]:
        candidate = repo_path / backlog_dir
        if candidate.is_dir():
            backlog_enabled = True
            backlog_path = str(candidate)
            break

    # Create project
    project = Project(
        project_id=project_id,
        name=name,
        path=str(repo_path),
        remote_url=remote_url,
        default_branch=default_branch,
        backlog_enabled=backlog_enabled,
        backlog_path=backlog_path,
    )

    await db.create_project(project)

    return {
        "project_id": project.project_id,
        "name": project.name,
        "path": project.path,
        "remote_url": project.remote_url,
        "default_branch": project.default_branch,
        "backlog_enabled": project.backlog_enabled,
        "message": f"Project '{name}' registered successfully",
    }


async def scan_projects(db: Database, root: Path) -> dict:
    """Scan directory for git repositories and register them.

    Args:
        db: Database instance.
        root: Root directory to scan.

    Returns:
        Summary of scan results.
    """
    found = []
    registered = []
    skipped = []
    errors = []

    # Walk one level deep (direct children of root)
    for item in root.iterdir():
        if item.name.startswith("."):
            continue  # Skip hidden directories

        if not item.is_dir():
            continue

        git_dir = item / ".git"
        if not git_dir.exists():
            continue

        found.append(str(item))

        try:
            # Check if already registered
            existing = await db.get_project_by_path(str(item))
            if existing:
                skipped.append(
                    {
                        "path": str(item),
                        "project_id": existing.project_id,
                        "reason": "already registered",
                    }
                )
                continue

            # Register it
            result = await register_project(db, str(item))
            registered.append(
                {
                    "path": str(item),
                    "project_id": result["project_id"],
                    "name": result["name"],
                }
            )

        except Exception as e:
            errors.append(
                {
                    "path": str(item),
                    "error": str(e),
                }
            )

    return {
        "scanned_root": str(root),
        "found": len(found),
        "registered": len(registered),
        "skipped": len(skipped),
        "errors": len(errors),
        "details": {
            "registered": registered,
            "skipped": skipped,
            "errors": errors,
        },
    }


async def unregister_project(db: Database, project_id: str) -> dict:
    """Unregister a project.

    Args:
        db: Database instance.
        project_id: Project identifier.

    Returns:
        Result dictionary.

    Raises:
        ValueError: If project not found or has active sessions.
    """
    project = await db.get_project(project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found")

    # Check for active sessions
    sessions = await db.get_sessions_by_project(project_id)
    active = [s for s in sessions if s.state.value != "closing"]
    if active:
        raise ValueError(
            f"Project has {len(active)} active session(s). "
            "Close them first with /close."
        )

    await db.delete_project(project_id)

    return {
        "project_id": project_id,
        "message": f"Project '{project.name}' unregistered",
    }
