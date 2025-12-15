# Job Tracker Message Specification

## Overview

When a job is launched, a dedicated **Job Tracker Message** is created in Telegram. This message receives real-time updates as events flow from the Claude Code session, allowing users to watch the AI work in real-time.

```
┌─────────────────────────────────────────────────────────────────┐
│  User: /run add login validation                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  🔧 Job #a1b2c3 • S1 (myproject)                               │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                                 │
│  📖 Reading src/auth.py                                        │
│  ✏️ Editing src/auth.py                                        │  ◀── Live updates
│     └─ Added email validation                                   │
│  🔨 Running: pytest tests/                                      │
│     └─ ✅ 12 passed                                            │
│                                                                 │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│  ⏱️ 23s • 📝 2 files • 🔄 4 turns                              │
│                                                                 │
│  [⏸️ Pause Updates]  [⏹️ Cancel]                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Architecture

### Data Flow

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ Claude Code  │────▶│  Event Parser    │────▶│  Event Filter    │
│ (stream-json)│     │  (JSON → Events) │     │  (Config-based)  │
└──────────────┘     └──────────────────┘     └──────────────────┘
                                                       │
                                                       ▼
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   Telegram   │◀────│  Message Renderer│◀────│  Event Buffer    │
│ editMessage  │     │  (Events → Text) │     │  (Rate limiting) │
└──────────────┘     └──────────────────┘     └──────────────────┘
```

### Components

| Component | Responsibility |
|-----------|----------------|
| **EventParser** | Converts stream-json lines to typed `SessionEvent` objects |
| **EventFilter** | Applies user config to decide which events to include |
| **EventBuffer** | Accumulates events, respects rate limits (1 edit/sec) |
| **MessageRenderer** | Formats buffered events into Telegram message text |
| **TrackerManager** | Manages tracker message lifecycle per job |

---

## Event Types

### Core Event Taxonomy

```python
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

class EventCategory(Enum):
    """High-level event categories for filtering."""
    SYSTEM = "system"           # Session init/end
    AI_SPEECH = "ai_speech"     # Claude's text responses
    AI_THINKING = "ai_thinking" # Extended thinking content
    TOOL_START = "tool_start"   # Tool invocation begins
    TOOL_RESULT = "tool_result" # Tool execution result
    TOOL_ERROR = "tool_error"   # Tool execution failed
    APPROVAL = "approval"       # Waiting for user approval
    PROGRESS = "progress"       # Internal progress markers


@dataclass
class SessionEvent:
    """Base event from Claude Code session."""

    # Core fields
    event_id: str                           # Unique event ID
    category: EventCategory                 # For filtering
    timestamp: datetime                     # When event occurred

    # Optional context
    session_id: str | None = None
    job_id: str | None = None


@dataclass
class SystemInitEvent(SessionEvent):
    """Session started."""
    category: EventCategory = EventCategory.SYSTEM
    subtype: Literal["init"] = "init"
    tools: list[str] = field(default_factory=list)
    cwd: str | None = None


@dataclass
class SystemResultEvent(SessionEvent):
    """Session completed."""
    category: EventCategory = EventCategory.SYSTEM
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
    category: EventCategory = EventCategory.AI_SPEECH
    text: str = ""
    is_final: bool = False      # Last text in conversation


@dataclass
class AIThinkingEvent(SessionEvent):
    """Claude's extended thinking."""
    category: EventCategory = EventCategory.AI_THINKING
    thinking: str = ""


@dataclass
class ToolStartEvent(SessionEvent):
    """Tool invocation started."""
    category: EventCategory = EventCategory.TOOL_START
    tool_name: str = ""
    tool_use_id: str = ""
    tool_input: dict = field(default_factory=dict)

    # Derived convenience fields
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


@dataclass
class ToolResultEvent(SessionEvent):
    """Tool execution completed."""
    category: EventCategory = EventCategory.TOOL_RESULT
    tool_use_id: str = ""
    tool_name: str = ""          # Carried from start event
    result: str = ""
    is_error: bool = False

    # For display
    success_indicator: str = ""  # e.g., "✅ 12 passed" for pytest


@dataclass
class ApprovalEvent(SessionEvent):
    """Waiting for user approval."""
    category: EventCategory = EventCategory.APPROVAL
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    approval_id: str | None = None
```

### Tool-Specific Display Hints

