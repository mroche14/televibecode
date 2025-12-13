"""Tests for the backlog parser."""

import tempfile
from pathlib import Path

from televibecode.backlog.parser import (
    extract_task_id,
    extract_title,
    parse_priority,
    parse_status,
    parse_tags,
    parse_task_file,
    parse_yaml_frontmatter,
    scan_backlog_directory,
    task_to_markdown,
)
from televibecode.db.models import Task, TaskPriority, TaskStatus


class TestYAMLFrontmatter:
    """Test YAML frontmatter parsing."""

    def test_valid_frontmatter(self):
        """Test parsing valid YAML frontmatter."""
        content = """---
status: in_progress
priority: high
tags: [feature, auth]
---

# Task Title

Task description here.
"""
        frontmatter, body = parse_yaml_frontmatter(content)
        assert frontmatter["status"] == "in_progress"
        assert frontmatter["priority"] == "high"
        assert frontmatter["tags"] == ["feature", "auth"]
        assert "Task Title" in body

    def test_no_frontmatter(self):
        """Test parsing content without frontmatter."""
        content = "# Just a title\n\nSome content."
        frontmatter, body = parse_yaml_frontmatter(content)
        assert frontmatter == {}
        assert "Just a title" in body

    def test_invalid_yaml(self):
        """Test handling invalid YAML."""
        content = """---
status: [unclosed
---
content
"""
        frontmatter, body = parse_yaml_frontmatter(content)
        # Invalid YAML should result in empty frontmatter
        assert frontmatter == {}


class TestTaskIdExtraction:
    """Test task ID extraction."""

    def test_from_frontmatter(self):
        """Test extracting ID from frontmatter."""
        task_id = extract_task_id("anything.md", {"id": "T-123"})
        assert task_id == "T-123"

    def test_from_filename_with_prefix(self):
        """Test extracting ID from filename with T- prefix."""
        task_id = extract_task_id("T-001-add-auth.md", {})
        assert task_id == "T-001"

    def test_from_filename_numeric(self):
        """Test extracting ID from filename with numeric prefix."""
        task_id = extract_task_id("001-implement-feature.md", {})
        assert task_id == "T-001"

    def test_no_id_found(self):
        """Test when no ID can be extracted."""
        task_id = extract_task_id("random-task.md", {})
        assert task_id is None


class TestTitleExtraction:
    """Test title extraction."""

    def test_from_frontmatter(self):
        """Test extracting title from frontmatter."""
        title = extract_title("file.md", {"title": "My Task"}, "# Different")
        assert title == "My Task"

    def test_from_h1_heading(self):
        """Test extracting title from H1 heading."""
        title = extract_title("file.md", {}, "# Task Title\n\nDescription")
        assert title == "Task Title"

    def test_from_filename(self):
        """Test extracting title from filename."""
        title = extract_title("T-001-add-user-auth.md", {}, "no heading here")
        assert "Add User Auth" in title


class TestStatusParsing:
    """Test status string parsing."""

    def test_todo_variants(self):
        """Test various TODO status strings."""
        assert parse_status("todo") == TaskStatus.TODO
        assert parse_status("to-do") == TaskStatus.TODO
        assert parse_status("pending") == TaskStatus.TODO
        assert parse_status("open") == TaskStatus.TODO

    def test_in_progress_variants(self):
        """Test various in-progress status strings."""
        assert parse_status("in_progress") == TaskStatus.IN_PROGRESS
        assert parse_status("in-progress") == TaskStatus.IN_PROGRESS
        assert parse_status("wip") == TaskStatus.IN_PROGRESS
        assert parse_status("working") == TaskStatus.IN_PROGRESS

    def test_blocked(self):
        """Test blocked status."""
        assert parse_status("blocked") == TaskStatus.BLOCKED
        assert parse_status("on-hold") == TaskStatus.BLOCKED

    def test_review(self):
        """Test review status."""
        assert parse_status("review") == TaskStatus.NEEDS_REVIEW
        assert parse_status("needs_review") == TaskStatus.NEEDS_REVIEW

    def test_done_variants(self):
        """Test done status variants."""
        assert parse_status("done") == TaskStatus.DONE
        assert parse_status("completed") == TaskStatus.DONE
        assert parse_status("closed") == TaskStatus.DONE

    def test_default(self):
        """Test default status for unknown values."""
        assert parse_status(None) == TaskStatus.TODO
        assert parse_status("unknown") == TaskStatus.TODO


