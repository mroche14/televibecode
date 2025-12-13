"""Intent classification using Agno for natural language support."""

import contextlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

# Agno is optional - only used for AI-based classification
try:
    from agno.agent import Agent
except ImportError:
    Agent = None  # type: ignore[assignment,misc]


class IntentType(str, Enum):
    """Classified intent types from natural language input."""

    # Session management
    CREATE_SESSION = "create_session"
    SWITCH_SESSION = "switch_session"
    CLOSE_SESSION = "close_session"
    LIST_SESSIONS = "list_sessions"
    SESSION_STATUS = "session_status"

    # Task management
    LIST_TASKS = "list_tasks"
    CLAIM_TASK = "claim_task"
    UPDATE_TASK = "update_task"
    SYNC_BACKLOG = "sync_backlog"

    # Job execution
    RUN_INSTRUCTION = "run_instruction"
    CHECK_JOB_STATUS = "check_job_status"
    VIEW_JOB_LOGS = "view_job_logs"
    CANCEL_JOB = "cancel_job"

    # Approval actions
    APPROVE_ACTION = "approve_action"
    DENY_ACTION = "deny_action"
    LIST_APPROVALS = "list_approvals"

    # Project management
    LIST_PROJECTS = "list_projects"
    SCAN_PROJECTS = "scan_projects"

    # General
    HELP = "help"
    UNKNOWN = "unknown"


@dataclass
class ParsedIntent:
    """Result of intent parsing."""

    intent: IntentType
    confidence: float
    entities: dict[str, Any]
    raw_text: str
    suggested_command: str | None = None