```python
TOOL_DISPLAY_CONFIG = {
    "Read": {
        "icon": "📖",
        "verb": "Reading",
        "show_path": True,
        "show_result": False,  # Content usually too large
    },
    "Write": {
        "icon": "📝",
        "verb": "Creating",
        "show_path": True,
        "show_result": False,
    },
    "Edit": {
        "icon": "✏️",
        "verb": "Editing",
        "show_path": True,
        "show_result": True,   # Show what changed (truncated)
    },
    "Bash": {
        "icon": "🔨",
        "verb": "Running",
        "show_command": True,
        "show_result": True,   # Show command output (truncated)
        "parse_test_results": True,  # Special handling for pytest/npm test
    },
    "Grep": {
        "icon": "🔍",
        "verb": "Searching",
        "show_pattern": True,
        "show_result": False,
    },
    "Glob": {
        "icon": "📂",
        "verb": "Finding files",
        "show_pattern": True,
        "show_result": False,
    },
    "WebFetch": {
        "icon": "🌐",
        "verb": "Fetching",
        "show_url": True,
        "show_result": False,
    },
    "WebSearch": {
        "icon": "🔎",
        "verb": "Searching web",
        "show_query": True,
        "show_result": False,
    },
    "TodoWrite": {
        "icon": "📋",
        "verb": "Updating tasks",
        "show_result": False,
    },
    "Task": {
        "icon": "🤖",
        "verb": "Spawning agent",
        "show_description": True,
        "show_result": True,
    },
}
```

---

## Event Filtering Configuration

### Configuration Schema

```python
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class EventFilterConfig:
    """Configuration for which events to display in tracker message."""

    # ═══════════════════════════════════════════════════════════════
    # Category-level toggles
    # ═══════════════════════════════════════════════════════════════

    show_ai_speech: bool = True
    """Show Claude's text responses (what the AI "says")."""

    show_ai_thinking: bool = False
    """Show extended thinking content (very verbose)."""

    show_tool_start: bool = True
    """Show when tools begin execution."""

    show_tool_result: bool = False
    """Show tool execution results (can be verbose)."""

    show_tool_errors: bool = True
    """Always show tool errors (recommended: True)."""

    show_approvals: bool = True
    """Show when waiting for approval."""

    # ═══════════════════════════════════════════════════════════════
    # Tool-specific overrides
    # ═══════════════════════════════════════════════════════════════

    tool_whitelist: list[str] | None = None
    """Only show these tools. None = show all. Example: ["Write", "Edit", "Bash"]"""

    tool_blacklist: list[str] = field(default_factory=list)
    """Never show these tools. Example: ["Read", "Glob", "Grep"]"""

    # Per-tool result visibility (overrides show_tool_result)
    show_result_for_tools: list[str] = field(default_factory=lambda: ["Bash", "Edit"])
    """Show results for these specific tools even if show_tool_result=False."""

    # ═══════════════════════════════════════════════════════════════
    # AI Speech options
    # ═══════════════════════════════════════════════════════════════

    ai_speech_max_length: int = 150
    """Max characters per AI speech message (0 = unlimited)."""

    ai_speech_show_final_only: bool = False
    """Only show the final AI response, not intermediate ones."""

    # ═══════════════════════════════════════════════════════════════
    # Tool display options
    # ═══════════════════════════════════════════════════════════════

    tool_display_mode: Literal["minimal", "normal", "detailed"] = "normal"
    """
    minimal: Icon only (📝)
    normal:  Icon + tool + target (📝 Writing src/auth.py)
    detailed: Icon + tool + target + details (📝 Writing src/auth.py - Added validation)
    """

    show_file_paths: bool = True
    """Show file paths for file operations."""

    truncate_paths: bool = True
    """Truncate long paths (show ...src/auth.py instead of full path)."""

    show_bash_commands: bool = True
    """Show command for Bash operations."""

    bash_command_max_length: int = 50
    """Max characters for bash command display."""

    # ═══════════════════════════════════════════════════════════════
    # Result parsing
    # ═══════════════════════════════════════════════════════════════

    parse_test_output: bool = True
    """Parse pytest/jest/npm test output for pass/fail counts."""

    parse_lint_output: bool = True
    """Parse linter output for error/warning counts."""

    result_max_length: int = 100
    """Max characters for tool result display."""

    # ═══════════════════════════════════════════════════════════════
    # Progress section
    # ═══════════════════════════════════════════════════════════════

    show_elapsed_time: bool = True
    show_file_count: bool = True
    show_turn_count: bool = True
    show_token_count: bool = False
    show_cost: bool = False  # Show after completion

    # ═══════════════════════════════════════════════════════════════
    # History/Buffer
    # ═══════════════════════════════════════════════════════════════

    max_events_displayed: int = 10
    """Max events to show in message (older events scroll off)."""

    collapse_repeated_tools: bool = True
    """Collapse repeated same-tool events (e.g., 5x Read → "📖 Read 5 files")"""

    group_by_phase: bool = False
    """Group events by phase (research → implementation → testing)."""


# ═══════════════════════════════════════════════════════════════════
# Preset Configurations
# ═══════════════════════════════════════════════════════════════════

PRESETS: dict[str, EventFilterConfig] = {
    "minimal": EventFilterConfig(
        show_ai_speech=False,
        show_tool_start=True,
        show_tool_result=False,
        tool_display_mode="minimal",
        max_events_displayed=5,
    ),

    "normal": EventFilterConfig(
        show_ai_speech=True,
        ai_speech_max_length=100,
        show_tool_start=True,
        show_tool_result=False,
        show_result_for_tools=["Bash"],
        tool_display_mode="normal",
        max_events_displayed=8,
    ),

    "verbose": EventFilterConfig(
        show_ai_speech=True,
        ai_speech_max_length=200,
        show_tool_start=True,
        show_tool_result=True,
        tool_display_mode="detailed",
        max_events_displayed=15,
        show_token_count=True,
    ),

    "debug": EventFilterConfig(
        show_ai_speech=True,
        show_ai_thinking=True,
        ai_speech_max_length=0,  # Unlimited
        show_tool_start=True,
        show_tool_result=True,
        tool_display_mode="detailed",
        max_events_displayed=20,
        show_token_count=True,
        show_cost=True,
    ),

    "speech_only": EventFilterConfig(
        show_ai_speech=True,
        ai_speech_max_length=0,
        show_tool_start=False,
        show_tool_result=False,
        max_events_displayed=5,
    ),

    "tools_only": EventFilterConfig(
        show_ai_speech=False,
        show_tool_start=True,
        show_tool_result=True,
        tool_display_mode="detailed",
        max_events_displayed=10,
    ),
}
```

