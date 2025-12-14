"""Telegram command handlers."""

import contextlib

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from televibecode.ai import transcribe_telegram_voice
from televibecode.ai.command_suggester import reset_chat_history, suggest_commands
from televibecode.ai.models import ModelRegistry
from televibecode.ai.tool_tester import (
    get_tested_models,
    load_results,
    needs_testing,
    run_full_test,
)

# Conversational agent (optional but preferred)
try:
    from televibecode.ai.agent import (
        TeleVibeAgent,
        get_agent,
        get_pending_action,
        clear_pending_action,
    )
    AGENT_AVAILABLE = True
except ImportError:
    AGENT_AVAILABLE = False
    TeleVibeAgent = None
    get_agent = None
    get_pending_action = None
    clear_pending_action = None
from televibecode.config import Settings
from televibecode.db import (
    Database,
    JobStatus,
    SessionState,
    TaskPriority,
    TaskStatus,
)
from televibecode.orchestrator.tools import approvals, projects, sessions, tasks
from televibecode.runner import (
    get_job_logs,
    get_job_summary,
    list_session_jobs,
    run_instruction,
)
from televibecode.telegram.formatters import format_project_list, format_session_list
from televibecode.telegram.state import ChatStateManager

__all__ = [
    "start_command",
    "help_command",
    "projects_command",
    "scan_command",
    "sessions_command",
    "new_session_command",
    "use_session_command",
    "close_session_command",
    "cleanup_sessions_command",
    "cleanup_callback_handler",
    "status_command",
    "handle_reply_message",
    "session_callback_handler",
    "tasks_command",
    "next_tasks_command",
    "claim_task_command",
    "sync_backlog_command",
    "task_callback_handler",
    "run_command",
    "jobs_command",
    "summary_command",
    "tail_command",
    "cancel_command",
    "approvals_command",
    "approval_callback_handler",
    "natural_language_handler",
    "voice_message_handler",
    "models_command",
    "model_command",
    "model_callback_handler",
    "command_callback_handler",
    "voice_confirm_callback_handler",
    "newproject_command",
    "newproject_callback_handler",
    "reset_command",
    "agent_callback_handler",
]


def _session_state_icon(state: SessionState) -> str:
    """Get icon for session state."""
    icons = {
        SessionState.IDLE: "🟢",
        SessionState.RUNNING: "🔧",
        SessionState.BLOCKED: "⏸️",
        SessionState.CLOSING: "🔴",
    }
    return icons.get(state, "❓")


def build_session_keyboard(
    sessions_list: list,
    active_session_id: str | None = None,
    show_status: bool = False,
) -> InlineKeyboardMarkup:
    """Build inline keyboard for session switching.

    Args:
        sessions_list: List of Session objects.
        active_session_id: Currently active session ID.
        show_status: Include status button.

    Returns:
        InlineKeyboardMarkup with session buttons.
    """
    buttons = []
    row = []

    for session in sessions_list:
        # Build button label
        icon = _session_state_icon(session.state)
        is_active = session.session_id == active_session_id
        label = f"{icon} {session.session_id}"
        if is_active:
            label = f"[{label}]"

        row.append(
            InlineKeyboardButton(
                label,
                callback_data=f"session:use:{session.session_id}",
            )
        )

        # Max 3 buttons per row
        if len(row) >= 3:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    # Add action buttons if there are sessions
    if sessions_list and show_status:
        action_row = [
            InlineKeyboardButton("📊 Status", callback_data="session:status"),
            InlineKeyboardButton("🔄 Refresh", callback_data="session:refresh"),
            InlineKeyboardButton("🗑️ Cleanup", callback_data="cleanup:confirm"),
        ]
        buttons.append(action_row)

    return InlineKeyboardMarkup(buttons)


def get_db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    """Get database from context."""
    return context.bot_data["db"]


def get_settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    """Get settings from context."""
    return context.bot_data["settings"]


def get_chat_state(context: ContextTypes.DEFAULT_TYPE) -> ChatStateManager:
    """Get chat state manager from context."""
    return context.bot_data["chat_state"]


async def send_with_context(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    session_id: str | None = None,
    project_id: str | None = None,
    job_id: str | None = None,
    message_type: str = "general",
    **kwargs,
) -> Message:
    """Send a message and store its context for reply routing.

    Args:
        update: Telegram Update.
        context: Bot context.
        text: Message text.
        session_id: Associated session ID.
        project_id: Associated project ID.
        job_id: Associated job ID.
        message_type: Type of message.
        **kwargs: Additional args for reply_text (e.g., parse_mode).

    Returns:
        The sent Message.
    """
    msg = await update.message.reply_text(text, **kwargs)

    # Store context for this message
    chat_state = get_chat_state(context)
    chat_state.store_message_context(
        message_id=msg.message_id,
        chat_id=msg.chat_id,
        session_id=session_id,
        project_id=project_id,
        job_id=job_id,
        message_type=message_type,
    )

    return msg


