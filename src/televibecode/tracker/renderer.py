"""Renderer for job tracker messages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from televibecode.tracker.config import TrackerConfig
from televibecode.tracker.events import (
    AISpeechEvent,
    AIThinkingEvent,
    ApprovalEvent,
    SessionEvent,
    ToolResultEvent,
    ToolStartEvent,
    get_tool_icon,
    get_tool_verb,
)

if TYPE_CHECKING:
    pass


@dataclass
class TrackerState:
    """Current state of a job tracker message."""

    # Identity
    job_id: str
    session_id: str
    project_name: str
    instruction: str

    # Message tracking
    message_id: int | None = None
    chat_id: int | None = None

    # Event buffer
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
    status: Literal[
        "starting", "running", "waiting_approval", "done", "failed", "cancelled"
    ] = "starting"
    final_result: str | None = None
    error: str | None = None

    # UI state
    updates_paused: bool = False
    last_update_time: datetime | None = None


class TrackerRenderer:
    """Renders TrackerState to Telegram message."""

    def __init__(self, config: TrackerConfig):
        self.config = config

    def render(
        self, state: TrackerState
    ) -> tuple[str, InlineKeyboardMarkup | None]:
        """Render state to message text and keyboard.

        Returns:
            Tuple of (message_text, keyboard_markup).
        """
        parts = []

        # Header
        parts.append(self._render_header(state))

        # Separator
        parts.append("")

        # Event log
        event_log = self._render_events(state.events)
        if event_log:
            parts.append(event_log)
            parts.append("")

        # Progress bar (if running)
        if state.status == "running" and self.config.show_progress_bar:
            parts.append(self._render_progress_bar(state))

        # Stats line
        stats = self._render_stats(state)
        if stats:
            parts.append(stats)

        # Completion footer
        if state.status in ("done", "failed", "cancelled"):
            parts.append(self._render_completion(state))

        text = "\n".join(filter(lambda x: x is not None, parts))

        # Enforce Telegram limit
        if len(text) > 4000:
            text = text[:3950] + "\n\n_...truncated_"

        keyboard = self._render_keyboard(state)

        return text, keyboard

    def _render_header(self, state: TrackerState) -> str:
        """Render the header section."""
        status_icons = {
            "starting": "🔄",
            "running": "🔧",
            "waiting_approval": "⏸️",
            "done": "✅",
            "failed": "❌",
            "cancelled": "⏹️",
        }
        icon = status_icons.get(state.status, "❓")

        instr = state.instruction[:40]
        if len(state.instruction) > 40:
            instr += "..."

        header = f"{icon} *Job* `{state.job_id}` • `{state.session_id}`"
        return f"{header} ({state.project_name})\n📝 _{instr}_"

    def _render_events(self, events: list[SessionEvent]) -> str | None:
        """Render the event log section."""
        if not events:
            return None

        lines = []
        max_events = self.config.max_events_displayed

        # Get events to display
        display_events = events[-max_events:]

        # Show truncation indicator
        if len(events) > max_events:
            lines.append(f"_...{len(events) - max_events} earlier_")

        # Collapse repeated tools if enabled
        if self.config.collapse_repeated_tools:
            display_events = self._collapse_repeated(display_events)

        for event in display_events:
            line = self._render_event(event)
            if line:
                lines.append(line)

        return "\n".join(lines) if lines else None

    def _collapse_repeated(
        self, events: list[SessionEvent]
    ) -> list[SessionEvent | tuple[str, int, list[str]]]:
        """Collapse repeated tool events."""
        result: list[SessionEvent | tuple[str, int, list[str]]] = []
        current_tool: str | None = None
        current_count = 0
        current_files: list[str] = []

        for event in events:
            if isinstance(event, ToolStartEvent):
                if event.tool_name == current_tool and current_tool in (
                    "Read",
                    "Glob",
                    "Grep",
                ):
                    current_count += 1
                    if event.file_path:
                        current_files.append(event.file_path)
                else:
                    # Flush previous
                    if current_count > 1:
                        result.append((current_tool, current_count, current_files))
                    elif current_count == 1:
                        # Add the single event back
                        pass  # Already in result
                    current_tool = event.tool_name
                    current_count = 1
                    current_files = [event.file_path] if event.file_path else []
                    result.append(event)
            else:
                # Flush tool group
                should_collapse = (
                    current_count > 1
                    and result
                    and isinstance(result[-1], ToolStartEvent)
                )
                if should_collapse:
                    # Replace last item with collapsed
                    result[-1] = (current_tool, current_count, current_files)
                current_tool = None
                current_count = 0
                current_files = []
                result.append(event)

        # Final flush
        if current_count > 1 and result:
            last = result[-1]
            if isinstance(last, ToolStartEvent):
                result[-1] = (current_tool, current_count, current_files)

        return result

    def _render_event(
        self, event: SessionEvent | tuple[str, int, list[str]]
    ) -> str | None:
        """Render a single event."""
        # Handle collapsed events
        if isinstance(event, tuple):
            tool_name, count, files = event
            icon = get_tool_icon(tool_name)
            return f"{icon} {tool_name} ×{count}"

        if isinstance(event, AISpeechEvent):
            if not self.config.show_ai_speech:
                return None
            text = event.text
            max_len = self.config.ai_speech_max_length
            if max_len > 0 and len(text) > max_len:
                text = text[:max_len] + "..."
            # Escape markdown
            text = text.replace("_", "\\_").replace("*", "\\*")
            return f"💬 _{text}_"

        if isinstance(event, AIThinkingEvent):
            if not self.config.show_ai_thinking:
                return None
            text = event.thinking[:80] + "..."
            return f"🧠 _{text}_"

        if isinstance(event, ToolStartEvent):
            if not self.config.show_tool_start:
                return None
            return self._render_tool_start(event)

        if isinstance(event, ToolResultEvent):
            if event.is_error and self.config.show_tool_errors:
                err = event.result[:80]
                return f"   └─ ❌ {err}"

            show_result = self.config.show_tool_result
            show_for_tool = event.tool_name in self.config.show_result_for_tools
            if not show_result and not show_for_tool:
                return None

            return self._render_tool_result(event)

        if isinstance(event, ApprovalEvent):
            if not self.config.show_approvals:
                return None
            icon = get_tool_icon(event.tool_name)
            return f"⏸️ *Waiting*: {icon} {event.tool_name}"

        return None

    def _render_tool_start(self, event: ToolStartEvent) -> str:
        """Render a tool start event."""
        icon = get_tool_icon(event.tool_name)
        verb = get_tool_verb(event.tool_name)

        if self.config.tool_display_mode == "minimal":
            return icon

        parts = [icon, verb]

        # Add target based on tool
        if self.config.show_file_paths and event.file_path:
            path = self._truncate_path(event.file_path)
            parts.append(f"`{path}`")

        elif self.config.show_bash_commands and event.command:
            cmd = event.command
            max_len = self.config.bash_command_max_length
            if len(cmd) > max_len:
                cmd = cmd[:max_len] + "..."
            parts.append(f"`{cmd}`")

        elif event.pattern:
            parts.append(f"`{event.pattern[:30]}`")

        elif event.url:
            url = event.url
            if len(url) > 40:
                url = url[:40] + "..."
            parts.append(url)

        elif event.query:
            parts.append(f'"{event.query[:30]}"')

        elif event.description:
            parts.append(event.description[:40])

        return " ".join(parts)

    def _render_tool_result(self, event: ToolResultEvent) -> str | None:
        """Render a tool result."""
        result = event.result

        # Parse test output
        if self.config.parse_test_output and event.tool_name == "Bash":
            parsed = self._parse_test_output(result)
            if parsed:
                return f"   └─ {parsed}"

        # Truncate
        max_len = self.config.result_max_length
        if len(result) > max_len:
            result = result[:max_len] + "..."

        if result.strip():
            return f"   └─ {result}"
        return None

    def _parse_test_output(self, output: str) -> str | None:
        """Parse test output for pass/fail."""
        # pytest
        match = re.search(r"(\d+) passed", output)
        if match:
            passed = match.group(1)
            failed = re.search(r"(\d+) failed", output)
            if failed:
                return f"❌ {passed} passed, {failed.group(1)} failed"
            return f"✅ {passed} passed"

        # jest
        match = re.search(r"Tests:\s*(\d+) passed", output)
        if match:
            return f"✅ {match.group(1)} passed"

        # npm/generic
        if "error" in output.lower():
            return "❌ Error"
        if "success" in output.lower() or "passed" in output.lower():
            return "✅ Success"

        return None

    def _truncate_path(self, path: str) -> str:
        """Truncate a file path."""
        if not self.config.truncate_paths:
            return path
        max_len = self.config.path_max_length
        if len(path) <= max_len:
            return path
        return "..." + path[-(max_len - 3) :]

    def _render_progress_bar(self, state: TrackerState) -> str:
        """Render progress bar."""
        # Estimate progress from events
        activity = min(len(state.events) + state.turn_count, 20)
        filled = activity
        empty = 20 - filled
        return f"[{'█' * filled}{'░' * empty}]"

    def _render_stats(self, state: TrackerState) -> str | None:
        """Render stats line."""
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
            parts.append(f"🔄 {state.turn_count}")

        if self.config.show_token_count:
            tokens = state.input_tokens + state.output_tokens
            if tokens > 0:
                if tokens > 1000:
                    parts.append(f"🔤 {tokens // 1000}k")
                else:
                    parts.append(f"🔤 {tokens}")

        if self.config.show_cost and state.cost_usd > 0:
            parts.append(f"💰 ${state.cost_usd:.3f}")

        return " • ".join(parts) if parts else None

    def _render_completion(self, state: TrackerState) -> str:
        """Render completion footer."""
        if state.status == "done":
            result = state.final_result or "Completed"
            if len(result) > 150:
                result = result[:150] + "..."
            return f"\n✅ *Done*\n_{result}_"

        if state.status == "failed":
            error = state.error or "Unknown error"
            if len(error) > 150:
                error = error[:150] + "..."
            return f"\n❌ *Failed*\n_{error}_"

        if state.status == "cancelled":
            return "\n⏹️ *Cancelled*"

        return ""

    def _render_keyboard(
        self, state: TrackerState
    ) -> InlineKeyboardMarkup | None:
        """Render inline keyboard."""
        if state.status in ("done", "failed", "cancelled"):
            return InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📋 Summary",
                            callback_data=f"tracker:summary:{state.job_id}",
                        ),
                        InlineKeyboardButton(
                            "📜 Logs",
                            callback_data=f"tracker:logs:{state.job_id}",
                        ),
                    ]
                ]
            )

        # Running state
        buttons = []

        if state.updates_paused:
            buttons.append(
                InlineKeyboardButton(
                    "▶️ Resume",
                    callback_data=f"tracker:resume:{state.job_id}",
                )
            )
        else:
            buttons.append(
                InlineKeyboardButton(
                    "⏸️ Pause",
                    callback_data=f"tracker:pause:{state.job_id}",
                )
            )

        buttons.append(
            InlineKeyboardButton(
                "⏹️ Cancel",
                callback_data=f"tracker:cancel:{state.job_id}",
            )
        )

        return InlineKeyboardMarkup([buttons])
