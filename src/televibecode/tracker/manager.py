"""Job tracker manager for Telegram messages."""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal

import structlog
from telegram import Bot
from telegram.error import BadRequest

from televibecode.tracker.config import TrackerConfig
from televibecode.tracker.events import (
    AISpeechEvent,
    AIThinkingEvent,
    ApprovalEvent,
    EventCategory,
    SessionEvent,
    SystemInitEvent,
    SystemResultEvent,
    ToolResultEvent,
    ToolStartEvent,
)
from televibecode.tracker.renderer import TrackerRenderer, TrackerState

if TYPE_CHECKING:
    pass

log = structlog.get_logger()


class RateLimiter:
    """Rate limiter for Telegram message edits.

    Telegram limits ~30 edits/min per message, ~1 edit/sec.
    """

    def __init__(self, min_interval_ms: int = 1500):
        self.min_interval = timedelta(milliseconds=min_interval_ms)
        self._last_edit: dict[int, datetime] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self, message_id: int) -> asyncio.Lock:
        """Get or create lock for message."""
        if message_id not in self._locks:
            self._locks[message_id] = asyncio.Lock()
        return self._locks[message_id]

    async def acquire(self, message_id: int) -> None:
        """Wait until we can edit the message."""
        lock = self._get_lock(message_id)
        async with lock:
            now = datetime.now(timezone.utc)
            if message_id in self._last_edit:
                elapsed = now - self._last_edit[message_id]
                if elapsed < self.min_interval:
                    wait_secs = (self.min_interval - elapsed).total_seconds()
                    await asyncio.sleep(wait_secs)
            self._last_edit[message_id] = datetime.now(timezone.utc)

    def cleanup(self, message_id: int) -> None:
        """Clean up tracking for a message."""
        self._last_edit.pop(message_id, None)
        self._locks.pop(message_id, None)


