"""Job runner for Claude Code execution."""

from televibecode.runner.executor import (
    JobExecutor,
    JobProgress,
    get_job_logs,
    get_job_summary,
    list_session_jobs,
    run_instruction,
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

__all__ = [
    # Subprocess executor (default)
    "JobExecutor",
    "JobProgress",
    "run_instruction",
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
