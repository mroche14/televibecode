"""MCP tools for project management."""

import contextlib
import re
import subprocess
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


def validate_project_name(name: str) -> str | None:
    """Validate project name.

    Args:
        name: Proposed project name.

    Returns:
        Error message if invalid, None if valid.
    """
    if not name:
        return "Project name cannot be empty"
    if len(name) > 64:
        return "Project name too long (max 64 characters)"
    if not re.match(r"^[a-z][a-z0-9-]*$", name):
        return "Name must be lowercase letters, numbers, dashes only"
    if name.startswith("-") or name.endswith("-"):
        return "Name cannot start or end with a dash"
    if "--" in name:
        return "Name cannot contain consecutive dashes"
    return None


async def create_project(
    db: Database,
    projects_root: Path,
    name: str,
    remote: str | None = None,
) -> dict:
    """Create a new project from scratch.

    Args:
        db: Database instance.
        projects_root: Root directory for projects.
        name: Project name (lowercase, alphanumeric, dashes).
        remote: Optional remote to create ("github" or "gitlab").

    Returns:
        Created project dictionary with remote_url if created.

    Raises:
        ValueError: If name invalid, directory exists, or remote creation fails.
    """
    # Validate name
    error = validate_project_name(name)
    if error:
        raise ValueError(error)

    project_path = projects_root / name

    # Check if already exists
    if project_path.exists():
        raise ValueError(f"Directory already exists: {project_path}")

    # Check if already registered
    existing = await db.get_project(name)
    if existing:
        raise ValueError(f"Project '{name}' already registered")

    # Create directory
    project_path.mkdir(parents=True)

    try:
        # Initialize git repo with main branch
        repo = Repo.init(project_path, initial_branch="main")

        # Create README.md
        readme = project_path / "README.md"
        readme.write_text(f"# {name}\n\nA new project.\n")

        # Create .gitignore
        gitignore = project_path / ".gitignore"
        gitignore.write_text(
            "# IDE\n"
            ".idea/\n"
            ".vscode/\n"
            "*.swp\n"
            "*.swo\n"
            "\n"
            "# Python\n"
            "__pycache__/\n"
            "*.pyc\n"
            ".venv/\n"
            "venv/\n"
            ".env\n"
            "\n"
            "# Node\n"
            "node_modules/\n"
            "\n"
            "# OS\n"
            ".DS_Store\n"
            "Thumbs.db\n"
        )

        # Initial commit
        repo.index.add(["README.md", ".gitignore"])
        repo.index.commit("Initial commit")

        # Create remote if requested
        remote_url = None
        if remote:
            remote_url = _create_remote(project_path, name, remote)
            if remote_url:
                repo.create_remote("origin", remote_url)
                # Push to remote
                repo.remotes.origin.push("main", set_upstream=True)

        # Register in database
        project = Project(
            project_id=name,
            name=name,
            path=str(project_path),
            remote_url=remote_url,
            default_branch="main",
            backlog_enabled=False,
            backlog_path=None,
        )

        await db.create_project(project)

        return {
            "project_id": name,
            "name": name,
            "path": str(project_path),
            "remote_url": remote_url,
            "default_branch": "main",
            "message": f"Project '{name}' created successfully",
        }

    except Exception as e:
        # Clean up on failure
        import shutil

        if project_path.exists():
            shutil.rmtree(project_path)
        raise ValueError(f"Failed to create project: {e}") from e


def _create_remote(project_path: Path, name: str, remote: str) -> str | None:
    """Create a remote repository on GitHub or GitLab.

    Args:
        project_path: Local project path.
        name: Repository name.
        remote: "github" or "gitlab".

    Returns:
        Remote URL if successful, None if failed.

    Raises:
        ValueError: If CLI not available or creation fails.
    """
    if remote == "github":
        # Check if gh CLI is available
        result = subprocess.run(
            ["which", "gh"], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise ValueError(
                "GitHub CLI (gh) not found. Install with: brew install gh"
            )

        # Create repo
        result = subprocess.run(
            ["gh", "repo", "create", name, "--private", "--source", str(project_path)],
            capture_output=True,
            text=True,
            check=False,
            cwd=project_path,
        )
        if result.returncode != 0:
            raise ValueError(f"Failed to create GitHub repo: {result.stderr}")

        # Get repo URL
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "url", "-q", ".url"],
            capture_output=True,
            text=True,
            check=False,
            cwd=project_path,
        )
        if result.returncode == 0:
            return result.stdout.strip()

        return None

    elif remote == "gitlab":
        # Check if glab CLI is available
        result = subprocess.run(
            ["which", "glab"], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise ValueError(
                "GitLab CLI (glab) not found. Install with: brew install glab"
            )

        # Create repo
        result = subprocess.run(
            ["glab", "repo", "create", name, "--private"],
            capture_output=True,
            text=True,
            check=False,
            cwd=project_path,
        )
        if result.returncode != 0:
            raise ValueError(f"Failed to create GitLab repo: {result.stderr}")

        # Get repo URL from output (glab outputs it)
        # Format: "Created repository user/name on GitLab: https://..."
        for line in result.stdout.split("\n"):
            if "https://" in line or "git@" in line:
                # Extract URL
                parts = line.split()
                for part in parts:
                    if part.startswith("https://") or part.startswith("git@"):
                        return part.rstrip(".")
        return None

    else:
        raise ValueError(f"Unknown remote type: {remote}. Use 'github' or 'gitlab'.")
