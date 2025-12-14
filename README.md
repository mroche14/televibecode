# TeleVibeCode

<p align="center">
  <img src="docs/hero.png" alt="TeleVibeCode - Command your AI coding swarm from anywhere" width="800">
</p>

**Control Claude Code sessions from your phone via Telegram.** Run coding tasks, monitor progress, and approve changes—all while away from your desk.

## What It Does

TeleVibeCode lets you:

1. **Start coding sessions** on any of your git repositories
2. **Send instructions** to Claude Code ("add login validation", "fix the failing tests")
3. **Monitor progress** with live updates as Claude works
4. **Approve dangerous operations** before they execute (git push, file deletions, shell commands)
5. **Manage multiple sessions** across different projects simultaneously

Each session runs in an isolated git worktree, so parallel work on the same repo is safe.

## Example Interaction

```
You:  /projects
Bot:  📂 my-webapp (3 sessions)
      📂 my-api (1 session)
      📂 shared-lib (idle)

You:  /new my-webapp feature/auth
Bot:  ✅ Created session S12 on my-webapp
      🌿 Branch: feature/auth
      📁 Workspace: ~/.televibe/workspaces/my-webapp/S12/

You:  /run Add email validation to the signup form
Bot:  🔧 Running... [████████░░░░░░░░░░░░]
      ⏱️ 12s
      🔨 Edit
      📝 2 files

Bot:  ✅ Done
      Modified: src/components/SignupForm.tsx, src/utils/validation.ts
      Added email format validation with error messages

You:  /run Push the changes
Bot:  ⚠️ Approval Required
      ⬆️ Type: Git Push
      📂 Session: S12
      🔹 Action: git push origin feature/auth

      [✅ Approve] [❌ Deny]
```

## How It Works

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Telegram   │────▶│   TeleVibeCode  │────▶│   Claude Code   │
│  (your phone)     │   (orchestrator)│     │   (in worktree) │
└─────────────┘     └─────────────────┘     └─────────────────┘
                            │
                    ┌───────┴───────┐
                    │   SQLite DB   │
                    │ (state, jobs) │
                    └───────────────┘
```

TeleVibeCode runs as a server on your dev machine (or a VPS). It:
- Receives commands from Telegram
- Manages git worktrees for session isolation
- Spawns Claude Code processes with your instructions
- Streams progress back to Telegram
- Gates dangerous operations behind approval buttons

## Quick Start

### 1. Get a Telegram Bot Token

1. Open Telegram, search for `@BotFather`
2. Send `/newbot` and follow the prompts
3. Copy the token (looks like `7123456789:AAH...`)

### 2. Get an AI API Key (for intent classification)

The bot uses a lightweight LLM for understanding natural language. Free options:

- **Gemini** (recommended): https://aistudio.google.com/apikey
- **OpenRouter**: https://openrouter.ai (free models available)
- **Groq**: https://console.groq.com/keys (ultra-fast inference + voice transcription)
- **Cerebras**: https://cloud.cerebras.ai (fastest inference available)

> **OpenRouter Free Models**: To use free models on OpenRouter, you must enable data sharing in your [privacy settings](https://openrouter.ai/settings/privacy):
> - Enable "Free endpoints that may train on inputs" - allows providers to use prompts for training
> - Enable "Free endpoints that may publish prompts" - allows prompts to be published to public datasets
>
> Without these settings, free model requests will fail with a 404 error.

### 3. Install and Run

```bash
# Install
uv tool install televibecode
# or: pip install televibecode

# Create .env in your projects directory
cat > ~/projects/.env << 'EOF'
TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_ALLOWED_CHAT_IDS=YOUR_CHAT_ID_HERE
# AI providers (set at least one)
GEMINI_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxx
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
CEREBRAS_API_KEY=csk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
EOF