### Environment Variable Mapping

```bash
# .env file

# Preset (overrides individual settings)
TELEVIBE_TRACKER_PRESET=normal

# Or individual settings
TELEVIBE_SHOW_AI_SPEECH=true
TELEVIBE_SHOW_AI_THINKING=false
TELEVIBE_SHOW_TOOL_START=true
TELEVIBE_SHOW_TOOL_RESULT=false
TELEVIBE_TOOL_DISPLAY_MODE=normal
TELEVIBE_AI_SPEECH_MAX_LENGTH=150
TELEVIBE_MAX_EVENTS_DISPLAYED=10
TELEVIBE_TOOL_WHITELIST=Write,Edit,Bash
TELEVIBE_TOOL_BLACKLIST=Read,Glob
TELEVIBE_SHOW_COST=false
```

---

## Message Rendering

### Message Structure

```
┌─────────────────────────────────────────────────────────────────┐
│ HEADER                                                          │
│ ─────────────────────────────────────────────────────────────── │
│ 🔧 Job #a1b2c3 • S1 (myproject)                                │
│ 📝 "add login validation"                                       │
├─────────────────────────────────────────────────────────────────┤
│ EVENT LOG (scrolling window)                                    │
│ ─────────────────────────────────────────────────────────────── │
│                                                                 │
│ 💬 "I'll add email validation to the login form..."            │
│                                                                 │
│ 📖 Reading src/components/LoginForm.tsx                        │
│ ✏️ Editing src/components/LoginForm.tsx                        │
│    └─ Added email format check                                  │
│ 📖 Reading src/utils/validation.ts                             │
│ ✏️ Editing src/utils/validation.ts                             │
│    └─ Added validateEmail function                              │
│                                                                 │
│ 💬 "Now I'll add tests..."                                     │
│                                                                 │
│ 📝 Creating tests/validation.test.ts                           │
│ 🔨 Running: npm test                                           │
│    └─ ✅ 15 passed                                             │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│ PROGRESS BAR (optional)                                         │
│ ─────────────────────────────────────────────────────────────── │
│ [████████████░░░░░░░░] 60%                                     │
├─────────────────────────────────────────────────────────────────┤
│ STATS LINE                                                      │
│ ─────────────────────────────────────────────────────────────── │
│ ⏱️ 45s • 📝 3 files • 🔄 6 turns                               │
├─────────────────────────────────────────────────────────────────┤
│ CONTROLS (inline keyboard)                                      │
│ ─────────────────────────────────────────────────────────────── │
│ [⏸️ Pause] [📋 Details] [⏹️ Cancel]                            │
└─────────────────────────────────────────────────────────────────┘
```

