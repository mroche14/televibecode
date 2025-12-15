# Claude Code Session Extraction & Telegram Streaming

This document covers all options for extracting information from Claude Code sessions and streaming it to Telegram.

## Table of Contents

1. [Stream-JSON Event Types](#stream-json-event-types)
2. [What Can Be Extracted](#what-can-be-extracted)
3. [Telegram Streaming Mechanics](#telegram-streaming-mechanics)
4. [Display Options](#display-options)
5. [Configuration Schema](#configuration-schema)
6. [Implementation Approaches](#implementation-approaches)

---

## Stream-JSON Event Types

When running Claude Code with `--output-format stream-json`, events are emitted as newline-delimited JSON.

### Event Sequence

```
┌─────────────────────────────────────────────────────────────────┐
│ SESSION START                                                    │
├─────────────────────────────────────────────────────────────────┤
│ {"type":"system","subtype":"init","session_id":"...","tools":[]}│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ CONVERSATION LOOP (repeats)                                      │
├─────────────────────────────────────────────────────────────────┤
│ {"type":"assistant","message":{"content":[...]}}                │
│   └─ content types: text, tool_use, thinking                    │
│                                                                  │
│ {"type":"user","message":{"content":[...]}}                     │
│   └─ content types: tool_result                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ SESSION END                                                      │
├─────────────────────────────────────────────────────────────────┤
│ {"type":"result","subtype":"success","cost_usd":...,"num_turns":│
│   ...,"session_id":"...","duration_ms":...}                     │
└─────────────────────────────────────────────────────────────────┘
```

### Detailed Event Structures

#### 1. System Init Event
```json
{
  "type": "system",
  "subtype": "init",
  "session_id": "abc123",
  "cwd": "/path/to/workspace",
  "tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "TodoWrite", ...]
}
```

#### 2. Assistant Message - Text Response
```json
{
  "type": "assistant",
  "message": {
    "id": "msg_xxx",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-20250514",
    "content": [
      {
        "type": "text",
        "text": "I'll create that file for you. Let me write a Python script that..."
      }
    ],
    "stop_reason": null,
    "usage": {"input_tokens": 1234, "output_tokens": 567}
  },
  "session_id": "abc123"
}
```

#### 3. Assistant Message - Tool Use
```json
{
  "type": "assistant",
  "message": {
    "content": [
      {
        "type": "tool_use",
        "id": "toolu_01ABC",
        "name": "Write",
        "input": {
          "file_path": "/workspace/hello.py",
          "content": "print('Hello, World!')"
        }
      }
    ]
  },
  "session_id": "abc123"
}
```

#### 4. Assistant Message - Thinking (Extended Thinking Models)
```json
{
  "type": "assistant",
  "message": {
    "content": [
      {
        "type": "thinking",
        "thinking": "Let me analyze this step by step...",
        "signature": "sig_xxx"
      }
    ]
  }
}
```

#### 5. User Message - Tool Result
```json
{
  "type": "user",
  "message": {
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_01ABC",
        "content": "File written successfully: /workspace/hello.py"
      }
    ]
  },
  "session_id": "abc123"
}
```

#### 6. User Message - Tool Error
```json
{
  "type": "user",
  "message": {
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_01ABC",
        "content": "Error: Permission denied",
        "is_error": true
      }
    ]
  }
}
```

#### 7. Result Event (Session Complete)
```json
{
  "type": "result",
  "subtype": "success",
  "session_id": "abc123",
  "cost_usd": 0.0234,
  "num_turns": 5,
  "duration_ms": 45000,
  "duration_api_ms": 12000,
  "is_error": false,
  "usage": {
    "input_tokens": 5000,
    "output_tokens": 2000,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 1000
  }
}
```

#### 8. Result Event (Error)
```json
{
  "type": "result",
  "subtype": "error",
  "session_id": "abc123",
  "is_error": true,
  "error_message": "API rate limit exceeded",
  "num_turns": 2
}
```

---

## What Can Be Extracted

### Extractable Information

| Category | Data | Event Source | Notes |
|----------|------|--------------|-------|
| **AI Speech** | Text responses | `assistant.content[type=text]` | What Claude "says" |
| **AI Thinking** | Internal reasoning | `assistant.content[type=thinking]` | Extended thinking only |
| **Tool Calls** | Tool name + inputs | `assistant.content[type=tool_use]` | Actions Claude takes |
| **Tool Results** | Execution output | `user.content[type=tool_result]` | What happened |
| **Tool Errors** | Failure info | `user.content[is_error=true]` | What went wrong |
| **Files Changed** | File paths | Extract from Write/Edit tool_use | Track modifications |
| **Final Answer** | Last text block | Last `assistant` with `text` content | The conclusion |
| **Session Stats** | Cost, turns, duration | `result` event | Summary metrics |
| **Token Usage** | Input/output tokens | `assistant.usage` or `result.usage` | API consumption |

### Tool-Specific Extraction

| Tool | Interesting Fields | Use Case |
|------|-------------------|----------|
| `Read` | `file_path` | Files being examined |
| `Write` | `file_path`, `content` | New files created |
| `Edit` | `file_path`, `old_string`, `new_string` | Code changes |
| `Bash` | `command`, `description` | Shell commands run |
| `Grep` | `pattern`, `path` | Searches performed |
| `Glob` | `pattern` | File discovery |
| `WebFetch` | `url` | External resources |
| `WebSearch` | `query` | Research queries |
| `TodoWrite` | `todos` | Task tracking |

---

## Telegram Streaming Mechanics

### How It Works

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│   Bot sends     │         │  User sends     │         │  Bot continues  │
│  initial msg    │────────▶│  new messages   │────────▶│  editing old    │
│  (gets msg_id)  │         │  (new msg_ids)  │         │  message by ID  │
└─────────────────┘         └─────────────────┘         └─────────────────┘
      │                                                        │
      │  msg_id = 123                                         │
      │                                                        │
      ▼                                                        ▼
┌─────────────────┐                                    ┌─────────────────┐
│ "🔧 Starting..."│                                    │ "✅ Done!       │
│                 │  ◀──── editMessageText(123) ─────  │ Created 3 files │
│                 │                                    │ Modified 2 files│
└─────────────────┘                                    └─────────────────┘
```

### Key Points

1. **Message ID Targeting**: Bot tracks specific `message_id` and updates it via `editMessageText`
2. **Position Independent**: Works regardless of where message is in chat
3. **Rate Limits**: ~1 edit per second per message (429 error if faster)
4. **Visibility**: User must scroll up to see updates if they're typing

### Telegram API Methods

| Method | Use Case |
|--------|----------|
| `sendMessage` | Initial message, returns `message_id` |
| `editMessageText` | Update text content |
| `editMessageReplyMarkup` | Update inline buttons |
| `deleteMessage` | Remove message |

---

## Display Options

### Option 1: Minimal Status (Current)

```
🔧 Running... [████████░░░░░░░░░░░░]
⏱️ 12s
🔨 Write
📝 2 files
```

**Pros**: Low bandwidth, clean
**Cons**: Limited visibility into what's happening

### Option 2: Tool Stream

```
🔧 Running in S1 (myproject)...

📖 Reading src/auth.py
✏️ Editing src/auth.py
  └─ Adding validation logic
📖 Reading tests/test_auth.py
✏️ Writing tests/test_auth.py
🔨 Running pytest tests/
  └─ ✅ 5 passed

⏱️ 45s | 💰 $0.02
```

**Pros**: See every action
**Cons**: Can be verbose

### Option 3: AI Thoughts + Actions

```
🤖 "I'll add input validation to the login form..."

📖 Read: src/components/LoginForm.tsx
✏️ Edit: src/components/LoginForm.tsx
   └─ Added email validation regex
✏️ Edit: src/utils/validation.ts
   └─ New validateEmail function

🤖 "Now let me add the tests..."

✏️ Write: tests/validation.test.ts
🔨 Bash: npm test
   └─ ✅ All tests passing
```

**Pros**: Full context, like watching Claude work
**Cons**: Very verbose, high update frequency

### Option 4: Summary Only (No Streaming)

```
✅ Job Complete

📝 Modified:
  • src/components/LoginForm.tsx
  • src/utils/validation.ts

📄 Created:
  • tests/validation.test.ts

💬 "Added email validation to the login form with comprehensive tests."

⏱️ 45s | 🔄 5 turns | 💰 $0.02
```

**Pros**: Clean, no rate limit issues
**Cons**: No real-time feedback

### Option 5: Expandable Details

```
🔧 Running... [████████████░░░░░░░░] 67%

[📋 Show Details]  [⏹️ Cancel]

────────────────────────
Expand to see:
• 3 files read
• 2 files modified
• 1 command run
```

*When expanded via callback:*

```
📋 Job Details (S1 - myproject)

🔨 Actions:
1. 📖 Read src/auth.py
2. ✏️ Edit src/auth.py
3. 📖 Read tests/test_auth.py
4. ✏️ Write tests/test_auth.py
5. 🔨 Bash: pytest

💬 Last: "Tests are now passing"

[🔼 Collapse]  [⏹️ Cancel]
```

**Pros**: User controls detail level
**Cons**: Requires button interactions

---

## Configuration Schema

### Proposed Settings Structure

```python
@dataclass
class StreamingConfig:
    """Configuration for session output streaming."""

    # What to show in real-time
    show_ai_text: bool = True           # AI's spoken responses
    show_ai_thinking: bool = False      # Extended thinking (verbose)
    show_tool_start: bool = True        # When tool begins
    show_tool_result: bool = False      # Tool output (can be large)
    show_tool_errors: bool = True       # Always show errors

    # Streaming behavior
    stream_to_telegram: bool = True     # Enable live updates
    update_interval_ms: int = 2000      # Min time between edits
    max_message_length: int = 4000      # Telegram limit ~4096

    # Progress display
    show_progress_bar: bool = True
    show_elapsed_time: bool = True
    show_file_count: bool = True
    show_current_tool: bool = True
    show_token_usage: bool = False
    show_cost: bool = True

    # AI text handling
    truncate_ai_text: int = 200         # Max chars per AI message
    show_final_answer: bool = True      # Always show conclusion

    # Tool display
    tool_display_mode: Literal[
        "icon_only",      # 🔨
        "name_only",      # Write
        "icon_and_name",  # 🔨 Write
        "detailed"        # 🔨 Write: src/file.py
    ] = "icon_and_name"

    # Collapsible sections
    expandable_details: bool = True     # Add [Show Details] button

    # Post-completion
    show_summary: bool = True           # Final summary message
    show_files_changed: bool = True
    show_session_stats: bool = True
```

### Environment Variable Overrides

```bash
# .env

# Streaming
TELEVIBE_STREAM_AI_TEXT=true
TELEVIBE_STREAM_TOOLS=true
TELEVIBE_STREAM_INTERVAL_MS=2000

# Display
TELEVIBE_SHOW_PROGRESS_BAR=true
TELEVIBE_SHOW_COST=true
TELEVIBE_SHOW_THINKING=false

# Verbosity preset
TELEVIBE_VERBOSITY=normal  # minimal | normal | verbose | debug
```

### Verbosity Presets

| Preset | AI Text | Tools | Thinking | Results | Updates |
|--------|---------|-------|----------|---------|---------|
| `minimal` | ❌ | Icon only | ❌ | Summary | 5s |
| `normal` | Truncated | Icon+name | ❌ | Summary | 2s |
| `verbose` | Full | Detailed | ❌ | Full | 1s |
| `debug` | Full | Detailed | ✅ | Full | 500ms |

---

## Implementation Approaches

### Approach 1: Enhanced JobProgress (Minimal Change)

Extend existing `JobProgress` dataclass:

```python
@dataclass
class JobProgress:
    job_id: str
    status: str = "starting"
    elapsed_seconds: int = 0

    # Existing
    files_touched: list[str] = field(default_factory=list)
    current_tool: str | None = None
    tool_count: int = 0
    message_count: int = 0
    last_message: str | None = None
    error: str | None = None

    # New: Detailed extraction
    ai_messages: list[str] = field(default_factory=list)
    tool_history: list[ToolAction] = field(default_factory=list)
    final_answer: str | None = None
    thinking_content: list[str] = field(default_factory=list)

    # New: Stats
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    num_turns: int = 0

@dataclass
class ToolAction:
    tool_name: str
    tool_input: dict
    result: str | None = None
    is_error: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

### Approach 2: Event-Based Architecture

Create an event system for flexible handling:

```python
class SessionEvent(Protocol):
    event_type: str
    timestamp: datetime
    session_id: str

@dataclass
class AITextEvent:
    event_type: Literal["ai_text"] = "ai_text"
    text: str
    is_final: bool = False
    timestamp: datetime = field(default_factory=...)
    session_id: str = ""

@dataclass
class ToolStartEvent:
    event_type: Literal["tool_start"] = "tool_start"
    tool_name: str
    tool_input: dict
    tool_use_id: str
    timestamp: datetime = field(default_factory=...)
    session_id: str = ""

@dataclass
class ToolResultEvent:
    event_type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    result: str
    is_error: bool = False
    timestamp: datetime = field(default_factory=...)
    session_id: str = ""

# Event handler registration
class SessionEventHandler:
    def __init__(self, config: StreamingConfig):
        self.config = config
        self.handlers: dict[str, list[Callable]] = {}

    def on(self, event_type: str, handler: Callable):
        self.handlers.setdefault(event_type, []).append(handler)

    async def emit(self, event: SessionEvent):
        for handler in self.handlers.get(event.event_type, []):
            await handler(event)
```

### Approach 3: Streaming Formatter

Separate formatting from extraction:

```python
class TelegramStreamFormatter:
    """Formats session events for Telegram display."""

    def __init__(self, config: StreamingConfig):
        self.config = config

    def format_progress(self, progress: JobProgress) -> str:
        """Format current progress for display."""
        parts = []

        if self.config.show_progress_bar:
            parts.append(self._progress_bar(progress))

        if self.config.show_elapsed_time:
            parts.append(f"⏱️ {progress.elapsed_seconds}s")

        if self.config.show_current_tool and progress.current_tool:
            parts.append(self._format_tool(progress.current_tool))

        if self.config.show_ai_text and progress.last_message:
            text = self._truncate(progress.last_message, self.config.truncate_ai_text)
            parts.append(f"💬 _{text}_")

        return "\n".join(parts)

    def format_tool_action(self, action: ToolAction) -> str:
        """Format a tool action based on config."""
        if self.config.tool_display_mode == "icon_only":
            return TOOL_ICONS.get(action.tool_name, "🔧")
        elif self.config.tool_display_mode == "detailed":
            return self._detailed_tool(action)
        # ...

    def format_summary(self, progress: JobProgress) -> str:
        """Format final summary."""
        # ...

TOOL_ICONS = {
    "Read": "📖",
    "Write": "📝",
    "Edit": "✏️",
    "Bash": "🔨",
    "Grep": "🔍",
    "Glob": "📂",
    "WebFetch": "🌐",
    "WebSearch": "🔎",
    "TodoWrite": "📋",
}
```

---

## SDK vs Subprocess Comparison

| Feature | Subprocess + stream-json | Claude Agent SDK |
|---------|-------------------------|------------------|
| Event access | Parse JSON lines | Typed Python objects |
| Tool interception | Parse events | `PreToolUse`/`PostToolUse` hooks |
| AI text | Parse `assistant.content[type=text]` | `TextBlock` objects |
| Thinking | Parse `assistant.content[type=thinking]` | `ThinkingBlock` objects |
| Session stats | Parse `result` event | `ResultMessage` object |
| Interrupt | `SIGTERM` process | `client.interrupt()` |
| Custom tools | Not possible | `@tool` decorator |

### SDK Example: Full Extraction

```python
from claude_agent_sdk import (
    ClaudeSDKClient, ClaudeAgentOptions,
    AssistantMessage, ResultMessage,
    TextBlock, ToolUseBlock, ThinkingBlock, ToolResultBlock
)

async def run_with_full_extraction(instruction: str, workspace: str):
    """Run instruction and extract all events."""

    events = []

    options = ClaudeAgentOptions(
        cwd=workspace,
        permission_mode="acceptEdits",
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(instruction)

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        events.append({
                            "type": "ai_text",
                            "text": block.text,
                        })
                    elif isinstance(block, ToolUseBlock):
                        events.append({
                            "type": "tool_start",
                            "tool": block.name,
                            "input": block.input,
                            "id": block.id,
                        })
                    elif isinstance(block, ThinkingBlock):
                        events.append({
                            "type": "thinking",
                            "content": block.thinking,
                        })
                    elif isinstance(block, ToolResultBlock):
                        events.append({
                            "type": "tool_result",
                            "id": block.tool_use_id,
                            "result": block.content,
                            "is_error": block.is_error,
                        })

            elif isinstance(message, ResultMessage):
                events.append({
                    "type": "session_complete",
                    "duration_ms": message.duration_ms,
                    "cost_usd": message.total_cost_usd,
                    "num_turns": message.num_turns,
                    "is_error": message.is_error,
                })

    return events
```

---

## Next Steps

1. **Choose verbosity presets** - What should minimal/normal/verbose show?
2. **Decide on default config** - What's the right balance for mobile?
3. **Implement extraction layer** - Extend JobProgress or use events?
4. **Add Telegram formatter** - Separate display logic
5. **Add configuration** - Env vars and/or per-chat settings
6. **Test rate limits** - Ensure we don't hit Telegram 429 errors

---

## References

- [Claude Code CLI Reference](https://code.claude.com/docs/en/cli-reference)
- [Claude Agent SDK - Python](https://platform.claude.com/docs/en/agent-sdk/python)
- [Telegram Bot API - editMessageText](https://core.telegram.org/bots/api#editmessagetext)
- [GitHub: claude-code-log](https://github.com/daaain/claude-code-log) - JSONL parser reference
