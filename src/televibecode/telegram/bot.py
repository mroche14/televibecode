"""Telegram bot setup and initialization."""

import asyncio

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

from televibecode.config import Settings
from televibecode.db import Database
from televibecode.telegram.handlers import (
    approval_callback_handler,
    approvals_command,
    cancel_command,
    claim_task_command,
    close_session_command,
    handle_reply_message,
    help_command,
    jobs_command,
    natural_language_handler,
    new_session_command,
    next_tasks_command,
    projects_command,
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
    use_session_command,
)
from televibecode.telegram.state import ChatStateManager

log = structlog.get_logger()


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
        self.state = ChatStateManager()
        self.app: Application | None = None

    async def setup(self) -> Application:
        """Set up the bot application.

        Returns:
            Configured Application instance.
        """
        # Build application
        self.app = Application.builder().token(self.settings.telegram_bot_token).build()

        # Store references in bot_data for handlers
        self.app.bot_data["db"] = self.db
        self.app.bot_data["settings"] = self.settings
        self.app.bot_data["chat_state"] = self.state

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
            BotCommand("sessions", "List active sessions"),
            BotCommand("new", "Create a new session"),
            BotCommand("use", "Switch to a session"),
            BotCommand("close", "Close a session"),
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
        ]
        await self.app.bot.set_my_commands(commands)
        log.info("bot_commands_menu_set", count=len(commands))

    def _register_handlers(self) -> None:
        """Register command and message handlers."""
        # Basic commands
        self.app.add_handler(CommandHandler("start", start_command))
        self.app.add_handler(CommandHandler("help", help_command))

        # Project commands
        self.app.add_handler(CommandHandler("projects", projects_command))
        self.app.add_handler(CommandHandler("scan", scan_command))

        # Session commands
        self.app.add_handler(CommandHandler("sessions", sessions_command))
        self.app.add_handler(CommandHandler("new", new_session_command))
        self.app.add_handler(CommandHandler("use", use_session_command))
        self.app.add_handler(CommandHandler("close", close_session_command))
        self.app.add_handler(CommandHandler("status", status_command))

        # Reply-to message handler (for session routing)
        self.app.add_handler(
            MessageHandler(
                filters.TEXT & filters.REPLY & ~filters.COMMAND,
                handle_reply_message,
            )
        )

        # Task commands
        self.app.add_handler(CommandHandler("tasks", tasks_command))
        self.app.add_handler(CommandHandler("next", next_tasks_command))
        self.app.add_handler(CommandHandler("claim", claim_task_command))
        self.app.add_handler(CommandHandler("sync", sync_backlog_command))

        # Job commands
        self.app.add_handler(CommandHandler("run", run_command))
        self.app.add_handler(CommandHandler("jobs", jobs_command))
        self.app.add_handler(CommandHandler("summary", summary_command))
        self.app.add_handler(CommandHandler("tail", tail_command))
        self.app.add_handler(CommandHandler("cancel", cancel_command))

        # Approval commands
        self.app.add_handler(CommandHandler("approvals", approvals_command))

        # Callback query handlers (for inline keyboards)
        self.app.add_handler(
            CallbackQueryHandler(
                session_callback_handler,
                pattern="^session:",
            )
        )
        self.app.add_handler(
            CallbackQueryHandler(
                task_callback_handler,
                pattern="^task:",
            )
        )
        self.app.add_handler(
            CallbackQueryHandler(
                approval_callback_handler,
                pattern="^approval:",
            )
        )

        # Natural language handler (non-command, non-reply text)
        self.app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & ~filters.REPLY,
                natural_language_handler,
            )
        )

        # Fallback for unknown commands
        self.app.add_handler(
            MessageHandler(
                filters.COMMAND,
                self._unknown_command,
            )
        )

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

    async def run_polling(self) -> None:
        """Run the bot with polling (for development)."""
        if not self.app:
            await self.setup()

        log.info("telegram_bot_starting", mode="polling")

        # Initialize and start
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)

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