### Renderer Implementation

```python
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TrackerMessageState:
    """Current state of the tracker message."""

    # Identity
    job_id: str
    session_id: str
    project_name: str
    instruction: str

    # Message tracking
    message_id: int | None = None
    chat_id: int | None = None

    # Event buffer (most recent events)
    events: list[SessionEvent] = field(default_factory=list)

    # Stats
    start_time: datetime | None = None
    elapsed_seconds: int = 0
    files_touched: set[str] = field(default_factory=set)
    turn_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    # Status
    status: Literal["starting", "running", "waiting_approval", "done", "failed", "cancelled"] = "starting"
    final_result: str | None = None
    error: str | None = None

    # UI state
    updates_paused: bool = False
    last_update_time: datetime | None = None


class TrackerMessageRenderer:
    """Renders TrackerMessageState to Telegram message text."""

    def __init__(self, config: EventFilterConfig):
        self.config = config

    def render(self, state: TrackerMessageState) -> tuple[str, InlineKeyboardMarkup | None]:
        """Render state to message text and keyboard.

        Returns:
            Tuple of (message_text, keyboard_markup)
        """
        parts = []

        # Header
        parts.append(self._render_header(state))

        # Event log
        if state.events:
            parts.append(self._render_events(state.events))

        # Progress bar (if running)
        if state.status == "running":
            parts.append(self._render_progress_bar(state))

        # Stats line
        parts.append(self._render_stats(state))

        # Status-specific footer
        if state.status in ("done", "failed", "cancelled"):
            parts.append(self._render_completion(state))

        text = "\n".join(filter(None, parts))
        keyboard = self._render_keyboard(state)

        return text, keyboard

    def _render_header(self, state: TrackerMessageState) -> str:
        """Render the header section."""
        status_icon = {
            "starting": "🔄",
            "running": "🔧",
            "waiting_approval": "⏸️",
            "done": "✅",
            "failed": "❌",
            "cancelled": "⏹️",
        }.get(state.status, "❓")

        instr_display = state.instruction[:40]
        if len(state.instruction) > 40:
            instr_display += "..."

        return (
            f"{status_icon} *Job* `{state.job_id}` • `{state.session_id}` ({state.project_name})\n"
            f"📝 _{instr_display}_"
        )

    def _render_events(self, events: list[SessionEvent]) -> str:
        """Render the event log section."""
        lines = []

        # Apply max_events_displayed limit
        display_events = events[-self.config.max_events_displayed:]

        # Check if we truncated
        if len(events) > len(display_events):
            lines.append(f"_...{len(events) - len(display_events)} earlier events..._")

        for event in display_events:
            line = self._render_event(event)
            if line:
                lines.append(line)

        return "\n".join(lines) if lines else ""

    def _render_event(self, event: SessionEvent) -> str | None:
        """Render a single event based on config."""

        if isinstance(event, AISpeechEvent):
            if not self.config.show_ai_speech:
                return None
            text = event.text
            if self.config.ai_speech_max_length > 0:
                text = text[:self.config.ai_speech_max_length]
                if len(event.text) > self.config.ai_speech_max_length:
                    text += "..."
            return f"💬 _{text}_"

        elif isinstance(event, AIThinkingEvent):
            if not self.config.show_ai_thinking:
                return None
            text = event.thinking[:100] + "..."
            return f"🧠 _{text}_"

        elif isinstance(event, ToolStartEvent):
            if not self.config.show_tool_start:
                return None
            return self._render_tool_start(event)

        elif isinstance(event, ToolResultEvent):
            if event.is_error and self.config.show_tool_errors:
                return f"   └─ ❌ {event.result[:80]}"

            if not self.config.show_tool_result:
                if event.tool_name not in self.config.show_result_for_tools:
                    return None

            return self._render_tool_result(event)

        elif isinstance(event, ApprovalEvent):
            if not self.config.show_approvals:
                return None
            tool_cfg = TOOL_DISPLAY_CONFIG.get(event.tool_name, {})
            icon = tool_cfg.get("icon", "⚠️")
            return f"⏸️ *Approval needed*: {icon} {event.tool_name}"

        return None

    def _render_tool_start(self, event: ToolStartEvent) -> str:
        """Render a tool start event."""
        tool_cfg = TOOL_DISPLAY_CONFIG.get(event.tool_name, {})
        icon = tool_cfg.get("icon", "🔧")
        verb = tool_cfg.get("verb", event.tool_name)

        if self.config.tool_display_mode == "minimal":
            return icon

        # Build the main line
        parts = [icon, verb]

        # Add target based on tool type
        if self.config.show_file_paths and event.file_path:
            path = event.file_path
            if self.config.truncate_paths and len(path) > 40:
                path = "..." + path[-37:]
            parts.append(f"`{path}`")

        elif self.config.show_bash_commands and event.command:
            cmd = event.command
            if len(cmd) > self.config.bash_command_max_length:
                cmd = cmd[:self.config.bash_command_max_length] + "..."
            parts.append(f"`{cmd}`")

        elif event.description:
            parts.append(event.description[:50])

        return " ".join(parts)

    def _render_tool_result(self, event: ToolResultEvent) -> str | None:
        """Render a tool result event."""
        result = event.result

        # Parse special outputs
        if self.config.parse_test_output and event.tool_name == "Bash":
            parsed = self._parse_test_output(result)
            if parsed:
                return f"   └─ {parsed}"

        # Truncate
        if len(result) > self.config.result_max_length:
            result = result[:self.config.result_max_length] + "..."

        if event.success_indicator:
            return f"   └─ {event.success_indicator}"

        return f"   └─ {result}" if result.strip() else None

    def _parse_test_output(self, output: str) -> str | None:
        """Parse test output for pass/fail counts."""
        import re

        # pytest: "5 passed, 2 failed"
        pytest_match = re.search(r"(\d+) passed", output)
        if pytest_match:
            passed = pytest_match.group(1)
            failed_match = re.search(r"(\d+) failed", output)
            if failed_match:
                return f"❌ {passed} passed, {failed_match.group(1)} failed"
            return f"✅ {passed} passed"

        # jest: "Tests: 5 passed, 5 total"
        jest_match = re.search(r"Tests:\s*(\d+) passed", output)
        if jest_match:
            return f"✅ {jest_match.group(1)} passed"

        # npm test success
        if "npm test" in output.lower() and "error" not in output.lower():
            return "✅ Tests passed"

        return None

    def _render_progress_bar(self, state: TrackerMessageState) -> str:
        """Render progress bar based on activity."""
        # Estimate progress from events/turns
        activity = min(len(state.events) + state.turn_count, 20)
        filled = activity
        empty = 20 - filled
        bar = f"[{'█' * filled}{'░' * empty}]"
        return bar

    def _render_stats(self, state: TrackerMessageState) -> str:
        """Render the stats line."""
        parts = []

        if self.config.show_elapsed_time:
            mins, secs = divmod(state.elapsed_seconds, 60)
            if mins > 0:
                parts.append(f"⏱️ {mins}m {secs}s")
            else:
                parts.append(f"⏱️ {secs}s")

        if self.config.show_file_count and state.files_touched:
            count = len(state.files_touched)
            parts.append(f"📝 {count} file{'s' if count != 1 else ''}")

        if self.config.show_turn_count and state.turn_count > 0:
            parts.append(f"🔄 {state.turn_count} turns")

        if self.config.show_token_count:
            tokens = state.input_tokens + state.output_tokens
            if tokens > 1000:
                parts.append(f"🔤 {tokens // 1000}k tokens")

        if self.config.show_cost and state.cost_usd > 0:
            parts.append(f"💰 ${state.cost_usd:.3f}")

        return " • ".join(parts) if parts else ""

    def _render_completion(self, state: TrackerMessageState) -> str:
        """Render completion footer."""
        if state.status == "done":
            result = state.final_result or "Completed successfully"
            if len(result) > 200:
                result = result[:200] + "..."
            return f"\n✅ *Done*\n_{result}_"

        elif state.status == "failed":
            error = state.error or "Unknown error"
            return f"\n❌ *Failed*\n_{error}_"

        elif state.status == "cancelled":
            return "\n⏹️ *Cancelled*"

        return ""

    def _render_keyboard(self, state: TrackerMessageState) -> InlineKeyboardMarkup | None:
        """Render inline keyboard controls."""
        if state.status in ("done", "failed", "cancelled"):
            # Show post-completion buttons
            return InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📋 Summary", callback_data=f"tracker:summary:{state.job_id}"),
                    InlineKeyboardButton("📜 Logs", callback_data=f"tracker:logs:{state.job_id}"),
                ]
            ])

        # Running state buttons
        buttons = []

        if state.updates_paused:
            buttons.append(
                InlineKeyboardButton("▶️ Resume", callback_data=f"tracker:resume:{state.job_id}")
            )
        else:
            buttons.append(
                InlineKeyboardButton("⏸️ Pause", callback_data=f"tracker:pause:{state.job_id}")
            )

        buttons.append(
            InlineKeyboardButton("⏹️ Cancel", callback_data=f"tracker:cancel:{state.job_id}")
        )

        return InlineKeyboardMarkup([buttons])
```

