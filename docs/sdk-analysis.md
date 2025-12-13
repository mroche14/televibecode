# Claude Agent SDK Analysis for TeleVibeCode

## Executive Summary

**Verdict: The Claude Agent SDK can fully replace our subprocess approach.**

The SDK provides native Python access to all Claude Code capabilities with better control, error handling, and integration possibilities.

## Feature Comparison

### TeleVibeCode Requirements vs SDK Capabilities

| Requirement | Current (Subprocess) | SDK Support | Notes |
|-------------|---------------------|-------------|-------|
| **Job Execution** | `claude -p <instruction>` | `ClaudeSDKClient.query()` | Native async Python |
| **Approval Gating** | Parse JSON stream, manual hook scripts | `PreToolUse` hooks as Python functions | Much cleaner |
| **Streaming Output** | Parse `--output-format stream-json` | `async for message in client.receive_response()` | Native async iterator |
| **Timeout Handling** | `SIGTERM`/`SIGKILL` subprocess | `client.interrupt()` + app-level timeout | Cleaner interrupt |
| **Git Worktree Isolation** | Set `cwd` in subprocess | `ClaudeAgentOptions(cwd=workspace_path)` | Same capability |
| **CLAUDE.md Loading** | Automatic in CLI | `setting_sources=["project"]` | Explicit opt-in |
| **Log Capture** | Write to file from stdout | Capture messages from iterator | More structured |
| **Concurrent Jobs** | Semaphore + multiple processes | Multiple `ClaudeSDKClient` instances | Same pattern |
| **Custom Tools** | Not supported | `@tool` decorator + MCP servers | New capability |
| **Session Continuity** | Not supported | `ClaudeSDKClient` maintains context | New capability |

### Built-in Tools (All Available via SDK)

```python
# All Claude Code tools are accessible:
allowed_tools = [
    "Read",      # Read files with line numbers
    "Write",     # Create new files
    "Edit",      # Precise text replacement
    "Bash",      # Run commands (with timeout, background support)
    "BashOutput", # Get background process output
    "KillBash",  # Kill background processes
    "Glob",      # Find files by pattern
    "Grep",      # Search file contents
    "WebSearch", # Web search
    "WebFetch",  # Fetch web pages
    "Task",      # Spawn subagents
    "TodoWrite", # Task management
    "NotebookEdit", # Jupyter notebooks
]
```

### Permission Modes

```python
# SDK permission modes map directly to our approval strategies:
permission_mode = "default"          # Standard (requires approval)
permission_mode = "acceptEdits"      # Auto-approve file edits
permission_mode = "plan"             # Planning mode (no execution)
permission_mode = "bypassPermissions" # Full auto-approve (dangerous)
```

### Hook System (Key for Approval Flow)

The SDK supports Python-native hooks for intercepting tool usage:

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, HookMatcher

async def approval_hook(input_data, tool_use_id, context):
    """Hook that integrates with TeleVibeCode approval system."""
    tool_name = input_data.get('tool_name')
    tool_input = input_data.get('tool_input', {})

    # Check if this tool requires approval
    if tool_name == "Bash":
        command = tool_input.get('command', '')

        # Whitelist safe commands
        safe_commands = ["git status", "git diff", "ls", "pwd", "pytest"]
        if any(command.startswith(safe) for safe in safe_commands):
            return {}  # Allow

        # Request approval from Telegram
        approved = await request_telegram_approval(
            tool=tool_name,
            command=command,
            job_id=context.job_id  # Custom context
        )

        if not approved:
            return {
                'hookSpecificOutput': {
                    'hookEventName': 'PreToolUse',
                    'permissionDecision': 'deny',
                    'permissionDecisionReason': 'User denied via Telegram'
                }
            }

    return {}  # Allow by default

options = ClaudeAgentOptions(
    hooks={
        'PreToolUse': [
            HookMatcher(matcher='Bash', hooks=[approval_hook]),
            HookMatcher(matcher='Write|Edit', hooks=[file_change_hook]),
        ],
        'PostToolUse': [
            HookMatcher(hooks=[log_tool_usage]),
        ]
    }
)
```

## SDK API Comparison

### query() vs ClaudeSDKClient

| Feature | `query()` | `ClaudeSDKClient` |
|---------|-----------|-------------------|
| Session | New each time | Persistent |
| Conversation | Single exchange | Multi-turn |
| Interrupts | Not supported | `client.interrupt()` |
| Hooks | Not supported | Full support |
| Custom Tools | Not supported | Full support |
| Use Case | One-off tasks | Interactive sessions |

**Recommendation for TeleVibeCode: Use `ClaudeSDKClient`**

- Need hooks for approval gating
- Need interrupt support for job cancellation
- May want session continuity for follow-up instructions

## Proposed SDK Integration

### New Executor Implementation

```python
# src/televibecode/runner/sdk_executor.py
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    HookMatcher,
    AssistantMessage,
    ToolUseBlock,
    ToolResultBlock,
    ResultMessage,
)

