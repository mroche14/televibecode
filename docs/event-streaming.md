# Event Streaming Architecture

## Overview

Real-time updates from jobs to Telegram (and other clients) require an event streaming system. This document covers event types, transport mechanisms, and client integration.

## Event Model

### Event Structure

```python
@dataclass
class Event:
    event_id: str           # Unique ID (UUID)
    event_type: str         # e.g., "job.started"
    timestamp: datetime     # When event occurred
    source: EventSource     # What generated the event

    # Context
    project_id: str
    session_id: Optional[str]
    job_id: Optional[str]

    # Payload
    data: dict              # Event-specific data

    # Routing
    visibility: str         # "public" | "internal"
    recipients: list[str]   # Specific chat_ids or "all"

@dataclass
class EventSource:
    component: str          # "runner", "orchestrator", "session_manager"
    instance_id: str        # For distributed setups
```

### Event Taxonomy

```
orchestrator.
├── started                 # Orchestrator process started
├── stopped                 # Orchestrator shutting down
└── error                   # Orchestrator-level error

project.
├── registered              # New project added
├── removed                 # Project unregistered
└── scanned                 # Scan completed

session.
├── created                 # Session created
├── state_changed           # idle → running, etc.
├── workspace_ready         # Worktree set up
├── closed                  # Session closed
└── error                   # Session-level error

job.
├── queued                  # Job added to queue
├── started                 # Execution began
├── progress                # Progress update
├── tool_started            # Tool invocation starting
├── tool_completed          # Tool finished
├── approval_needed         # Waiting for approval
├── approved                # Approval granted
├── denied                  # Approval denied
├── completed               # Job finished successfully
├── failed                  # Job failed
└── canceled                # Job canceled

task.
├── created                 # New task in backlog
├── claimed                 # Task assigned to session
├── status_changed          # Status transition
└── completed               # Task done

coordination.
├── message_sent            # Cross-session message
├── export_declared         # Interface exported
├── conflict_detected       # Git conflict found
└── sync_point_reached      # All sessions ready
```

### Event Payloads

**job.started**:
```json
{
  "event_type": "job.started",
  "project_id": "project-a",
  "session_id": "S12",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "instruction": "implement login form",
    "workspace": "/projects/workspaces/project-a/S12/feature-x",
    "branch": "feature-x"
  }
}
```

**job.progress**:
```json
{
  "event_type": "job.progress",
  "job_id": "550e8400-...",
  "data": {
    "type": "tool_use",
    "tool": "Write",
    "file": "src/auth/login.py",
    "action": "creating"
  }
}
```

**job.approval_needed**:
```json
{
  "event_type": "job.approval_needed",
  "job_id": "550e8400-...",
  "data": {
    "scope": "push",
    "action": "git push origin feature-x",
    "reason": "Push to remote repository",
    "context": {
      "commits": 2,
      "files_changed": 3
    }
  }
}
```

**job.completed**:
```json
{
  "event_type": "job.completed",
  "job_id": "550e8400-...",
  "data": {
    "success": true,
    "duration_seconds": 125,
    "summary": "Implemented login form with validation",
    "files_changed": [
      "src/auth/login.py",
      "src/auth/forms.py",
      "tests/test_login.py"
    ],
    "diff_stat": "+245 -12"
  }
}
```

## Event Bus

### In-Process Bus

For single-process deployment:

```python
from asyncio import Queue
from typing import Callable, Awaitable

EventHandler = Callable[[Event], Awaitable[None]]

class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = {}
        self._queue: Queue[Event] = Queue()
        self._running = False

    def subscribe(self, event_pattern: str, handler: EventHandler):
        """Subscribe to events matching pattern (supports wildcards)"""
        if event_pattern not in self._handlers:
            self._handlers[event_pattern] = []
        self._handlers[event_pattern].append(handler)

    async def publish(self, event: Event):
        """Publish event to the bus"""
        await self._queue.put(event)

    async def start(self):
        """Start processing events"""
        self._running = True
        while self._running:
            event = await self._queue.get()
            await self._dispatch(event)

    async def _dispatch(self, event: Event):
        """Dispatch event to matching handlers"""
        for pattern, handlers in self._handlers.items():
            if self._matches(pattern, event.event_type):
                for handler in handlers:
                    try:
                        await handler(event)
                    except Exception as e:
                        logger.error(f"Handler error: {e}")

    def _matches(self, pattern: str, event_type: str) -> bool:
        """Check if event_type matches pattern (supports 'job.*')"""
        if pattern == "*":
            return True
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            return event_type.startswith(prefix + ".")
        return pattern == event_type

# Usage
bus = EventBus()

# Subscribe to all job events
bus.subscribe("job.*", telegram_notifier.handle_job_event)

# Subscribe to specific event
bus.subscribe("job.approval_needed", approval_handler.handle)

# Publish
await bus.publish(Event(
    event_type="job.started",
    ...
))
```

