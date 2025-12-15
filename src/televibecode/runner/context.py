"""Context injection for Claude Code instructions.

Provides session and project context to enhance instructions so Claude
knows where it is working and what mode it's operating in.
"""

from televibecode.db.models import ExecutionMode, Project, Session


def get_enhanced_instruction(
    instruction: str,
    session: Session,
    project: Project,
) -> str:
    """Enhance instruction with session context.

    Prepends context information so Claude knows:
    - What session it's working in
    - What project it's working on
    - What execution mode it's using
    - Where the workspace is located

    Args:
        instruction: Original user instruction.
        session: Session being used.
        project: Project being worked on.

    Returns:
        Enhanced instruction with context prepended.
    """
    mode_desc = (
        "isolated worktree (safe for experiments)"
        if session.execution_mode == ExecutionMode.WORKTREE
        else "project folder directly (changes affect main project)"
    )

    context = f"""# TeleVibeCode Session Context
- Session: {session.session_id}
- Project: {project.name} ({project.project_id})
- Branch: {session.branch}
- Mode: {session.execution_mode.value} - {mode_desc}
- Workspace: {session.workspace_path}

---

"""
    return context + instruction


def get_context_summary(session: Session, project: Project) -> str:
    """Get a short context summary for display.

    Args:
        session: Session being used.
        project: Project being worked on.

    Returns:
        Short summary string.
    """
    mode_icon = "🌳" if session.execution_mode == ExecutionMode.WORKTREE else "📁"
    return (
        f"{mode_icon} {session.session_id} | "
        f"{project.name}:{session.branch} | "
        f"{session.execution_mode.value}"
    )
