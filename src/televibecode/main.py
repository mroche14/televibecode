"""TeleVibeCode CLI entry point."""

import argparse
import asyncio
import logging
import os
import shutil
import signal
import sys
from pathlib import Path

import structlog
from dotenv import load_dotenv

from televibecode import __version__
from televibecode.config import load_settings
from televibecode.db import Database
from televibecode.orchestrator import create_mcp_server
from televibecode.telegram import create_bot

# ANSI color codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

# Colors
CYAN = "\033[36m"
MAGENTA = "\033[35m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BLUE = "\033[34m"
WHITE = "\033[37m"
RED = "\033[31m"

# Bright colors
BRIGHT_CYAN = "\033[96m"
BRIGHT_MAGENTA = "\033[95m"
BRIGHT_YELLOW = "\033[93m"
BRIGHT_GREEN = "\033[92m"
BRIGHT_BLUE = "\033[94m"


def print_banner() -> None:  # noqa: E501
    """Print the startup banner with blue-to-violet gradient."""
    r = RESET
    # Gradient from blue (39) to violet (99): 39 -> 63 -> 62 -> 98 -> 99
    c1 = "\033[38;5;39m"   # Blue
    c2 = "\033[38;5;63m"
    c3 = "\033[38;5;62m"
    c4 = "\033[38;5;98m"
    c5 = "\033[38;5;99m"   # Violet

    print()
    print(f"  {c1}████████╗███████╗██╗     ███████╗██╗   ██╗██╗██████╗ ███████╗{r}")
    print(f"  {c1}╚══██╔══╝██╔════╝██║     ██╔════╝██║   ██║██║██╔══██╗██╔════╝{r}")
    print(f"  {c2}   ██║   █████╗  ██║     █████╗  ██║   ██║██║██████╔╝█████╗  {r}")
    print(f"  {c2}   ██║   ██╔══╝  ██║     ██╔══╝  ╚██╗ ██╔╝██║██╔══██╗██╔══╝  {r}")
    print(f"  {c3}   ██║   ███████╗███████╗███████╗ ╚████╔╝ ██║██████╔╝███████╗{r}")
    print(f"  {c3}   ╚═╝   ╚══════╝╚══════╝╚══════╝  ╚═══╝  ╚═╝╚═════╝ ╚══════╝{r}")
    print()
    print(f"  {c4}                    ██████╗ ██████╗ ██████╗ ███████╗{r}")
    print(f"  {c4}                    ██╔════╝██╔═══██╗██╔══██╗██╔════╝{r}")
    print(f"  {c5}                    ██║     ██║   ██║██║  ██║█████╗  {r}")
    print(f"  {c5}                    ██║     ██║   ██║██║  ██║██╔══╝  {r}")
    print(f"  {c5}                    ╚██████╗╚██████╔╝██████╔╝███████╗{r}")
    print(f"  {c5}                     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝{r}")
    print()
    print(f"  {DIM}Remote AI coding orchestration via Telegram  v{__version__}{r}")
    print()


def configure_logging(level: str) -> None:
    """Configure structlog for the application."""
    # Configure stdlib logging
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def serve(root: Path) -> None:
    """Run the TeleVibeCode server.

    Args:
        root: Projects root directory.
    """
    # Load .env into os.environ (required for agno and other libs)
    env_file = root / ".env"
    if not env_file.exists():
        env_file = root / ".televibe" / ".env"
    load_dotenv(env_file if env_file.exists() else None)

    # Set GOOGLE_API_KEY alias for agno (it expects GOOGLE_API_KEY, not GEMINI_API_KEY)
    if os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.getenv("GEMINI_API_KEY")

    # Load settings
    settings = load_settings(root)
    settings.ensure_dirs()

    configure_logging(settings.log_level)
    log = structlog.get_logger()

    # Print stylish startup banner
    print_banner()

    log.info(
        "config_loaded",
        root=str(settings.televibe_root),
        db_path=str(settings.db_path),
        log_level=settings.log_level,
    )

    # Log security status
    if settings.telegram_allowed_chat_ids:
        log.info(
            "security_enabled",
            allowed_chats=len(settings.telegram_allowed_chat_ids),
            chat_ids=settings.telegram_allowed_chat_ids,
        )
    else:
        log.warning(
            "security_disabled",
            message="TELEGRAM_ALLOWED_CHAT_IDS not set - bot is PUBLIC!",
        )

    # Log AI provider status
    ai_providers = []
    if settings.has_gemini:
        ai_providers.append("Gemini")
    if settings.has_openrouter:
        ai_providers.append("OpenRouter")
    if settings.has_groq:
        ai_providers.append("Groq")
    if settings.has_cerebras:
        ai_providers.append("Cerebras")

    if ai_providers:
        log.info(
            "ai_providers_configured",
            providers=ai_providers,
            message=f"AI enabled: {', '.join(ai_providers)}",
        )
    else:
        log.warning(
            "ai_providers_missing",
            message="No AI providers configured. "
            "Set GEMINI_API_KEY, OPENROUTER_API_KEY, or GROQ_API_KEY.",
        )

    # Log Groq (audio transcription) status
    if settings.has_groq:
        log.info(
            "groq_configured",
            message="Voice transcription enabled (Groq Whisper)",
        )
    else:
        log.info(
            "groq_not_configured",
            message="Voice messages disabled. Set GROQ_API_KEY for transcription.",
        )

    # Check for Claude Code CLI
    claude_path = shutil.which("claude")
    if claude_path:
        log.info(
            "claude_cli_found",
            path=claude_path,
            message=f"Claude Code CLI: {claude_path}",
        )
    else:
        log.error(
            "claude_cli_missing",
            message="Claude Code CLI not found in PATH!",
        )
        print()
        print("ERROR: 'claude' command not found.")
        print()
        print("TeleVibeCode requires Claude Code CLI to run instructions.")
        print("Install it with:")
        print()
        print("  npm install -g @anthropic-ai/claude-code")
        print()
        print("Or run directly with npx:")
        print()
        print("  npx @anthropic-ai/claude-code")
        print()
        print("After installing, make sure 'claude' is in your PATH:")
        print()
        print("  which claude")
        print()
        sys.exit(1)

    # Initialize database
    log.info("database_connecting", path=str(settings.db_path))
    db = Database(settings.db_path)
    await db.connect()
    log.info("database_ready", path=str(settings.db_path))

    # Create MCP server
    _ = create_mcp_server(db, settings.televibe_root)
    log.info("mcp_server_ready")

    # Create and start Telegram bot
    log.info("telegram_bot_initializing")
    bot = create_bot(settings, db)
    await bot.setup()

    # Set up graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler():
        log.info("shutdown_signal_received", message="Ctrl+C pressed, shutting down...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Start bot polling
    assert bot.app is not None, "Bot application not initialized"
    await bot.app.initialize()
    await bot.app.start()
    await bot.set_commands_menu()
    assert bot.app.updater is not None, "Bot updater not initialized"
    await bot.app.updater.start_polling(drop_pending_updates=True)

    # Ready message with style (blue-violet theme)
    violet = "\033[38;5;99m"
    print()
    print(f"{DIM}{'─' * 70}{RESET}")
    print(f"  {BRIGHT_GREEN}✓{RESET} {BOLD}TeleVibeCode is running!{RESET}")
    print(f"{DIM}{'─' * 70}{RESET}")
    print()
    print(
        f"  {BRIGHT_BLUE}📱{RESET} Open Telegram and send "
        f"{BOLD}/help{RESET} to your bot to get started"
    )
    print(f"  {violet}⌨️ {RESET} Press {BOLD}Ctrl+C{RESET} to stop the server")
    print()

    log.info(
        "server_ready",
        message="TeleVibeCode is running!",
        telegram_bot="connected",
        database="connected",
        ai_providers=ai_providers or ["none"],
    )

    # Write health flag for supervisor
    health_file = Path.home() / ".televibe" / "health.flag"
    health_file.parent.mkdir(parents=True, exist_ok=True)
    health_file.write_text("ok")
    log.info("health_flag_written", path=str(health_file))

    # Handle post-restart notifications
    await bot.handle_post_restart()

    # Wait for shutdown signal
    await shutdown_event.wait()

    # Cleanup
    log.info("shutting_down")
    await bot.stop()
    await db.close()
    log.info("televibecode_stopped")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="televibecode",
        description="Remote orchestration harness for Claude Code via Telegram",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # serve command
    serve_parser = subparsers.add_parser(
        "serve",
        help="Start the TeleVibeCode server",
    )
    serve_parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Projects root directory (default: current directory)",
    )

    # scan command (quick utility)
    scan_parser = subparsers.add_parser(
        "scan",
        help="Scan for projects without starting the server",
    )
    scan_parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Directory to scan (default: current directory)",
    )

    # supervised command (runs with self-healing supervisor)
    supervised_parser = subparsers.add_parser(
        "supervised",
        help="Start TeleVibeCode with self-healing supervisor",
    )
    supervised_parser.add_argument(
        "--root",
        type=Path,
        default=Path.home() / "projects",
        help="Projects root directory (default: ~/projects)",
    )

    args = parser.parse_args()

    if args.command == "serve":
        asyncio.run(serve(args.root))
    elif args.command == "scan":
        asyncio.run(scan_only(args.root))
    elif args.command == "supervised":
        run_supervised(args.root)
    else:
        parser.print_help()
        sys.exit(1)


async def scan_only(root: Path) -> None:
    """Scan for projects without starting the full server.

    Args:
        root: Directory to scan.
    """
    from televibecode.orchestrator.tools import projects

    root = root.expanduser().resolve()
    print(f"Scanning {root} for git repositories...\n")

    # Create temporary DB in memory
    db = Database(Path(":memory:"))
    await db.connect()

    result = await projects.scan_projects(db, root)

    print(f"Found {result['found']} git repositories:\n")

    for p in result["details"]["registered"]:
        print(f"  📂 {p['name']}")
        print(f"     ID: {p['project_id']}")
        print(f"     Path: {p['path']}")
        print()

    await db.close()


def run_supervised(root: Path) -> None:
    """Run TeleVibeCode with the self-healing supervisor.

    The supervisor will:
    - Monitor the TeleVibeCode process
    - Handle restart requests via /restart command
    - Spawn Claude Code to fix issues if startup fails
    - Revert to last working commit if healing fails

    Args:
        root: Projects root directory.
    """
    from televibecode.supervisor import main as supervisor_main

    supervisor_main(root)


if __name__ == "__main__":
    main()