### Redis-Based Bus

For distributed or persistent events:

```python
import redis.asyncio as redis
import json

class RedisEventBus:
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis = redis.from_url(redis_url)
        self.pubsub = self.redis.pubsub()
        self._handlers: dict[str, list[EventHandler]] = {}

    async def publish(self, event: Event):
        # Publish to channel
        channel = f"televibe:events:{event.event_type}"
        await self.redis.publish(channel, event.to_json())

        # Also store in stream for persistence
        stream = f"televibe:stream:{event.project_id}"
        await self.redis.xadd(stream, {"event": event.to_json()})

    async def subscribe(self, pattern: str, handler: EventHandler):
        channel_pattern = f"televibe:events:{pattern.replace('*', '*')}"
        await self.pubsub.psubscribe(channel_pattern)
        self._handlers[pattern] = handler

    async def start(self):
        async for message in self.pubsub.listen():
            if message["type"] == "pmessage":
                event = Event.from_json(message["data"])
                await self._dispatch(event)

    async def get_history(
        self,
        project_id: str,
        since: datetime,
        limit: int = 100,
    ) -> list[Event]:
        """Get historical events from stream"""
        stream = f"televibe:stream:{project_id}"
        since_ms = int(since.timestamp() * 1000)

        entries = await self.redis.xrange(
            stream,
            min=since_ms,
            max="+",
            count=limit,
        )

        return [Event.from_json(e["event"]) for e in entries]
```

## Telegram Integration

### Event to Telegram Mapping

```python
class TelegramNotifier:
    def __init__(self, bot: Bot, event_bus: EventBus):
        self.bot = bot
        self.chat_registry = ChatRegistry()

        # Subscribe to relevant events
        event_bus.subscribe("job.*", self.handle_job_event)
        event_bus.subscribe("session.*", self.handle_session_event)
        event_bus.subscribe("coordination.*", self.handle_coordination_event)

    async def handle_job_event(self, event: Event):
        # Get chat IDs interested in this session
        chat_ids = await self.chat_registry.get_chats_for_session(
            event.session_id
        )

        message = self.format_job_event(event)

        for chat_id in chat_ids:
            await self.send_update(chat_id, event, message)

    def format_job_event(self, event: Event) -> str:
        session = event.session_id
        project = event.project_id

        if event.event_type == "job.started":
            return (
                f"🔧 {session} ({project}):\n"
                f"Started: {event.data['instruction'][:100]}"
            )

        elif event.event_type == "job.progress":
            tool = event.data.get("tool", "")
            file = event.data.get("file", "")
            return f"⚙️ {session}: {tool} {file}"

        elif event.event_type == "job.completed":
            files = len(event.data.get("files_changed", []))
            summary = event.data.get("summary", "")[:200]
            return (
                f"✅ {session} ({project}):\n"
                f"Completed: {summary}\n"
                f"Files changed: {files}"
            )

        elif event.event_type == "job.failed":
            error = event.data.get("error", "Unknown error")[:200]
            return f"❌ {session} ({project}):\nFailed: {error}"

        elif event.event_type == "job.approval_needed":
            return None  # Handled specially with buttons

        return f"📋 {session}: {event.event_type}"

    async def send_update(
        self,
        chat_id: int,
        event: Event,
        message: str,
    ):
        # Check notification preferences
        prefs = await self.chat_registry.get_preferences(chat_id)

        if prefs.level == "off":
            return

        if prefs.level == "errors" and event.event_type not in [
            "job.failed", "job.approval_needed"
        ]:
            return

        if prefs.level == "approvals" and event.event_type != "job.approval_needed":
            return

        # Send message
        if event.event_type == "job.approval_needed":
            await self.send_approval_request(chat_id, event)
        else:
            await self.bot.send_message(chat_id, message)

    async def send_approval_request(self, chat_id: int, event: Event):
        job_id = event.job_id
        scope = event.data["scope"]
        action = event.data["action"]

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{job_id}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"deny:{job_id}"),
            ]
        ])

        message = (
            f"⚠️ {event.session_id} ({event.project_id}):\n"
            f"Approval needed\n\n"
            f"Action: {action}\n"
            f"Scope: {scope}"
        )

        await self.bot.send_message(
            chat_id,
            message,
            reply_markup=keyboard,
        )
```