def get_session_from_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> str | None:
    """Get session ID from a reply-to message if available.

    Args:
        update: Telegram Update.
        context: Bot context.

    Returns:
        Session ID from replied message, or None.
    """
    if not update.message or not update.message.reply_to_message:
        return None

    chat_state = get_chat_state(context)
    reply_to_id = update.message.reply_to_message.message_id
    return chat_state.get_session_for_reply(reply_to_id)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    await update.message.reply_text(
        "Welcome to TeleVibeCode!\n\n"
        "I help you manage Claude Code sessions remotely.\n\n"
        "Use /help to see available commands.\n"
        "Use /projects to see your registered projects."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    help_text = """
*TeleVibeCode Commands*

*Projects*
/projects - List all projects
/scan - Scan for new projects

*Sessions*
/sessions - List active sessions
/new <project> [branch] - Create session
/use <session> - Set active session
/close <session> - Close session
/status [session] - Detailed status

*Tasks*
/tasks [project] - List tasks
/next [project] - Show next priority tasks
/claim <task\\_id> - Claim task for session
/sync [project] - Sync from Backlog.md

*Jobs*
/run <instruction> - Run Claude Code
/jobs [session] - List recent jobs
/summary [job\\_id] - Show job summary
/tail [job\\_id] [lines] - Show job logs
/cancel [job\\_id] - Cancel running job

*Reply Routing*
Reply to any bot message to send instructions to that session's context.

*AI Models*
/models - List available AI models (ranked)
/model <id> - Switch to a specific model

*Other*
/reset - Clear AI conversation history
/help - Show this message
    """.strip()

    await update.message.reply_text(help_text, parse_mode="Markdown")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reset command - clears AI conversation history."""
    chat_id = update.effective_chat.id

    # Reset the command suggester memory
    success = reset_chat_history(chat_id)

    if success:
        await update.message.reply_text(
            "AI conversation history cleared.\n\n"
            "The command suggester will start fresh without previous context."
        )
    else:
        await update.message.reply_text(
            "Failed to clear conversation history. Please try again."
        )


async def projects_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /projects command."""
    db = get_db(context)
    project_list = await projects.list_projects(db)

    if not project_list:
        await update.message.reply_text(
            "No projects registered.\n\n"
            "Use /scan to discover projects, or register one manually."
        )
        return

    text = format_project_list(project_list)
    await update.message.reply_text(text, parse_mode="Markdown")


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /scan command."""
    db = get_db(context)
    settings = context.bot_data["settings"]

    await update.message.reply_text("Scanning for projects...")

    result = await projects.scan_projects(db, settings.televibe_root)

    if result["registered"]:
        text = f"Found {result['found']} repositories.\n\n"
        text += f"*Registered*: {len(result['details']['registered'])}\n"
        for p in result["details"]["registered"]:
            text += f"  • `{p['project_id']}` - {p['name']}\n"

        if result["details"]["skipped"]:
            skipped_count = len(result["details"]["skipped"])
            text += f"\n*Skipped*: {skipped_count} (already registered)\n"

        if result["details"]["errors"]:
            text += f"\n*Errors*: {len(result['details']['errors'])}\n"
            for e in result["details"]["errors"]:
                text += f"  • {e['path']}: {e['error']}\n"

        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"Scanned {settings.televibe_root}\n\n"
            f"Found {result['found']} repositories.\n"
            f"All already registered or no new projects found."
        )


async def newproject_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /newproject command - create a new project from scratch."""
    args = context.args
    chat_id = update.effective_chat.id

    if not args:
        await update.message.reply_text(
            "*Create New Project*\n\n"
            "Usage: `/newproject <name>`\n\n"
            "Name must be:\n"
            "• Lowercase letters, numbers, dashes\n"
            "• Start with a letter\n"
            "• No spaces or special characters\n\n"
            "Example: `/newproject my-app`",
            parse_mode="Markdown",
        )
        return

    name = args[0].lower()

    # Validate name first
    error = projects.validate_project_name(name)
    if error:
        await update.message.reply_text(f"❌ Invalid name: {error}")
        return

    # Check if already exists
    settings: Settings = context.bot_data["settings"]
    project_path = settings.televibe_root / name

    if project_path.exists():
        await update.message.reply_text(
            f"❌ Directory already exists: `{project_path}`",
            parse_mode="Markdown",
        )
        return

    db = get_db(context)
    existing = await db.get_project(name)
    if existing:
        await update.message.reply_text(
            f"❌ Project `{name}` already registered.",
            parse_mode="Markdown",
        )
        return

    # Store pending project name and show remote options
    if "pending_projects" not in context.bot_data:
        context.bot_data["pending_projects"] = {}
    context.bot_data["pending_projects"][chat_id] = name

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🐙 GitHub", callback_data=f"newproj:github:{name}"
                ),
                InlineKeyboardButton(
                    "🦊 GitLab", callback_data=f"newproj:gitlab:{name}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "⏭️ Skip (local only)", callback_data=f"newproj:skip:{name}"
                ),
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data="newproj:cancel"),
            ],
        ]
    )

    await update.message.reply_text(
        f"📂 Creating project `{name}`\n\n"
        "Create a remote repository?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def newproject_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle newproject button callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("newproj:"):
        return

    parts = data.split(":", 2)
    if len(parts) < 2:
        return

    action = parts[1]
    chat_id = update.effective_chat.id

    if action == "cancel":
        # Clean up
        if "pending_projects" in context.bot_data:
            context.bot_data["pending_projects"].pop(chat_id, None)
        with contextlib.suppress(BadRequest):
            await query.edit_message_text("Cancelled.")
        return

    if len(parts) < 3:
        return

    name = parts[2]
    remote = None if action == "skip" else action

    # Show progress
    with contextlib.suppress(BadRequest):
        remote_text = f" + {action.title()} remote" if remote else ""
        await query.edit_message_text(f"⏳ Creating `{name}`{remote_text}...")

    db = get_db(context)
    settings: Settings = context.bot_data["settings"]
    chat_state = get_chat_state(context)

    try:
        # Create the project
        result = await projects.create_project(
            db=db,
            projects_root=settings.televibe_root,
            name=name,
            remote=remote,
        )

        # Create initial session
        from televibecode.orchestrator.tools import sessions

        session_result = await sessions.create_session(
            db=db,
            settings=settings,
            project_id=name,
        )

        # Set as active session
        chat_state.set_active_session(chat_id, session_result["session_id"])

        # Build success message
        msg_lines = [
            "✅ *Project created!*\n",
            f"📂 `{result['path']}`",
        ]
        if result.get("remote_url"):
            msg_lines.append(f"🌐 {result['remote_url']}")
        msg_lines.extend(
            [
                f"\n🔹 Session `{session_result['session_id']}` created",
                f"🌿 Branch: `{session_result['branch']}`",
                "\nReady for instructions!",
            ]
        )

        with contextlib.suppress(BadRequest):
            await query.edit_message_text(
                "\n".join(msg_lines), parse_mode="Markdown"
            )

    except ValueError as e:
        with contextlib.suppress(BadRequest):
            await query.edit_message_text(f"❌ Error: {e}")

    finally:
        # Clean up pending
        if "pending_projects" in context.bot_data:
            context.bot_data["pending_projects"].pop(chat_id, None)


async def sessions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sessions command."""
    db = get_db(context)
    chat_state = get_chat_state(context)
    chat_id = update.effective_chat.id

    # Check if filtering by project
    args = context.args
    project_id = args[0] if args else None

    if project_id:
        sessions_list = await db.get_sessions_by_project(project_id)
        title = f"Sessions for `{project_id}`"
    else:
        sessions_list = await db.get_active_sessions()
        title = "Active Sessions"

    if not sessions_list:
        if project_id:
            await update.message.reply_text(
                f"No sessions for project `{project_id}`.\n\n"
                f"Create one with: `/new {project_id} [branch]`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "No active sessions.\n\nCreate one with: `/new <project> [branch]`",
                parse_mode="Markdown",
            )
        return

    # Get active session for highlighting
    active_session = chat_state.get_active_session(chat_id)

    # Build keyboard
    keyboard = build_session_keyboard(
        sessions_list,
        active_session_id=active_session,
        show_status=True,
    )

    text = format_session_list(sessions_list, title)
    text += "\n\n_Tap a session to switch to it._"

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def new_session_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /new command - create a new session.

    Usage: /new <project_id> [branch] [name]
    """
    db = get_db(context)
    settings = get_settings(context)
    chat_state = get_chat_state(context)
    args = context.args or []

    if not args:
        await update.message.reply_text(
            "Usage: `/new <project_id> [branch] [name]`\n\n"
            "Examples:\n"
            "  `/new myproject` - auto-generate branch\n"
            "  `/new myproject feature-x` - use specific branch\n"
            '  `/new myproject feature-x "Fix auth bug"`',
            parse_mode="Markdown",
        )
        return

    project_id = args[0]
    branch = args[1] if len(args) > 1 else None
    display_name = " ".join(args[2:]) if len(args) > 2 else None

    # Remove quotes from display name if present
    if display_name:
        display_name = display_name.strip('"').strip("'")

    try:
        result = await sessions.create_session(
            db=db,
            settings=settings,
            project_id=project_id,
            branch=branch,
            display_name=display_name,
        )

        # Set as active session for this chat
        chat_id = update.effective_chat.id
        chat_state.set_active_session(chat_id, result["session_id"])

        text = (
            f"*Session Created*\n\n"
            f"📂 `{result['session_id']}` on `{result['project_name']}`\n"
            f"🌿 Branch: `{result['branch']}`\n"
            f"📍 {result['workspace_path']}\n\n"
            f"_This is now your active session._"
        )
        await send_with_context(
            update,
            context,
            text,
            session_id=result["session_id"],
            project_id=project_id,
            message_type="session",
            parse_mode="Markdown",
        )

    except ValueError as e:
        await update.message.reply_text(f"Failed to create session: {e}")


async def use_session_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /use command - set active session.

    Usage: /use <session_id>
    """
    db = get_db(context)
    chat_state = get_chat_state(context)
    args = context.args or []

    if not args:
        # Show current active session
        chat_id = update.effective_chat.id
        current = chat_state.get_active_session(chat_id)

        if current:
            session = await db.get_session(current)
            if session:
                text = (
                    f"Active session: `{current}` "
                    f"({session.project_id}/{session.branch})\n\n"
                    f"Use `/use <session_id>` to switch."
                )
                await update.message.reply_text(text, parse_mode="Markdown")
                return

        await update.message.reply_text(
            "No active session.\n\n"
            "Use `/use <session_id>` to set one, or `/sessions` to list available.",
            parse_mode="Markdown",
        )
        return

    session_id = args[0].upper()
    if not session_id.startswith("S"):
        session_id = f"S{session_id}"

    session = await db.get_session(session_id)
    if not session:
        await update.message.reply_text(
            f"Session `{session_id}` not found.\n\n"
            f"Use `/sessions` to see available sessions.",
            parse_mode="Markdown",
        )
        return

    # Set as active
    chat_id = update.effective_chat.id
    chat_state.set_active_session(chat_id, session_id)

    project = await db.get_project(session.project_id)
    project_name = project.name if project else session.project_id

    await send_with_context(
        update,
        context,
        f"*Active Session*: `{session_id}`\n\n"
        f"📂 {project_name}\n"
        f"🌿 {session.branch}\n"
        f"🔹 State: {session.state.value}",
        session_id=session_id,
        project_id=session.project_id,
        message_type="session",
        parse_mode="Markdown",
    )


async def close_session_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /close command - close a session.

    Usage: /close [session_id] [--force]
    """
    db = get_db(context)
    chat_state = get_chat_state(context)
    args = context.args or []

    # Parse args
    session_id = None
    force = False

    for arg in args:
        if arg in ("--force", "-f"):
            force = True
        elif not session_id:
            session_id = arg.upper()
            if not session_id.startswith("S"):
                session_id = f"S{session_id}"

    # If no session specified, use active
    if not session_id:
        chat_id = update.effective_chat.id
        session_id = chat_state.get_active_session(chat_id)

        if not session_id:
            await update.message.reply_text(
                "No session specified and no active session.\n\n"
                "Usage: `/close <session_id>` or set an active session first.",
                parse_mode="Markdown",
            )
            return

    try:
        result = await sessions.close_session(
            db=db,
            session_id=session_id,
            force=force,
        )

        # Clear active session if it was this one
        chat_id = update.effective_chat.id
        if chat_state.get_active_session(chat_id) == session_id:
            chat_state.set_active_session(chat_id, None)

        await update.message.reply_text(
            f"Session `{session_id}` closed.\n"
            f"Branch: `{result.get('branch', 'N/A')}`\n"
            f"Worktree removed: {'Yes' if result.get('worktree_removed') else 'No'}",
            parse_mode="Markdown",
        )

    except ValueError as e:
        await update.message.reply_text(
            f"Failed to close session: {e}\n\n_Use `--force` to force close._",
            parse_mode="Markdown",
        )


async def cleanup_sessions_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /cleanup command - close all sessions.

    Usage: /cleanup [--force]
    """
    db = get_db(context)
    args = context.args or []
    force = "--force" in args or "-f" in args

    # Get all active sessions
    all_sessions = await db.get_active_sessions()

    if not all_sessions:
        await update.message.reply_text("No active sessions to clean up.")
        return

    if not force:
        # Ask for confirmation
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"🗑️ Yes, close all {len(all_sessions)} sessions",
                    callback_data="cleanup:confirm",
                ),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="cleanup:cancel")],
        ])

        session_list = "\n".join(
            f"• `{s.session_id}` - {s.project_id}" for s in all_sessions[:10]
        )
        if len(all_sessions) > 10:
            session_list += f"\n... and {len(all_sessions) - 10} more"

        await update.message.reply_text(
            f"⚠️ *Close all {len(all_sessions)} sessions?*\n\n"
            f"{session_list}\n\n"
            f"This will remove all worktrees.",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return

    # Force cleanup - do it directly
    await _do_cleanup_all_sessions(update, context, all_sessions)


async def _do_cleanup_all_sessions(update, context, all_sessions) -> None:
    """Actually perform the cleanup of all sessions."""
    db = get_db(context)
    chat_state = get_chat_state(context)
    chat_id = update.effective_chat.id

    closed = 0
    failed = 0
    errors = []

    for session in all_sessions:
        try:
            await sessions.close_session(db=db, session_id=session.session_id, force=True)
            closed += 1
            log.info("cleanup_session_closed", session_id=session.session_id)
        except Exception as e:
            failed += 1
            errors.append(f"{session.session_id}: {e}")
            log.error("cleanup_session_failed", session_id=session.session_id, error=str(e))

    # Clear active session
    chat_state.set_active_session(chat_id, None)

    msg = f"🧹 *Cleanup Complete*\n\n✅ Closed: {closed}\n❌ Failed: {failed}"
    if errors:
        msg += f"\n\nErrors:\n" + "\n".join(errors[:5])

    # Handle both message and callback query
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")


async def cleanup_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle cleanup confirmation callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data  # cleanup:confirm or cleanup:cancel

    if data == "cleanup:cancel":
        await query.edit_message_text("Cleanup cancelled.")
        return

    if data == "cleanup:confirm":
        db = get_db(context)
        all_sessions = await db.get_active_sessions()
        await _do_cleanup_all_sessions(update, context, all_sessions)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command - show detailed session status.

    Usage: /status [session_id]
    """
    db = get_db(context)
    chat_state = get_chat_state(context)
    args = context.args or []

    # Get session ID
    session_id = None
    if args:
        session_id = args[0].upper()
        if not session_id.startswith("S"):
            session_id = f"S{session_id}"
    else:
        chat_id = update.effective_chat.id
        session_id = chat_state.get_active_session(chat_id)

    if not session_id:
        await update.message.reply_text(
            "No session specified and no active session.\n\n"
            "Usage: `/status <session_id>` or set an active session first.",
            parse_mode="Markdown",
        )
        return

    try:
        status = await sessions.get_session_status(db, session_id)

        text = f"*Session {session_id}*\n\n"
        text += f"📂 {status['project_name']}\n"
        text += f"🌿 Branch: `{status['branch']}`\n"
        text += f"🔹 State: {status['state']}\n"

        # Git status
        git = status.get("git_status")
        if git and not git.get("error"):
            text += "\n*Git Status*:\n"
            if git.get("has_changes"):
                text += f"  📝 Staged: {git['staged']}\n"
                text += f"  📝 Unstaged: {git['unstaged']}\n"
                text += f"  📝 Untracked: {git['untracked']}\n"
            else:
                text += "  Clean working tree\n"

            if git.get("ahead", 0) > 0:
                text += f"  ⬆️ Ahead by {git['ahead']} commit(s)\n"
            if git.get("behind", 0) > 0:
                text += f"  ⬇️ Behind by {git['behind']} commit(s)\n"

        # Recent jobs
        jobs = status.get("recent_jobs", [])
        if jobs:
            text += f"\n*Recent Jobs* ({len(jobs)}):\n"
            for j in jobs[:3]:
                if j["status"] == "done":
                    icon = "✅"
                elif j["status"] == "failed":
                    icon = "❌"
                else:
                    icon = "🔧"
                text += f"  {icon} {j['instruction']}\n"

        # Last summary
        if status.get("last_summary"):
            summary = status["last_summary"][:150]
            if len(status["last_summary"]) > 150:
                summary += "..."
            text += f"\n*Last Summary*:\n{summary}"

        await update.message.reply_text(text, parse_mode="Markdown")

    except ValueError as e:
        await update.message.reply_text(f"Error: {e}")


async def handle_reply_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle text messages that are replies to bot messages.

    This enables reply-to session routing: when a user replies to a
    bot message, we route to the session associated with that message.
    """
    if not update.message or not update.message.reply_to_message:
        return

    # Check if this is a reply to the bot
    bot_id = context.bot.id
    replied_to = update.message.reply_to_message
    if replied_to.from_user and replied_to.from_user.id != bot_id:
        return  # Not a reply to our bot

    # Get session from reply context
    session_id = get_session_from_reply(update, context)

    if not session_id:
        # No session context found for this message
        # Check if there's an active session instead
        chat_state = get_chat_state(context)
        chat_id = update.effective_chat.id
        session_id = chat_state.get_active_session(chat_id)

        if not session_id:
            await update.message.reply_text(
                "No session context found for this reply.\n\n"
                "Use `/new <project>` to create a session, "
                "or `/use <session>` to set an active one.",
                parse_mode="Markdown",
            )
            return

    # Get the session
    db = get_db(context)
    session = await db.get_session(session_id)

    if not session:
        await update.message.reply_text(
            f"Session `{session_id}` no longer exists.",
            parse_mode="Markdown",
        )
        return

    # Get the text from the reply
    text = update.message.text or ""

    if not text.strip():
        await update.message.reply_text("Please provide an instruction.")
        return

    # Run the instruction in the session
    await _run_as_instruction(update, context, session_id, text)


async def session_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle callback queries from session inline keyboards.

    Callback data format: session:<action>:<session_id>
    Actions: use, status, refresh
    """
    query = update.callback_query
    await query.answer()  # Acknowledge the callback

    data = query.data
    if not data.startswith("session:"):
        return

    parts = data.split(":")
    if len(parts) < 2:
        return

    action = parts[1]
    db = get_db(context)
    chat_state = get_chat_state(context)
    chat_id = update.effective_chat.id

    if action == "use" and len(parts) >= 3:
        session_id = parts[2]

        # Set as active session
        session = await db.get_session(session_id)
        if not session:
            await query.edit_message_text(
                f"Session `{session_id}` no longer exists.",
                parse_mode="Markdown",
            )
            return

        chat_state.set_active_session(chat_id, session_id)

        project = await db.get_project(session.project_id)
        project_name = project.name if project else session.project_id

        # Update the message with new active session highlighted
        sessions_list = await db.get_active_sessions()
        keyboard = build_session_keyboard(
            sessions_list,
            active_session_id=session_id,
            show_status=True,
        )

        text = (
            f"*Switched to {session_id}*\n\n"
            f"📂 {project_name}\n"
            f"🌿 {session.branch}\n"
            f"🔹 State: {session.state.value}\n\n"
            f"_Reply to this message to send instructions._"
        )

        # Store context for the edited message
        chat_state.store_message_context(
            message_id=query.message.message_id,
            chat_id=chat_id,
            session_id=session_id,
            project_id=session.project_id,
            message_type="session",
        )

        try:
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        except BadRequest as e:
            # Ignore "Message is not modified" error (user clicked same button)
            if "not modified" not in str(e).lower():
                raise

    elif action == "status":
        # Show status of active session
        active = chat_state.get_active_session(chat_id)
        if not active:
            await query.edit_message_text(
                "No active session. Select one from the list.",
                parse_mode="Markdown",
            )
            return

        try:
            status = await sessions.get_session_status(db, active)

            text = f"*Session {active}*\n\n"
            text += f"📂 {status['project_name']}\n"
            text += f"🌿 Branch: `{status['branch']}`\n"
            text += f"🔹 State: {status['state']}\n"

            git = status.get("git_status")
            if git and not git.get("error"):
                if git.get("has_changes"):
                    text += f"\n📝 Changes: {git['staged']}S/{git['unstaged']}U\n"
                else:
                    text += "\n✨ Clean working tree\n"

            # Build keyboard for going back
            sessions_list = await db.get_active_sessions()
            keyboard = build_session_keyboard(
                sessions_list,
                active_session_id=active,
                show_status=True,
            )

            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

        except ValueError as e:
            await query.edit_message_text(f"Error: {e}")

    elif action == "refresh":
        # Refresh the sessions list
        sessions_list = await db.get_active_sessions()

        if not sessions_list:
            await query.edit_message_text(
                "No active sessions.\n\nCreate one with: `/new <project> [branch]`",
                parse_mode="Markdown",
            )
            return

        active = chat_state.get_active_session(chat_id)
        keyboard = build_session_keyboard(
            sessions_list,
            active_session_id=active,
            show_status=True,
        )

        text = format_session_list(sessions_list, "Active Sessions")
        text += "\n\n_Tap a session to switch to it._"

        try:
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        except BadRequest as e:
            # Ignore "Message is not modified" error (nothing changed)
            if "not modified" not in str(e).lower():
                raise


# =============================================================================
# Task Commands
# =============================================================================


def _task_priority_icon(priority: TaskPriority) -> str:
    """Get icon for task priority."""
    icons = {
        TaskPriority.LOW: "🔵",
        TaskPriority.MEDIUM: "🟡",
        TaskPriority.HIGH: "🟠",
        TaskPriority.CRITICAL: "🔴",
    }
    return icons.get(priority, "⚪")


def _task_status_icon(status: TaskStatus) -> str:
    """Get icon for task status."""
    icons = {
        TaskStatus.TODO: "📋",
        TaskStatus.IN_PROGRESS: "🔧",
        TaskStatus.BLOCKED: "⏸️",
        TaskStatus.NEEDS_REVIEW: "👀",
        TaskStatus.DONE: "✅",
    }
    return icons.get(status, "❓")


def build_task_keyboard(
    task_list: list[dict],
    show_claim: bool = True,
) -> InlineKeyboardMarkup:
    """Build inline keyboard for task actions.

    Args:
        task_list: List of task dictionaries.
        show_claim: Show claim button.

    Returns:
        InlineKeyboardMarkup with task buttons.
    """
    buttons = []

    for task in task_list[:5]:  # Max 5 tasks
        task_id = task["task_id"]

        row = [
            InlineKeyboardButton(
                f"📋 {task_id}",
                callback_data=f"task:view:{task_id}",
            ),
        ]

        if show_claim and not task.get("session_id"):
            row.append(
                InlineKeyboardButton(
                    "Claim",
                    callback_data=f"task:claim:{task_id}",
                )
            )

        buttons.append(row)

    # Add refresh button
    if task_list:
        buttons.append(
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="task:refresh"),
            ]
        )

    return InlineKeyboardMarkup(buttons)