---

## Rate Limiting & Buffering

### Rate Limiter

```python
import asyncio
from datetime import datetime, timedelta


class TelegramRateLimiter:
    """Rate limiter for Telegram message edits.

    Telegram limits: ~30 edits per minute per message, ~1 edit per second.
    """

    def __init__(
        self,
        min_interval_ms: int = 1000,      # Minimum time between edits
        burst_limit: int = 3,              # Max rapid edits allowed
        burst_window_ms: int = 3000,       # Window for burst counting
    ):
        self.min_interval = timedelta(milliseconds=min_interval_ms)
        self.burst_limit = burst_limit
        self.burst_window = timedelta(milliseconds=burst_window_ms)

        # Per-message tracking
        self._last_edit: dict[int, datetime] = {}  # message_id -> last edit time
        self._edit_times: dict[int, list[datetime]] = {}  # message_id -> recent edit times

    async def acquire(self, message_id: int) -> bool:
        """Wait until we can edit the message.

        Returns:
            True if edit is allowed, False if should skip.
        """
        now = datetime.now()

        # Check minimum interval
        if message_id in self._last_edit:
            elapsed = now - self._last_edit[message_id]
            if elapsed < self.min_interval:
                wait_time = (self.min_interval - elapsed).total_seconds()
                await asyncio.sleep(wait_time)

        # Check burst limit
        if message_id in self._edit_times:
            # Clean old entries
            cutoff = now - self.burst_window
            self._edit_times[message_id] = [
                t for t in self._edit_times[message_id] if t > cutoff
            ]

            if len(self._edit_times[message_id]) >= self.burst_limit:
                # At burst limit, wait for window to pass
                oldest = self._edit_times[message_id][0]
                wait_time = (oldest + self.burst_window - now).total_seconds()
                if wait_time > 0:
                    await asyncio.sleep(wait_time)

        # Record this edit
        self._last_edit[message_id] = datetime.now()
        self._edit_times.setdefault(message_id, []).append(datetime.now())

        return True

    def cleanup(self, message_id: int):
        """Clean up tracking for a message."""
        self._last_edit.pop(message_id, None)
        self._edit_times.pop(message_id, None)
```

