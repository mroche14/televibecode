# TeleVibeCode

<p align="center">
  <img src="docs/hero.png" alt="TeleVibeCode - Command your AI coding swarm from anywhere" width="800">
</p>

Remote orchestration harness for managing multiple Claude Code + SuperClaude sessions via Telegram.

## Overview

TeleVibeCode enables "virtual coders" - parallel AI coding sessions that can be controlled, monitored, and coordinated from your mobile device.

**Core Principle**: Telegram only talks to the Orchestrator MCP.

```
Telegram Bot ↔ Orchestrator MCP ↔ Sessions / Repos / Tasks / Claude Code + SuperClaude
```

## Architecture

| Layer | Components |
|-------|------------|
| **Layer 0** | Claude Code CLI + SuperClaude Framework |
| **Layer 1** | Orchestrator MCP + Telegram Bot + Runner |
| **Layer 2** | Backlog.md task management per repo |
| **Layer 3** | Multi-agent orchestration via SuperClaude |

## Features

- **Multi-Project Management**: Manage multiple repositories from a central location
- **Session Isolation**: Each session runs in its own git worktree
- **Task Integration**: Backlog.md integration for in-repo task tracking
- **Remote Control**: Run instructions, view logs, approve actions via Telegram
- **Approval Gating**: Require approval for sensitive operations (push, deploy)

## Installation & Usage

```bash
# Install TeleVibeCode
uv tool install televibecode
# or: pip install televibecode

# Run the server, pointed at your projects directory
televibecode serve --root ~/projects

# Or with explicit config
televibecode serve --root ~/projects --config ~/projects/.televibe/config.yaml
```

## Configuration

### Required Environment Variables

```bash
# Telegram Bot Token (required)
# Create a bot via @BotFather on Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here

# AI API Key for intermediate intelligence layer (required)
# Used for natural language parsing and intent detection
AGNO_API_KEY=your_api_key_here
AGNO_PROVIDER=gemini  # gemini | anthropic | openai | openrouter
```

### Free API Options

**Gemini (Recommended)**
- Free API key at: https://aistudio.google.com/apikey
- Generous free tier (15 RPM for Gemini 1.5 Flash)
- Set `AGNO_PROVIDER=gemini`

**OpenRouter**
- Sign up at: https://openrouter.ai
- Free models: `grok-beta`, `mistral-7b-instruct`
- Set `AGNO_PROVIDER=openrouter` and `AGNO_MODEL=grok-beta`

### Example .env

```bash
TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
AGNO_PROVIDER=gemini
AGNO_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Startup Checks

If required variables are missing, the server will prompt or exit with helpful messages:

```
Missing required environment variable: TELEGRAM_BOT_TOKEN
Get your token from @BotFather on Telegram.

Missing required environment variable: AGNO_API_KEY
Set AGNO_PROVIDER and AGNO_API_KEY. Free option: Gemini at https://aistudio.google.com/apikey
```

**Load order**: `.env` file in `--root` directory → environment variables → CLI flags

## Projects Root Layout

Point TeleVibeCode at your **existing projects folder**. No restructuring needed:

```
~/projects/                     # Your existing projects folder
├── .televibe/                  # TeleVibeCode artifacts (auto-created)
│   ├── state.db
│   ├── config.yaml
│   ├── logs/
│   └── workspaces/             # Session worktrees
│       └── my-web-app/S12/feature-auth/
├── my-web-app/                 # Your repos stay where they are
├── my-api/
└── my-library/
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/projects` | List all registered projects |
| `/sessions` | List active sessions |
| `/new <project> [branch]` | Create new session |
| `/use <session>` | Set active session |
| `/run <instruction>` | Run instruction in session |
| `/status` | Get current job status |
| `/tasks <project>` | List project tasks |
| `/approvals` | List pending approvals |

## Documentation

### Core Specs
- [Architecture](docs/architecture.md) - High-level system design
- [Data Models](docs/data-models.md) - Entity schemas and SQLite DDL
- [Orchestrator MCP](docs/orchestrator-mcp.md) - MCP tool specifications
- [Telegram Bot](docs/telegram-bot.md) - Commands and UX patterns

### Deep Dives
- [Runner Integration](docs/runner-integration.md) - Claude Code execution, hooks, permissions
- [Multi-Session Coordination](docs/multi-session.md) - Session handoffs, team patterns
- [Event Streaming](docs/event-streaming.md) - Real-time updates, log streaming

### Requirements & Operations
- [Requirements](docs/requirements.md) - NFRs, acceptance criteria, behavior scenarios
- [Operations](docs/operations.md) - Failure modes, circuit breakers, monitoring, runbooks
- [Spec Review](docs/spec-review.md) - Expert panel analysis and recommendations

### Planning
- [Implementation Roadmap](docs/roadmap.md) - Phased development plan
- [Implementation Workflow](docs/workflow.md) - Step-by-step task breakdown
- [Technology Reference](docs/technology-reference.md) - Implementation patterns for all dependencies

## Development

```bash
# Clone and install dependencies
git clone https://github.com/mroche14/televibecode
cd televibecode
uv sync

# Run in development mode
uv run televibecode serve --root /path/to/test/projects

# Run tests
uv run pytest

# Lint
uv run ruff check .
```

## License

MIT
