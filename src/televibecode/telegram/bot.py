"""Telegram bot setup and initialization."""

import asyncio
import json
from pathlib import Path

import structlog
from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.ext.filters import BaseFilter

from televibecode.config import Settings
from televibecode.db import Database
from televibecode.telegram.handlers import (
    agent_callback_handler,
    approval_callback_handler,
    approvals_command,
    cancel_command,
    choice_callback_handler,
    claim_task_command,
    cleanup_callback_handler,
    cleanup_sessions_command,
    close_callback_handler,
    close_session_command,
    command_callback_handler,
    handle_reply_message,
    help_command,
    jobs_command,
    model_callback_handler,
    model_command,
    models_command,
    natural_language_handler,
    new_session_command,
    newproject_callback_handler,
    newproject_command,
    next_tasks_command,
    projects_command,
    push_command,
    reset_command,
    restart_command,
    run_command,
    scan_command,
    session_callback_handler,
    sessions_command,
    start_command,
    status_command,
    summary_command,
    sync_backlog_command,
    tail_command,
    task_callback_handler,
    tasks_command,
    tracker_callback_handler,
    tracker_command,
    use_session_command,
    voice_confirm_callback_handler,
    voice_message_handler,
)
from televibecode.telegram.state import ChatStateManager
from televibecode.tracker import JobTrackerManager, TrackerConfig

log = structlog.get_logger()


class AllowedChatFilter(BaseFilter):
    """Filter that only allows messages from whitelisted chat IDs."""

    def __init__(self, allowed_chat_ids: list[int]):
        """Initialize the filter.

        Args:
            allowed_chat_ids: List of allowed chat IDs. Empty list allows all.
        """
        super().__init__()
        self.allowed_chat_ids = set(allowed_chat_ids)

    def check_update(self, update: Update) -> bool:
        """Check if the update is from an allowed chat.

        Args:
            update: Telegram update.

        Returns:
            True if allowed, False otherwise.
        """
        # If no whitelist configured, allow all (but warn on startup)
        if not self.allowed_chat_ids:
            return True

        # Get chat ID from various update types
        chat_id = None
        if update.effective_chat:
            chat_id = update.effective_chat.id
        elif update.callback_query and update.callback_query.message:
            chat_id = update.callback_query.message.chat.id

        return chat_id in self.allowed_chat_ids


