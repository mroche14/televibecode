"""Smart command suggestion using AI for natural language to command mapping."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# Agno is optional - only used for AI-based suggestions
try:
    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb

    AGNO_AVAILABLE = True
except ImportError:
    Agent = None  # type: ignore[assignment,misc]
    SqliteDb = None  # type: ignore[assignment,misc]
    AGNO_AVAILABLE = False


# Commands that modify state - always require confirmation
WRITE_COMMANDS = {
    "/new",  # Creates session and worktree
    "/newproject",  # Creates new project directory and repo
    "/close",  # Closes session, removes worktree
    "/run",  # Executes code changes
    "/cancel",  # Cancels running job
    "/claim",  # Claims task, modifies state
    "/sync",  # Syncs backlog, modifies DB
    "/scan",  # Scans projects, modifies DB
}

# Commands that only read state - can auto-execute with high confidence
READ_COMMANDS = {
    "/help",
    "/projects",
    "/sessions",
    "/use",  # Just switches context, no modification
    "/status",
    "/jobs",
    "/tail",
    "/tasks",
    "/next",
    "/summary",
    "/approvals",
    "/models",
    "/model",  # Viewing current model (without args)
}


@dataclass
class CommandSuggestion:
    """A suggested command with confidence."""

    command: str  # e.g., "/sessions" or "/new televibecode"
    description: str  # Human-readable description
    confidence: float  # 0.0 to 1.0
    is_write: bool = False  # True if command modifies state

    @property
    def auto_execute(self) -> bool:
        """Whether to auto-execute without confirmation.

        Only read-only commands with very high confidence can auto-execute.
        Write commands always require confirmation.
        """
        if self.is_write:
            return False
        return self.confidence >= 0.95


def is_write_command(command: str) -> bool:
    """Check if a command modifies state.

    Args:
        command: Full command string (e.g., "/run pytest" or "/sessions").

    Returns:
        True if command modifies state.
    """
    # Extract base command (first word)
    base_cmd = command.split()[0] if command else ""
    return base_cmd in WRITE_COMMANDS


@dataclass
class SuggestionResult:
    """Result of command suggestion."""

    suggestions: list[CommandSuggestion] = field(default_factory=list)
    message: str | None = None  # Optional message to show user
    needs_context: str | None = None  # What context is missing (e.g., "project_id")
    is_greeting: bool = False  # True if user is just saying hi
    is_conversational: bool = False  # True if not a command request
    error_type: str | None = None  # Error type: "rate_limit", "provider_error", etc.


# Available commands with descriptions
COMMANDS = {
    "/help": "Show all available commands",
    "/projects": "List registered git repositories",
    "/scan": "Scan for new repositories in projects folder",
    "/newproject <name>": "Create a new project from scratch",
    "/sessions": "List all active coding sessions",
    "/new <project>": "Create a new session for a project",
    "/use <session>": "Switch to a session (e.g., /use S1)",
    "/close": "Close the current session",
    "/status": "Show status of current session",
    "/run <instruction>": "Run a coding instruction in current session",
    "/jobs": "List recent jobs and their status",
    "/tail": "View logs of the current/last job",
    "/cancel": "Cancel the currently running job",
    "/tasks": "List backlog tasks for current project",
    "/claim <task>": "Claim a task to work on (e.g., /claim T-123)",
    "/sync": "Sync tasks from Backlog.md files",
    "/approvals": "List pending approval requests",
    "/models": "Browse and select AI models",
    "/model": "Show or set current AI model",
}

SYSTEM_PROMPT = """You are a command assistant for TeleVibeCode, \
a Telegram bot that controls Claude Code sessions.

Your job is to understand what the user wants and \
suggest the exact command(s) they should use.

AVAILABLE COMMANDS:
{commands}

CURRENT CONTEXT:
- Active session: {active_session}
- Available projects: {projects}
- Available sessions: {sessions}