def format_task_list(task_list: list[dict], title: str = "Tasks") -> str:
    """Format task list for display.

    Args:
        task_list: List of task dictionaries.
        title: Title for the list.

    Returns:
        Formatted markdown string.
    """
    text = f"*{title}*\n\n"

    for task in task_list:
        priority_icon = _task_priority_icon(TaskPriority(task["priority"]))
        status_icon = _task_status_icon(TaskStatus(task["status"]))

        text += f"{priority_icon} `{task['task_id']}` {status_icon}\n"
        text += f"   {task['title']}\n"

        if task.get("epic"):
            text += f"   📁 {task['epic']}\n"
        if task.get("session_id"):
            text += f"   🔗 {task['session_id']}\n"

        text += "\n"

    text += f"_Total: {len(task_list)} task(s)_"
    return text


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tasks command - list project tasks.

    Usage: /tasks [project_id] [status]
    """
    db = get_db(context)
    args = context.args or []

    # Get project ID (required or from active session)
    project_id = None
    status_filter = None

    if args:
        project_id = args[0]
        if len(args) > 1:
            status_filter = args[1]
    else:
        # Try to get from active session
        chat_state = get_chat_state(context)
        chat_id = update.effective_chat.id
        active_session = chat_state.get_active_session(chat_id)

        if active_session:
            session = await db.get_session(active_session)
            if session:
                project_id = session.project_id

    if not project_id:
        await update.message.reply_text(
            "Usage: `/tasks <project_id> [status]`\n\n"
            "Or set an active session first with `/use <session>`",
            parse_mode="Markdown",
        )
        return

    try:
        task_list = await tasks.list_project_tasks(db, project_id, status=status_filter)

        if not task_list:
            await update.message.reply_text(
                f"No tasks found for project `{project_id}`.\n\n"
                f"Use `/sync {project_id}` to sync from backlog.",
                parse_mode="Markdown",
            )
            return

        title = f"Tasks for `{project_id}`"
        if status_filter:
            title += f" ({status_filter})"

        text = format_task_list(task_list, title)
        keyboard = build_task_keyboard(task_list)

        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    except ValueError as e:
        await update.message.reply_text(f"Error: {e}")


async def next_tasks_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /next command - show prioritized next tasks.

    Usage: /next [project_id]
    """
    db = get_db(context)
    args = context.args or []

    # Get project ID
    project_id = None
    if args:
        project_id = args[0]
    else:
        chat_state = get_chat_state(context)
        chat_id = update.effective_chat.id
        active_session = chat_state.get_active_session(chat_id)

        if active_session:
            session = await db.get_session(active_session)
            if session:
                project_id = session.project_id

    if not project_id:
        await update.message.reply_text(
            "Usage: `/next <project_id>`\n\nOr set an active session first.",
            parse_mode="Markdown",
        )
        return

    try:
        task_list = await tasks.get_next_tasks(db, project_id, limit=5)

        if not task_list:
            await update.message.reply_text(
                f"No pending tasks for project `{project_id}`.",
                parse_mode="Markdown",
            )
            return

        text = f"*Next Tasks for `{project_id}`*\n\n"

        for i, task in enumerate(task_list, 1):
            priority_icon = _task_priority_icon(TaskPriority(task["priority"]))
            text += f"{i}. {priority_icon} `{task['task_id']}`\n"
            text += f"   *{task['title']}*\n"
            if task.get("description"):
                desc = task["description"][:100]
                if len(task["description"]) > 100:
                    desc += "..."
                text += f"   _{desc}_\n"
            text += "\n"

        keyboard = build_task_keyboard(task_list)

        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    except ValueError as e:
        await update.message.reply_text(f"Error: {e}")


async def claim_task_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /claim command - claim a task for current session.

    Usage: /claim <task_id> [session_id]
    """
    db = get_db(context)
    chat_state = get_chat_state(context)
    args = context.args or []

    if not args:
        await update.message.reply_text(
            "Usage: `/claim <task_id> [session_id]`",
            parse_mode="Markdown",
        )
        return

    task_id = args[0]
    session_id = args[1] if len(args) > 1 else None

    # Get session ID from active if not provided
    if not session_id:
        chat_id = update.effective_chat.id
        session_id = chat_state.get_active_session(chat_id)

    if not session_id:
        await update.message.reply_text(
            "No session specified and no active session.\n\n"
            "Use `/claim <task_id> <session_id>` or set an active session.",
            parse_mode="Markdown",
        )
        return

    try:
        result = await tasks.claim_task(db, task_id, session_id)

        await update.message.reply_text(
            f"*Task Claimed*\n\n"
            f"📋 `{result['task_id']}`\n"
            f"📝 {result['title']}\n"
            f"🔗 Session: `{result['session_id']}`\n"
            f"📊 Status: {result['status']}",
            parse_mode="Markdown",
        )

    except ValueError as e:
        await update.message.reply_text(f"Error: {e}")


async def sync_backlog_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /sync command - sync tasks from backlog.

    Usage: /sync <project_id>
    """
    db = get_db(context)
    args = context.args or []

    if not args:
        await update.message.reply_text(
            "Usage: `/sync <project_id>`",
            parse_mode="Markdown",
        )
        return

    project_id = args[0]

    await update.message.reply_text(f"Syncing backlog for `{project_id}`...")

    try:
        result = await tasks.sync_backlog(db, project_id)

        text = (
            f"*Backlog Synced*\n\n"
            f"📂 Project: `{result['project_id']}`\n"
            f"📁 Path: `{result['backlog_path']}`\n\n"
            f"📊 Found: {result['found']}\n"
            f"✅ Created: {result['created']}\n"
            f"🔄 Updated: {result['updated']}\n"
            f"➖ Unchanged: {result['unchanged']}"
        )

        await update.message.reply_text(text, parse_mode="Markdown")

    except ValueError as e:
        await update.message.reply_text(f"Error: {e}")


