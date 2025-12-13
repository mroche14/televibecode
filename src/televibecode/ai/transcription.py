"""Audio transcription using Groq Whisper API."""

from pathlib import Path

import httpx
import structlog

log = structlog.get_logger()

# Groq Whisper API endpoint
GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Available Whisper models on Groq (fastest to most accurate)
WHISPER_MODELS = {
    "turbo": "whisper-large-v3-turbo",  # Fastest, good quality
    "english": "distil-whisper-large-v3-en",  # English-optimized
    "accurate": "whisper-large-v3",  # Most accurate, slower
}

# Default model - turbo is fastest and good for voice messages
DEFAULT_MODEL = "whisper-large-v3-turbo"


async def transcribe_audio(
    audio_data: bytes,
    api_key: str,
    filename: str = "audio.ogg",
    model: str = DEFAULT_MODEL,
    language: str | None = None,
    prompt: str | None = None,
) -> str:
    """Transcribe audio using Groq Whisper API.

    Args:
        audio_data: Raw audio file bytes.
        api_key: Groq API key.
        filename: Original filename (helps determine format).
        model: Whisper model to use.
        language: Optional language code (e.g., 'en', 'es').
        prompt: Optional prompt for context/style.

    Returns:
        Transcribed text.

    Raises:
        Exception: If transcription fails.
    """
    log.info(
        "transcription_starting",
        filename=filename,
        size_bytes=len(audio_data),
        model=model,
    )

    # Determine content type from filename
    ext = Path(filename).suffix.lower()
    content_types = {
        ".ogg": "audio/ogg",
        ".oga": "audio/ogg",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/m4a",
        ".webm": "audio/webm",
    }
    content_type = content_types.get(ext, "audio/ogg")

    # Build multipart form data
    files = {
        "file": (filename, audio_data, content_type),
    }
    data = {
        "model": model,
        "response_format": "text",
    }

    if language:
        data["language"] = language
    if prompt:
        data["prompt"] = prompt

    async with httpx.AsyncClient() as client:
        response = await client.post(
            GROQ_TRANSCRIPTION_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
            data=data,
            timeout=60.0,  # Voice messages can take a few seconds
        )

        if response.status_code != 200:
            log.error(
                "transcription_failed",
                status=response.status_code,
                error=response.text,
            )
            raise Exception(f"Transcription failed: {response.text}")

        text = response.text.strip()
        log.info(
            "transcription_complete",
            text_length=len(text),
            preview=text[:100] if text else "(empty)",
        )
        return text


async def transcribe_telegram_voice(
    voice_file: bytes,
    api_key: str,
) -> str:
    """Transcribe a Telegram voice message.

    Telegram voice messages are in OGG Opus format.

    Args:
        voice_file: Voice message file bytes.
        api_key: Groq API key.

    Returns:
        Transcribed text.
    """
    return await transcribe_audio(
        audio_data=voice_file,
        api_key=api_key,
        filename="voice.ogg",
        model=DEFAULT_MODEL,
        # Provide context for better transcription
        prompt="This is a voice command for a coding assistant bot.",
    )