### Notification Batching

Avoid spamming with too many updates:

```python
class BatchedNotifier:
    def __init__(self, bot: Bot, batch_interval: float = 2.0):
        self.bot = bot
        self.batch_interval = batch_interval
        self._batches: dict[int, list[Event]] = {}  # chat_id -> events
        self._batch_tasks: dict[int, asyncio.Task] = {}

    async def queue_event(self, chat_id: int, event: Event):
        if chat_id not in self._batches:
            self._batches[chat_id] = []

        self._batches[chat_id].append(event)

        # Start batch timer if not already running
        if chat_id not in self._batch_tasks:
            self._batch_tasks[chat_id] = asyncio.create_task(
                self._flush_after_delay(chat_id)
            )

    async def _flush_after_delay(self, chat_id: int):
        await asyncio.sleep(self.batch_interval)
        await self._flush(chat_id)

    async def _flush(self, chat_id: int):
        events = self._batches.pop(chat_id, [])
        self._batch_tasks.pop(chat_id, None)

        if not events:
            return

        # Combine events into single message
        message = self._format_batch(events)
        await self.bot.send_message(chat_id, message)

    def _format_batch(self, events: list[Event]) -> str:
        # Group by session
        by_session: dict[str, list[Event]] = {}
        for e in events:
            by_session.setdefault(e.session_id, []).append(e)

        lines = []
        for session_id, session_events in by_session.items():
            lines.append(f"📂 {session_id}:")
            for e in session_events[-5:]:  # Last 5 events
                lines.append(f"  • {e.event_type.split('.')[-1]}")

        return "\n".join(lines)
```

## Log Streaming

### Real-Time Log Tailing

```python
class LogStreamer:
    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir
        self._watchers: dict[str, list[asyncio.Queue]] = {}

    async def tail(
        self,
        job_id: str,
        lines: int = 50,
    ) -> AsyncGenerator[str, None]:
        """Stream log lines for a job"""
        log_path = self.logs_dir / f"{job_id}.log"

        # First, yield existing content
        if log_path.exists():
            async with aiofiles.open(log_path) as f:
                content = await f.read()
                for line in content.split("\n")[-lines:]:
                    yield line

        # Then watch for new content
        queue: asyncio.Queue = asyncio.Queue()
        if job_id not in self._watchers:
            self._watchers[job_id] = []
        self._watchers[job_id].append(queue)

        try:
            while True:
                line = await queue.get()
                if line is None:  # End of stream
                    break
                yield line
        finally:
            self._watchers[job_id].remove(queue)

    async def write_line(self, job_id: str, line: str):
        """Write a line and notify watchers"""
        log_path = self.logs_dir / f"{job_id}.log"

        async with aiofiles.open(log_path, "a") as f:
            await f.write(line + "\n")

        # Notify watchers
        for queue in self._watchers.get(job_id, []):
            await queue.put(line)

    async def end_stream(self, job_id: str):
        """Signal end of log stream"""
        for queue in self._watchers.get(job_id, []):
            await queue.put(None)
        self._watchers.pop(job_id, None)
```

### Telegram Log Streaming