async def task_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle callback queries from task inline keyboards.

    Callback data format: task:<action>:<task_id>
    Actions: view, claim, status, refresh
    """
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("task:"):
        return

    parts = data.split(":")
    if len(parts) < 2:
        return

    action = parts[1]
    db = get_db(context)
    chat_state = get_chat_state(context)
    chat_id = update.effective_chat.id

    if action == "view" and len(parts) >= 3:
        task_id = parts[2]

        task_detail = await tasks.get_task_detail(db, task_id)
        if not task_detail:
            await query.edit_message_text(
                f"Task `{task_id}` not found.",
                parse_mode="Markdown",
            )
            return

        priority_icon = _task_priority_icon(TaskPriority(task_detail["priority"]))
        status_icon = _task_status_icon(TaskStatus(task_detail["status"]))

        text = f"*Task {task_id}*\n\n"
        text += f"📝 *{task_detail['title']}*\n\n"
        text += f"{priority_icon} Priority: {task_detail['priority']}\n"
        text += f"{status_icon} Status: {task_detail['status']}\n"

        if task_detail.get("epic"):
            text += f"📁 Epic: {task_detail['epic']}\n"
        if task_detail.get("assignee"):
            text += f"👤 Assignee: {task_detail['assignee']}\n"
        if task_detail.get("session_id"):
            text += f"🔗 Session: {task_detail['session_id']}\n"
        if task_detail.get("branch"):
            text += f"🌿 Branch: {task_detail['branch']}\n"

        if task_detail.get("description"):
            text += f"\n_{task_detail['description'][:300]}_"

        # Build action buttons
        buttons = []
        if not task_detail.get("session_id"):
            buttons.append(
                [
                    InlineKeyboardButton(
                        "✋ Claim",
                        callback_data=f"task:claim:{task_id}",
                    ),
                ]
            )

        # Status change buttons
        status_row = []
        current_status = task_detail["status"]
        if current_status != "done":
            status_row.append(
                InlineKeyboardButton(
                    "✅ Done",
                    callback_data=f"task:status:{task_id}:done",
                )
            )
        if current_status != "in_progress":
            status_row.append(
                InlineKeyboardButton(
                    "🔧 WIP",
                    callback_data=f"task:status:{task_id}:in_progress",
                )
            )
        if status_row:
            buttons.append(status_row)

        keyboard = InlineKeyboardMarkup(buttons) if buttons else None

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    elif action == "claim" and len(parts) >= 3:
        task_id = parts[2]
        session_id = chat_state.get_active_session(chat_id)

        if not session_id:
            await query.edit_message_text(
                "No active session. Use `/use <session>` first.",
                parse_mode="Markdown",
            )
            return

        try:
            result = await tasks.claim_task(db, task_id, session_id)

            await query.edit_message_text(
                f"*Task Claimed*\n\n"
                f"📋 `{result['task_id']}`\n"
                f"📝 {result['title']}\n"
                f"🔗 Session: `{result['session_id']}`",
                parse_mode="Markdown",
            )

        except ValueError as e:
            await query.edit_message_text(f"Error: {e}")

    elif action == "status" and len(parts) >= 4:
        task_id = parts[2]
        new_status = parts[3]

        try:
            result = await tasks.update_task_status(db, task_id, new_status)

            await query.edit_message_text(
                f"*Status Updated*\n\n"
                f"📋 `{result['task_id']}`\n"
                f"📝 {result['title']}\n"
                f"📊 {result['old_status']} → {result['new_status']}",
                parse_mode="Markdown",
            )

        except ValueError as e:
            await query.edit_message_text(f"Error: {e}")

    elif action == "refresh":
        # Get project from active session
        session_id = chat_state.get_active_session(chat_id)
        if not session_id:
            await query.edit_message_text(
                "No active session. Use `/use <session>` first.",
                parse_mode="Markdown",
            )
            return

        session = await db.get_session(session_id)
        if not session:
            await query.edit_message_text("Session not found.")
            return

        try:
            task_list = await tasks.list_project_tasks(db, session.project_id)

            if not task_list:
                await query.edit_message_text(
                    f"No tasks for project `{session.project_id}`.",
                    parse_mode="Markdown",
                )
                return

            text = format_task_list(task_list, f"Tasks for `{session.project_id}`")
            keyboard = build_task_keyboard(task_list)

            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

        except ValueError as e:
            await query.edit_message_text(f"Error: {e}")


# =============================================================================
# Job Commands
# =============================================================================


def _job_status_icon(status: JobStatus) -> str:
    """Get icon for job status."""
    icons = {
        JobStatus.QUEUED: "📋",
        JobStatus.RUNNING: "🔧",
        JobStatus.WAITING_APPROVAL: "⚠️",
        JobStatus.DONE: "✅",
        JobStatus.FAILED: "❌",
        JobStatus.CANCELED: "⏹️",
    }
    return icons.get(status, "❓")


async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /run command - run an instruction.

    Usage: /run [session_id] <instruction>
    """
    db = get_db(context)
    settings = get_settings(context)
    chat_state = get_chat_state(context)
    chat_id = update.effective_chat.id

    args = context.args or []

    if not args:
        await update.message.reply_text(
            "Usage: `/run [session_id] <instruction>`\n\n"
            "Example:\n"
            "  `/run fix the auth bug`\n"
            "  `/run S1 add unit tests`",
            parse_mode="Markdown",
        )
        return

    # Check if first arg is a session ID
    session_id = None
    instruction_start = 0

    if args[0].upper().startswith("S") and len(args) > 1:
        potential_id = args[0].upper()
        if not potential_id.startswith("S"):
            potential_id = f"S{potential_id}"
        session = await db.get_session(potential_id)
        if session:
            session_id = potential_id
            instruction_start = 1

    # Get session from active if not provided
    if not session_id:
        session_id = chat_state.get_active_session(chat_id)

    if not session_id:
        await update.message.reply_text(
            "No session specified and no active session.\n\n"
            "Use `/new <project>` to create a session, "
            "or `/use <session>` to set an active one.",
            parse_mode="Markdown",
        )
        return

    # Get instruction
    instruction = " ".join(args[instruction_start:])
    if not instruction:
        await update.message.reply_text(
            "Please provide an instruction.\n\nUsage: `/run <instruction>`",
            parse_mode="Markdown",
        )
        return

    # Show typing indicator
    await context.bot.send_chat_action(chat_id, "typing")

    # Send initial status message
    session = await db.get_session(session_id)
    if not session:
        await update.message.reply_text(f"Session `{session_id}` not found.")
        return

    project = await db.get_project(session.project_id)
    project_name = project.name if project else session.project_id

    instr_display = instruction[:100] + "..." if len(instruction) > 100 else instruction
    status_msg = await send_with_context(
        update,
        context,
        f"*Starting Job*\n\n"
        f"📂 {project_name} / `{session_id}`\n"
        f"🌿 Branch: `{session.branch}`\n\n"
        f"📝 _{instr_display}_\n\n"
        f"⏳ Queued...",
        session_id=session_id,
        project_id=session.project_id,
        message_type="job",
        parse_mode="Markdown",
    )

    try:
        # Run the job
        job = await run_instruction(
            db=db,
            settings=settings,
            session_id=session_id,
            instruction=instruction,
        )

        # Update message with job ID
        await status_msg.edit_text(
            f"*Job Started*\n\n"
            f"📂 {project_name} / `{session_id}`\n"
            f"🌿 Branch: `{session.branch}`\n"
            f"🔹 Job: `{job.job_id}`\n\n"
            f"📝 _{instr_display}_\n\n"
            f"🔧 Running...\n\n"
            f"Use `/summary {job.job_id}` to check progress.",
            parse_mode="Markdown",
        )

        # Store job context
        chat_state.store_message_context(
            message_id=status_msg.message_id,
            chat_id=chat_id,
            session_id=session_id,
            project_id=session.project_id,
            job_id=job.job_id,
            message_type="job",
        )

    except ValueError as e:
        await status_msg.edit_text(
            f"*Job Failed to Start*\n\nError: {e}",
            parse_mode="Markdown",
        )


async def jobs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /jobs command - list recent jobs.

    Usage: /jobs [session_id]
    """
    db = get_db(context)
    chat_state = get_chat_state(context)
    chat_id = update.effective_chat.id
    args = context.args or []

    # Get session ID
    session_id = None
    if args:
        session_id = args[0].upper()
        if not session_id.startswith("S"):
            session_id = f"S{session_id}"
    else:
        session_id = chat_state.get_active_session(chat_id)

    if not session_id:
        await update.message.reply_text(
            "No session specified and no active session.\n\n"
            "Usage: `/jobs [session_id]`",
            parse_mode="Markdown",
        )
        return

    try:
        jobs_list = await list_session_jobs(db, session_id, limit=10)

        if not jobs_list:
            await update.message.reply_text(
                f"No jobs found for session `{session_id}`.",
                parse_mode="Markdown",
            )
            return

        text = f"*Jobs for `{session_id}`*\n\n"

        for job in jobs_list:
            icon = _job_status_icon(JobStatus(job["status"]))
            text += f"{icon} `{job['job_id']}` - {job['status']}\n"
            text += f"   _{job['instruction']}_\n"
            if job.get("error"):
                text += f"   ❌ {job['error'][:50]}\n"
            text += "\n"

        text += f"_Total: {len(jobs_list)} job(s)_"

        await update.message.reply_text(text, parse_mode="Markdown")

    except ValueError as e:
        await update.message.reply_text(f"Error: {e}")


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /summary command - show job summary.

    Usage: /summary [job_id|session_id]
    """
    db = get_db(context)
    chat_state = get_chat_state(context)
    chat_id = update.effective_chat.id
    args = context.args or []

    job_id = None
    session_id = None

    if args:
        arg = args[0]
        # Check if it's a session ID
        if arg.upper().startswith("S"):
            session_id = arg.upper()
        else:
            job_id = arg
    else:
        # Get from active session's current job
        session_id = chat_state.get_active_session(chat_id)

    # If we have a session, get its current or last job
    if session_id and not job_id:
        session = await db.get_session(session_id)
        if session:
            if session.current_job_id:
                job_id = session.current_job_id
            else:
                # Get most recent job
                jobs_list = await db.get_jobs_by_session(session_id, limit=1)
                if jobs_list:
                    job_id = jobs_list[0].job_id

    if not job_id:
        await update.message.reply_text(
            "No job specified.\n\n"
            "Usage: `/summary <job_id>` or `/summary <session_id>`",
            parse_mode="Markdown",
        )
        return

    summary = await get_job_summary(db, job_id)
    if not summary:
        await update.message.reply_text(f"Job `{job_id}` not found.")
        return

    icon = _job_status_icon(JobStatus(summary["status"]))

    text = "*Job Summary*\n\n"
    text += f"{icon} `{summary['job_id']}` - {summary['status']}\n"
    text += f"📂 {summary['project_id']} / `{summary['session_id']}`\n\n"
    text += f"*Instruction:*\n_{summary['instruction'][:200]}_\n\n"

    if summary.get("result_summary"):
        text += f"*Result:*\n{summary['result_summary'][:300]}\n\n"

    if summary.get("files_changed"):
        text += f"*Files Changed:* {len(summary['files_changed'])}\n"
        for f in summary["files_changed"][:5]:
            text += f"  • `{f}`\n"
        if len(summary["files_changed"]) > 5:
            text += f"  _...and {len(summary['files_changed']) - 5} more_\n"
        text += "\n"

    if summary.get("error"):
        text += f"*Error:*\n`{summary['error'][:200]}`\n\n"

    # Timing info
    if summary.get("started_at"):
        text += f"⏱️ Started: {summary['started_at'][:19]}\n"
    if summary.get("finished_at"):
        text += f"⏱️ Finished: {summary['finished_at'][:19]}\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def tail_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tail command - show job logs.

    Usage: /tail [job_id] [lines]
    """
    db = get_db(context)
    chat_state = get_chat_state(context)
    chat_id = update.effective_chat.id
    args = context.args or []

    job_id = None
    tail_lines = 30

    for arg in args:
        if arg.isdigit():
            tail_lines = min(int(arg), 100)
        else:
            job_id = arg

    # Get job ID from active session if not provided
    if not job_id:
        session_id = chat_state.get_active_session(chat_id)
        if session_id:
            session = await db.get_session(session_id)
            if session and session.current_job_id:
                job_id = session.current_job_id

    if not job_id:
        await update.message.reply_text(
            "No job specified.\n\nUsage: `/tail [job_id] [lines]`",
            parse_mode="Markdown",
        )
        return

    try:
        result = await get_job_logs(db, job_id, tail=tail_lines)

        if not result["logs"]:
            await update.message.reply_text(
                f"No logs available for job `{job_id}`.",
                parse_mode="Markdown",
            )
            return

        icon = _job_status_icon(JobStatus(result["status"]))

        text = f"*Logs for `{job_id}`* {icon}\n\n"
        text += f"```\n{result['logs'][:3500]}\n```"

        if len(result["logs"]) > 3500:
            text += "\n\n_...truncated_"

        await update.message.reply_text(text, parse_mode="Markdown")

    except ValueError as e:
        await update.message.reply_text(f"Error: {e}")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancel command - cancel a running job.

    Usage: /cancel [job_id]
    """
    db = get_db(context)
    chat_state = get_chat_state(context)
    chat_id = update.effective_chat.id
    args = context.args or []

    job_id = args[0] if args else None

    # Get from active session if not provided
    if not job_id:
        session_id = chat_state.get_active_session(chat_id)
        if session_id:
            session = await db.get_session(session_id)
            if session and session.current_job_id:
                job_id = session.current_job_id

    if not job_id:
        await update.message.reply_text(
            "No job specified.\n\nUsage: `/cancel [job_id]`",
            parse_mode="Markdown",
        )
        return

    job = await db.get_job(job_id)
    if not job:
        await update.message.reply_text(f"Job `{job_id}` not found.")
        return

    if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
        await update.message.reply_text(
            f"Job `{job_id}` is not running (status: {job.status.value}).",
            parse_mode="Markdown",
        )
        return

    # Update status
    job.status = JobStatus.CANCELED
    job.error = "Cancelled by user"
    await db.update_job(job)

    # Update session
    session = await db.get_session(job.session_id)
    if session:
        session.state = SessionState.IDLE
        session.current_job_id = None
        await db.update_session(session)

    await update.message.reply_text(
        f"*Job Cancelled*\n\n⏹️ `{job_id}` has been cancelled.",
        parse_mode="Markdown",
    )


# =============================================================================
# Approval Commands
# =============================================================================


def _approval_type_icon(approval_type: str) -> str:
    """Get icon for approval type."""
    icons = {
        "shell_command": "🖥️",
        "file_write": "📝",
        "git_push": "⬆️",
        "deploy": "🚀",
        "dangerous_edit": "⚠️",
        "external_request": "🌐",
    }
    return icons.get(approval_type, "❓")