### Event Buffer

```python
@dataclass
class EventBuffer:
    """Buffers events and triggers updates at appropriate intervals."""

    config: EventFilterConfig
    rate_limiter: TelegramRateLimiter

    # Pending events
    _pending_events: list[SessionEvent] = field(default_factory=list)
    _last_flush: datetime | None = None

    # Callbacks
    on_flush: Callable[[list[SessionEvent]], Awaitable[None]] | None = None

    async def add_event(self, event: SessionEvent):
        """Add event to buffer."""
        # Apply filter
        if not self._should_include(event):
            return

        self._pending_events.append(event)

        # Check if we should flush
        should_flush = (
            # Important events flush immediately
            isinstance(event, (ApprovalEvent, SystemResultEvent)) or
            event.category == EventCategory.TOOL_ERROR or
            # Or we have enough events
            len(self._pending_events) >= 3 or
            # Or enough time has passed
            (self._last_flush and
             (datetime.now() - self._last_flush).total_seconds() > 2)
        )

        if should_flush:
            await self.flush()

    async def flush(self):
        """Flush pending events to callback."""
        if not self._pending_events or not self.on_flush:
            return

        events = self._pending_events.copy()
        self._pending_events.clear()
        self._last_flush = datetime.now()

        await self.on_flush(events)

    def _should_include(self, event: SessionEvent) -> bool:
        """Check if event passes filter."""
        cfg = self.config

        if isinstance(event, AISpeechEvent):
            return cfg.show_ai_speech

        if isinstance(event, AIThinkingEvent):
            return cfg.show_ai_thinking

        if isinstance(event, ToolStartEvent):
            if not cfg.show_tool_start:
                return False
            if cfg.tool_whitelist and event.tool_name not in cfg.tool_whitelist:
                return False
            if event.tool_name in cfg.tool_blacklist:
                return False
            return True

        if isinstance(event, ToolResultEvent):
            if event.is_error:
                return cfg.show_tool_errors
            if cfg.show_tool_result:
                return True
            return event.tool_name in cfg.show_result_for_tools

        if isinstance(event, ApprovalEvent):
            return cfg.show_approvals

        return True
```