```python
async def handle_tail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session_id = context.args[0] if context.args else get_active_session(update.chat_id)
    lines = int(context.args[1]) if len(context.args) > 1 else 20

    session = await get_session(session_id)
    if not session.current_job_id:
        await update.message.reply_text(f"No active job in {session_id}")
        return

    # Send initial message
    message = await update.message.reply_text(
        f"📜 Streaming logs for {session_id}...\n\n```\nConnecting...```",
        parse_mode="Markdown",
    )

    # Stream logs
    log_buffer = []
    last_update = time.time()

    async for line in log_streamer.tail(session.current_job_id, lines):
        log_buffer.append(line)

        # Update message every 2 seconds
        if time.time() - last_update > 2:
            await message.edit_text(
                f"📜 Logs for {session_id}:\n\n```\n" +
                "\n".join(log_buffer[-30:]) +
                "\n```",
                parse_mode="Markdown",
            )
            last_update = time.time()

    # Final update
    await message.edit_text(
        f"📜 Logs for {session_id} (complete):\n\n```\n" +
        "\n".join(log_buffer[-50:]) +
        "\n```",
        parse_mode="Markdown",
    )
```

## SSE Endpoint (Web Clients)

For web-based clients or dashboards:

```python
from starlette.responses import StreamingResponse

async def sse_events(request: Request) -> StreamingResponse:
    """Server-Sent Events endpoint for real-time updates"""
    project_id = request.query_params.get("project_id")
    session_id = request.query_params.get("session_id")

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()

        # Subscribe to events
        def filter_event(event: Event) -> bool:
            if project_id and event.project_id != project_id:
                return False
            if session_id and event.session_id != session_id:
                return False
            return True

        async def handler(event: Event):
            if filter_event(event):
                await queue.put(event)

        event_bus.subscribe("*", handler)

        try:
            while True:
                event = await queue.get()
                yield f"event: {event.event_type}\n"
                yield f"data: {event.to_json()}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
```

## Event Persistence

### Event Store

For audit trails and replay:

```python
class EventStore:
    def __init__(self, db: Database):
        self.db = db

    async def store(self, event: Event):
        await self.db.execute(
            """
            INSERT INTO events (
                event_id, event_type, timestamp, source,
                project_id, session_id, job_id, data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.event_type,
                event.timestamp.isoformat(),
                json.dumps(event.source.__dict__),
                event.project_id,
                event.session_id,
                event.job_id,
                json.dumps(event.data),
            )
        )

    async def query(
        self,
        project_id: Optional[str] = None,
        session_id: Optional[str] = None,
        event_types: Optional[list[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[Event]:
        conditions = []
        params = []

        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if event_types:
            placeholders = ",".join("?" * len(event_types))
            conditions.append(f"event_type IN ({placeholders})")
            params.extend(event_types)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since.isoformat())
        if until:
            conditions.append("timestamp <= ?")
            params.append(until.isoformat())

        where = " AND ".join(conditions) if conditions else "1=1"

        rows = await self.db.fetch_all(
            f"""
            SELECT * FROM events
            WHERE {where}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (*params, limit)
        )

        return [Event.from_row(row) for row in rows]

    async def replay(
        self,
        project_id: str,
        since: datetime,
        handler: EventHandler,
    ):
        """Replay historical events through a handler"""
        events = await self.query(
            project_id=project_id,
            since=since,
            limit=10000,
        )

        for event in reversed(events):  # Chronological order
            await handler(event)
```

### Event Retention

```python
async def cleanup_old_events(retention_days: int = 30):
    """Remove events older than retention period"""
    cutoff = datetime.now() - timedelta(days=retention_days)

    await db.execute(
        "DELETE FROM events WHERE timestamp < ?",
        (cutoff.isoformat(),)
    )
```

## Metrics & Monitoring

### Event Metrics

```python
from prometheus_client import Counter, Histogram

events_total = Counter(
    "televibe_events_total",
    "Total events processed",
    ["event_type", "project_id"],
)

event_processing_seconds = Histogram(
    "televibe_event_processing_seconds",
    "Event processing duration",
    ["event_type"],
)

async def instrumented_handler(event: Event):
    events_total.labels(
        event_type=event.event_type,
        project_id=event.project_id,
    ).inc()

    with event_processing_seconds.labels(
        event_type=event.event_type
    ).time():
        await original_handler(event)
```

### Health Checks

```python
async def event_bus_health() -> dict:
    return {
        "status": "healthy" if event_bus._running else "unhealthy",
        "queue_size": event_bus._queue.qsize(),
        "handlers_registered": sum(len(h) for h in event_bus._handlers.values()),
    }
```