def build_approval_keyboard(approval_id: str) -> InlineKeyboardMarkup:
    """Build inline keyboard for approval actions.

    Args:
        approval_id: Approval ID.

    Returns:
        InlineKeyboardMarkup with approve/deny buttons.
    """
    buttons = [
        [
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"approval:approve:{approval_id}",
            ),
            InlineKeyboardButton(
                "❌ Deny",
                callback_data=f"approval:deny:{approval_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "📋 Details",
                callback_data=f"approval:details:{approval_id}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


async def approvals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /approvals command - list pending approvals.

    Usage: /approvals [session_id]
    """
    db = get_db(context)
    chat_state = get_chat_state(context)
    chat_id = update.effective_chat.id
    args = context.args or []

    # Get session ID
    session_id = None
    if args:
        session_id = args[0].upper()
        if not session_id.startswith("S"):
            session_id = f"S{session_id}"
    else:
        session_id = chat_state.get_active_session(chat_id)

    try:
        pending = await approvals.list_pending_approvals(db, session_id)

        if not pending:
            scope = f"session `{session_id}`" if session_id else "any session"
            await update.message.reply_text(
                f"No pending approvals for {scope}.",
                parse_mode="Markdown",
            )
            return

        text = "*Pending Approvals*\n\n"

        for a in pending:
            icon = _approval_type_icon(a["approval_type"])
            atype = a["approval_type"].replace("_", " ").title()
            text += f"{icon} `{a['approval_id']}` - {atype}\n"
            text += f"   📂 `{a['session_id']}` / `{a['job_id']}`\n"
            desc = a["action_description"][:60]
            if len(a["action_description"]) > 60:
                desc += "..."
            text += f"   _{desc}_\n\n"

        text += f"_Total: {len(pending)} pending approval(s)_"

        # If there's only one, show the action buttons
        if len(pending) == 1:
            keyboard = build_approval_keyboard(pending[0]["approval_id"])
            await update.message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        else:
            await update.message.reply_text(text, parse_mode="Markdown")

    except ValueError as e:
        await update.message.reply_text(f"Error: {e}")


async def send_approval_request(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    approval_data: dict,
) -> Message:
    """Send an approval request message with buttons.

    Args:
        context: Bot context.
        chat_id: Chat to send to.
        approval_data: Approval dictionary.

    Returns:
        Sent message.
    """
    text = approvals.format_approval_message(approval_data)
    keyboard = build_approval_keyboard(approval_data["approval_id"])

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

    # Store the message context
    chat_state: ChatStateManager = context.bot_data["chat_state"]
    chat_state.store_message_context(
        message_id=msg.message_id,
        chat_id=chat_id,
        session_id=approval_data.get("session_id"),
        project_id=approval_data.get("project_id"),
        job_id=approval_data.get("job_id"),
        message_type="approval",
    )

    return msg


async def approval_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle callback queries from approval inline keyboards.

    Callback data format: approval:<action>:<approval_id>
    Actions: approve, deny, details
    """
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("approval:"):
        return

    parts = data.split(":")
    if len(parts) < 3:
        return

    action = parts[1]
    approval_id = parts[2]
    db = get_db(context)

    # Get user info for approval tracking
    user = query.from_user
    user_name = user.username or user.first_name or str(user.id)

    if action == "approve":
        try:
            result = await approvals.approve_action(db, approval_id, user_name)

            await query.edit_message_text(
                f"*✅ Approved*\n\n"
                f"Action approved by @{user_name}\n"
                f"Job `{result['job_id']}` can now continue.",
                parse_mode="Markdown",
            )

        except ValueError as e:
            await query.edit_message_text(f"Error: {e}")

    elif action == "deny":
        try:
            result = await approvals.deny_action(db, approval_id, user_name)

            await query.edit_message_text(
                f"*❌ Denied*\n\n"
                f"Action denied by @{user_name}\n"
                f"Job `{result['job_id']}` has been cancelled.",
                parse_mode="Markdown",
            )

        except ValueError as e:
            await query.edit_message_text(f"Error: {e}")

    elif action == "details":
        try:
            detail = await approvals.get_approval_detail(db, approval_id)

            if not detail:
                await query.edit_message_text(
                    f"Approval `{approval_id}` not found.",
                    parse_mode="Markdown",
                )
                return

            icon = _approval_type_icon(detail["approval_type"])
            atype = detail["approval_type"].replace("_", " ").title()

            text = "*Approval Details*\n\n"
            text += f"🔹 ID: `{detail['approval_id']}`\n"
            text += f"{icon} Type: {atype}\n"
            text += f"📂 Session: `{detail['session_id']}`\n"
            text += f"🔹 Job: `{detail['job_id']}`\n"
            text += f"📊 State: {detail['state']}\n\n"

            text += f"*Action*:\n_{detail['action_description']}_\n\n"

            details = detail.get("action_details")
            if details:
                text += "*Details*:\n"
                if isinstance(details, dict):
                    for k, v in details.items():
                        text += f"  • {k}: `{str(v)[:50]}`\n"
                text += "\n"

            job = detail.get("job")
            if job and job.get("instruction"):
                text += f"*Job Instruction*:\n_{job['instruction'][:150]}_\n"

            # Show action buttons if still pending
            if detail["state"] == "pending":
                keyboard = build_approval_keyboard(approval_id)
                await query.edit_message_text(
                    text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
            else:
                await query.edit_message_text(text, parse_mode="Markdown")

        except ValueError as e:
            await query.edit_message_text(f"Error: {e}")


# =============================================================================
# Natural Language Handler
# =============================================================================


async def _get_agno_model(
    settings: Settings,
    chat_state: ChatStateManager,
    chat_id: int,
) -> str:
    """Get the agno model string for a chat.

    Uses user's selected model if set, otherwise falls back to defaults.
    Loads user preferences from database on first access.

    Args:
        settings: Application settings.
        chat_state: Chat state manager.
        chat_id: Chat ID to get model for.

    Returns:
        Model string in 'provider:model_id' format.
    """
    # Ensure preferences are loaded from DB
    await chat_state.ensure_loaded(chat_id)

    # Check if user has selected a model
    model_id, provider = chat_state.get_ai_model(chat_id)

    if model_id and provider:
        # Convert to agno format
        if provider == "gemini":
            return f"google:{model_id}"
        elif provider == "openrouter":
            return f"openrouter:{model_id}"
        elif provider == "groq":
            return f"groq:{model_id}"
        elif provider == "cerebras":
            return f"cerebras:{model_id}"

    # Fall back to defaults based on available keys
    # Prefer Cerebras (fastest), then Groq, then OpenRouter, then Gemini
    if settings.has_cerebras:
        return "cerebras:llama-3.3-70b"
    if settings.has_groq:
        return "groq:llama-3.3-70b-versatile"
    if settings.has_openrouter:
        return "openrouter:meta-llama/llama-3.3-70b-instruct:free"
    if settings.has_gemini:
        return "google:gemini-2.0-flash"
    # No AI available - will use pattern matching only
    return "openrouter:meta-llama/llama-3.2-3b-instruct:free"


async def natural_language_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle natural language messages (non-command, non-reply).

    Uses the conversational agent (preferred) or command suggester (fallback).
    The agent can execute read operations directly and asks for confirmation
    on write operations.
    """
    text = update.message.text.strip()
    if not text:
        return

    chat_id = update.effective_chat.id

    # Show typing indicator while processing
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Use conversational agent if available (preferred)
    if AGENT_AVAILABLE and get_agent is not None:
        await _process_with_agent(text, update, context)
    else:
        # Fallback to command suggester
        await _process_with_suggestions(text, update, context)


async def _process_with_agent(
    text: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Process text input using the conversational agent.

    The agent can:
    - Execute read operations directly and report results
    - Ask for confirmation on write operations
    - Have natural conversations

    Args:
        text: User's text input.
        update: Telegram update.
        context: Bot context.
    """
    chat_id = update.effective_chat.id
    chat_state = get_chat_state(context)
    settings: Settings = context.bot_data["settings"]
    db: Database = context.bot_data["db"]

    # Get AI model
    model = await _get_agno_model(settings, chat_state, chat_id)

    # Get or create agent
    agent_db_path = settings.televibe_dir / "agent.db"
    agent = get_agent(db=db, model=model, db_path=agent_db_path)

    # Set context for this chat (active session, settings)
    active_session = chat_state.get_active_session(chat_id)
    agent.set_chat_context(
        chat_id,
        active_session=active_session,
        settings=settings,
    )

    # Chat with agent
    response = await agent.chat(text, chat_id)

    # Handle errors
    if response.error:
        if response.error in ("rate_limit", "provider_error"):
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Switch Model", callback_data="m:browse")]]
            )
            await update.effective_message.reply_text(
                f"⚠️ {response.message}",
                reply_markup=keyboard,
            )
        else:
            await update.effective_message.reply_text(response.message)
        return

    # Check if there's a pending action needing confirmation
    if response.pending_action:
        action = response.pending_action
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes", callback_data="agent:confirm"),
                InlineKeyboardButton("❌ No", callback_data="agent:deny"),
            ]
        ])

        # Show agent's message with confirmation buttons
        msg = response.message
        if msg:
            msg += f"\n\n{action.confirm_message}"
        else:
            msg = action.confirm_message

        await update.effective_message.reply_text(
            msg,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return

    # No pending action - just show the response
    if response.message:
        await update.effective_message.reply_text(
            response.message,
            parse_mode="Markdown",
        )


async def agent_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle agent confirmation callbacks (Yes/No buttons).

    Callback data format: agent:confirm or agent:deny
    """
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("agent:"):
        return

    chat_id = update.effective_chat.id
    action_type = data.split(":")[1]  # "confirm" or "deny"

    # Get agent
    settings: Settings = context.bot_data["settings"]
    db: Database = context.bot_data["db"]
    chat_state = get_chat_state(context)
    model = await _get_agno_model(settings, chat_state, chat_id)

    agent_db_path = settings.televibe_dir / "agent.db"
    agent = get_agent(db=db, model=model, db_path=agent_db_path)

    # Make sure agent has settings context for execution
    agent.set_chat_context(
        chat_id,
        active_session=chat_state.get_active_session(chat_id),
        settings=settings,
    )

    if action_type == "confirm":
        # Execute the pending action
        response = await agent.confirm_action(chat_id)

        # Update the message
        with contextlib.suppress(BadRequest):
            await query.edit_message_text(
                response.message,
                parse_mode="Markdown",
            )

        # If this created a session, update chat state
        if "Session" in response.message and "created" in response.message:
            # Extract session ID from response (e.g., "Session S3 created")
            import re
            match = re.search(r"Session \*\*(\w+)\*\*", response.message)
            if match:
                new_session_id = match.group(1)
                chat_state.set_active_session(chat_id, new_session_id)

    elif action_type == "deny":
        # Cancel the pending action
        response = await agent.deny_action(chat_id)

        with contextlib.suppress(BadRequest):
            await query.edit_message_text(f"❌ {response.message}")


async def _run_as_instruction(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session_id: str,
    instruction: str,
) -> None:
    """Run text as an instruction in a session.

    Args:
        update: Telegram update.
        context: Bot context.
        session_id: Session to run in.
        instruction: Instruction text.
    """
    import asyncio

    db = get_db(context)
    settings = get_settings(context)
    chat_state = get_chat_state(context)
    chat_id = update.effective_chat.id

    # Helper for sending messages (works in both message and callback contexts)
    async def send(text: str, parse_mode: str | None = "Markdown") -> Message:
        return await context.bot.send_message(chat_id, text, parse_mode=parse_mode)

    # Verify session exists and is idle
    session = await db.get_session(session_id)
    if not session:
        await send(f"Session `{session_id}` not found.")
        return

    if session.state == SessionState.RUNNING:
        await send(
            f"Session `{session_id}` is already running "
            f"job `{session.current_job_id}`.\n"
            "Wait for it to complete or use /cancel."
        )
        return

    # Show typing while starting
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        job = await run_instruction(db, settings, session_id, instruction)

        # Send confirmation
        truncated = instruction[:60] + "..." if len(instruction) > 60 else instruction
        msg = await send(
            f"🔧 *Job Started*\n\n"
            f"🔹 Job: `{job.job_id}`\n"
            f"📂 Session: `{session_id}`\n"
            f"📝 _{truncated}_\n\n"
            f"Use /status to monitor progress or /tail to see logs."
        )

        # Store message context for reply routing
        chat_state.store_message_context(
            message_id=msg.message_id,
            chat_id=chat_id,
            session_id=session_id,
            project_id=session.project_id,
            job_id=job.job_id,
            message_type="job",
        )

        # Start background task to monitor job completion
        asyncio.create_task(
            _monitor_job_completion(
                context.bot, db, chat_id, job.job_id, session_id, msg.message_id
            )
        )

    except ValueError as e:
        await send(f"Error: {e}", parse_mode=None)


async def _monitor_job_completion(
    bot,
    db: Database,
    chat_id: int,
    job_id: str,
    session_id: str,
    status_message_id: int,
) -> None:
    """Monitor a job and send completion notification.

    Args:
        bot: Telegram bot instance.
        db: Database instance.
        chat_id: Chat to send notification to.
        job_id: Job to monitor.
        session_id: Session ID.
        status_message_id: Initial status message ID to edit.
    """
    import asyncio

    # Poll for completion (max 1 hour)
    max_polls = 720  # 5 seconds * 720 = 1 hour
    poll_interval = 5

    for _ in range(max_polls):
        await asyncio.sleep(poll_interval)

        job = await db.get_job(job_id)
        if not job:
            return

        # Check if job is done
        if job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELED):
            # Send completion notification
            if job.status == JobStatus.DONE:
                files_text = ""
                if job.files_changed:
                    count = len(job.files_changed)
                    files_text = f"\n📝 {count} file{'s' if count != 1 else ''} changed"

                summary_text = ""
                if job.result_summary:
                    summary = job.result_summary[:200]
                    if len(job.result_summary) > 200:
                        summary += "..."
                    summary_text = f"\n\n💬 _{summary}_"

                await bot.send_message(
                    chat_id,
                    f"✅ *Job Completed*\n\n"
                    f"🔹 Job: `{job_id}`\n"
                    f"📂 Session: `{session_id}`{files_text}{summary_text}\n\n"
                    f"Use /summary or /tail to see details.",
                    parse_mode="Markdown",
                )

            elif job.status == JobStatus.FAILED:
                error_text = ""
                if job.error:
                    error = job.error[:200]
                    if len(job.error) > 200:
                        error += "..."
                    error_text = f"\n\n❗ _{error}_"

                await bot.send_message(
                    chat_id,
                    f"❌ *Job Failed*\n\n"
                    f"🔹 Job: `{job_id}`\n"
                    f"📂 Session: `{session_id}`{error_text}\n\n"
                    f"Use /tail to see logs.",
                    parse_mode="Markdown",
                )

            elif job.status == JobStatus.CANCELED:
                await bot.send_message(
                    chat_id,
                    f"⏹️ *Job Canceled*\n\n"
                    f"🔹 Job: `{job_id}`\n"
                    f"📂 Session: `{session_id}`",
                    parse_mode="Markdown",
                )

            return

    # Timeout - job still running after 1 hour
    await bot.send_message(
        chat_id,
        f"⚠️ *Job Timeout*\n\n"
        f"🔹 Job: `{job_id}` is still running after 1 hour.\n"
        f"Use /status to check or /cancel to stop.",
        parse_mode="Markdown",
    )


# =============================================================================
# Model Management Commands
# =============================================================================


def _get_provider_icon_by_enum(provider) -> str:
    """Get icon for AI provider (by Provider enum).

    Icons:
        💎 = Gemini (Google)
        🌐 = OpenRouter
        ⚡ = Groq
        🧠 = Cerebras
    """
    from televibecode.ai.models import Provider

    if provider == Provider.GEMINI:
        return "💎"
    if provider == Provider.OPENROUTER:
        return "🌐"
    if provider == Provider.GROQ:
        return "⚡"
    if provider == Provider.CEREBRAS:
        return "🧠"
    return "🤖"


def _get_provider_icon(model_id: str) -> str:
    """Get icon for model provider (by model ID string - legacy)."""
    model_lower = model_id.lower()
    if "grok" in model_lower or "x-ai" in model_lower:
        return "⚡"  # Grok
    if "gemini" in model_lower or "google" in model_lower:
        return "💎"  # Gemini
    if "gpt" in model_lower or "openai" in model_lower:
        return "🧠"  # OpenAI
    if "claude" in model_lower or "anthropic" in model_lower:
        return "🎭"  # Claude
    if "llama" in model_lower or "meta" in model_lower:
        return "🦙"  # Llama
    if "deepseek" in model_lower:
        return "🔍"  # DeepSeek
    if "mistral" in model_lower:
        return "🌀"  # Mistral
    if "qwen" in model_lower:
        return "🐼"  # Qwen
    if "gemma" in model_lower:
        return "💠"  # Gemma
    return "🤖"


def _get_quality_bar(score: float, max_score: float = 100.0) -> str:
    """Get visual quality bar."""
    if max_score == 0:
        return ""
    ratio = min(score / max_score, 1.0)
    filled = int(ratio * 5)
    return "█" * filled + "░" * (5 - filled)


def _get_tier_medal(rank: int) -> str:
    """Get medal for top ranks."""
    if rank == 1:
        return "🥇"
    if rank == 2:
        return "🥈"
    if rank == 3:
        return "🥉"
    return f"{rank}."


# Models per page for pagination
MODELS_PER_PAGE = 10


def _build_models_page(
    models: list,
    page: int,
    filter_type: str,
    current_model_id: str | None,
    max_score: float,
    test_results: dict[str, bool] | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Build paginated models display.

    Args:
        models: List of ModelInfo objects.
        page: Current page (0-indexed).
        filter_type: Filter type (all, free, gem, or, tools).
        current_model_id: Currently selected model ID.
        max_score: Maximum rank score for scaling.
        test_results: Dict of model_id -> supports_tools from empirical tests.

    Returns:
        Tuple of (message_text, keyboard).
    """
    total_pages = (len(models) + MODELS_PER_PAGE - 1) // MODELS_PER_PAGE
    if total_pages == 0:
        total_pages = 1

    # Clamp page
    page = max(0, min(page, total_pages - 1))

    # Get models for this page
    start_idx = page * MODELS_PER_PAGE
    end_idx = start_idx + MODELS_PER_PAGE
    page_models = models[start_idx:end_idx]

    # Build header
    filter_names = {
        "all": "All",
        "free": "Free",
        "gem": "Gemini",
        "or": "OpenRouter",
        "groq": "Groq",
        "cere": "Cerebras",
        "tools": "Tools ✓",
    }
    filter_name = filter_names.get(filter_type, "All")

    text = f"🤖 *AI Models* — {filter_name}\n"
    text += f"Page {page + 1}/{total_pages} ({len(models)} models)\n\n"
    text += "• 💎 Gemini  • 🌐 OpenRouter\n"
    text += "• ⚡ Groq  • 🧠 Cerebras\n"
    text += "• 🔧 Tools  • 🆓 Free\n"

    # Show test status
    if test_results:
        tested_count = len(test_results)
        text += f"\n🧪 {tested_count} models tested\n"

    # Show current model
    if current_model_id:
        if len(current_model_id) > 30:
            short_id = current_model_id[:30] + "..."
        else:
            short_id = current_model_id
        text += f"\n📍 Current: `{short_id}`"

    # Build button list (1 per row, left-aligned with padding)
    keyboard_rows = []
    button_width = 32  # Fixed width for consistent alignment

    for i, m in enumerate(page_models):
        global_idx = start_idx + i
        # Use provider enum for icon (💎=Gemini, 🌐=OpenRouter, ⚡=Groq, 🧠=Cerebras)
        provider_icon = _get_provider_icon_by_enum(m.provider)
        selected = " ✓" if m.id == current_model_id else ""

        # Tool support indicator
        if test_results and m.id in test_results:
            # Empirically tested
            tool_icon = "🔧" if test_results[m.id] else "❌"
        elif m.supports_tools:
            # Heuristic says yes but not tested
            tool_icon = "🔧"
        else:
            # Heuristic says no
            tool_icon = ""

        # Create button with provider icon + model name
        # For OpenRouter: keep subprovider (e.g., "meta-llama/llama-3.3")
        # For others: just use the model ID
        clean_id = m.id.replace(":free", "")
        if m.provider.value == "openrouter":
            # Keep org/model format, just shorten the model name part if too long
            parts = clean_id.split("/")
            if len(parts) == 2:
                org, model = parts
                # Shorten org if needed
                if len(org) > 10:
                    org = org[:8] + ".."
                # Shorten model if needed
                if len(model) > 18:
                    model = model[:16] + ".."
                short_name = f"{org}/{model}"
            else:
                short_name = clean_id[:26] if len(clean_id) > 26 else clean_id
        else:
            # For Gemini/Groq/Cerebras: just use model ID
            short_name = clean_id[:26] if len(clean_id) > 26 else clean_id

        label = f"{provider_icon}{tool_icon} {short_name}{selected}"

        # Pad with spaces to push text left (workaround for centered buttons)
        padding = button_width - len(label)
        if padding > 0:
            label = label + " " * padding

        # Callback: m:s:INDEX (select by index)
        callback = f"m:s:{global_idx}"
        keyboard_rows.append([InlineKeyboardButton(label, callback_data=callback)])

    # Navigation row
    nav_row = []
    if page > 0:
        prev_data = f"m:p:{page - 1}:{filter_type}"
        nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=prev_data))
    if page < total_pages - 1:
        next_data = f"m:p:{page + 1}:{filter_type}"
        nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=next_data))

    if nav_row:
        keyboard_rows.append(nav_row)

    # Filter row (with tools filter)
    filter_row = []
    filters = [("all", "All"), ("free", "🆓"), ("tools", "🔧"), ("gem", "💎"), ("or", "🌐"), ("groq", "⚡"), ("cere", "🧠")]
    for f_key, f_label in filters:
        label = f"[{f_label}]" if f_key == filter_type else f_label
        filter_row.append(InlineKeyboardButton(label, callback_data=f"m:f:{f_key}"))
    keyboard_rows.append(filter_row)

    # Refresh and Test buttons
    action_row = [
        InlineKeyboardButton("🔄 Refresh", callback_data="m:r"),
        InlineKeyboardButton("🧪 Test", callback_data="m:t"),
    ]
    keyboard_rows.append(action_row)

    return text, InlineKeyboardMarkup(keyboard_rows)