---

## Tracker Manager

### Lifecycle Management

```python
class JobTrackerManager:
    """Manages job tracker messages across all jobs."""

    def __init__(
        self,
        bot: Bot,
        config: EventFilterConfig,
    ):
        self.bot = bot
        self.config = config
        self.rate_limiter = TelegramRateLimiter()
        self.renderer = TrackerMessageRenderer(config)

        # Active trackers: job_id -> TrackerMessageState
        self._trackers: dict[str, TrackerMessageState] = {}

    async def create_tracker(
        self,
        chat_id: int,
        job_id: str,
        session_id: str,
        project_name: str,
        instruction: str,
    ) -> TrackerMessageState:
        """Create a new tracker message for a job."""

        state = TrackerMessageState(
            job_id=job_id,
            session_id=session_id,
            project_name=project_name,
            instruction=instruction,
            chat_id=chat_id,
            start_time=datetime.now(),
        )

        # Render initial message
        text, keyboard = self.renderer.render(state)

        # Send message
        msg = await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

        state.message_id = msg.message_id
        self._trackers[job_id] = state

        return state

    async def add_event(self, job_id: str, event: SessionEvent):
        """Add an event to a job's tracker."""
        state = self._trackers.get(job_id)
        if not state or state.updates_paused:
            return

        # Add event
        state.events.append(event)

        # Update stats based on event type
        if isinstance(event, ToolStartEvent):
            if event.file_path:
                state.files_touched.add(event.file_path)

        elif isinstance(event, SystemResultEvent):
            state.turn_count = event.num_turns
            state.cost_usd = event.cost_usd or 0
            state.input_tokens = event.input_tokens
            state.output_tokens = event.output_tokens
            state.status = "failed" if event.is_error else "done"
            if event.is_error:
                state.error = event.error_message

        # Update elapsed time
        if state.start_time:
            state.elapsed_seconds = int(
                (datetime.now() - state.start_time).total_seconds()
            )

        # Rate-limited update
        await self._update_message(state)

    async def _update_message(self, state: TrackerMessageState):
        """Update the tracker message (rate-limited)."""
        if not state.message_id or not state.chat_id:
            return

        # Acquire rate limit slot
        await self.rate_limiter.acquire(state.message_id)

        # Render and update
        text, keyboard = self.renderer.render(state)

        try:
            await self.bot.edit_message_text(
                chat_id=state.chat_id,
                message_id=state.message_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            state.last_update_time = datetime.now()
        except BadRequest as e:
            if "message is not modified" not in str(e).lower():
                raise

    async def pause_updates(self, job_id: str):
        """Pause updates for a tracker."""
        state = self._trackers.get(job_id)
        if state:
            state.updates_paused = True
            await self._update_message(state)

    async def resume_updates(self, job_id: str):
        """Resume updates for a tracker."""
        state = self._trackers.get(job_id)
        if state:
            state.updates_paused = False
            await self._update_message(state)

    async def complete_tracker(
        self,
        job_id: str,
        status: Literal["done", "failed", "cancelled"],
        result: str | None = None,
        error: str | None = None,
    ):
        """Mark a tracker as complete."""
        state = self._trackers.get(job_id)
        if not state:
            return

        state.status = status
        state.final_result = result
        state.error = error

        # Final update (bypass rate limit)
        await self.rate_limiter.acquire(state.message_id)
        text, keyboard = self.renderer.render(state)

        try:
            await self.bot.edit_message_text(
                chat_id=state.chat_id,
                message_id=state.message_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        except BadRequest:
            pass

        # Cleanup
        self.rate_limiter.cleanup(state.message_id)

    def get_tracker(self, job_id: str) -> TrackerMessageState | None:
        """Get tracker state for a job."""
        return self._trackers.get(job_id)

    def remove_tracker(self, job_id: str):
        """Remove a tracker (cleanup)."""
        state = self._trackers.pop(job_id, None)
        if state and state.message_id:
            self.rate_limiter.cleanup(state.message_id)
```

---

## Integration Points

### 1. Executor Integration

