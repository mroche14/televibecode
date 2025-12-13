"""Backlog.md parser for task extraction."""

import re
from pathlib import Path
from typing import Any

import yaml

from televibecode.db.models import Task, TaskPriority, TaskStatus


def parse_yaml_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML front-matter from markdown content.

    Args:
        content: Markdown content with optional YAML front-matter.

    Returns:
        Tuple of (frontmatter dict, remaining content).
    """
    frontmatter: dict[str, Any] = {}
    body = content

    # Check for YAML front-matter (starts with ---)
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
                body = parts[2].strip()
            except yaml.YAMLError:
                pass  # Invalid YAML, treat as regular content

    return frontmatter, body


def extract_task_id(filename: str, frontmatter: dict) -> str | None:
    """Extract task ID from filename or frontmatter.

    Args:
        filename: The markdown filename.
        frontmatter: Parsed YAML frontmatter.

    Returns:
        Task ID or None.
    """
    # Check frontmatter first
    if "id" in frontmatter:
        return str(frontmatter["id"])

    # Try to extract from filename (e.g., T-001-task-name.md)
    match = re.match(r"^(T-?\d+)", filename)
    if match:
        return match.group(1)

    # Try numeric prefix (e.g., 001-task-name.md)
    match = re.match(r"^(\d+)", filename)
    if match:
        return f"T-{match.group(1)}"

    return None


def extract_title(filename: str, frontmatter: dict, body: str) -> str:
    """Extract task title from various sources.

    Args:
        filename: The markdown filename.
        frontmatter: Parsed YAML frontmatter.
        body: Markdown body content.

    Returns:
        Task title.
    """
    # Check frontmatter
    if "title" in frontmatter:
        return str(frontmatter["title"])

    # Try first H1 heading in body
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()

    # Fall back to filename
    name = Path(filename).stem
    # Remove task ID prefix if present
    name = re.sub(r"^T?-?\d+-?", "", name)
    # Convert dashes/underscores to spaces
    name = name.replace("-", " ").replace("_", " ")
    return name.title()


def parse_status(value: str | None) -> TaskStatus:
    """Parse status string to TaskStatus enum.

    Args:
        value: Status string from frontmatter.

    Returns:
        TaskStatus enum value.
    """
    if not value:
        return TaskStatus.TODO

    value = value.lower().strip()
    status_map = {
        "todo": TaskStatus.TODO,
        "to-do": TaskStatus.TODO,
        "pending": TaskStatus.TODO,
        "open": TaskStatus.TODO,
        "in_progress": TaskStatus.IN_PROGRESS,
        "in-progress": TaskStatus.IN_PROGRESS,
        "inprogress": TaskStatus.IN_PROGRESS,
        "wip": TaskStatus.IN_PROGRESS,
        "working": TaskStatus.IN_PROGRESS,
        "blocked": TaskStatus.BLOCKED,
        "on-hold": TaskStatus.BLOCKED,
        "waiting": TaskStatus.BLOCKED,
        "review": TaskStatus.NEEDS_REVIEW,
        "needs_review": TaskStatus.NEEDS_REVIEW,
        "needs-review": TaskStatus.NEEDS_REVIEW,
        "done": TaskStatus.DONE,
        "completed": TaskStatus.DONE,
        "closed": TaskStatus.DONE,
        "finished": TaskStatus.DONE,
    }
    return status_map.get(value, TaskStatus.TODO)


def parse_priority(value: str | None) -> TaskPriority:
    """Parse priority string to TaskPriority enum.

    Args:
        value: Priority string from frontmatter.

    Returns:
        TaskPriority enum value.
    """
    if not value:
        return TaskPriority.MEDIUM

    value = value.lower().strip()
    priority_map = {
        "low": TaskPriority.LOW,
        "p3": TaskPriority.LOW,
        "minor": TaskPriority.LOW,
        "medium": TaskPriority.MEDIUM,
        "normal": TaskPriority.MEDIUM,
        "p2": TaskPriority.MEDIUM,
        "high": TaskPriority.HIGH,
        "important": TaskPriority.HIGH,
        "p1": TaskPriority.HIGH,
        "critical": TaskPriority.CRITICAL,
        "urgent": TaskPriority.CRITICAL,
        "p0": TaskPriority.CRITICAL,
        "blocker": TaskPriority.CRITICAL,
    }
    return priority_map.get(value, TaskPriority.MEDIUM)


def parse_tags(value: Any) -> list[str]:
    """Parse tags from frontmatter.

    Args:
        value: Tags value (string, list, or None).

    Returns:
        List of tag strings.
    """
    if not value:
        return []

    if isinstance(value, list):
        return [str(t).strip() for t in value if t]

    if isinstance(value, str):
        # Handle comma-separated or space-separated
        if "," in value:
            return [t.strip() for t in value.split(",") if t.strip()]
        return [t.strip() for t in value.split() if t.strip()]

    return []


def parse_task_file(
    file_path: Path,
    project_id: str,
) -> Task | None:
    """Parse a markdown file into a Task.

    Args:
        file_path: Path to the markdown file.
        project_id: Project ID for the task.

    Returns:
        Task object or None if parsing fails.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return None

    frontmatter, body = parse_yaml_frontmatter(content)

    # Extract task ID
    task_id = extract_task_id(file_path.name, frontmatter)
    if not task_id:
        # Generate ID from filename hash
        task_id = f"T-{abs(hash(file_path.name)) % 10000:04d}"

    # Extract title
    title = extract_title(file_path.name, frontmatter, body)

    # Build description from body (first paragraph or truncated)
    description = None
    if body:
        # Get first non-heading paragraph
        paragraphs = []
        for para in body.split("\n\n"):
            para = para.strip()
            if para and not para.startswith("#"):
                paragraphs.append(para)
        if paragraphs:
            description = paragraphs[0][:500]

    return Task(
        task_id=task_id,
        project_id=project_id,
        title=title,
        description=description,
        status=parse_status(frontmatter.get("status")),
        priority=parse_priority(frontmatter.get("priority")),
        epic=frontmatter.get("epic"),
        assignee=frontmatter.get("assignee"),
        tags=parse_tags(frontmatter.get("tags")),
        branch=frontmatter.get("branch"),
    )