def _get_provider_sort_key(model_id: str) -> tuple[int, str]:
    """Get sort key for grouping by provider.

    Returns (priority, provider_name) for sorting.
    """
    model_lower = model_id.lower()
    # Priority order for providers
    if "grok" in model_lower or "x-ai" in model_lower:
        return (0, "grok")
    if "gemini" in model_lower or model_lower.startswith("gemini"):
        return (1, "gemini")
    if "gpt" in model_lower or "openai" in model_lower:
        return (2, "openai")
    if "claude" in model_lower or "anthropic" in model_lower:
        return (3, "anthropic")
    if "llama" in model_lower or "meta" in model_lower:
        return (4, "llama")
    if "deepseek" in model_lower:
        return (5, "deepseek")
    if "mistral" in model_lower:
        return (6, "mistral")
    if "qwen" in model_lower:
        return (7, "qwen")
    if "gemma" in model_lower:
        return (8, "gemma")
    return (99, "other")


async def _get_filtered_models(
    settings: Settings,
    filter_type: str,
    apply_tool_results: bool = True,
) -> tuple[list, dict[str, bool]]:
    """Get models with filter applied, grouped by provider.

    Args:
        settings: Application settings.
        filter_type: Filter type (all, free, gem, or, tools).
        apply_tool_results: Whether to apply empirical tool test results.

    Returns:
        Tuple of (filtered list of ModelInfo, test results dict).
    """
    # Don't require tools by default - we'll filter manually if needed
    models = await ModelRegistry.get_all_available_models(
        openrouter_key=settings.openrouter_api_key,
        gemini_key=settings.gemini_api_key,
        groq_key=settings.groq_api_key,
        cerebras_key=settings.cerebras_api_key,
        free_only=(filter_type in ("all", "free", "tools")),
        require_tools=False,  # We'll filter based on test results
    )

    # Load and apply empirical test results
    test_results = get_tested_models()
    if apply_tool_results and test_results:
        models = ModelRegistry.apply_test_results(models, test_results)

    # Apply filters
    if filter_type == "gem":
        models = [m for m in models if m.provider.value == "gemini"]
    elif filter_type == "or":
        models = [m for m in models if m.provider.value == "openrouter"]
    elif filter_type == "groq":
        models = [m for m in models if m.provider.value == "groq"]
    elif filter_type == "cere":
        models = [m for m in models if m.provider.value == "cerebras"]
    elif filter_type == "free":
        models = [m for m in models if m.is_free]
    elif filter_type == "tools":
        # Only show models that support tools (based on test results or heuristics)
        models = [m for m in models if m.supports_tools]

    # Sort by provider group, then by rank within group
    models.sort(
        key=lambda m: (
            _get_provider_sort_key(m.id)[0],
            -m.rank_score,  # Higher score first within provider
        )
    )

    return models, test_results