```python
# In executor.py or sdk_executor.py

async def execute_job(self, job: Job) -> Job:
    # ... existing setup ...

    # Create tracker
    tracker_manager: JobTrackerManager = self.tracker_manager
    tracker = await tracker_manager.create_tracker(
        chat_id=job.chat_id,  # Need to pass this
        job_id=job.job_id,
        session_id=job.session_id,
        project_name=project.name,
        instruction=job.instruction,
    )

    # Parse events and feed to tracker
    async for line in self._stream_output(proc, log_file):
        event = self._parse_event(line)
        if event:
            await tracker_manager.add_event(job.job_id, event)

    # Complete tracker
    await tracker_manager.complete_tracker(
        job_id=job.job_id,
        status="done" if job.status == JobStatus.DONE else "failed",
        result=job.result_summary,
        error=job.error,
    )
```

### 2. Handler Integration

```python
# In handlers.py

async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... existing code ...

    # Get or create tracker manager
    tracker_manager = context.bot_data.get("tracker_manager")
    if not tracker_manager:
        config = get_tracker_config(context)  # From settings
        tracker_manager = JobTrackerManager(context.bot, config)
        context.bot_data["tracker_manager"] = tracker_manager

    # Run job with tracker
    job = await run_instruction(
        db=db,
        settings=settings,
        session_id=session_id,
        instruction=instruction,
        tracker_manager=tracker_manager,
        chat_id=chat_id,
    )
```

### 3. Callback Handlers

```python
async def tracker_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle tracker button callbacks."""
    query = update.callback_query
    await query.answer()

    # Parse: tracker:ACTION:JOB_ID
    parts = query.data.split(":")
    if len(parts) != 3:
        return

    _, action, job_id = parts
    tracker_manager: JobTrackerManager = context.bot_data.get("tracker_manager")

    if action == "pause":
        await tracker_manager.pause_updates(job_id)

    elif action == "resume":
        await tracker_manager.resume_updates(job_id)

    elif action == "cancel":
        # Cancel the job
        db = get_db(context)
        await cancel_job(db, job_id)
        await tracker_manager.complete_tracker(job_id, "cancelled")

    elif action == "summary":
        # Show job summary
        db = get_db(context)
        summary = await get_job_summary(db, job_id)
        await query.message.reply_text(format_summary(summary))

    elif action == "logs":
        # Show job logs
        db = get_db(context)
        logs = await get_job_logs(db, job_id, tail=30)
        await query.message.reply_text(f"```\n{logs}\n```", parse_mode="Markdown")
```

---

## Configuration Storage

### Per-Chat Preferences

```python
# In state.py or preferences.py

@dataclass
class ChatPreferences:
    """Per-chat preferences including tracker config."""

    chat_id: int

    # Model preferences
    preferred_model: str | None = None

    # Tracker preferences
    tracker_preset: str = "normal"
    tracker_config_overrides: dict = field(default_factory=dict)

    def get_tracker_config(self) -> EventFilterConfig:
        """Get effective tracker config for this chat."""
        base = PRESETS.get(self.tracker_preset, PRESETS["normal"])

        # Apply overrides
        if self.tracker_config_overrides:
            return dataclasses.replace(base, **self.tracker_config_overrides)

        return base


# Commands to configure
async def tracker_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /tracker command - configure tracker display.

    Usage:
        /tracker              - Show current config
        /tracker preset       - Set preset (minimal/normal/verbose/debug)
        /tracker show X       - Toggle showing X (ai_speech, tools, results, etc.)
        /tracker hide X       - Toggle hiding X
    """
    # Implementation...
```

---

## Summary

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| One message per job | Yes | Clear tracking, edit by message_id |
| Event filtering | Config-based | Users have different preferences |
| Rate limiting | 1 edit/sec + burst | Respect Telegram limits |
| Event buffering | 2-3 second window | Batch updates, reduce API calls |
| Presets | 4 levels | Easy defaults, fine-tune if needed |
| Persistence | Per-chat | Different users, different needs |

### Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/televibecode/tracker/events.py` | Event dataclasses |
| `src/televibecode/tracker/config.py` | EventFilterConfig + presets |
| `src/televibecode/tracker/renderer.py` | TrackerMessageRenderer |
| `src/televibecode/tracker/manager.py` | JobTrackerManager |
| `src/televibecode/tracker/rate_limiter.py` | TelegramRateLimiter |
| `src/televibecode/runner/executor.py` | Integration with tracker |
| `src/televibecode/telegram/handlers.py` | Callback handlers |
| `src/televibecode/telegram/state.py` | ChatPreferences |

### Next Steps

1. Implement event parsing from stream-json
2. Create EventFilterConfig with presets
3. Build TrackerMessageRenderer
4. Add rate limiter
5. Create JobTrackerManager
6. Integrate with executors
7. Add /tracker config command
8. Add callback handlers for buttons
