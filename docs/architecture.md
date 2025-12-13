# TeleVibeCode Architecture

## Overview

TeleVibeCode is a remote orchestration harness for managing multiple Claude Code + SuperClaude sessions via Telegram. It enables "virtual coders" - parallel AI coding sessions that can be controlled, monitored, and coordinated from mobile.

## Core Principle

**Telegram only talks to the Orchestrator MCP.**

```
Telegram Bot ↔ Orchestrator MCP ↔ Sessions / Repos / Tasks / Claude Code + SuperClaude
```

The Orchestrator is:
- The **source of truth** for projects, sessions, tasks, and jobs
- The **only API surface** that Telegram (and other clients) interact with
- **Installed separately**, pointed at a projects root directory at runtime

## Layer Architecture

### Layer 0: Core Tools

| Component | Role |
|-----------|------|
| **Claude Code CLI** | AI coding agent using Anthropic subscription |
| **SuperClaude Framework** | Meta-config layer with 20+ slash commands, 10-20 specialized agents, behavioral modes, MCP integrations |

SuperClaude provides:
- Behavioral instruction injection & component orchestration
- Specialized role agents (reviewer, architect, refactorer, QA, etc.)
- Behavioral modes (planning, editing, review, introspection)
- MCP integrations (docs, browser, etc.)

### Layer 1: Remote Harness

#### Components

| Component | Responsibility |
|-----------|---------------|
| **Telegram Bot** | User interface - commands, cards, approvals, notifications |
| **Orchestrator MCP** | Central brain - manages projects, sessions, tasks, jobs |
| **Session Manager** | Workspace lifecycle - git worktrees, Claude processes |
| **Runner** | Job execution - Claude Code + SuperClaude in job mode |
| **Middle AI Layer** | Intent normalization, routing, policy enforcement |

#### Data Flow

```
User (Telegram)
    │
    ▼
Telegram Bot ──────────────────────────────────────┐
    │                                               │
    ▼                                               │
Middle AI Layer (optional)                          │
    │ - Intent normalization                        │
    │ - Session routing                             │
    │ - Policy injection                            │
    ▼                                               │
Orchestrator MCP ◄──────────────────────────────────┘
    │
    ├─► Project Registry (repos/)
    ├─► Session Registry (workspaces/)
    ├─► Task Store (Backlog.md per repo)
    └─► Job Queue
            │
            ▼
        Runner
            │
            ▼
    Claude Code + SuperClaude
        (in workspace)
```

### Layer 2: Task/Project Management

**Primary**: Backlog.md per repository
- `/backlog/*.md` files with YAML front-matter
- Terminal Kanban + web UI
- Built-in MCP server for AI integration

**Integration**:
- Sessions reference `backlog_task_ids[]`
- Jobs update task status automatically
- Middle AI can suggest next tasks

### Layer 3: Multi-Agent Orchestration

SuperClaude Framework acts as the orchestration brain:
- Defines roles/personas per session
- Provides behavioral modes
- Offers slash commands for workflows

Harness sends prompts like:
```
/sc:implement Implement task T-123 as per spec, don't push, summarize diff at end.
/sc:analyze Review current branch vs main, comment on risks, do not change code.
```

## Deployment Model

TeleVibeCode is a **server/tool** installed separately from the projects it manages.

### Installation

```bash
# Install TeleVibeCode (the tool)
uv tool install televibecode
# or: pip install televibecode

# Run it, pointed at your projects directory
televibecode serve --root ~/projects
```

### Projects Root Layout

The `--root` directory is where your repositories live. TeleVibeCode creates a `.televibe/` folder for its runtime state:

```
~/projects/                     # Your projects root (--root)
├── .televibe/                  # TeleVibeCode runtime artifacts
│   ├── state.db               # SQLite: projects, sessions, tasks, jobs
│   ├── config.yaml            # Server configuration
│   └── logs/                  # Job execution logs
│       └── jobs/
├── repos/                      # Your git repositories
│   ├── my-web-app/
│   │   ├── .git/
│   │   └── backlog/           # Backlog.md tasks
│   ├── my-api/
│   └── my-library/
└── workspaces/                 # Git worktrees for active sessions
    ├── my-web-app/
    │   └── S12/
    │       └── feature-auth/   # Worktree for session S12
    └── my-api/
        └── S7/
            └── refactor-endpoints/
```

### Key Separation

| Concern | Location |
|---------|----------|
| TeleVibeCode code | Installed via pip/uv (e.g., `~/.local/bin/televibecode`) |
| TeleVibeCode state | `<projects-root>/.televibe/` |
| User repositories | `<projects-root>/repos/` |
| Session workspaces | `<projects-root>/workspaces/` |

## Message Tagging Convention

All bot messages include context tags:

```
📂 [project-a] 🔹 [S12] 🌿 feature-x
```

Job updates:
```
🔧 S12 (project-a/feature-x): Running "implement T-123"
✅ S12 (project-a/feature-x): Completed - 3 files changed
⚠️ S12 (project-a/feature-x): Approval needed for git push
```

## Session Lifecycle

1. **Creation**: User requests new session on project + branch
2. **Worktree Setup**: Git worktree created in `/workspaces/<project>/<session>/<branch>/`
3. **Configuration**: SuperClaude profile + MCP servers configured
4. **Execution**: Jobs run via Runner in workspace directory
5. **Monitoring**: Status, logs, summaries streamed to Telegram
6. **Closure**: Worktree cleaned up, session archived

## Approval Gating

High-impact actions require explicit approval:
- File writes (configurable)
- Shell command execution
- Git push / PR creation
- Deployments

Approvals flow through Telegram with inline buttons.