async def models_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /models command - list available AI models with pagination."""
    settings = get_settings(context)
    chat_state = get_chat_state(context)
    chat_id = update.effective_chat.id

    if not settings.has_ai:
        await update.message.reply_text(
            "❌ *No AI providers configured*\n\n"
            "Add to your `.env` file:\n"
            "• `OPENROUTER_API_KEY` - many free models\n"
            "• `GEMINI_API_KEY` - Google's models",
            parse_mode="Markdown",
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Check if tool tests need to run today
    results = load_results()
    if needs_testing(results):
        # Notify user that tests will run
        await update.message.reply_text(
            "🧪 Running daily tool support tests...\n"
            "This may take a few minutes on first run.",
        )
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        # Run tests in background
        await run_full_test(
            openrouter_key=settings.openrouter_api_key,
            gemini_key=settings.gemini_api_key,
            groq_key=settings.groq_api_key,
            cerebras_key=settings.cerebras_api_key,
        )

    # Get available models (default filter: all free)
    filter_type = "all"
    models, test_results = await _get_filtered_models(settings, filter_type)

    if not models:
        await update.message.reply_text("No models available.")
        return

    # Store models in user_data for callback selection
    context.user_data["models_cache"] = models
    context.user_data["models_filter"] = filter_type
    context.user_data["models_test_results"] = test_results

    # Get current model
    current_model_id, _ = chat_state.get_ai_model(chat_id)

    # Find max score for scaling
    max_score = max(m.rank_score for m in models) if models else 1.0

    # Build paginated display (start at page 0)
    text, keyboard = _build_models_page(
        models,
        page=0,
        filter_type=filter_type,
        current_model_id=current_model_id,
        max_score=max_score,
        test_results=test_results,
    )

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /model command - set AI model."""
    chat_state = get_chat_state(context)
    settings = get_settings(context)
    chat_id = update.effective_chat.id

    if not settings.has_ai:
        await update.message.reply_text(
            "No AI providers configured.\n\n"
            "Add GEMINI_API_KEY or OPENROUTER_API_KEY to your .env file."
        )
        return

    # Parse args
    args = context.args
    if not args:
        # Show current model
        model_id, provider = chat_state.get_ai_model(chat_id)
        if model_id:
            await update.message.reply_text(
                f"Current model: `{model_id}` ({provider})\n\n"
                f"Use /models to see available options.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "No model selected (using auto).\n\n"
                "Use /models to see available options."
            )
        return

    model_id = args[0]

    # Try to find the model
    model = await ModelRegistry.find_model(model_id, settings.openrouter_api_key)

    if not model:
        await update.message.reply_text(
            f"Model `{model_id}` not found.\n\nUse /models to see available options.",
            parse_mode="Markdown",
        )
        return

    # Set the model (with persistence)
    await chat_state.set_ai_model_persistent(chat_id, model.id, model.provider.value)

    await update.message.reply_text(
        f"Model set to `{model.id}`\n"
        f"Provider: {model.provider.value}\n"
        f"Context: {model.context_length:,} tokens",
        parse_mode="Markdown",
    )