# Run (points at your existing projects folder)
televibecode serve --root ~/projects
```

### 4. Start Chatting

Open your bot in Telegram and send `/help`.

## Directory Layout

TeleVibeCode creates a `.televibe/` folder in your projects root. Your repositories stay untouched:

```
~/projects/                     # Your existing projects folder
├── .televibe/                  # TeleVibeCode data (auto-created)
│   ├── state.db               # Sessions, jobs, approvals
│   ├── logs/                  # Job execution logs
│   └── workspaces/            # Git worktrees per session
│       └── my-webapp/S12/     # Session S12's isolated workspace
├── my-webapp/                  # Your repos (unchanged)
├── my-api/
└── shared-lib/
```

## Telegram Commands

### Projects & Sessions
| Command | Description |
|---------|-------------|
| `/projects` | List registered git repositories |
| `/scan` | Scan for new repositories in root |
| `/sessions` | List all active sessions |
| `/new <project> [branch]` | Create session with optional branch |
| `/use <session>` | Set session as active (for subsequent commands) |
| `/close [session]` | Close a session |

### Running Instructions
| Command | Description |
|---------|-------------|
| `/run <instruction>` | Execute instruction in active session |
| `/status` | Current session/job status |
| `/jobs [session]` | List recent jobs |
| `/tail [job]` | View job logs |
| `/cancel` | Cancel running job |

### Tasks & Approvals
| Command | Description |
|---------|-------------|
| `/tasks [project]` | List backlog tasks |
| `/claim <task>` | Assign task to current session |
| `/sync` | Sync tasks from Backlog.md files |
| `/approvals` | List pending approval requests |

### Other
| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/settings` | View/change notification settings |

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from @BotFather |
| `TELEGRAM_ALLOWED_CHAT_IDS` | **Recommended** | Comma-separated chat IDs (see Security) |
| `GEMINI_API_KEY` | No* | Google Gemini API key |
| `OPENROUTER_API_KEY` | No* | OpenRouter API key (access to many free models) |
| `GROQ_API_KEY` | No* | Groq API key (fast inference + voice transcription) |
| `CEREBRAS_API_KEY` | No* | Cerebras API key (fastest inference) |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `MAX_CONCURRENT_JOBS` | No | Default: 3 |
| `EXECUTOR_TYPE` | No | `subprocess` (default) or `sdk` |

*Set at least one AI provider key for natural language support. Use `/models` in Telegram to see available models and `/model <id>` to switch.

**AI Providers Overview:**

| Provider | Speed | Free Tier | Best For |
|----------|-------|-----------|----------|
| Gemini | Fast | 1M tokens/day | General use, long context |
| OpenRouter | Varies | Many free models | Model variety |
| Groq | Ultra-fast | 250K tokens/min | Speed, voice transcription |
| Cerebras | Fastest | Free tier available | Maximum speed |

### Executor Types

TeleVibeCode supports two executor backends:

**Subprocess (default):** Spawns `claude -p <instruction>` as a subprocess. Simple and reliable.

**SDK:** Uses the official [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) for native Python integration. Requires additional install:

```bash
pip install televibecode[sdk]
# or: uv add televibecode[sdk]
```

Then set in `.env`:
```bash
EXECUTOR_TYPE=sdk
```

SDK benefits:
- Native Python hooks for approval gating
- Clean interrupt support (`client.interrupt()`)
- Structured message types (no JSON parsing)
- Session continuity for follow-up instructions

### Security

**Important**: By default, anyone who discovers your bot can use it. This is dangerous since the bot can execute code on your machine.

**Restrict access by chat ID:**

1. Start the bot without `TELEGRAM_ALLOWED_CHAT_IDS` (you'll see a security warning)
2. Send any message to your bot - it will reply with your chat ID
3. Add the chat ID to your `.env`:

```bash
TELEGRAM_ALLOWED_CHAT_IDS=8581681908
```

For multiple users, use comma-separated IDs:
```bash
TELEGRAM_ALLOWED_CHAT_IDS=8581681908,123456789
```

**Finding your chat ID:**
- From Telegram Web: The number in the URL (`https://web.telegram.org/a/#8581681908`)
- From the bot: Send any message when unconfigured - it shows your ID in the error

Unauthorized users see: "Access denied. Your chat ID: `XXXXX`"

### Load Order

1. `.env` file in `--root` directory
2. `.env` file in `--root/.televibe/`
3. Environment variables
4. CLI flags

## Current Status

**Implemented (Phases 1-5):**
- Project and session management
- Job execution with progress streaming
- Telegram bot with all core commands
- Approval workflow for gated operations
- SQLite persistence
- Backlog.md task parsing
- Natural language intent classification

**Coming Soon (Phase 6):**
- Multi-agent coordination via SuperClaude
- Session handoffs
- Team/shared access patterns

## Development

```bash
git clone https://github.com/mroche14/televibecode
cd televibecode
uv sync

# Run tests
uv run pytest

# Lint & type check
uv run ruff check .
uv run mypy src/

# Run locally
uv run televibecode serve --root /path/to/test/projects
```

## Requirements

- Python 3.12+
- Claude Code CLI installed and authenticated
- Telegram account

## License

MIT
