#!/usr/bin/env python3
"""TeleVibeCode Supervisor.

A simple, robust supervisor that:
1. Starts and monitors TeleVibeCode
2. Handles restart requests
3. Self-heals with Claude Code on failure

This script has minimal dependencies and survives code changes.
Run with: python -m televibecode.supervisor
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Configuration
TELEVIBE_DIR = Path.home() / ".televibe"
STATE_FILE = TELEVIBE_DIR / "restart_state.json"
HEALTH_FILE = TELEVIBE_DIR / "health.flag"
HEALED_FILE = TELEVIBE_DIR / "healed.flag"
ERROR_LOG = TELEVIBE_DIR / "crash.log"

HEALTH_TIMEOUT = 45  # seconds to wait for healthy restart
MAX_HEAL_ATTEMPTS = 3
HEAL_TIMEOUT = 300  # 5 minutes max for Claude to fix

# Get bot token from environment for notifications
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.environ.get("TELEVIBE_ADMIN_CHAT", "")


def log(message: str) -> None:
    """Simple logging to stdout with timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [supervisor] {message}", flush=True)


def notify_telegram(message: str, chat_id: str | None = None) -> bool:
    """Send notification via Telegram API using curl (no Python deps)."""
    if not BOT_TOKEN:
        log("No BOT_TOKEN, skipping Telegram notification")
        return False

    target_chat = chat_id or ADMIN_CHAT_ID
    if not target_chat:
        log("No chat ID for notification")
        return False

    try:
        result = subprocess.run(
            [
                "curl",
                "-s",
                "-X",
                "POST",
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                "-d",
                f"chat_id={target_chat}",
                "-d",
                f"text={message}",
                "-d",
                "parse_mode=Markdown",
            ],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception as e:
        log(f"Failed to send Telegram notification: {e}")
        return False


def edit_telegram_message(chat_id: str, message_id: int, text: str) -> bool:
    """Edit a Telegram message."""
    if not BOT_TOKEN:
        return False

    try:
        result = subprocess.run(
            [
                "curl",
                "-s",
                "-X",
                "POST",
                f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText",
                "-d",
                f"chat_id={chat_id}",
                "-d",
                f"message_id={message_id}",
                "-d",
                f"text={text}",
                "-d",
                "parse_mode=Markdown",
            ],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def get_git_commit() -> str:
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def load_state() -> dict:
    """Load restart state from file."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    """Save restart state to file."""
    TELEVIBE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def clear_state() -> None:
    """Clear restart state."""
    STATE_FILE.unlink(missing_ok=True)
    HEALTH_FILE.unlink(missing_ok=True)
    HEALED_FILE.unlink(missing_ok=True)


def run_televibecode(root: Path) -> subprocess.Popen:
    """Start the TeleVibeCode process.

    Args:
        root: Projects root directory.
    """
    log(f"Starting TeleVibeCode with root: {root}")

    # Clear health flag
    HEALTH_FILE.unlink(missing_ok=True)

    # Load .env file to get environment variables
    from dotenv import load_dotenv

    env_file = root / ".env"
    if not env_file.exists():
        env_file = root / ".televibe" / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        log(f"Loaded env from: {env_file}")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"  # Disable buffering for immediate output
    project_dir = Path(__file__).parent.parent.parent

    # Use uv run if available, otherwise try direct command
    import shutil

    if shutil.which("uv"):
        cmd = ["uv", "run", "televibecode", "serve", "--root", str(root)]
    else:
        cmd = ["televibecode", "serve", "--root", str(root)]

    # Use PIPE to capture output, but we'll stream it to console in main_loop
    return subprocess.Popen(
        cmd,
        stderr=subprocess.STDOUT,  # Merge stderr into stdout
        stdout=subprocess.PIPE,
        text=True,
        env=env,
        cwd=project_dir,
    )


def check_health(proc: subprocess.Popen) -> bool:
    """Check if TeleVibeCode is healthy."""
    # Process must be running
    if proc.poll() is not None:
        return False

    # Check for health flag (TeleVibeCode writes this on successful startup)
    return HEALTH_FILE.exists()


def spawn_claude_healer(error_log: str, state: dict) -> tuple[bool, str]:
    """Spawn Claude Code to fix the issue.

    Returns:
        Tuple of (success, conclusion_message)
    """
    attempt = state.get("attempt", 1)
    last_commit = state.get("last_working_commit", "unknown")

    log(f"Spawning Claude Code healer (attempt {attempt})...")

    # Get previous crash log for context (if exists from prior attempts)
    previous_log = ""
    if ERROR_LOG.exists():
        try:
            lines = ERROR_LOG.read_text().splitlines()
            previous_log = "\n".join(lines[-50:])  # Last 50 lines
        except Exception:
            pass

    instruction = f"""# TeleVibeCode Self-Healing Task

TeleVibeCode failed to start. You need to fix it.

## Current Error
```
{error_log[-3000:]}
```

## Previous Log Context (last 50 lines)
```
{previous_log[-2000:] if previous_log else "(No previous log)"}
```

## Context
- Last working commit: {last_commit}
- Current commit: {get_git_commit()}
- Heal attempt: {attempt} of {MAX_HEAL_ATTEMPTS}
- Project path: {Path(__file__).parent.parent.parent}

## Your Task
1. Analyze the error carefully
2. Find and fix the bug in the code
3. Make the MINIMAL change needed to fix the startup error
4. After fixing, create this file to signal success:
   touch ~/.televibe/healed.flag
5. Write a brief summary of what you fixed to:
   ~/.televibe/heal_summary.txt

## Rules
- DO NOT make unrelated changes
- DO NOT refactor or improve code
- ONLY fix what's broken
- If you can't fix it, still create healed.flag and also
  ~/.televibe/heal_failed.txt with explanation

Focus on making TeleVibeCode start successfully.
"""

    summary_file = TELEVIBE_DIR / "heal_summary.txt"
    summary_file.unlink(missing_ok=True)

    try:
        result = subprocess.run(
            [
                "claude",
                "--dangerously-skip-permissions",
                "-p",
                instruction,
            ],
            capture_output=True,
            text=True,
            timeout=HEAL_TIMEOUT,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Try to get summary from file first
        conclusion = ""
        if summary_file.exists():
            conclusion = summary_file.read_text().strip()
        elif result.stdout:
            # Fall back to last part of stdout
            lines = result.stdout.strip().split("\n")
            # Get last non-empty lines as summary
            conclusion = "\n".join(lines[-5:]) if lines else ""

        return result.returncode == 0, conclusion

    except subprocess.TimeoutExpired:
        log("Claude healer timed out")
        return False, "Healer timed out"
    except FileNotFoundError:
        log("Claude CLI not found")
        return False, "Claude CLI not found"
    except Exception as e:
        log(f"Failed to spawn Claude healer: {e}")
        return False, f"Error: {e}"


def main_loop(root: Path):
    """Main supervisor loop.

    Args:
        root: Projects root directory.
    """
    # Load .env early for BOT_TOKEN (needed for notifications)
    from dotenv import load_dotenv

    # Look for .env in multiple locations
    project_dir = Path(__file__).parent.parent.parent
    possible_env_files = [
        root / ".env",
        root / ".televibe" / ".env",
        project_dir / ".env",  # televibecode project dir
    ]

    env_loaded = False
    for env_file in possible_env_files:
        if env_file.exists():
            load_dotenv(env_file)
            log(f"Loaded .env from: {env_file}")
            env_loaded = True
            break

    if not env_loaded:
        log(f"Warning: No .env found. Checked: {[str(p) for p in possible_env_files]}")

    # Update global BOT_TOKEN after loading .env
    global BOT_TOKEN, ADMIN_CHAT_ID
    BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    ADMIN_CHAT_ID = os.environ.get("TELEVIBE_ADMIN_CHAT", "")

    log("TeleVibeCode Supervisor starting...")

    # Ensure directory exists
    TELEVIBE_DIR.mkdir(parents=True, exist_ok=True)

    # Track last known working commit
    last_working_commit = get_git_commit()

    while True:
        state = load_state()
        current_commit = get_git_commit()

        # Start the process
        proc = run_televibecode(root)
        output_lines: list[str] = []

        # Stream output while waiting for health or failure
        import select

        start_time = time.time()
        healthy = False

        while time.time() - start_time < HEALTH_TIMEOUT:
            # Check if process exited
            if proc.poll() is not None:
                # Read remaining output
                if proc.stdout:
                    for line in proc.stdout:
                        print(line, end="", flush=True)
                        output_lines.append(line)
                log(f"Process exited with code {proc.returncode}")
                break

            # Read available output (non-blocking)
            if proc.stdout:
                ready, _, _ = select.select([proc.stdout], [], [], 0.5)
                if ready:
                    line = proc.stdout.readline()
                    if line:
                        print(line, end="", flush=True)
                        output_lines.append(line)

            if check_health(proc):
                healthy = True
                log("Health check passed!")
                break

        if healthy:
            # Success! Update state
            last_working_commit = current_commit
            attempt = state.get("attempt", 0)

            # Notify if this was a restart
            if state.get("notify_chats"):
                for chat_id in state["notify_chats"]:
                    msg_id = state.get("notify_message_ids", {}).get(str(chat_id))
                    msg = f"✅ TeleVibeCode restarted! (commit: `{current_commit}`)"
                    if msg_id:
                        edit_telegram_message(str(chat_id), msg_id, msg)
                    else:
                        notify_telegram(msg, str(chat_id))

            if attempt > 0:
                msg = f"✅ Self-healing succeeded after {attempt} attempt(s)!"
                notify_telegram(msg)

            clear_state()

            # Wait for process to exit (stream output)
            log("TeleVibeCode running normally. Waiting for exit...")
            if proc.stdout:
                for line in proc.stdout:
                    print(line, end="", flush=True)
            proc.wait()

            # Check if restart was requested
            if STATE_FILE.exists():
                log("Restart requested, cycling...")
                continue
            else:
                log("Clean exit, stopping supervisor")
                break

        # Failed to start - use captured output for healing
        error_output = "".join(output_lines) if output_lines else "(No output captured)"

        # Save error log
        ERROR_LOG.write_text(error_output)

        attempt = state.get("attempt", 0) + 1
        log(f"Startup failed. Attempt {attempt} of {MAX_HEAL_ATTEMPTS}")

        if attempt > MAX_HEAL_ATTEMPTS:
            log("Max heal attempts reached. Manual intervention required.")
            msg = (
                f"❌ Failed to heal after {MAX_HEAL_ATTEMPTS} attempts.\n\n"
                f"Manual intervention required.\n"
                f"Check ~/.televibe/crash.log for details."
            )
            for chat_id in state.get("notify_chats", []):
                notify_telegram(msg, str(chat_id))
            break

        # Update state
        state["attempt"] = attempt
        state["last_working_commit"] = last_working_commit
        state["error_commit"] = current_commit
        save_state(state)

        # Notify about healing attempt (to user who triggered restart)
        msg = (
            f"🔧 Failed to start (attempt {attempt}/{MAX_HEAL_ATTEMPTS}).\n"
            f"Spawning Claude Code to fix..."
        )
        for chat_id in state.get("notify_chats", []):
            notify_telegram(msg, str(chat_id))

        # Spawn healer
        HEALED_FILE.unlink(missing_ok=True)
        success, conclusion = spawn_claude_healer(error_output, state)

        # Check if Claude signaled completion
        if HEALED_FILE.exists():
            HEALED_FILE.unlink()
            log("Claude healer completed, retrying...")
            # Send conclusion to user
            summary = conclusion[:500] if conclusion else "Fix applied"
            msg = f"🔧 *Claude applied a fix:*\n\n{summary}\n\n_Retrying..._"
            for chat_id in state.get("notify_chats", []):
                notify_telegram(msg, str(chat_id))
        else:
            log("Claude healer did not signal completion, retrying anyway...")
            details = conclusion[:300] if conclusion else "No details"
            msg = f"⚠️ Claude healing unclear.\n\n{details}\n\n_Retrying..._"
            for chat_id in state.get("notify_chats", []):
                notify_telegram(msg, str(chat_id))

        # Small delay before retry
        time.sleep(2)


def handle_signal(signum, frame):
    """Handle shutdown signals gracefully."""
    log(f"Received signal {signum}, shutting down...")
    clear_state()
    sys.exit(0)


def main(root: Path | None = None):
    """Entry point.

    Args:
        root: Projects root directory. Defaults to ~/projects.
    """
    if root is None:
        root = Path.home() / "projects"

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        main_loop(root)
    except KeyboardInterrupt:
        log("Interrupted")
    except Exception as e:
        log(f"Supervisor error: {e}")
        notify_telegram(f"❌ Supervisor crashed: {e}")
        raise


if __name__ == "__main__":
    main()