async def model_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle model selection callbacks with pagination.

    Callback formats:
    - m:p:PAGE:FILTER - Navigate to page
    - m:f:FILTER - Change filter (all, free, gem, or, tools)
    - m:s:INDEX - Select model by index
    - m:r - Refresh model list
    - m:t - Run tool tests
    """
    query = update.callback_query
    await query.answer()

    chat_state = get_chat_state(context)
    settings = get_settings(context)
    chat_id = query.message.chat.id

    data = query.data
    parts = data.split(":")

    if len(parts) < 2:
        return

    action = parts[1]

    # Get cached models or fetch fresh
    models = context.user_data.get("models_cache", [])
    filter_type = context.user_data.get("models_filter", "all")
    test_results = context.user_data.get("models_test_results", {})

    # Handle tool testing
    if action == "t":
        await query.edit_message_text(
            "🧪 *Running tool tests...*\n\n"
            "Testing models in batches of 10.\n"
            "This may take a few minutes.",
            parse_mode="Markdown",
        )

        # Force run tests
        await run_full_test(
            openrouter_key=settings.openrouter_api_key,
            gemini_key=settings.gemini_api_key,
            groq_key=settings.groq_api_key,
            cerebras_key=settings.cerebras_api_key,
            force=True,
        )

        # Refresh models with new test results
        models, test_results = await _get_filtered_models(settings, filter_type)
        context.user_data["models_cache"] = models
        context.user_data["models_test_results"] = test_results

        current_model_id, _ = chat_state.get_ai_model(chat_id)
        max_score = max(m.rank_score for m in models) if models else 1.0

        text, keyboard = _build_models_page(
            models,
            page=0,
            filter_type=filter_type,
            current_model_id=current_model_id,
            max_score=max_score,
            test_results=test_results,
        )
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=keyboard
        )
        return

    # Handle refresh
    if action == "r":
        models, test_results = await _get_filtered_models(settings, filter_type)
        context.user_data["models_cache"] = models
        context.user_data["models_test_results"] = test_results

        if not models:
            await query.edit_message_text("No models available.")
            return

        current_model_id, _ = chat_state.get_ai_model(chat_id)
        max_score = max(m.rank_score for m in models) if models else 1.0

        text, keyboard = _build_models_page(
            models,
            page=0,
            filter_type=filter_type,
            current_model_id=current_model_id,
            max_score=max_score,
            test_results=test_results,
        )
        try:
            await query.edit_message_text(
                text, parse_mode="Markdown", reply_markup=keyboard
            )
        except BadRequest as e:
            # Ignore "Message is not modified" error (nothing changed)
            if "not modified" not in str(e).lower():
                raise
        return

    # Handle page navigation: m:p:PAGE:FILTER
    if action == "p" and len(parts) >= 4:
        page = int(parts[2])
        filter_type = parts[3]

        # Refresh models if cache is empty
        if not models:
            models, test_results = await _get_filtered_models(settings, filter_type)
            context.user_data["models_cache"] = models
            context.user_data["models_filter"] = filter_type
            context.user_data["models_test_results"] = test_results

        if not models:
            await query.edit_message_text("No models available.")
            return

        current_model_id, _ = chat_state.get_ai_model(chat_id)
        max_score = max(m.rank_score for m in models) if models else 1.0

        text, keyboard = _build_models_page(
            models,
            page=page,
            filter_type=filter_type,
            current_model_id=current_model_id,
            max_score=max_score,
            test_results=test_results,
        )
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=keyboard
        )
        return

    # Handle filter change: m:f:FILTER
    if action == "f" and len(parts) >= 3:
        filter_type = parts[2]

        # Fetch models with new filter
        models, test_results = await _get_filtered_models(settings, filter_type)
        context.user_data["models_cache"] = models
        context.user_data["models_filter"] = filter_type
        context.user_data["models_test_results"] = test_results

        if not models:
            await query.edit_message_text(
                f"No models available for filter: {filter_type}\n\n"
                "Try a different filter.",
            )
            return

        current_model_id, _ = chat_state.get_ai_model(chat_id)
        max_score = max(m.rank_score for m in models) if models else 1.0

        text, keyboard = _build_models_page(
            models,
            page=0,
            filter_type=filter_type,
            current_model_id=current_model_id,
            max_score=max_score,
            test_results=test_results,
        )
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=keyboard
        )
        return

    # Handle model selection: m:s:INDEX
    if action == "s" and len(parts) >= 3:
        try:
            idx = int(parts[2])
        except ValueError:
            return

        if not models or idx >= len(models):
            await query.edit_message_text("Model list expired. Use /models to refresh.")
            return

        model = models[idx]

        # Set the model (with persistence)
        await chat_state.set_ai_model_persistent(
            chat_id, model.id, model.provider.value
        )

        # Tool support status
        tool_status = "🔧 Yes" if model.supports_tools else "❌ No"
        if test_results and model.id in test_results:
            tool_status += " (tested)"
        else:
            tool_status += " (heuristic)"

        icon = _get_provider_icon(model.id)
        await query.edit_message_text(
            f"✅ *Model Selected*\n\n"
            f"{icon} `{model.id}`\n\n"
            f"Provider: {model.provider.value}\n"
            f"Context: {model.context_length:,} tokens\n"
            f"Free: {'Yes' if model.is_free else 'No'}\n"
            f"Tools: {tool_status}",
            parse_mode="Markdown",
        )


# =============================================================================
# Voice Message Handler (Audio Transcription)
# =============================================================================


async def voice_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle voice messages by transcribing and showing confirmation.

    Uses Groq Whisper API to transcribe voice messages, then shows
    a confirmation button before processing. This prevents accidental
    execution from misheard transcriptions.
    """
    settings: Settings = context.bot_data["settings"]
    chat_id = update.effective_chat.id

    # Check if Groq is configured
    if not settings.has_groq:
        await update.message.reply_text(
            "🎤 Voice messages require Groq API.\n\n"
            "Add `GROQ_API_KEY` to your `.env` file.\n"
            "Get a free key at: https://console.groq.com/keys",
            parse_mode="Markdown",
        )
        return

    # Show typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        # Get voice message file
        voice = update.message.voice or update.message.audio
        if not voice:
            await update.message.reply_text("No voice message found.")
            return

        # Download the voice file
        file = await context.bot.get_file(voice.file_id)
        voice_bytes = await file.download_as_bytearray()

        # Transcribe using Groq Whisper
        transcribed_text = await transcribe_telegram_voice(
            voice_file=bytes(voice_bytes),
            api_key=settings.groq_api_key,
        )

        if not transcribed_text or not transcribed_text.strip():
            await update.message.reply_text(
                "🎤 Couldn't understand the audio. Please try again."
            )
            return

        # Truncate for callback data (Telegram limit is 64 bytes)
        truncated = transcribed_text[:40] if len(transcribed_text) > 40 else ""
        truncated = truncated or transcribed_text

        # Show transcription with confirmation buttons
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="✅ Confirm",
                        callback_data=f"voice:confirm:{truncated}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Cancel",
                        callback_data="voice:cancel",
                    )
                ],
            ]
        )

        # Store full text in context for retrieval (callback data is limited)
        if "voice_transcriptions" not in context.bot_data:
            context.bot_data["voice_transcriptions"] = {}
        context.bot_data["voice_transcriptions"][chat_id] = transcribed_text

        await update.message.reply_text(
            f"🎤 *Transcribed:*\n_{transcribed_text}_\n\n"
            "Confirm to process this message:",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    except Exception as e:
        await update.message.reply_text(
            f"🎤 Transcription error: {e}\n\nPlease try again or send as text."
        )


# Command execution dispatch table
_COMMAND_DISPATCH = {
    "/help": help_command,
    "/projects": projects_command,
    "/scan": scan_command,
    "/sessions": sessions_command,
    "/status": status_command,
    "/jobs": jobs_command,
    "/tail": tail_command,
    "/tasks": tasks_command,
    "/next": next_tasks_command,
    "/approvals": approvals_command,
    "/models": models_command,
}


async def _execute_command(
    command: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Execute a suggested command.

    Args:
        command: Full command string (e.g., "/sessions" or "/new myproject").
        update: Telegram update.
        context: Bot context.

    Returns:
        True if command was executed, False if not recognized.
    """
    parts = command.split(maxsplit=1)
    base_cmd = parts[0]
    args = parts[1] if len(parts) > 1 else ""

    # Get common context
    db: Database = context.bot_data["db"]
    chat_state = get_chat_state(context)
    chat_id = update.effective_chat.id

    # Helper to send messages (works in both message and callback contexts)
    async def send(text: str, parse_mode: str | None = None) -> None:
        await context.bot.send_message(chat_id, text, parse_mode=parse_mode)

    # Handle simple commands - implement directly instead of delegating
    # (handlers use update.effective_message which is None in callback context)
    if base_cmd == "/sessions" and not args:
        active_sessions = await db.get_active_sessions()
        if not active_sessions:
            await send("No active sessions.\n\nUse /new <project> to create one.")
        else:
            lines = ["**Active Sessions:**\n"]
            for s in active_sessions:
                state_emoji = {"idle": "💤", "running": "🔄", "paused": "⏸️"}.get(
                    s.state.value, "❓"
                )
                lines.append(f"{state_emoji} `{s.session_id}` - {s.project_id}")
            await send("\n".join(lines), parse_mode="Markdown")
        return True

    if base_cmd == "/projects" and not args:
        all_projects = await db.get_all_projects()
        if not all_projects:
            await send("No projects registered.\n\nUse /scan to find repositories.")
        else:
            lines = ["**Registered Projects:**\n"]
            for p in all_projects:
                lines.append(f"📂 `{p.project_id}` - {p.path}")
            await send("\n".join(lines), parse_mode="Markdown")
        return True

    if base_cmd == "/status" and not args:
        session_id = chat_state.get_active_session(chat_id)
        if not session_id:
            await send("No active session. Use /use or /new first.")
        else:
            session = await db.get_session(session_id)
            if session:
                await send(
                    f"**Session {session_id}**\n\n"
                    f"📂 Project: `{session.project_id}`\n"
                    f"🌿 Branch: `{session.branch}`\n"
                    f"📁 {session.workspace_path}",
                    parse_mode="Markdown",
                )
            else:
                await send(f"Session {session_id} not found.")
        return True

    if base_cmd == "/jobs" and not args:
        session_id = chat_state.get_active_session(chat_id)
        if not session_id:
            await send("No active session.")
        else:
            recent_jobs = await db.get_jobs_by_session(session_id, limit=5)
            if not recent_jobs:
                await send(f"No jobs for session {session_id}.")
            else:
                lines = [f"**Recent Jobs ({session_id}):**\n"]
                for j in recent_jobs:
                    status_emoji = {
                        "queued": "⏳",
                        "running": "🔄",
                        "done": "✅",
                        "failed": "❌",
                        "canceled": "⏹️",
                    }.get(j.status.value, "❓")
                    lines.append(f"{status_emoji} `{j.job_id[:8]}` - {j.instruction[:30]}")
                await send("\n".join(lines), parse_mode="Markdown")
        return True

    if base_cmd == "/help" and not args:
        help_text = (
            "**TeleVibeCode Commands**\n\n"
            "📂 **Projects**\n"
            "/projects - List registered projects\n"
            "/scan - Scan for new projects\n\n"
            "🔧 **Sessions**\n"
            "/sessions - List active sessions\n"
            "/new <project> - Create session\n"
            "/use <session> - Switch session\n"
            "/close - Close session\n"
            "/status - Show status\n\n"
            "🚀 **Jobs**\n"
            "/run <instruction> - Run code task\n"
            "/jobs - List recent jobs\n"
            "/tail - View job logs\n"
            "/cancel - Cancel job\n\n"
            "🤖 **AI**\n"
            "/models - Browse AI models\n"
            "/model - Set AI model\n"
            "/reset - Clear AI history"
        )
        await send(help_text, parse_mode="Markdown")
        return True

    if base_cmd == "/use" and args:
        session_id = args.strip().upper()
        result = await sessions.get_session(db, session_id)
        if not result:
            await send(f"Session {session_id} not found.")
            return True
        chat_state.set_active_session(chat_id, session_id)
        await send(
            f"✅ Switched to session {session_id}\n\n"
            f"📂 {result['project_id']} 🌿 {result['branch']}"
        )
        return True

    if base_cmd == "/new" and args:
        project_id = args.strip()
        settings: Settings = context.bot_data["settings"]
        try:
            result = await sessions.create_session(db, settings, project_id)
        except ValueError as e:
            await send(f"Error: {e}")
            return True
        chat_state.set_active_session(chat_id, result["session_id"])
        await send(
            f"✅ Session created: {result['session_id']}\n\n"
            f"📂 {result['project_id']} 🌿 {result['branch']}\n"
            f"📁 {result['workspace_path']}"
        )
        return True

    if base_cmd == "/close":
        if args:
            session_id = args.strip().upper()
        else:
            session_id = chat_state.get_active_session(chat_id)
        if not session_id:
            await send("No active session to close.")
            return True
        try:
            await sessions.close_session(db, session_id)
        except ValueError as e:
            await send(f"Error: {e}")
            return True
        if chat_state.get_active_session(chat_id) == session_id:
            chat_state.set_active_session(chat_id, None)
        await send(f"✅ Session {session_id} closed.")
        return True

    if base_cmd == "/cancel":
        session_id = chat_state.get_active_session(chat_id)
        if not session_id:
            await send("No active session.")
            return True
        # Cancel logic would go here
        await send(f"🛑 Cancelling job for session {session_id}...")
        return True

    if base_cmd == "/run" and args:
        session_id = chat_state.get_active_session(chat_id)
        if not session_id:
            await send("No active session. Use /use or /new first.")
            return True
        await _run_as_instruction(update, context, session_id, args)
        return True

    if base_cmd == "/claim" and args:
        task_id = args.strip().upper()
        session_id = chat_state.get_active_session(chat_id)
        if not session_id:
            await send("No active session. Use /use first to claim a task.")
            return True
        try:
            await tasks.claim_task(db, task_id, session_id)
        except ValueError as e:
            await send(f"Error: {e}")
            return True
        await send(f"✅ Task {task_id} claimed by session {session_id}")
        return True

    if base_cmd == "/sync":
        await sync_backlog_command(update, context)
        return True

    if base_cmd == "/newproject" and args:
        name = args.strip().lower()  # Force lowercase
        settings: Settings = context.bot_data["settings"]

        # Validate name
        error = projects.validate_project_name(name)
        if error:
            await send(f"❌ Invalid name: {error}")
            return True

        try:
            # Create project (local only when from suggestions)
            result = await projects.create_project(
                db=db,
                projects_root=settings.televibe_root,
                name=name,
                remote=None,  # Skip remote for quick creation
            )

            # Create initial session
            session_result = await sessions.create_session(
                db=db,
                settings=settings,
                project_id=name,
            )

            # Set as active session
            chat_state.set_active_session(chat_id, session_result["session_id"])

            await send(
                f"✅ Project created!\n\n"
                f"📂 `{result['path']}`\n"
                f"🔹 Session `{session_result['session_id']}` created\n"
                f"🌿 Branch: `{session_result['branch']}`\n\n"
                f"Ready for instructions!"
            )
        except ValueError as e:
            await send(f"❌ Error: {e}")
        return True

    return False


def _build_suggestion_keyboard(
    suggestions: list, include_cancel: bool = True
) -> InlineKeyboardMarkup:
    """Build inline keyboard for command suggestions.

    Args:
        suggestions: List of CommandSuggestion objects.
        include_cancel: Whether to include a cancel button.

    Returns:
        InlineKeyboardMarkup with command buttons.
    """
    buttons = []
    for i, s in enumerate(suggestions[:4]):  # Max 4 suggestions
        # Truncate long descriptions
        desc = s.description[:30] + "..." if len(s.description) > 30 else s.description
        label = f"{s.command}" if s.confidence >= 0.8 else f"{desc}"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{'✅ ' if s.is_write else ''}{label}",
                    callback_data=f"cmd:{i}:{s.command[:50]}",
                )
            ]
        )

    if include_cancel:
        buttons.append(
            [InlineKeyboardButton(text="❌ Cancel", callback_data="cmd:cancel")]
        )

    return InlineKeyboardMarkup(buttons)


async def command_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle command suggestion button callbacks.

    Callback data format: cmd:<index>:<command> or cmd:cancel
    """
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("cmd:"):
        return

    parts = data.split(":", 2)
    if len(parts) < 2:
        return

    if parts[1] == "cancel":
        with contextlib.suppress(BadRequest):
            await query.edit_message_text("Cancelled.")
        return

    # Extract command from callback data
    if len(parts) < 3:
        return

    command = parts[2]

    # Show processing
    with contextlib.suppress(BadRequest):
        await query.edit_message_text(f"Executing: `{command}`", parse_mode="Markdown")

    # Execute the command
    executed = await _execute_command(command, update, context)

    if not executed:
        chat_id = update.effective_chat.id
        await context.bot.send_message(
            chat_id, f"Could not execute: {command}\nPlease use the command directly."
        )


async def voice_confirm_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle voice transcription confirmation callbacks.

    Callback data format: voice:confirm:<text> or voice:cancel
    """
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("voice:"):
        return

    parts = data.split(":", 2)
    if len(parts) < 2:
        return

    chat_id = update.effective_chat.id

    if parts[1] == "cancel":
        # Clean up stored transcription
        if "voice_transcriptions" in context.bot_data:
            context.bot_data["voice_transcriptions"].pop(chat_id, None)
        with contextlib.suppress(BadRequest):
            await query.edit_message_text("🎤 Cancelled.")
        return

    if parts[1] == "confirm":
        # Get full text from stored context (callback data is truncated)
        transcribed_text = None
        if "voice_transcriptions" in context.bot_data:
            store = context.bot_data["voice_transcriptions"]
            transcribed_text = store.pop(chat_id, None)

        # Fallback to truncated text from callback data
        if not transcribed_text and len(parts) >= 3:
            transcribed_text = parts[2]

        if not transcribed_text:
            with contextlib.suppress(BadRequest):
                await query.edit_message_text("🎤 Session expired. Please try again.")
            return

        # Update message to show processing
        with contextlib.suppress(BadRequest):
            await query.edit_message_text(
                f"🎤 Processing: _{transcribed_text}_",
                parse_mode="Markdown",
            )

        # Now process using command suggester
        await _process_with_suggestions(transcribed_text, update, context)


async def _process_with_suggestions(
    text: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Process text input using command suggester.

    Args:
        text: User's text input.
        update: Telegram update.
        context: Bot context.
    """
    chat_id = update.effective_chat.id
    chat_state = get_chat_state(context)
    settings: Settings = context.bot_data["settings"]
    db: Database = context.bot_data["db"]

    # Get context for suggestions
    active_session = chat_state.get_active_session(chat_id)

    # Get available projects and sessions (these return list[dict] directly)
    projects_list = await projects.list_projects(db)
    project_ids = [p["project_id"] for p in projects_list]

    sessions_list = await sessions.list_sessions(db)
    session_ids = [s["session_id"] for s in sessions_list]

    # Get AI model
    model = await _get_agno_model(settings, chat_state, chat_id)

    # Get suggestions (use persistent memory database)
    suggester_db_path = settings.televibe_dir / "command_suggester.db"
    result = await suggest_commands(
        message=text,
        chat_id=chat_id,
        model=model,
        db_path=suggester_db_path,
        active_session=active_session,
        projects=project_ids,
        sessions=session_ids,
    )

    # Handle greetings
    if result.is_greeting:
        await update.effective_message.reply_text(result.message or "Hello!")
        return

    # Handle conversational (just message, no commands)
    if result.is_conversational and result.message:
        await update.effective_message.reply_text(result.message)
        return

    # Handle missing context
    if result.needs_context:
        msg = f"I need more context: {result.needs_context}\n\n"
        if result.needs_context == "session":
            msg += "Use /sessions to see available sessions, or /new to create one."
        elif result.needs_context == "project":
            msg += "Use /projects to see available projects."
        await update.effective_message.reply_text(msg)
        return

    # Handle suggestions
    if result.suggestions:
        # Check for auto-execute (only for high-confidence read-only commands)
        top = result.suggestions[0]
        if top.auto_execute and not top.is_write:
            # Execute directly
            executed = await _execute_command(top.command, update, context)
            if executed:
                return

        # Show buttons for confirmation
        # For single high-confidence suggestion, make it prominent
        if len(result.suggestions) == 1 and top.confidence >= 0.8:
            keyboard = _build_suggestion_keyboard(result.suggestions)
            msg = f"Did you mean:\n\n`{top.command}`\n_{top.description}_"
        else:
            # Multiple suggestions
            keyboard = _build_suggestion_keyboard(result.suggestions)
            lines = ["Which command?", ""]
            for s in result.suggestions[:4]:
                filled = int(s.confidence * 5)
                conf_bar = "●" * filled + "○" * (5 - filled)
                lines.append(f"`{s.command}` {conf_bar}")
            msg = "\n".join(lines)

        await update.effective_message.reply_text(
            msg,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return

    # No suggestions - check for errors first
    if result.error_type in ("rate_limit", "provider_error"):
        # Show error with button to switch models
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Switch Model", callback_data="m:browse")]]
        )
        msg = result.message or "AI model error. Try switching models."
        await update.effective_message.reply_text(
            f"⚠️ {msg}",
            reply_markup=keyboard,
        )
        return

    # No suggestions - show help message
    msg = result.message or "I'm not sure what you mean. Try /help to see commands."
    await update.effective_message.reply_text(msg)
