"""AI layer for intent parsing and natural language support."""

from televibecode.ai.intent import (
    IntentClassifier,
    IntentType,
    ParsedIntent,
    classify_message,
    get_classifier,
)
from televibecode.ai.transcription import (
    transcribe_audio,
    transcribe_telegram_voice,
)

# Conversational agent
try:
    from televibecode.ai.agent import (
        AgentResponse,
        PendingAction,
        TeleVibeAgent,
        clear_pending_action,
        get_agent,
        get_pending_action,
        reset_agent,
        set_pending_action,
    )

    AGENT_AVAILABLE = True
except ImportError:
    AGENT_AVAILABLE = False
    TeleVibeAgent = None  # type: ignore
    AgentResponse = None  # type: ignore
    PendingAction = None  # type: ignore
    get_agent = None  # type: ignore
    reset_agent = None  # type: ignore
    get_pending_action = None  # type: ignore
    set_pending_action = None  # type: ignore
    clear_pending_action = None  # type: ignore

__all__ = [
    "IntentClassifier",
    "IntentType",
    "ParsedIntent",
    "classify_message",
    "get_classifier",
    "transcribe_audio",
    "transcribe_telegram_voice",
    # Agent
    "AGENT_AVAILABLE",
    "TeleVibeAgent",
    "AgentResponse",
    "PendingAction",
    "get_agent",
    "reset_agent",
    "get_pending_action",
    "set_pending_action",
    "clear_pending_action",
]