class TestPriorityParsing:
    """Test priority string parsing."""

    def test_low_priority(self):
        """Test low priority parsing."""
        assert parse_priority("low") == TaskPriority.LOW
        assert parse_priority("p3") == TaskPriority.LOW
        assert parse_priority("minor") == TaskPriority.LOW

    def test_medium_priority(self):
        """Test medium priority parsing."""
        assert parse_priority("medium") == TaskPriority.MEDIUM
        assert parse_priority("normal") == TaskPriority.MEDIUM
        assert parse_priority("p2") == TaskPriority.MEDIUM

    def test_high_priority(self):
        """Test high priority parsing."""
        assert parse_priority("high") == TaskPriority.HIGH
        assert parse_priority("important") == TaskPriority.HIGH
        assert parse_priority("p1") == TaskPriority.HIGH

    def test_critical_priority(self):
        """Test critical priority parsing."""
        assert parse_priority("critical") == TaskPriority.CRITICAL
        assert parse_priority("urgent") == TaskPriority.CRITICAL
        assert parse_priority("p0") == TaskPriority.CRITICAL

    def test_default(self):
        """Test default priority."""
        assert parse_priority(None) == TaskPriority.MEDIUM


class TestTagParsing:
    """Test tag parsing."""

    def test_list_tags(self):
        """Test parsing tags from list."""
        tags = parse_tags(["feature", "auth", "urgent"])
        assert tags == ["feature", "auth", "urgent"]

    def test_comma_separated(self):
        """Test parsing comma-separated tags."""
        tags = parse_tags("feature, auth, urgent")
        assert tags == ["feature", "auth", "urgent"]

    def test_space_separated(self):
        """Test parsing space-separated tags."""
        tags = parse_tags("feature auth urgent")
        assert tags == ["feature", "auth", "urgent"]

    def test_empty(self):
        """Test empty tags."""
        assert parse_tags(None) == []
        assert parse_tags("") == []


class TestTaskFileParser:
    """Test full task file parsing."""

    def test_parse_complete_file(self):
        """Test parsing a complete task file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("""---
id: T-001
status: in_progress
priority: high
tags: [feature, auth]
epic: Authentication
assignee: developer
---

# Implement User Authentication

Add OAuth2 authentication to the application.

## Requirements
- Support Google login
- Support GitHub login
""")
            f.flush()
            path = Path(f.name)

        task = parse_task_file(path, "test-project")
        assert task is not None
        assert task.task_id == "T-001"
        assert task.title == "Implement User Authentication"
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.priority == TaskPriority.HIGH
        assert task.epic == "Authentication"
        assert task.assignee == "developer"
        assert "feature" in task.tags

        # Cleanup
        path.unlink()

    def test_parse_minimal_file(self):
        """Test parsing a minimal task file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Simple Task\n\nDo this thing.")
            f.flush()
            path = Path(f.name)

        task = parse_task_file(path, "test-project")
        assert task is not None
        assert task.title == "Simple Task"
        assert task.status == TaskStatus.TODO

        path.unlink()


class TestBacklogScanning:
    """Test backlog directory scanning."""

    def test_scan_directory(self):
        """Test scanning a backlog directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = Path(tmpdir)

            # Create task files
            (backlog / "T-001-feature.md").write_text("""---
status: todo
priority: high
---
# Feature Task
""")
            (backlog / "T-002-bugfix.md").write_text("""---
status: in_progress
---
# Bug Fix Task
""")
            # README should be skipped
            (backlog / "README.md").write_text("# Backlog\n\nTask list.")

            tasks = scan_backlog_directory(backlog, "test-project")
            assert len(tasks) == 2

    def test_scan_recursive(self):
        """Test recursive scanning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = Path(tmpdir)

            # Create nested structure
            features = backlog / "features"
            features.mkdir()
            (features / "T-001.md").write_text("# Feature 1")

            bugs = backlog / "bugs"
            bugs.mkdir()
            (bugs / "T-002.md").write_text("# Bug 1")

            tasks = scan_backlog_directory(backlog, "test-project", recursive=True)
            assert len(tasks) == 2

    def test_scan_nonexistent(self):
        """Test scanning nonexistent directory."""
        tasks = scan_backlog_directory(Path("/nonexistent"), "test-project")
        assert tasks == []


class TestTaskToMarkdown:
    """Test task to markdown conversion."""

    def test_full_task(self):
        """Test converting a full task to markdown."""
        task = Task(
            task_id="T-001",
            project_id="test",
            title="Implement Feature",
            description="Add new feature to the system.",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            epic="Features",
            assignee="developer",
            tags=["feature", "v2"],
            branch="feature/T-001",
            session_id="S5",
        )

        markdown = task_to_markdown(task)

        assert "id: T-001" in markdown
        assert "status: in_progress" in markdown
        assert "priority: high" in markdown
        assert "# Implement Feature" in markdown
        assert "Add new feature" in markdown

    def test_minimal_task(self):
        """Test converting a minimal task."""
        task = Task(
            task_id="T-002",
            project_id="test",
            title="Simple Task",
        )

        markdown = task_to_markdown(task)
        assert "id: T-002" in markdown
        assert "# Simple Task" in markdown
