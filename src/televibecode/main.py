"""TeleVibeCode CLI entry point."""

import argparse
import asyncio
import signal
import sys
from pathlib import Path

import structlog

from televibecode import __version__
from televibecode.config import load_settings
from televibecode.db import Database
from televibecode.orchestrator import create_mcp_server
from televibecode.telegram import create_bot


def configure_logging(level: str) -> None:
    """Configure structlog for the application."""
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
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger()


async def serve(root: Path) -> None:
    """Run the TeleVibeCode server.

    Args:
        root: Projects root directory.
    """
    # Load settings
    settings = load_settings(root)
    settings.ensure_dirs()

    configure_logging(settings.log_level)

    log.info(
        "televibecode_starting",
        version=__version__,
        root=str(settings.televibe_root),
        db_path=str(settings.db_path),
    )

    # Initialize database
    db = Database(settings.db_path)
    await db.connect()
    log.info("database_connected", path=str(settings.db_path))

    # Create MCP server (stored for future use in Phase 2+)
    _ = create_mcp_server(db, settings.televibe_root)
    log.info("mcp_server_created")

    # Create and start Telegram bot
    bot = create_bot(settings, db)
    await bot.setup()

    # Set up graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler():
        log.info("shutdown_signal_received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Start bot polling
    log.info("starting_telegram_bot")
    assert bot.app is not None, "Bot application not initialized"
    await bot.app.initialize()
    await bot.app.start()
    await bot.set_commands_menu()
    assert bot.app.updater is not None, "Bot updater not initialized"
    await bot.app.updater.start_polling(drop_pending_updates=True)

    log.info(
        "televibecode_running",
        message="TeleVibeCode is running. Press Ctrl+C to stop.",
    )

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

    args = parser.parse_args()

    if args.command == "serve":
        asyncio.run(serve(args.root))
    elif args.command == "scan":
        asyncio.run(scan_only(args.root))
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


if __name__ == "__main__":
    main()
