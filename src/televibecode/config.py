"""Configuration management for TeleVibeCode."""

import sys
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """TeleVibeCode configuration settings."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str = Field(
        ...,
        description="Telegram bot token from @BotFather",
    )
    telegram_allowed_chat_ids: list[int] = Field(
        default_factory=list,
        description="Allowed Telegram chat IDs (empty = allow all - INSECURE)",
    )

    @field_validator("telegram_allowed_chat_ids", mode="before")
    @classmethod
    def parse_chat_ids(cls, v: str | list[int] | None) -> list[int]:
        """Parse chat IDs from comma-separated string or list."""
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return v
        # Parse comma-separated string: "123,456,789"
        return [int(x.strip()) for x in str(v).split(",") if x.strip()]

    # AI Provider API Keys (set whichever you have)
    gemini_api_key: str | None = Field(
        default=None,
        description="Google Gemini API key",
    )
    openrouter_api_key: str | None = Field(
        default=None,
        description="OpenRouter API key (access to many free models)",
    )
    groq_api_key: str | None = Field(
        default=None,
        description="Groq API key (for Whisper audio transcription)",
    )

    @property
    def has_gemini(self) -> bool:
        """Check if Gemini is available."""
        return bool(self.gemini_api_key)

    @property
    def has_openrouter(self) -> bool:
        """Check if OpenRouter is available."""
        return bool(self.openrouter_api_key)

    @property
    def has_groq(self) -> bool:
        """Check if Groq (audio transcription) is available."""
        return bool(self.groq_api_key)

    @property
    def has_ai(self) -> bool:
        """Check if any AI provider is available."""
        return self.has_gemini or self.has_openrouter

    # Paths
    televibe_root: Path = Field(
        default_factory=Path.cwd,
        description="Root directory containing projects",
    )

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level",
    )

    # Limits
    max_concurrent_jobs: int = Field(
        default=3,
        description="Maximum concurrent job executions",
    )

    # Executor type
    executor_type: Literal["subprocess", "sdk"] = Field(
        default="subprocess",
        description="Job executor: 'subprocess' (default) or 'sdk'",
    )

    @property
    def use_sdk_executor(self) -> bool:
        """Check if SDK executor should be used."""
        return self.executor_type == "sdk"

    @field_validator("televibe_root", mode="before")
    @classmethod
    def resolve_root(cls, v: str | Path) -> Path:
        """Resolve and validate root path."""
        path = Path(v).expanduser().resolve()
        return path

    @property
    def televibe_dir(self) -> Path:
        """Path to .televibe directory."""
        return self.televibe_root / ".televibe"

    @property
    def db_path(self) -> Path:
        """Path to SQLite database."""
        return self.televibe_dir / "state.db"

    @property
    def logs_dir(self) -> Path:
        """Path to logs directory."""
        return self.televibe_dir / "logs"

    @property
    def workspaces_dir(self) -> Path:
        """Path to workspaces directory."""
        return self.televibe_dir / "workspaces"

    def ensure_dirs(self) -> None:
        """Create required directories if they don't exist."""
        self.televibe_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)


def load_settings(root: Path | None = None) -> Settings:
    """Load settings from environment and .env file.

    Args:
        root: Optional root directory override.

    Returns:
        Validated Settings instance.

    Raises:
        SystemExit: If required settings are missing.
    """
    # If root provided, look for .env there
    env_file = None
    if root:
        env_file = root / ".env"
        if not env_file.exists():
            env_file = root / ".televibe" / ".env"
            if not env_file.exists():
                env_file = None

    try:
        if env_file and env_file.exists():
            # _env_file is a valid pydantic-settings parameter
            return Settings(_env_file=env_file, televibe_root=root or Path.cwd())  # type: ignore[call-arg]
        if root:
            return Settings(televibe_root=root)
        return Settings()

    except Exception as e:
        _print_missing_config_help(e)
        sys.exit(1)


def _print_missing_config_help(error: Exception) -> None:
    """Print helpful message for missing configuration."""
    error_str = str(error)

    print("\n" + "=" * 60)
    print("TeleVibeCode Configuration Error")
    print("=" * 60 + "\n")

    if "telegram_bot_token" in error_str.lower():
        print("Missing required environment variable: TELEGRAM_BOT_TOKEN")
        print("Get your token from @BotFather on Telegram.")
        print("\n  1. Open Telegram and search for @BotFather")
        print("  2. Send /newbot and follow the prompts")
        print("  3. Copy the token and set it in your environment")
        print()

    print("Example .env file:")
    print("-" * 40)
    print("TELEGRAM_BOT_TOKEN=your_token_here")
    print("TELEGRAM_ALLOWED_CHAT_IDS=your_chat_id")
    print()
    print("# AI providers (set one or both)")
    print("GEMINI_API_KEY=your_gemini_key")
    print("OPENROUTER_API_KEY=your_openrouter_key")
    print()
    print("# Voice transcription (optional)")
    print("GROQ_API_KEY=your_groq_key")
    print("-" * 40)
    print()
    print("Get API keys:")
    print("  - Gemini: https://aistudio.google.com/apikey")
    print("  - OpenRouter: https://openrouter.ai/keys")
    print("  - Groq: https://console.groq.com/keys")
    print()

    # Print the actual validation error for debugging
    print(f"Validation error: {error}")
    print()
