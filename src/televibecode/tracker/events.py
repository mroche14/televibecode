"""Event types for Claude Code session tracking."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal


class EventCategory(Enum):
    """High-level event categories for filtering."""

    SYSTEM = "system"
    AI_SPEECH = "ai_speech"
    AI_THINKING = "ai_thinking"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    APPROVAL = "approval"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event_id() -> str:
    return str(uuid.uuid4())[:8]


@dataclass
class SessionEvent:
    """Base event from Claude Code session."""

    event_id: str = field(default_factory=_event_id)
    category: EventCategory = EventCategory.SYSTEM
    timestamp: datetime = field(default_factory=_now)
    session_id: str | None = None
    job_id: str | None = None


@dataclass
class SystemInitEvent(SessionEvent):
    """Session started."""

    category: EventCategory = field(default=EventCategory.SYSTEM)
    subtype: Literal["init"] = "init"
    tools: list[str] = field(default_factory=list)
    cwd: str | None = None


@dataclass
class SystemResultEvent(SessionEvent):
    """Session completed."""

    category: EventCategory = field(default=EventCategory.SYSTEM)
    subtype: Literal["success", "error"] = "success"
    is_error: bool = False
    error_message: str | None = None
    cost_usd: float | None = None
    num_turns: int = 0
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class AISpeechEvent(SessionEvent):
    """Claude's text response."""

    category: EventCategory = field(default=EventCategory.AI_SPEECH)
    text: str = ""
    is_final: bool = False


@dataclass
class AIThinkingEvent(SessionEvent):
    """Claude's extended thinking."""

    category: EventCategory = field(default=EventCategory.AI_THINKING)
    thinking: str = ""


@dataclass
class ToolStartEvent(SessionEvent):
    """Tool invocation started."""

    category: EventCategory = field(default=EventCategory.TOOL_START)
    tool_name: str = ""
    tool_use_id: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)

    @property
    def file_path(self) -> str | None:
        """Extract file path for file operations."""
        return self.tool_input.get("file_path")

    @property
    def command(self) -> str | None:
        """Extract command for Bash operations."""
        return self.tool_input.get("command")

    @property
    def description(self) -> str | None:
        """Extract description if provided."""
        return self.tool_input.get("description")

    @property
    def pattern(self) -> str | None:
        """Extract pattern for Grep/Glob."""
        return self.tool_input.get("pattern")

    @property
    def url(self) -> str | None:
        """Extract URL for WebFetch."""
        return self.tool_input.get("url")

    @property
    def query(self) -> str | None:
        """Extract query for WebSearch."""
        return self.tool_input.get("query")


@dataclass
class ToolResultEvent(SessionEvent):
    """Tool execution completed."""

    category: EventCategory = field(default=EventCategory.TOOL_RESULT)
    tool_use_id: str = ""
    tool_name: str = ""
    result: str = ""
    is_error: bool = False


@dataclass
class ApprovalEvent(SessionEvent):
    """Waiting for user approval."""

    category: EventCategory = field(default=EventCategory.APPROVAL)
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    approval_id: str | None = None


# Tool display configuration
TOOL_ICONS: dict[str, str] = {
    "Read": "📖",
    "Write": "📝",
    "Edit": "✏️",
    "MultiEdit": "✏️",
    "Bash": "🔨",
    "Grep": "🔍",
    "Glob": "📂",
    "WebFetch": "🌐",
    "WebSearch": "🔎",
    "TodoWrite": "📋",
    "TodoRead": "📋",
    "Task": "🤖",
    "NotebookEdit": "📓",
    "NotebookRead": "📓",
}

TOOL_VERBS: dict[str, str] = {
    "Read": "Reading",
    "Write": "Creating",
    "Edit": "Editing",
    "MultiEdit": "Editing",
    "Bash": "Running",
    "Grep": "Searching",
    "Glob": "Finding",
    "WebFetch": "Fetching",
    "WebSearch": "Searching",
    "TodoWrite": "Updating tasks",
    "TodoRead": "Checking tasks",
    "Task": "Spawning agent",
    "NotebookEdit": "Editing notebook",
    "NotebookRead": "Reading notebook",
}


def get_tool_icon(tool_name: str) -> str:
    """Get icon for a tool."""
    return TOOL_ICONS.get(tool_name, "🔧")


def get_tool_verb(tool_name: str) -> str:
    """Get verb for a tool."""
    return TOOL_VERBS.get(tool_name, tool_name)