class JobTrackerManager:
    """Manages job tracker messages across all jobs."""

    def __init__(self, bot: Bot, default_config: TrackerConfig | None = None):
        """Initialize the tracker manager.

        Args:
            bot: Telegram bot instance.
            default_config: Default tracker config (used if no per-chat config).
        """
        self.bot = bot
        self.default_config = default_config or TrackerConfig()
        self.rate_limiter = RateLimiter(self.default_config.update_interval_ms)

        # Per-chat configs: chat_id -> TrackerConfig
        self._chat_configs: dict[int, TrackerConfig] = {}

        # Active trackers: job_id -> TrackerState
        self._trackers: dict[str, TrackerState] = {}

        # Pending tool starts (to match with results)
        self._pending_tools: dict[str, ToolStartEvent] = {}

    def set_chat_config(self, chat_id: int, config: TrackerConfig) -> None:
        """Set tracker config for a chat."""
        self._chat_configs[chat_id] = config
        log.info("tracker_config_set", chat_id=chat_id)

    def get_chat_config(self, chat_id: int) -> TrackerConfig:
        """Get tracker config for a chat."""
        return self._chat_configs.get(chat_id, self.default_config)

    def get_renderer(self, chat_id: int) -> TrackerRenderer:
        """Get renderer for a chat."""
        config = self.get_chat_config(chat_id)
        return TrackerRenderer(config)

    async def create_tracker(
        self,
        chat_id: int,
        job_id: str,
        session_id: str,
        project_name: str,
        instruction: str,
    ) -> TrackerState:
        """Create a new tracker message for a job.

        Args:
            chat_id: Telegram chat ID.
            job_id: Job identifier.
            session_id: Session identifier.
            project_name: Project name.
            instruction: Job instruction.

        Returns:
            TrackerState for the job.
        """
        state = TrackerState(
            job_id=job_id,
            session_id=session_id,
            project_name=project_name,
            instruction=instruction,
            chat_id=chat_id,
            start_time=datetime.now(timezone.utc),
        )

        # Render and send initial message
        renderer = self.get_renderer(chat_id)
        text, keyboard = renderer.render(state)

        try:
            msg = await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            state.message_id = msg.message_id
        except Exception as e:
            log.error("tracker_create_failed", job_id=job_id, error=str(e))
            raise

        self._trackers[job_id] = state
        log.info(
            "tracker_created",
            job_id=job_id,
            message_id=state.message_id,
            chat_id=chat_id,
        )

        return state

    async def add_event(self, job_id: str, event: SessionEvent) -> None:
        """Add an event to a job's tracker.

        Args:
            job_id: Job identifier.
            event: Event to add.
        """
        state = self._trackers.get(job_id)
        if not state:
            return

        if state.updates_paused and event.category not in (
            EventCategory.SYSTEM,
            EventCategory.TOOL_ERROR,
        ):
            return

        # Apply filter
        if state.chat_id:
            config = self.get_chat_config(state.chat_id)
        else:
            config = self.default_config
        if not self._should_include(event, config):
            return

        # Track tool starts for result matching
        if isinstance(event, ToolStartEvent):
            self._pending_tools[event.tool_use_id] = event

        # Enrich tool results with tool name
        is_tool_result = isinstance(event, ToolResultEvent)
        if is_tool_result and event.tool_use_id in self._pending_tools:
            start_event = self._pending_tools.pop(event.tool_use_id)
            event.tool_name = start_event.tool_name

        # Add to state
        state.events.append(event)

        # Update stats
        self._update_stats(state, event)

        # Update message
        await self._update_message(state)

    def _should_include(self, event: SessionEvent, config: TrackerConfig) -> bool:
        """Check if event passes filter."""
        if isinstance(event, AISpeechEvent):
            return config.show_ai_speech

        if isinstance(event, AIThinkingEvent):
            return config.show_ai_thinking

        if isinstance(event, ToolStartEvent):
            if not config.show_tool_start:
                return False
            if config.tool_whitelist and event.tool_name not in config.tool_whitelist:
                return False
            return event.tool_name not in config.tool_blacklist

        if isinstance(event, ToolResultEvent):
            if event.is_error:
                return config.show_tool_errors
            if config.show_tool_result:
                return True
            return event.tool_name in config.show_result_for_tools

        if isinstance(event, ApprovalEvent):
            return config.show_approvals

        # System events always included
        if isinstance(event, (SystemInitEvent, SystemResultEvent)):
            return True

        return True

    def _update_stats(self, state: TrackerState, event: SessionEvent) -> None:
        """Update stats based on event."""
        if isinstance(event, ToolStartEvent):
            if event.file_path:
                state.files_touched.add(event.file_path)

        elif isinstance(event, SystemResultEvent):
            state.turn_count = event.num_turns
            state.cost_usd = event.cost_usd or 0
            state.input_tokens = event.input_tokens
            state.output_tokens = event.output_tokens

        # Update elapsed time
        if state.start_time:
            state.elapsed_seconds = int(
                (datetime.now(timezone.utc) - state.start_time).total_seconds()
            )

    async def _update_message(self, state: TrackerState) -> None:
        """Update the tracker message (rate-limited)."""
        if not state.message_id or not state.chat_id:
            return

        # Rate limit
        await self.rate_limiter.acquire(state.message_id)

        # Render
        renderer = self.get_renderer(state.chat_id)
        text, keyboard = renderer.render(state)

        try:
            await self.bot.edit_message_text(
                chat_id=state.chat_id,
                message_id=state.message_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            state.last_update_time = datetime.now(timezone.utc)
        except BadRequest as e:
            if "message is not modified" not in str(e).lower():
                log.warning(
                    "tracker_update_failed",
                    job_id=state.job_id,
                    error=str(e),
                )

    async def set_status(
        self,
        job_id: str,
        status: Literal["running", "waiting_approval", "done", "failed", "cancelled"],
    ) -> None:
        """Update tracker status."""
        state = self._trackers.get(job_id)
        if not state:
            return

        state.status = status
        await self._update_message(state)

    async def pause_updates(self, job_id: str) -> None:
        """Pause updates for a tracker."""
        state = self._trackers.get(job_id)
        if state:
            state.updates_paused = True
            await self._update_message(state)

    async def resume_updates(self, job_id: str) -> None:
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
        files_changed: list[str] | None = None,
        send_completion_reply: bool = True,
    ) -> None:
        """Mark a tracker as complete.

        Args:
            job_id: Job identifier.
            status: Completion status.
            result: Result summary (for done status).
            error: Error message (for failed status).
            files_changed: List of files modified.
            send_completion_reply: Send a reply to the tracker message.
        """
        state = self._trackers.get(job_id)
        if not state:
            return

        state.status = status
        state.final_result = result
        state.error = error

        # Force final update to tracker message
        if state.message_id:
            await self.rate_limiter.acquire(state.message_id)

            if state.chat_id:
                renderer = self.get_renderer(state.chat_id)
            else:
                renderer = TrackerRenderer(self.default_config)
            text, keyboard = renderer.render(state)

            with contextlib.suppress(BadRequest):
                await self.bot.edit_message_text(
                    chat_id=state.chat_id,
                    message_id=state.message_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )

            # Send completion reply message
            if send_completion_reply and state.chat_id:
                await self._send_completion_reply(
                    state, status, result, error, files_changed
                )

            # Cleanup rate limiter
            self.rate_limiter.cleanup(state.message_id)

        log.info(
            "tracker_completed",
            job_id=job_id,
            status=status,
        )

    async def _send_completion_reply(
        self,
        state: TrackerState,
        status: str,
        result: str | None,
        error: str | None,
        files_changed: list[str] | None,
    ) -> None:
        """Send a completion message as a reply to the tracker message."""
        if not state.chat_id or not state.message_id:
            return

        # Build completion message
        if status == "done":
            icon = "✅"
            title = "Job Completed"
            body_parts = []

            if files_changed:
                count = len(files_changed)
                plural = "s" if count != 1 else ""
                body_parts.append(f"📝 Modified {count} file{plural}")
                # Show first few files
                for f in files_changed[:3]:
                    short = f if len(f) <= 40 else "..." + f[-37:]
                    body_parts.append(f"   • `{short}`")
                if len(files_changed) > 3:
                    remaining = len(files_changed) - 3
                    body_parts.append(f"   _...and {remaining} more_")

            if result:
                summary = result[:200]
                if len(result) > 200:
                    summary += "..."
                body_parts.append(f"\n💬 _{summary}_")

            if body_parts:
                body = "\n".join(body_parts)
            else:
                body = "Task completed successfully."

        elif status == "failed":
            icon = "❌"
            title = "Job Failed"
            err_msg = error or "Unknown error"
            if len(err_msg) > 200:
                err_msg = err_msg[:200] + "..."
            body = f"_{err_msg}_"

        else:  # cancelled
            icon = "⏹️"
            title = "Job Cancelled"
            body = "The job was cancelled."

        # Stats
        stats_parts = []
        if state.elapsed_seconds > 0:
            mins, secs = divmod(state.elapsed_seconds, 60)
            if mins > 0:
                stats_parts.append(f"⏱️ {mins}m {secs}s")
            else:
                stats_parts.append(f"⏱️ {secs}s")

        if state.turn_count > 0:
            stats_parts.append(f"🔄 {state.turn_count} turns")

        config = self.get_chat_config(state.chat_id)
        if config.show_cost and state.cost_usd > 0:
            stats_parts.append(f"💰 ${state.cost_usd:.3f}")

        stats_line = " • ".join(stats_parts) if stats_parts else ""

        # Full message
        text = f"{icon} *{title}*\n\n{body}"
        if stats_line:
            text += f"\n\n{stats_line}"

        text += f"\n\n`/summary {state.job_id}` • `/tail {state.job_id}`"

        try:
            await self.bot.send_message(
                chat_id=state.chat_id,
                text=text,
                parse_mode="Markdown",
                reply_to_message_id=state.message_id,
            )
        except Exception as e:
            log.warning(
                "completion_reply_failed",
                job_id=state.job_id,
                error=str(e),
            )

    def get_tracker(self, job_id: str) -> TrackerState | None:
        """Get tracker state for a job."""
        return self._trackers.get(job_id)

    def remove_tracker(self, job_id: str) -> None:
        """Remove a tracker."""
        state = self._trackers.pop(job_id, None)
        if state and state.message_id:
            self.rate_limiter.cleanup(state.message_id)