class SDKJobExecutor:
    """Execute jobs using Claude Agent SDK instead of subprocess."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._running_clients: dict[str, ClaudeSDKClient] = {}

    async def execute_job(
        self,
        job: Job,
        session: Session,
        on_event: Callable[[JobEvent], Awaitable[None]],
        on_approval_needed: Callable[[ApprovalRequest], Awaitable[bool]],
    ) -> JobResult:
        """Execute a job using the SDK."""

        # Build options
        options = ClaudeAgentOptions(
            cwd=session.workspace_path,
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
            permission_mode="default",
            setting_sources=["project"],  # Load CLAUDE.md
            hooks={
                'PreToolUse': [
                    HookMatcher(
                        matcher='Bash',
                        hooks=[self._create_approval_hook(job, on_approval_needed)]
                    ),
                ],
                'PostToolUse': [
                    HookMatcher(hooks=[self._create_logging_hook(job, on_event)]),
                ]
            },
            env={
                "TELEVIBE_JOB_ID": job.job_id,
                "TELEVIBE_SESSION_ID": session.session_id,
            }
        )

        # Create and track client
        client = ClaudeSDKClient(options)
        self._running_clients[job.job_id] = client

        try:
            async with client:
                await client.query(job.instruction)

                # Process responses
                async for message in client.receive_response():
                    await self._handle_message(message, job, on_event)

                    if isinstance(message, ResultMessage):
                        return JobResult(
                            success=not message.is_error,
                            duration_ms=message.duration_ms,
                            cost_usd=message.total_cost_usd,
                            usage=message.usage,
                        )
        finally:
            del self._running_clients[job.job_id]

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job via interrupt."""
        client = self._running_clients.get(job_id)
        if client:
            await client.interrupt()
            return True
        return False
```

### Migration Path

1. **Phase 1**: Add SDK as optional executor (feature flag)
2. **Phase 2**: Run both in parallel, compare results
3. **Phase 3**: Make SDK the default
4. **Phase 4**: Remove subprocess executor

## Advantages of SDK Approach

1. **Native Python Integration**
   - No subprocess spawning overhead
   - Direct async/await integration
   - Typed message objects

2. **Better Error Handling**
   - Structured exceptions (`CLINotFoundError`, `ProcessError`)
   - No JSON parsing errors from stdout

3. **Cleaner Approval Flow**
   - Hooks are Python functions, not shell scripts
   - Can directly integrate with async approval system
   - No polling required

4. **Session Continuity**
   - Can maintain conversation context
   - Follow-up instructions possible
   - Better for interactive workflows

5. **Custom Tools**
   - Can add TeleVibeCode-specific tools
   - In-process MCP servers (no subprocess)

6. **Interrupt Support**
   - Clean `client.interrupt()` method
   - No SIGTERM/SIGKILL handling

## Potential Concerns

1. **CLI Bundled Dependency**
   - SDK bundles Claude Code CLI internally
   - May have version sync issues

2. **Hook Limitations**
   - `SessionStart`/`SessionEnd` hooks not available in Python
   - Only `ClaudeSDKClient` supports hooks, not `query()`

3. **Breaking Changes**
   - SDK recently renamed from "Claude Code SDK"
   - API may still evolve

4. **Subprocess Still Used Internally**
   - SDK wraps CLI subprocess internally
   - Not true in-process execution

## Recommendation

**Proceed with SDK integration.** The benefits significantly outweigh the concerns:

- Cleaner code (no JSON stream parsing)
- Better approval integration (Python hooks vs shell scripts)
- Interrupt support (clean cancellation)
- Type safety (structured message objects)
- Future-proof (official Anthropic SDK)

Start with a parallel implementation to validate before fully migrating.

## References

- [Claude Agent SDK Overview](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Python SDK Reference](https://platform.claude.com/docs/en/agent-sdk/python)
- [GitHub Repository](https://github.com/anthropics/claude-agent-sdk-python)
- [Hook Documentation](https://docs.anthropic.com/en/docs/claude-code/hooks)