def scan_backlog_directory(
    backlog_path: Path,
    project_id: str,
    recursive: bool = True,
) -> list[Task]:
    """Scan a backlog directory for task files.

    Args:
        backlog_path: Path to backlog directory.
        project_id: Project ID for tasks.
        recursive: If True, scan subdirectories.

    Returns:
        List of parsed Task objects.
    """
    tasks: list[Task] = []

    if not backlog_path.exists() or not backlog_path.is_dir():
        return tasks

    # Find all markdown files
    pattern = "**/*.md" if recursive else "*.md"
    for md_file in backlog_path.glob(pattern):
        # Skip README files
        if md_file.name.lower() in ("readme.md", "index.md"):
            continue

        task = parse_task_file(md_file, project_id)
        if task:
            tasks.append(task)

    return tasks


def task_to_markdown(task: Task) -> str:
    """Convert a Task to markdown with YAML frontmatter.

    Args:
        task: Task object to convert.

    Returns:
        Markdown string with YAML frontmatter.
    """
    # Build frontmatter
    frontmatter: dict[str, Any] = {
        "id": task.task_id,
        "status": task.status.value,
        "priority": task.priority.value,
    }

    if task.epic:
        frontmatter["epic"] = task.epic
    if task.assignee:
        frontmatter["assignee"] = task.assignee
    if task.tags:
        frontmatter["tags"] = task.tags
    if task.branch:
        frontmatter["branch"] = task.branch
    if task.session_id:
        frontmatter["session_id"] = task.session_id

    # Build markdown
    yaml_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
    md = f"---\n{yaml_str}---\n\n"
    md += f"# {task.title}\n\n"

    if task.description:
        md += f"{task.description}\n"

    return md