class TeleVibeBot:
    """TeleVibeCode Telegram bot."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
    ):
        """Initialize the bot.

        Args:
            settings: Application settings.
            db: Database instance.
        """
        self.settings = settings
        self.db = db
        self.state = ChatStateManager(db=db)  # Enable preference persistence
        self.app: Application | None = None
        self.auth_filter = AllowedChatFilter(settings.telegram_allowed_chat_ids)
        self.tracker_manager: JobTrackerManager | None = None

    async def setup(self) -> Application:
        """Set up the bot application.

        Returns:
            Configured Application instance.
        """
        # Security check - warn if no chat IDs configured
        if not self.settings.telegram_allowed_chat_ids:
            log.warning(
                "security_warning",
                message="No TELEGRAM_ALLOWED_CHAT_IDS configured! "
                "Bot is accessible to ANYONE. Set allowed chat IDs in .env",
            )
        else:
            log.info(
                "auth_configured",
                allowed_chat_ids=self.settings.telegram_allowed_chat_ids,
            )

        # Build application
        self.app = Application.builder().token(self.settings.telegram_bot_token).build()

        # Initialize job tracker manager
        self.tracker_manager = JobTrackerManager(
            bot=self.app.bot,
            default_config=TrackerConfig(),
        )

        # Store references in bot_data for handlers
        self.app.bot_data["db"] = self.db
        self.app.bot_data["settings"] = self.settings
        self.app.bot_data["chat_state"] = self.state
        self.app.bot_data["auth_filter"] = self.auth_filter
        self.app.bot_data["tracker_manager"] = self.tracker_manager

        # Register handlers
        self._register_handlers()

        # Set up error handler
        self.app.add_error_handler(self._error_handler)

        log.info("telegram_bot_configured")
        return self.app

    async def set_commands_menu(self) -> None:
        """Set the bot commands menu for autocomplete."""
        commands = [
            BotCommand("help", "Show available commands"),
            BotCommand("projects", "List registered projects"),
            BotCommand("scan", "Scan for new projects"),
            BotCommand("newproject", "Create a new project"),
            BotCommand("sessions", "List active sessions"),
            BotCommand("new", "Create a new session"),
            BotCommand("use", "Switch to a session"),
            BotCommand("close", "Close a session"),
            BotCommand("push", "Push session branch to origin"),
            BotCommand("cleanup", "Close all sessions"),
            BotCommand("status", "Show session status"),
            BotCommand("tasks", "List tasks"),
            BotCommand("next", "Show next tasks"),
            BotCommand("claim", "Claim a task"),
            BotCommand("sync", "Sync backlog"),
            BotCommand("run", "Run an instruction"),
            BotCommand("jobs", "List recent jobs"),
            BotCommand("summary", "Show job summary"),
            BotCommand("tail", "View job logs"),
            BotCommand("cancel", "Cancel a job"),
            BotCommand("approvals", "List pending approvals"),
            BotCommand("models", "List available AI models"),
            BotCommand("model", "Switch AI model"),
            BotCommand("tracker", "Configure job tracker display"),
            BotCommand("reset", "Clear AI conversation history"),
        ]
        await self.app.bot.set_my_commands(commands)
        log.info("bot_commands_menu_set", count=len(commands))

    def _register_handlers(self) -> None:
        """Register command and message handlers."""
        # Auth filter for all handlers
        auth = self.auth_filter

        # PRIVILEGED COMMANDS - These are handled FIRST and never seen by AI
        # /restart is a human-only command for safety
        self.app.add_handler(CommandHandler("restart", restart_command, filters=auth))

        # Basic commands
        self.app.add_handler(CommandHandler("start", start_command, filters=auth))
        self.app.add_handler(CommandHandler("help", help_command, filters=auth))
        self.app.add_handler(CommandHandler("reset", reset_command, filters=auth))

        # Project commands
        self.app.add_handler(CommandHandler("projects", projects_command, filters=auth))
        self.app.add_handler(CommandHandler("scan", scan_command, filters=auth))
        self.app.add_handler(
            CommandHandler("newproject", newproject_command, filters=auth)
        )

        # Session commands
        self.app.add_handler(CommandHandler("sessions", sessions_command, filters=auth))
        self.app.add_handler(CommandHandler("new", new_session_command, filters=auth))
        self.app.add_handler(CommandHandler("use", use_session_command, filters=auth))
        self.app.add_handler(
            CommandHandler("close", close_session_command, filters=auth)
        )
        self.app.add_handler(CommandHandler("push", push_command, filters=auth))
        self.app.add_handler(
            CommandHandler("cleanup", cleanup_sessions_command, filters=auth)
        )
        self.app.add_handler(CommandHandler("status", status_command, filters=auth))

        # Reply-to message handler (for session routing)
        self.app.add_handler(
            MessageHandler(
                auth & filters.TEXT & filters.REPLY & ~filters.COMMAND,
                handle_reply_message,
            )
        )

        # Task commands
        self.app.add_handler(CommandHandler("tasks", tasks_command, filters=auth))
        self.app.add_handler(CommandHandler("next", next_tasks_command, filters=auth))
        self.app.add_handler(CommandHandler("claim", claim_task_command, filters=auth))
        self.app.add_handler(CommandHandler("sync", sync_backlog_command, filters=auth))

        # Job commands
        self.app.add_handler(CommandHandler("run", run_command, filters=auth))
        self.app.add_handler(CommandHandler("jobs", jobs_command, filters=auth))
        self.app.add_handler(CommandHandler("summary", summary_command, filters=auth))
        self.app.add_handler(CommandHandler("tail", tail_command, filters=auth))
        self.app.add_handler(CommandHandler("cancel", cancel_command, filters=auth))

        # Approval commands
        self.app.add_handler(
            CommandHandler("approvals", approvals_command, filters=auth)
        )

        # Model commands
        self.app.add_handler(CommandHandler("models", models_command, filters=auth))
        self.app.add_handler(CommandHandler("model", model_command, filters=auth))

        # Tracker config command
        self.app.add_handler(CommandHandler("tracker", tracker_command, filters=auth))

        # Callback query handlers (for inline keyboards)
        # Note: CallbackQueryHandler checks auth in the handler itself
        self.app.add_handler(
            CallbackQueryHandler(
                self._auth_callback_wrapper(session_callback_handler),
                pattern="^session:",
            )
        )
        self.app.add_handler(
            CallbackQueryHandler(
                self._auth_callback_wrapper(task_callback_handler),
                pattern="^task:",
            )
        )
        self.app.add_handler(
            CallbackQueryHandler(
                self._auth_callback_wrapper(approval_callback_handler),
                pattern="^approval:",
            )
        )
        self.app.add_handler(
            CallbackQueryHandler(
                self._auth_callback_wrapper(model_callback_handler),
                pattern="^m:",
            )
        )
        # New project callback handler (for GitHub/GitLab selection)
        self.app.add_handler(
            CallbackQueryHandler(
                self._auth_callback_wrapper(newproject_callback_handler),
                pattern="^newproj:",
            )
        )
        # Command suggestion callback handler (for natural language suggestions)
        self.app.add_handler(
            CallbackQueryHandler(
                self._auth_callback_wrapper(command_callback_handler),
                pattern="^cmd:",
            )
        )
        # Voice transcription confirmation handler
        self.app.add_handler(
            CallbackQueryHandler(
                self._auth_callback_wrapper(voice_confirm_callback_handler),
                pattern="^voice:",
            )
        )
        # Agent confirmation handler (Yes/No for write operations)
        self.app.add_handler(
            CallbackQueryHandler(
                self._auth_callback_wrapper(agent_callback_handler),
                pattern="^agent:",
            )
        )
        # Cleanup confirmation handler
        self.app.add_handler(
            CallbackQueryHandler(
                self._auth_callback_wrapper(cleanup_callback_handler),
                pattern="^cleanup:",
            )
        )
        # Close session branch options handler
        self.app.add_handler(
            CallbackQueryHandler(
                self._auth_callback_wrapper(close_callback_handler),
                pattern="^close:",
            )
        )
        # Agent MCQ choice handler (user selects from multiple options)
        self.app.add_handler(
            CallbackQueryHandler(
                self._auth_callback_wrapper(choice_callback_handler),
                pattern="^choice:",
            )
        )
        # Tracker config callback handler
        self.app.add_handler(
            CallbackQueryHandler(
                self._auth_callback_wrapper(tracker_callback_handler),
                pattern="^trk:",
            )
        )

        # Natural language handler (non-command, non-reply text)
        self.app.add_handler(
            MessageHandler(
                auth & filters.TEXT & ~filters.COMMAND & ~filters.REPLY,
                natural_language_handler,
            )
        )

        # Voice message handler (transcription via Groq Whisper)
        self.app.add_handler(
            MessageHandler(
                auth & (filters.VOICE | filters.AUDIO),
                voice_message_handler,
            )
        )

        # Fallback for unknown commands (still requires auth)
        self.app.add_handler(
            MessageHandler(
                auth & filters.COMMAND,
                self._unknown_command,
            )
        )

        # Unauthorized handler - catches messages from non-whitelisted users
        # Only active if whitelist is configured
        if self.settings.telegram_allowed_chat_ids:
            self.app.add_handler(
                MessageHandler(
                    filters.ALL & ~auth,
                    self._unauthorized_handler,
                ),
                group=1,  # Lower priority group
            )
            self.app.add_handler(
                CallbackQueryHandler(
                    self._unauthorized_callback,
                ),
                group=1,
            )

    def _auth_callback_wrapper(self, handler):
        """Wrap a callback handler with auth check.

        Args:
            handler: Original callback handler function.

        Returns:
            Wrapped handler that checks auth first.
        """

        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not self.auth_filter.check_update(update):
                await self._unauthorized_callback(update, context)
                return
            return await handler(update, context)

        return wrapper

    async def _unauthorized_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle messages from unauthorized users."""
        chat_id = update.effective_chat.id if update.effective_chat else "unknown"
        log.warning(
            "unauthorized_access_attempt",
            chat_id=chat_id,
            username=update.effective_user.username if update.effective_user else None,
        )
        await update.message.reply_text(
            "Access denied.\n\n"
            f"Your chat ID: `{chat_id}`\n\n"
            "This bot is private. If you are the owner, add your chat ID to "
            "TELEGRAM_ALLOWED_CHAT_IDS in your .env file.",
            parse_mode="Markdown",
        )

    async def _unauthorized_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle callback queries from unauthorized users."""
        query = update.callback_query
        if query:
            await query.answer("Access denied.", show_alert=True)

    async def _unknown_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle unknown commands."""
        await update.message.reply_text(
            "Unknown command. Use /help to see available commands."
        )

    async def _error_handler(
        self, update: Update | None, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle errors in handlers."""
        log.error(
            "telegram_handler_error",
            error=str(context.error),
            update=str(update) if update else None,
        )

        if update and update.effective_message:
            await update.effective_message.reply_text(
                "An error occurred. Please try again."
            )

    async def handle_post_restart(self) -> None:
        """Handle notifications after a restart.

        If there's a restart_state.json file, read it and notify
        the users who triggered the restart that we're back online.
        """
        state_file = Path.home() / ".televibe" / "restart_state.json"

        if not state_file.exists():
            return

        try:
            state = json.loads(state_file.read_text())
            log.info("post_restart_state_found", state=state)

            # Get current commit for the message
            try:
                import subprocess

                result = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    capture_output=True,
                    text=True,
                    cwd=Path(__file__).parent.parent.parent,
                )
                current_commit = (
                    result.stdout.strip() if result.returncode == 0 else "unknown"
                )
            except Exception:
                current_commit = "unknown"

            # Notify each chat with a new message
            for chat_id in state.get("notify_chats", []):
                try:
                    await self.app.bot.send_message(
                        chat_id=chat_id,
                        text=f"✅ *TeleVibeCode is back online!*\n\n"
                        f"Commit: `{current_commit}`",
                        parse_mode="Markdown",
                    )
                    log.info("post_restart_notification_sent", chat_id=chat_id)
                except Exception as e:
                    log.warning(
                        "post_restart_notification_failed",
                        chat_id=chat_id,
                        error=str(e),
                    )

            # Clear the state file (may already be deleted by supervisor)
            state_file.unlink(missing_ok=True)
            log.info("restart_state_cleared")

        except Exception as e:
            log.error("post_restart_handling_failed", error=str(e))
            # Don't let this crash startup - just log and continue
            state_file.unlink(missing_ok=True)

    async def run_polling(self) -> None:
        """Run the bot with polling (for development)."""
        if not self.app:
            await self.setup()

        log.info("telegram_bot_starting", mode="polling")

        # Initialize and start
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)

        # Write health flag for supervisor
        health_file = Path.home() / ".televibe" / "health.flag"
        health_file.parent.mkdir(parents=True, exist_ok=True)
        health_file.write_text("ok")
        log.info("health_flag_written")

        # Handle post-restart notifications
        await self.handle_post_restart()

        log.info("telegram_bot_running")

        # Keep running until stopped
        try:
            # Wait forever (or until interrupted)
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the bot gracefully."""
        if self.app:
            log.info("telegram_bot_stopping")
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            log.info("telegram_bot_stopped")


def create_bot(settings: Settings, db: Database) -> TeleVibeBot:
    """Create a TeleVibeBot instance.

    Args:
        settings: Application settings.
        db: Database instance.

    Returns:
        Configured TeleVibeBot.
    """
    return TeleVibeBot(settings, db)
