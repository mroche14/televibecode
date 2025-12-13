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

    # AI Layer (Agno) - optional for AI-based intent classification
    agno_api_key: str | None = Field(
        default=None,
        description="API key for LLM provider (optional)",
    )
    agno_provider: Literal["gemini", "anthropic", "openai", "openrouter"] = Field(
        default="gemini",
        description="LLM provider for intermediate AI layer",
    )
    agno_model: str | None = Field(
        default=None,
        description="Model ID override (uses provider default if not set)",
    )

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

    if "agno_api_key" in error_str.lower():
        print("Missing required environment variable: AGNO_API_KEY")
        print("Set AGNO_PROVIDER and AGNO_API_KEY for the AI layer.")
        print()
        print("Free options:")
        print("  - Gemini: https://aistudio.google.com/apikey")
        print("  - OpenRouter: https://openrouter.ai (free models: grok-beta)")
        print()

    print("Example .env file:")
    print("-" * 40)
    print("TELEGRAM_BOT_TOKEN=your_token_here")
    print("AGNO_PROVIDER=gemini")
    print("AGNO_API_KEY=your_api_key_here")
    print("-" * 40)
    print()

    # Print the actual validation error for debugging
    print(f"Validation error: {error}")
    print()