def parse_stream_event(line: str, job_id: str | None = None) -> SessionEvent | None:
    """Parse a stream-json line into a SessionEvent.

    Args:
        line: JSON line from Claude Code stream-json output.
        job_id: Job ID to attach to events.

    Returns:
        SessionEvent or None if not parseable.
    """
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    event_type = data.get("type")
    session_id = data.get("session_id")

    # System events
    if event_type == "system":
        subtype = data.get("subtype")
        if subtype == "init":
            return SystemInitEvent(
                session_id=session_id,
                job_id=job_id,
                tools=data.get("tools", []),
                cwd=data.get("cwd"),
            )

    # Result event
    if event_type == "result":
        subtype = data.get("subtype", "success")
        usage = data.get("usage", {})
        return SystemResultEvent(
            session_id=session_id,
            job_id=job_id,
            subtype=subtype,
            is_error=data.get("is_error", False),
            error_message=data.get("error_message"),
            cost_usd=data.get("cost_usd"),
            num_turns=data.get("num_turns", 0),
            duration_ms=data.get("duration_ms", 0),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    # Assistant message
    if event_type == "assistant":
        message = data.get("message", {})
        content_list = message.get("content", [])

        events = []
        for content in content_list:
            content_type = content.get("type")

            if content_type == "text":
                events.append(
                    AISpeechEvent(
                        session_id=session_id,
                        job_id=job_id,
                        text=content.get("text", ""),
                    )
                )

            elif content_type == "thinking":
                events.append(
                    AIThinkingEvent(
                        session_id=session_id,
                        job_id=job_id,
                        thinking=content.get("thinking", ""),
                    )
                )

            elif content_type == "tool_use":
                events.append(
                    ToolStartEvent(
                        session_id=session_id,
                        job_id=job_id,
                        tool_name=content.get("name", ""),
                        tool_use_id=content.get("id", ""),
                        tool_input=content.get("input", {}),
                    )
                )

        # Return first event (could return list but simplify for now)
        return events[0] if events else None

    # User message (tool results)
    if event_type == "user":
        message = data.get("message", {})
        content_list = message.get("content", [])

        for content in content_list:
            if content.get("type") == "tool_result":
                return ToolResultEvent(
                    session_id=session_id,
                    job_id=job_id,
                    tool_use_id=content.get("tool_use_id", ""),
                    result=content.get("content", ""),
                    is_error=content.get("is_error", False),
                )

    return None


def parse_stream_events(line: str, job_id: str | None = None) -> list[SessionEvent]:
    """Parse a stream-json line into multiple SessionEvents.

    Some lines contain multiple events (e.g., text + tool_use in same message).

    Args:
        line: JSON line from Claude Code stream-json output.
        job_id: Job ID to attach to events.

    Returns:
        List of SessionEvents.
    """
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return []

    event_type = data.get("type")
    session_id = data.get("session_id")
    events: list[SessionEvent] = []

    # System events
    if event_type == "system":
        subtype = data.get("subtype")
        if subtype == "init":
            events.append(
                SystemInitEvent(
                    session_id=session_id,
                    job_id=job_id,
                    tools=data.get("tools", []),
                    cwd=data.get("cwd"),
                )
            )

    # Result event
    elif event_type == "result":
        subtype = data.get("subtype", "success")
        usage = data.get("usage", {})
        events.append(
            SystemResultEvent(
                session_id=session_id,
                job_id=job_id,
                subtype=subtype,
                is_error=data.get("is_error", False),
                error_message=data.get("error_message"),
                cost_usd=data.get("cost_usd"),
                num_turns=data.get("num_turns", 0),
                duration_ms=data.get("duration_ms", 0),
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )
        )

    # Assistant message
    elif event_type == "assistant":
        message = data.get("message", {})
        content_list = message.get("content", [])

        for content in content_list:
            content_type = content.get("type")

            if content_type == "text":
                events.append(
                    AISpeechEvent(
                        session_id=session_id,
                        job_id=job_id,
                        text=content.get("text", ""),
                    )
                )

            elif content_type == "thinking":
                events.append(
                    AIThinkingEvent(
                        session_id=session_id,
                        job_id=job_id,
                        thinking=content.get("thinking", ""),
                    )
                )

            elif content_type == "tool_use":
                events.append(
                    ToolStartEvent(
                        session_id=session_id,
                        job_id=job_id,
                        tool_name=content.get("name", ""),
                        tool_use_id=content.get("id", ""),
                        tool_input=content.get("input", {}),
                    )
                )

    # User message (tool results)
    elif event_type == "user":
        message = data.get("message", {})
        content_list = message.get("content", [])

        for content in content_list:
            if content.get("type") == "tool_result":
                events.append(
                    ToolResultEvent(
                        session_id=session_id,
                        job_id=job_id,
                        tool_use_id=content.get("tool_use_id", ""),
                        result=content.get("content", ""),
                        is_error=content.get("is_error", False),
                    )
                )

    return events
