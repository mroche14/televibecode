"""Per-chat state management for Telegram bot."""

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from televibecode.db import Database


@dataclass
class MessageContext:
    """Context stored for a bot message, enabling reply routing."""

    message_id: int
    chat_id: int
    session_id: str | None = None
    project_id: str | None = None
    job_id: str | None = None
    message_type: str = "general"  # "session", "job", "approval", "general"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ChatSession:
    """State for a single chat."""

    chat_id: int
    active_session_id: str | None = None
    last_interaction: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    notification_level: str = "normal"  # "silent", "normal", "verbose"
    # AI model preference
    ai_model_id: str | None = None  # e.g., "meta-llama/llama-3.2-3b-instruct:free"
    ai_provider: str | None = None  # "openrouter" or "gemini"
    # Track if preferences have been loaded from DB
    _loaded_from_db: bool = False


class MessageContextStore:
    """Stores message context for reply routing.

    Maps message_id -> MessageContext to enable routing replies
    to the correct session even if other messages have been sent.
    """

    def __init__(self, max_entries: int = 1000):
        """Initialize the store.

        Args:
            max_entries: Maximum entries to keep (oldest are pruned).
        """
        self._store: OrderedDict[int, MessageContext] = OrderedDict()
        self._max_entries = max_entries

    def store(
        self,
        message_id: int,
        chat_id: int,
        session_id: str | None = None,
        project_id: str | None = None,
        job_id: str | None = None,
        message_type: str = "general",
    ) -> MessageContext:
        """Store context for a message.

        Args:
            message_id: Telegram message ID.
            chat_id: Telegram chat ID.
            session_id: Associated session ID.
            project_id: Associated project ID.
            job_id: Associated job ID.
            message_type: Type of message.

        Returns:
            The stored MessageContext.
        """
        ctx = MessageContext(
            message_id=message_id,
            chat_id=chat_id,
            session_id=session_id,
            project_id=project_id,
            job_id=job_id,
            message_type=message_type,
        )

        self._store[message_id] = ctx

        # Prune old entries if needed
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)  # Remove oldest

        return ctx

    def get(self, message_id: int) -> MessageContext | None:
        """Get context for a message.

        Args:
            message_id: Telegram message ID.

        Returns:
            MessageContext or None if not found.
        """
        return self._store.get(message_id)

    def get_session_for_reply(self, reply_to_message_id: int) -> str | None:
        """Get session ID from a reply-to message.

        Args:
            reply_to_message_id: ID of the message being replied to.

        Returns:
            Session ID or None.
        """
        ctx = self.get(reply_to_message_id)
        return ctx.session_id if ctx else None

    def clear_chat(self, chat_id: int) -> int:
        """Clear all stored contexts for a chat.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            Number of entries removed.
        """
        to_remove = [
            msg_id for msg_id, ctx in self._store.items() if ctx.chat_id == chat_id
        ]
        for msg_id in to_remove:
            del self._store[msg_id]
        return len(to_remove)

    def __len__(self) -> int:
        """Return number of stored contexts."""
        return len(self._store)