class IntentClassifier:
    """Classifies natural language input into intents."""

    # Pattern-based rules for quick matching
    PATTERNS: list[tuple[re.Pattern, IntentType, dict]] = [
        # Session patterns
        (
            re.compile(r"(?:start|create|new|begin)\s+(?:a\s+)?session", re.I),
            IntentType.CREATE_SESSION,
            {},
        ),
        (
            re.compile(
                r"(?:switch|use|change)\s+(?:to\s+)?(?:session\s+)?([sS]\d+)", re.I
            ),
            IntentType.SWITCH_SESSION,
            {"session_id_group": 1},
        ),
        (
            re.compile(r"(?:close|end|finish|stop)\s+(?:the\s+)?session", re.I),
            IntentType.CLOSE_SESSION,
            {},
        ),
        (
            re.compile(r"(?:list|show|what|view)\s+(?:all\s+)?sessions?", re.I),
            IntentType.LIST_SESSIONS,
            {},
        ),
        # Job status pattern before session status (more specific first)
        (
            re.compile(r"(?:job|work|jobs)\s+(?:status|progress)", re.I),
            IntentType.CHECK_JOB_STATUS,
            {},
        ),
        (
            re.compile(r"(?:session\s+)?(?:status|what.s happening)", re.I),
            IntentType.SESSION_STATUS,
            {},
        ),
        # Task patterns
        (
            re.compile(r"(?:list|show|what|view)\s+(?:all\s+)?tasks?", re.I),
            IntentType.LIST_TASKS,
            {},
        ),
        (
            re.compile(r"(?:next|pending|todo)\s+tasks?", re.I),
            IntentType.LIST_TASKS,
            {"filter": "pending"},
        ),
        (
            re.compile(r"(?:claim|take|grab|assign)\s+(?:task\s+)?(T[-]?\d+)", re.I),
            IntentType.CLAIM_TASK,
            {"task_id_group": 1},
        ),
        (
            re.compile(r"sync\s+(?:the\s+)?backlog", re.I),
            IntentType.SYNC_BACKLOG,
            {},
        ),
        # Job patterns
        (
            re.compile(r"(?:run|execute|do|start)\s+(.+)", re.I),
            IntentType.RUN_INSTRUCTION,
            {"instruction_group": 1},
        ),
        (
            re.compile(r"(?:show|view|get)\s+(?:job\s+)?logs?", re.I),
            IntentType.VIEW_JOB_LOGS,
            {},
        ),
        (
            re.compile(r"(?:cancel|stop|abort)\s+(?:the\s+)?(?:job|work)", re.I),
            IntentType.CANCEL_JOB,
            {},
        ),
        # Approval patterns
        (
            re.compile(r"(?:approve|allow|permit|yes)\s*$", re.I),
            IntentType.APPROVE_ACTION,
            {},
        ),
        (
            re.compile(r"(?:deny|reject|no|refuse)\s*$", re.I),
            IntentType.DENY_ACTION,
            {},
        ),
        (
            re.compile(r"(?:pending\s+)?approvals?", re.I),
            IntentType.LIST_APPROVALS,
            {},
        ),
        # Project patterns
        (
            re.compile(r"(?:list|show|what|view)\s+(?:all\s+)?projects?", re.I),
            IntentType.LIST_PROJECTS,
            {},
        ),
        (
            re.compile(r"scan\s+(?:for\s+)?projects?", re.I),
            IntentType.SCAN_PROJECTS,
            {},
        ),
        # Help
        (
            re.compile(r"(?:help|commands|how\s+to|what\s+can)", re.I),
            IntentType.HELP,
            {},
        ),
    ]

    INTENT_TO_COMMAND: dict[IntentType, str | None] = {
        IntentType.CREATE_SESSION: "/new",
        IntentType.SWITCH_SESSION: "/use",
        IntentType.CLOSE_SESSION: "/close",
        IntentType.LIST_SESSIONS: "/sessions",
        IntentType.SESSION_STATUS: "/status",
        IntentType.LIST_TASKS: "/tasks",
        IntentType.CLAIM_TASK: "/claim",
        IntentType.SYNC_BACKLOG: "/sync",
        IntentType.RUN_INSTRUCTION: "/run",
        IntentType.CHECK_JOB_STATUS: "/jobs",
        IntentType.VIEW_JOB_LOGS: "/tail",
        IntentType.CANCEL_JOB: "/cancel",
        IntentType.APPROVE_ACTION: None,  # Handled via callback
        IntentType.DENY_ACTION: None,  # Handled via callback
        IntentType.LIST_APPROVALS: "/approvals",
        IntentType.LIST_PROJECTS: "/projects",
        IntentType.SCAN_PROJECTS: "/scan",
        IntentType.HELP: "/help",
    }

    def __init__(self, use_ai: bool = True, model: str = "claude-sonnet-4-20250514"):
        """Initialize the classifier.

        Args:
            use_ai: Whether to use AI for complex classification.
            model: Model to use for AI classification.
        """
        self.use_ai = use_ai
        self.model = model
        self._agent: Any = None

    def _get_agent(self) -> Any:
        """Get or create the Agno agent."""
        if Agent is None:
            raise RuntimeError("Agno is not installed. Install with: uv add agno")
        if self._agent is None:
            self._agent = Agent(
                model=self.model,
                description="Intent classifier for TeleVibeCode Telegram bot",
                instructions=[
                    "You are an intent classifier for a coding assistant bot.",
                    "Classify the user's message into one of these intents:",
                    "- create_session: User wants to start a new coding session",
                    "- switch_session: User wants to switch to a different session",
                    "- close_session: User wants to end/close a session",
                    "- list_sessions: User wants to see all sessions",
                    "- session_status: User wants status of current session",
                    "- list_tasks: User wants to see tasks",
                    "- claim_task: User wants to work on a specific task",
                    "- sync_backlog: User wants to sync backlog files",
                    "- run_instruction: User wants to execute a coding task",
                    "- check_job_status: User wants to see job progress",
                    "- view_job_logs: User wants to see job logs",
                    "- cancel_job: User wants to cancel a running job",
                    "- approve_action: User is approving a pending action",
                    "- deny_action: User is denying a pending action",
                    "- list_approvals: User wants to see pending approvals",
                    "- list_projects: User wants to see registered projects",
                    "- scan_projects: User wants to scan for new projects",
                    "- help: User needs help",
                    "- unknown: Cannot determine intent",
                    "",
                    "Respond with ONLY the intent name, nothing else.",
                ],
            )
        return self._agent

    def classify_pattern(self, text: str) -> ParsedIntent | None:
        """Try to classify using pattern matching.

        Args:
            text: Input text.

        Returns:
            ParsedIntent or None if no pattern matches.
        """
        for pattern, intent, config in self.PATTERNS:
            match = pattern.search(text)
            if match:
                entities: dict[str, Any] = {}

                # Extract entities from capture groups
                for key, group_num in config.items():
                    if key.endswith("_group") and isinstance(group_num, int):
                        entity_name = key[:-6]  # Remove "_group" suffix
                        with contextlib.suppress(IndexError):
                            entities[entity_name] = match.group(group_num)
                    else:
                        entities[key] = group_num

                suggested_cmd = self.INTENT_TO_COMMAND.get(intent)
                if suggested_cmd and entities:
                    # Add entity values to command
                    for key, value in entities.items():
                        if key in ("session_id", "task_id", "instruction"):
                            suggested_cmd += f" {value}"

                return ParsedIntent(
                    intent=intent,
                    confidence=0.9,
                    entities=entities,
                    raw_text=text,
                    suggested_command=suggested_cmd,
                )

        return None

    async def classify_ai(self, text: str) -> ParsedIntent:
        """Classify using AI agent.

        Args:
            text: Input text.

        Returns:
            ParsedIntent from AI classification.
        """
        agent = self._get_agent()
        response = await agent.arun(text)

        # Parse response
        intent_str = response.content.strip().lower()

        try:
            intent = IntentType(intent_str)
        except ValueError:
            intent = IntentType.UNKNOWN

        return ParsedIntent(
            intent=intent,
            confidence=0.7,  # AI classification has lower confidence
            entities={},
            raw_text=text,
            suggested_command=self.INTENT_TO_COMMAND.get(intent),
        )

    async def classify(self, text: str) -> ParsedIntent:
        """Classify input text into an intent.

        Args:
            text: Natural language input.

        Returns:
            ParsedIntent with classification results.
        """
        # Try pattern matching first (fast)
        result = self.classify_pattern(text)
        if result:
            return result

        # Fall back to AI if enabled
        if self.use_ai:
            return await self.classify_ai(text)

        # No classification possible
        return ParsedIntent(
            intent=IntentType.UNKNOWN,
            confidence=0.0,
            entities={},
            raw_text=text,
            suggested_command=None,
        )

    def is_likely_instruction(self, text: str) -> bool:
        """Check if text is likely a coding instruction.

        Args:
            text: Input text.

        Returns:
            True if text looks like a coding instruction.
        """
        # Coding-related keywords
        coding_keywords = [
            "add",
            "create",
            "implement",
            "fix",
            "bug",
            "feature",
            "update",
            "change",
            "modify",
            "refactor",
            "test",
            "function",
            "class",
            "method",
            "file",
            "code",
            "error",
            "issue",
            "build",
            "deploy",
            "run",
            "write",
            "delete",
            "remove",
            "import",
            "export",
        ]

        text_lower = text.lower()
        return any(kw in text_lower for kw in coding_keywords)


# Global classifier instance
_classifier: IntentClassifier | None = None


def get_classifier(use_ai: bool = True) -> IntentClassifier:
    """Get the global intent classifier.

    Args:
        use_ai: Whether to enable AI classification.

    Returns:
        IntentClassifier instance.
    """
    global _classifier
    if _classifier is None:
        _classifier = IntentClassifier(use_ai=use_ai)
    return _classifier


async def classify_message(text: str) -> ParsedIntent:
    """Classify a message using the global classifier.

    Args:
        text: Message text.

    Returns:
        ParsedIntent result.
    """
    classifier = get_classifier()
    return await classifier.classify(text)