USER MESSAGE: "{message}"

Respond with a JSON object:
{{
  "suggestions": [
    {{
      "command": "/exact_command with_args",
      "description": "What this does",
      "confidence": 0.95
    }}
  ],
  "message": "Optional helpful message",
  "is_greeting": false,
  "is_conversational": false,
  "needs_context": null
}}

RULES:
1. If the intent is clear, give ONE suggestion with high confidence (>0.8)
2. If ambiguous, give 2-4 suggestions with varying confidence
3. For greetings (hi, hello, hey), set is_greeting=true and include a friendly message
4. For questions about capabilities, set is_conversational=true and explain in message
5. If user wants to run code but no session is active, set needs_context="session"
6. Always use the exact command format from AVAILABLE COMMANDS
7. Replace <project>, <session>, <task> with actual values from context when possible
8. For /run commands, include the user's instruction as the argument
9. Confidence guide: 0.95+ = execute directly, 0.7-0.95 = confirm, <0.7 = show options

EXAMPLES:
- "show me sessions" -> /sessions (confidence: 0.95)
- "start working on televibecode" -> /new televibecode (confidence: 0.9)
- "switch to S1" -> /use S1 (confidence: 0.95)
- "what's happening" -> [/status, /jobs, /sessions] (confidence: 0.6 each)
- "run the tests" -> /run pytest (if session active, confidence: 0.85)
- "hello" -> is_greeting=true, message="Hi! I'm ready to help..."
"""


class CommandSuggester:
    """Suggests commands based on natural language input."""

    def __init__(
        self,
        model: str = "openrouter:meta-llama/llama-3.2-3b-instruct:free",
        num_history_runs: int = 8,
        db_path: Path | None = None,
    ):
        """Initialize the suggester.

        Args:
            model: Model in format 'provider:model_id'.
            num_history_runs: Number of past runs to include in context.
            db_path: Path to SQLite database for persistent memory.
        """
        self.model = model
        self.num_history_runs = num_history_runs
        self.db_path = db_path
        self._agents: dict[int, Agent] = {}  # Per-chat agents for session isolation
        self._db: SqliteDb | None = None

    def _get_db(self) -> SqliteDb | None:
        """Get or create the SQLite database for persistent storage."""
        if SqliteDb is None or self.db_path is None:
            return None
        if self._db is None:
            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = SqliteDb(
                db_file=str(self.db_path),
                session_table="suggester_sessions",
            )
        return self._db

    def _get_agent(self, chat_id: int):
        """Get or create the Agno agent for a specific chat.

        Args:
            chat_id: Telegram chat ID for session isolation.
        """
        if not AGNO_AVAILABLE or Agent is None:
            raise RuntimeError("Agno not installed")
        if chat_id not in self._agents:
            db = self._get_db()
            self._agents[chat_id] = Agent(
                model=self.model,
                description="Command suggester for TeleVibeCode",
                instructions=["You suggest Telegram commands based on user input."],
                session_id=f"chat_{chat_id}",
                db=db,
                add_history_to_context=True,
                read_chat_history=True,
                num_history_runs=self.num_history_runs,
            )
        return self._agents[chat_id]

    def reset_chat(self, chat_id: int) -> bool:
        """Reset chat history for a specific chat.

        Args:
            chat_id: Telegram chat ID to reset.

        Returns:
            True if reset successful.
        """
        # Remove cached agent (creates fresh one on next use)
        if chat_id in self._agents:
            del self._agents[chat_id]
        return True

    def _build_prompt(
        self,
        message: str,
        active_session: str | None,
        projects: list[str],
        sessions: list[str],
    ) -> str:
        """Build the prompt with context."""
        commands_str = "\n".join(f"  {cmd}: {desc}" for cmd, desc in COMMANDS.items())

        return SYSTEM_PROMPT.format(
            commands=commands_str,
            active_session=active_session or "None",
            projects=", ".join(projects) if projects else "None",
            sessions=", ".join(sessions) if sessions else "None",
            message=message,
        )

    async def suggest(
        self,
        message: str,
        chat_id: int,
        active_session: str | None = None,
        projects: list[str] | None = None,
        sessions: list[str] | None = None,
    ) -> SuggestionResult:
        """Get command suggestions for a message.

        Args:
            message: User's natural language input.
            chat_id: Telegram chat ID for session memory.
            active_session: Currently active session ID.
            projects: List of available project IDs.
            sessions: List of available session IDs.

        Returns:
            SuggestionResult with suggested commands.
        """
        # Quick pattern matching for obvious cases
        quick_result = self._quick_match(message, active_session)
        if quick_result:
            return quick_result

        # Use AI for complex cases
        try:
            return await self._ai_suggest(
                message,
                chat_id,
                active_session,
                projects or [],
                sessions or [],
            )
        except Exception as e:
            # Fallback if AI fails - log the error for debugging
            import structlog
            log = structlog.get_logger()
            error_str = str(e).lower()
            log.error("ai_suggest_failed", error=str(e), message=message[:50])

            # Detect rate limit errors
            if "429" in str(e) or "rate" in error_str or "limit" in error_str:
                return SuggestionResult(
                    message="AI model rate limited. Use /model to switch models.",
                    error_type="rate_limit",
                )

            # Detect provider errors
            if "provider" in error_str or "upstream" in error_str:
                return SuggestionResult(
                    message="AI provider error. Use /model to try a different model.",
                    error_type="provider_error",
                )

            return SuggestionResult(
                message="I couldn't understand that. Try /help to see commands.",
                error_type="unknown",
            )

    def _quick_match(
        self, message: str, active_session: str | None
    ) -> SuggestionResult | None:
        """Quick pattern matching for common phrases."""
        msg = message.lower().strip()

        # Greetings
        if msg in ("hi", "hello", "hey", "yo", "sup"):
            status = f" Active session: {active_session}" if active_session else ""
            return SuggestionResult(
                is_greeting=True,
                message=f"Hey! Ready to help with your coding.{status}\n\n"
                "What would you like to do? Try:\n"
                "- 'show sessions' - see active sessions\n"
                "- 'show projects' - see available repos\n"
                "- 'help' - see all commands",
            )

        # Exact command matches (just missing the slash)
        # Read-only commands - can auto-execute
        if msg == "help":
            return SuggestionResult(
                suggestions=[CommandSuggestion("/help", "Show all commands", 1.0)]
            )
        if msg in ("sessions", "show sessions", "list sessions"):
            return SuggestionResult(
                suggestions=[
                    CommandSuggestion("/sessions", "List active sessions", 1.0)
                ]
            )
        if msg in ("projects", "show projects", "list projects"):
            return SuggestionResult(
                suggestions=[CommandSuggestion("/projects", "List repositories", 1.0)]
            )
        if msg in ("status", "whats happening", "what's happening"):
            return SuggestionResult(
                suggestions=[CommandSuggestion("/status", "Show session status", 0.95)]
            )
        if msg in ("jobs", "show jobs", "job status"):
            return SuggestionResult(
                suggestions=[CommandSuggestion("/jobs", "List recent jobs", 0.95)]
            )
        if msg in ("tasks", "show tasks", "list tasks", "backlog"):
            return SuggestionResult(
                suggestions=[CommandSuggestion("/tasks", "List backlog tasks", 0.95)]
            )
        if msg in ("models", "show models", "list models"):
            return SuggestionResult(
                suggestions=[CommandSuggestion("/models", "Browse AI models", 0.95)]
            )
        if msg in ("logs", "show logs", "tail"):
            return SuggestionResult(
                suggestions=[CommandSuggestion("/tail", "View job logs", 0.95)]
            )
        if msg in ("approvals", "pending approvals"):
            return SuggestionResult(
                suggestions=[
                    CommandSuggestion("/approvals", "List pending approvals", 0.95)
                ]
            )

        # Write commands - always require confirmation (is_write=True)
        if msg in ("scan", "scan projects"):
            return SuggestionResult(
                suggestions=[
                    CommandSuggestion(
                        "/scan", "Scan for repositories", 0.95, is_write=True
                    )
                ]
            )
        if msg in ("close", "close session", "end session"):
            return SuggestionResult(
                suggestions=[
                    CommandSuggestion(
                        "/close", "Close current session", 0.9, is_write=True
                    )
                ]
            )
        if msg in ("cancel", "cancel job", "stop"):
            return SuggestionResult(
                suggestions=[
                    CommandSuggestion(
                        "/cancel", "Cancel running job", 0.9, is_write=True
                    )
                ]
            )
        if msg in ("sync", "sync backlog", "sync tasks"):
            return SuggestionResult(
                suggestions=[
                    CommandSuggestion(
                        "/sync", "Sync backlog tasks", 0.95, is_write=True
                    )
                ]
            )

        # Session switching patterns (read-only - just changes context)
        session_match = re.match(r"(?:use|switch(?: to)?)\s+(s\d+)", msg, re.I)
        if session_match:
            sid = session_match.group(1).upper()
            return SuggestionResult(
                suggestions=[CommandSuggestion(f"/use {sid}", f"Switch to {sid}", 0.95)]
            )

        # New project patterns (write - creates new repo)
        # Must be checked before new session pattern
        newproj_match = re.match(
            r"(?:i want to )?(?:create|make|start)\s+"
            r"(?:a\s+)?(?:new\s+)?project\s+"
            r"(?:named?|called)?\s*(\S+)",
            msg,
            re.I,
        )
        if newproj_match:
            name = newproj_match.group(1).lower().rstrip(".,!?")
            return SuggestionResult(
                suggestions=[
                    CommandSuggestion(
                        f"/newproject {name}",
                        f"Create project '{name}'",
                        0.90,
                        is_write=True,
                    )
                ]
            )

        # Also match "newproject X" without slash
        newproj_simple = re.match(r"newproject\s+(\S+)", msg, re.I)
        if newproj_simple:
            name = newproj_simple.group(1).lower().rstrip(".,!?")
            return SuggestionResult(
                suggestions=[
                    CommandSuggestion(
                        f"/newproject {name}",
                        f"Create project '{name}'",
                        0.95,
                        is_write=True,
                    )
                ]
            )

        # New session patterns (write - creates worktree)
        new_match = re.match(
            r"(?:new|create|start)\s+(?:session\s+)?(?:on\s+|for\s+)?(\S+)", msg, re.I
        )
        if new_match:
            project = new_match.group(1)
            # Skip if it looks like "create project" (handled above)
            if project.lower() in ("project", "a"):
                pass
            else:
                return SuggestionResult(
                    suggestions=[
                        CommandSuggestion(
                            f"/new {project}",
                            f"Create session for {project}",
                            0.85,
                            is_write=True,
                        )
                    ]
                )

        # Run instruction patterns (write - executes code changes)
        run_match = re.match(r"(?:run|execute|do)\s+(.+)", msg, re.I)
        if run_match and active_session:
            instruction = run_match.group(1)
            suffix = "..." if len(instruction) > 50 else ""
            return SuggestionResult(
                suggestions=[
                    CommandSuggestion(
                        f"/run {instruction}",
                        f"Run: {instruction[:50]}{suffix}",
                        0.85,
                        is_write=True,
                    )
                ]
            )

        # Claim task pattern (write - modifies task state)
        claim_match = re.match(r"(?:claim|take|work on)\s+(t-?\d+)", msg, re.I)
        if claim_match:
            task_id = claim_match.group(1).upper()
            if not task_id.startswith("T-"):
                if task_id.startswith("T"):
                    task_id = f"T-{task_id[1:]}"
                else:
                    task_id = f"T-{task_id}"
            return SuggestionResult(
                suggestions=[
                    CommandSuggestion(
                        f"/claim {task_id}",
                        f"Claim task {task_id}",
                        0.85,
                        is_write=True,
                    )
                ]
            )

        return None

    async def _ai_suggest(
        self,
        message: str,
        chat_id: int,
        active_session: str | None,
        projects: list[str],
        sessions: list[str],
    ) -> SuggestionResult:
        """Use AI to suggest commands."""
        agent = self._get_agent(chat_id)

        prompt = self._build_prompt(message, active_session, projects, sessions)
        response = await agent.arun(prompt)

        # Parse JSON response
        try:
            # Extract JSON from response (may have extra text)
            content = response.content
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                raise ValueError("No JSON found")

            suggestions = []
            for s in data.get("suggestions", []):
                cmd = s.get("command", "")
                suggestions.append(
                    CommandSuggestion(
                        command=cmd,
                        description=s.get("description", ""),
                        confidence=float(s.get("confidence", 0.5)),
                        is_write=is_write_command(cmd),
                    )
                )

            return SuggestionResult(
                suggestions=suggestions,
                message=data.get("message"),
                needs_context=data.get("needs_context"),
                is_greeting=data.get("is_greeting", False),
                is_conversational=data.get("is_conversational", False),
            )

        except (json.JSONDecodeError, ValueError, KeyError):
            # AI didn't return valid JSON, try to extract command
            content = response.content.strip()
            if content.startswith("/"):
                cmd = content.split()[0]
                return SuggestionResult(
                    suggestions=[
                        CommandSuggestion(
                            cmd,
                            "Suggested command",
                            0.6,
                            is_write=is_write_command(cmd),
                        )
                    ]
                )

            return SuggestionResult(
                message="I'm not sure what you mean. Try /help to see commands."
            )


# Global suggester instance
_suggester: CommandSuggester | None = None
_suggester_model: str | None = None
_suggester_db_path: Path | None = None


def get_suggester(
    model: str = "openrouter:meta-llama/llama-3.2-3b-instruct:free",
    db_path: Path | None = None,
) -> CommandSuggester:
    """Get the global command suggester.

    Args:
        model: Model in format 'provider:model_id'.
        db_path: Path to SQLite database for persistent memory.

    Returns:
        CommandSuggester instance.
    """
    global _suggester, _suggester_model, _suggester_db_path
    if _suggester is None or _suggester_model != model or _suggester_db_path != db_path:
        _suggester = CommandSuggester(model=model, db_path=db_path)
        _suggester_model = model
        _suggester_db_path = db_path
    return _suggester


def reset_chat_history(chat_id: int) -> bool:
    """Reset chat history for a specific chat.

    Args:
        chat_id: Telegram chat ID to reset.

    Returns:
        True if reset successful, False otherwise.
    """
    global _suggester
    if _suggester is not None:
        return _suggester.reset_chat(chat_id)
    return True  # No suggester means nothing to reset


async def suggest_commands(
    message: str,
    chat_id: int,
    model: str = "openrouter:meta-llama/llama-3.2-3b-instruct:free",
    db_path: Path | None = None,
    active_session: str | None = None,
    projects: list[str] | None = None,
    sessions: list[str] | None = None,
) -> SuggestionResult:
    """Suggest commands for a natural language message.

    Args:
        message: User's input.
        chat_id: Telegram chat ID for session memory.
        model: AI model to use.
        db_path: Path to SQLite database for persistent memory.
        active_session: Current session ID.
        projects: Available project IDs.
        sessions: Available session IDs.

    Returns:
        SuggestionResult with suggestions.
    """
    suggester = get_suggester(model=model, db_path=db_path)
    return await suggester.suggest(message, chat_id, active_session, projects, sessions)
