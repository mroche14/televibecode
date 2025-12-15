"""Job runner for Claude Code execution."""

from televibecode.runner.executor import (
    JobExecutor,
    JobProgress,
    get_job_logs,
    get_job_summary,
    list_session_jobs,
)
from televibecode.runner.executor import (
    run_instruction as _run_instruction_subprocess,
)

# SDK executor (optional - requires claude-agent-sdk)
try:
    from televibecode.runner.sdk_executor import (
        ApprovalCallback,
        ApprovalRequest,
        ApprovalResponse,
        SDKJobExecutor,
        SDKJobProgress,
        is_sdk_available,
        run_instruction_sdk,
    )

    SDK_EXECUTOR_AVAILABLE = True
except ImportError:
    SDK_EXECUTOR_AVAILABLE = False

    # Placeholders when SDK not installed
    def is_sdk_available() -> bool:
        return False

    SDKJobExecutor = None  # type: ignore[assignment,misc]
    SDKJobProgress = None  # type: ignore[assignment,misc]
    run_instruction_sdk = None  # type: ignore[assignment]
    ApprovalCallback = None  # type: ignore[assignment,misc]
    ApprovalRequest = None  # type: ignore[assignment,misc]
    ApprovalResponse = None  # type: ignore[assignment,misc]


# Smart run_instruction that prefers SDK when available
async def run_instruction(
    db,
    settings,
    session_id: str,
    instruction: str,
    on_progress=None,
    on_approval_needed=None,
    on_event=None,
    on_complete=None,
):
    """Run an instruction in a session.

    Uses SDK executor if available (recommended), otherwise falls back
    to subprocess executor.

    Args:
        db: Database instance.
        settings: Application settings.
        session_id: Session to run in.
        instruction: Instruction for Claude Code.
        on_progress: Optional progress callback.
        on_approval_needed: Optional approval callback (SDK only).
        on_event: Optional callback for tracker events.
        on_complete: Optional callback when job completes.

    Returns:
        Job object.
    """
    if SDK_EXECUTOR_AVAILABLE and is_sdk_available():
        return await run_instruction_sdk(
            db=db,
            settings=settings,
            session_id=session_id,
            instruction=instruction,
            on_progress=on_progress,
            on_approval_needed=on_approval_needed,
            on_event=on_event,
            on_complete=on_complete,
        )
    else:
        return await _run_instruction_subprocess(
            db=db,
            settings=settings,
            session_id=session_id,
            instruction=instruction,
            on_progress=on_progress,
            on_event=on_event,
            on_complete=on_complete,
        )


__all__ = [
    # Smart executor (auto-selects SDK or subprocess)
    "run_instruction",
    # Subprocess executor
    "JobExecutor",
    "JobProgress",
    "get_job_logs",
    "get_job_summary",
    "list_session_jobs",
    # SDK executor (optional)
    "SDKJobExecutor",
    "SDKJobProgress",
    "run_instruction_sdk",
    "is_sdk_available",
    "SDK_EXECUTOR_AVAILABLE",
    "ApprovalCallback",
    "ApprovalRequest",
    "ApprovalResponse",
]