class ChatStateManager:
    """Manages per-chat state for the Telegram bot.

    Supports optional database persistence for user preferences.
    """

    def __init__(self, db: "Database | None" = None):
        """Initialize the state manager.

        Args:
            db: Optional database instance for preference persistence.
        """
        self._chats: dict[int, ChatSession] = {}
        self._message_contexts = MessageContextStore()
        self._db = db

    def set_database(self, db: "Database") -> None:
        """Set the database instance for persistence.

        Args:
            db: Database instance.
        """
        self._db = db

    def get_chat(self, chat_id: int) -> ChatSession:
        """Get or create chat state.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            ChatSession for this chat.
        """
        if chat_id not in self._chats:
            self._chats[chat_id] = ChatSession(chat_id=chat_id)
        return self._chats[chat_id]

    async def ensure_loaded(self, chat_id: int) -> ChatSession:
        """Ensure chat preferences are loaded from database.

        Call this before accessing preferences to ensure they're loaded.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            ChatSession with loaded preferences.
        """
        chat = self.get_chat(chat_id)

        # Load from DB if not yet loaded and DB is available
        if not chat._loaded_from_db and self._db:
            prefs = await self._db.get_user_preferences(chat_id)
            if prefs:
                chat.ai_model_id = prefs.get("ai_model_id")
                chat.ai_provider = prefs.get("ai_provider")
                chat.active_session_id = prefs.get("active_session_id")
                if prefs.get("notifications_enabled") is False:
                    chat.notification_level = "silent"
            chat._loaded_from_db = True

        return chat

    def get_active_session(self, chat_id: int) -> str | None:
        """Get active session ID for a chat.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            Active session ID or None.
        """
        chat = self.get_chat(chat_id)
        return chat.active_session_id

    def set_active_session(self, chat_id: int, session_id: str | None) -> None:
        """Set active session for a chat (in-memory only).

        Args:
            chat_id: Telegram chat ID.
            session_id: Session ID to set as active, or None to clear.
        """
        chat = self.get_chat(chat_id)
        chat.active_session_id = session_id
        chat.last_interaction = datetime.now(timezone.utc)

    async def set_active_session_persistent(
        self, chat_id: int, session_id: str | None
    ) -> None:
        """Set active session with database persistence.

        Args:
            chat_id: Telegram chat ID.
            session_id: Session ID or None to clear.
        """
        self.set_active_session(chat_id, session_id)
        if self._db:
            await self._db.set_user_active_session(chat_id, session_id)

    def update_interaction(self, chat_id: int) -> None:
        """Update last interaction time for a chat.

        Args:
            chat_id: Telegram chat ID.
        """
        chat = self.get_chat(chat_id)
        chat.last_interaction = datetime.now(timezone.utc)

    def set_notification_level(self, chat_id: int, level: str) -> None:
        """Set notification level for a chat.

        Args:
            chat_id: Telegram chat ID.
            level: One of "silent", "normal", "verbose".
        """
        if level not in ("silent", "normal", "verbose"):
            raise ValueError(f"Invalid notification level: {level}")

        chat = self.get_chat(chat_id)
        chat.notification_level = level

    def get_notification_level(self, chat_id: int) -> str:
        """Get notification level for a chat.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            Notification level string.
        """
        chat = self.get_chat(chat_id)
        return chat.notification_level

    def clear_chat(self, chat_id: int) -> None:
        """Clear state for a chat.

        Args:
            chat_id: Telegram chat ID.
        """
        if chat_id in self._chats:
            del self._chats[chat_id]
        self._message_contexts.clear_chat(chat_id)

    def set_ai_model(
        self, chat_id: int, model_id: str, provider: str
    ) -> None:
        """Set AI model preference for a chat (in-memory only).

        Args:
            chat_id: Telegram chat ID.
            model_id: Model ID (e.g., "meta-llama/llama-3.2-3b-instruct:free").
            provider: Provider name ("openrouter" or "gemini").
        """
        chat = self.get_chat(chat_id)
        chat.ai_model_id = model_id
        chat.ai_provider = provider
        chat.last_interaction = datetime.now(timezone.utc)

    async def set_ai_model_persistent(
        self, chat_id: int, model_id: str, provider: str
    ) -> None:
        """Set AI model with database persistence.

        Args:
            chat_id: Telegram chat ID.
            model_id: Model ID.
            provider: Provider name.
        """
        self.set_ai_model(chat_id, model_id, provider)
        if self._db:
            await self._db.set_user_ai_model(chat_id, model_id, provider)

    def get_ai_model(self, chat_id: int) -> tuple[str | None, str | None]:
        """Get AI model preference for a chat.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            Tuple of (model_id, provider) or (None, None) if not set.
        """
        chat = self.get_chat(chat_id)
        return chat.ai_model_id, chat.ai_provider

    # Message context methods (delegate to MessageContextStore)

    def store_message_context(
        self,
        message_id: int,
        chat_id: int,
        session_id: str | None = None,
        project_id: str | None = None,
        job_id: str | None = None,
        message_type: str = "general",
    ) -> MessageContext:
        """Store context for a bot message.

        Args:
            message_id: Telegram message ID.
            chat_id: Telegram chat ID.
            session_id: Associated session ID.
            project_id: Associated project ID.
            job_id: Associated job ID.
            message_type: Type of message.

        Returns:
            The stored MessageContext.
        """
        return self._message_contexts.store(
            message_id=message_id,
            chat_id=chat_id,
            session_id=session_id,
            project_id=project_id,
            job_id=job_id,
            message_type=message_type,
        )

    def get_message_context(self, message_id: int) -> MessageContext | None:
        """Get context for a message.

        Args:
            message_id: Telegram message ID.

        Returns:
            MessageContext or None.
        """
        return self._message_contexts.get(message_id)

    def get_session_for_reply(self, reply_to_message_id: int) -> str | None:
        """Get session ID from a reply-to message.

        Args:
            reply_to_message_id: ID of the message being replied to.

        Returns:
            Session ID or None.
        """
        return self._message_contexts.get_session_for_reply(reply_to_message_id)
