"""Git operations for worktree and branch management."""

from pathlib import Path

from git import Repo
from git.exc import GitCommandError


class GitOperations:
    """Wrapper for git operations on repositories."""

    def __init__(self, repo_path: str | Path):
        """Initialize with a repository path.

        Args:
            repo_path: Path to the git repository.

        Raises:
            ValueError: If path is not a valid git repository.
        """
        self.repo_path = Path(repo_path)
        try:
            self.repo = Repo(self.repo_path)
        except Exception as e:
            raise ValueError(f"Not a valid git repository: {repo_path}") from e

    def create_worktree(
        self,
        worktree_path: str | Path,
        branch: str,
        create_branch: bool = True,
        base_branch: str | None = None,
    ) -> dict:
        """Create a new git worktree.

        Args:
            worktree_path: Path where worktree will be created.
            branch: Branch name for the worktree.
            create_branch: If True, create a new branch.
            base_branch: Base branch for new branch (defaults to HEAD).

        Returns:
            Dictionary with worktree details.

        Raises:
            GitCommandError: If worktree creation fails.
        """
        worktree_path = Path(worktree_path)

        # Ensure parent directory exists
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if create_branch:
                # Create new branch and worktree
                base = base_branch or self.get_default_branch()
                self.repo.git.worktree("add", "-b", branch, str(worktree_path), base)
            else:
                # Use existing branch
                self.repo.git.worktree("add", str(worktree_path), branch)

            return {
                "worktree_path": str(worktree_path),
                "branch": branch,
                "created": True,
            }

        except GitCommandError as e:
            raise GitCommandError(f"Failed to create worktree: {e.stderr or e}") from e

    def remove_worktree(self, worktree_path: str | Path, force: bool = False) -> dict:
        """Remove a git worktree.

        Args:
            worktree_path: Path to the worktree to remove.
            force: If True, force removal even with uncommitted changes.

        Returns:
            Dictionary with removal result.
        """
        worktree_path = Path(worktree_path)

        try:
            if force:
                self.repo.git.worktree("remove", "--force", str(worktree_path))
            else:
                self.repo.git.worktree("remove", str(worktree_path))

            return {
                "worktree_path": str(worktree_path),
                "removed": True,
            }

        except GitCommandError as e:
            # If worktree doesn't exist, consider it removed
            if "is not a working tree" in str(e):
                return {
                    "worktree_path": str(worktree_path),
                    "removed": True,
                    "note": "Worktree did not exist",
                }
            raise

    def list_worktrees(self) -> list[dict]:
        """List all worktrees for this repository.

        Returns:
            List of worktree dictionaries.
        """
        output = self.repo.git.worktree("list", "--porcelain")
        worktrees: list[dict[str, str | bool]] = []
        current: dict[str, str | bool] = {}

        for line in output.split("\n"):
            if not line:
                if current:
                    worktrees.append(current)
                    current = {}
                continue

            if line.startswith("worktree "):
                current["path"] = line[9:]
            elif line.startswith("HEAD "):
                current["head"] = line[5:]
            elif line.startswith("branch "):
                current["branch"] = line[7:].replace("refs/heads/", "")
            elif line == "bare":
                current["bare"] = True
            elif line == "detached":
                current["detached"] = True

        if current:
            worktrees.append(current)

        return worktrees

    def create_branch(
        self,
        branch_name: str,
        base: str | None = None,
        checkout: bool = False,
    ) -> dict:
        """Create a new branch.

        Args:
            branch_name: Name for the new branch.
            base: Base ref for the branch (defaults to HEAD).
            checkout: If True, checkout the new branch.

        Returns:
            Dictionary with branch details.
        """
        base = base or "HEAD"

        try:
            if checkout:
                self.repo.git.checkout("-b", branch_name, base)
            else:
                self.repo.git.branch(branch_name, base)

            return {
                "branch": branch_name,
                "base": base,
                "created": True,
            }

        except GitCommandError as e:
            raise GitCommandError(
                f"Failed to create branch '{branch_name}': {e.stderr or e}"
            ) from e

    def delete_branch(self, branch_name: str, force: bool = False) -> dict:
        """Delete a branch.

        Args:
            branch_name: Name of branch to delete.
            force: If True, force delete even if not merged.

        Returns:
            Dictionary with deletion result.
        """
        try:
            if force:
                self.repo.git.branch("-D", branch_name)
            else:
                self.repo.git.branch("-d", branch_name)

            return {
                "branch": branch_name,
                "deleted": True,
            }

        except GitCommandError as e:
            if "not found" in str(e):
                return {
                    "branch": branch_name,
                    "deleted": True,
                    "note": "Branch did not exist",
                }
            raise

    def get_branch_status(self, worktree_path: str | Path | None = None) -> dict:
        """Get status of a branch/worktree.

        Args:
            worktree_path: Path to worktree (uses main repo if None).

        Returns:
            Dictionary with branch status.
        """
        repo = Repo(worktree_path) if worktree_path else self.repo

        try:
            branch = repo.active_branch.name
        except TypeError:
            branch = "HEAD (detached)"

        # Get status
        status = repo.git.status("--porcelain")
        has_changes = bool(status.strip())

        # Count changes
        staged = 0
        unstaged = 0
        untracked = 0

        for line in status.split("\n"):
            if not line:
                continue
            index_status = line[0]
            work_status = line[1]

            if index_status == "?":
                untracked += 1
            else:
                if index_status != " ":
                    staged += 1
                if work_status != " ":
                    unstaged += 1

        # Get ahead/behind if tracking
        ahead = 0
        behind = 0
        try:
            tracking = repo.active_branch.tracking_branch()
            if tracking:
                ahead_behind = repo.git.rev_list(
                    "--left-right", "--count", f"{tracking.name}...HEAD"
                )
                parts = ahead_behind.split()
                if len(parts) == 2:
                    behind = int(parts[0])
                    ahead = int(parts[1])
        except Exception:
            pass

        return {
            "branch": branch,
            "has_changes": has_changes,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "ahead": ahead,
            "behind": behind,
        }

    def get_default_branch(self) -> str:
        """Get the default branch name.

        Returns:
            Default branch name (main, master, etc.).
        """
        # Try to get from remote HEAD
        try:
            refs: str = self.repo.git.symbolic_ref("refs/remotes/origin/HEAD")
            return refs.replace("refs/remotes/origin/", "")
        except Exception:
            pass

        # Check common defaults
        for branch in ["main", "master"]:
            try:
                self.repo.git.rev_parse("--verify", branch)
                return branch
            except Exception:
                continue

        # Fall back to current branch
        try:
            return self.repo.active_branch.name
        except TypeError:
            return "main"

    def branch_exists(self, branch_name: str) -> bool:
        """Check if a branch exists.

        Args:
            branch_name: Branch name to check.

        Returns:
            True if branch exists.
        """
        try:
            self.repo.git.rev_parse("--verify", f"refs/heads/{branch_name}")
            return True
        except Exception:
            return False

    def get_short_sha(self, ref: str = "HEAD") -> str:
        """Get short SHA for a ref.

        Args:
            ref: Git ref (defaults to HEAD).

        Returns:
            Short SHA string.
        """
        result: str = self.repo.git.rev_parse("--short", ref)
        return result

    def get_commit_count(self, branch: str | None = None) -> int:
        """Get commit count for a branch.

        Args:
            branch: Branch name (defaults to current).

        Returns:
            Number of commits.
        """
        ref = branch or "HEAD"
        count = self.repo.git.rev_list("--count", ref)
        return int(count)


def generate_session_branch(
    project_id: str,
    session_number: int,
    description: str | None = None,
) -> str:
    """Generate a standardized branch name for a session.

    Args:
        project_id: Project identifier.
        session_number: Session number.
        description: Optional description to include.

    Returns:
        Branch name like 'televibe/S12' or 'televibe/S12-fix-auth'.
    """
    base = f"televibe/S{session_number}"
    if description:
        # Sanitize description for branch name
        clean = description.lower()
        clean = "".join(c if c.isalnum() or c == "-" else "-" for c in clean)
        clean = "-".join(filter(None, clean.split("-")))[:30]
        if clean:
            base = f"{base}-{clean}"
    return base
