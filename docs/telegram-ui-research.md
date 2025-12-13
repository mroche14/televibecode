# Telegram Bot API - Interactive UI Research

This document covers all interactive UI components, features, and patterns available in the Telegram Bot API that can enhance TeleVibeCode's user experience.

## Table of Contents

1. [Inline Keyboards & Callback Buttons](#1-inline-keyboards--callback-buttons)
2. [Reply Keyboards](#2-reply-keyboards)
3. [Reply-To Message Handling](#3-reply-to-message-handling)
4. [Message Editing & Live Updates](#4-message-editing--live-updates)
5. [Menu Buttons & Commands](#5-menu-buttons--commands)
6. [Typing & Chat Actions](#6-typing--chat-actions)
7. [Polls & Quizzes](#7-polls--quizzes)
8. [Media Groups & Albums](#8-media-groups--albums)
9. [Reactions](#9-reactions)
10. [Mini Apps / WebApps](#10-mini-apps--webapps)
11. [ForceReply & Input Placeholders](#11-forcereply--input-placeholders)
12. [Implementation Recommendations for TeleVibeCode](#12-implementation-recommendations-for-televibecode)

---

## 1. Inline Keyboards & Callback Buttons

Inline keyboards are attached to messages and allow users to interact without sending new messages.

### Button Types

| Type | Description | Use Case |
|------|-------------|----------|
| `callback_data` | Sends data back to bot | Approvals, toggles, selections |
| `url` | Opens a URL | Documentation links, PRs |
| `switch_inline_query` | Switches to inline mode | Search across chats |
| `copy_text` | Copies text to clipboard | Copy commands, IDs |
| `web_app` | Opens a Mini App | Complex UIs |

### Python Implementation

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

keyboard = [
    [
        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{job_id}"),
        InlineKeyboardButton("❌ Deny", callback_data=f"deny:{job_id}"),
    ],
    [
        InlineKeyboardButton("📋 View Logs", callback_data=f"logs:{job_id}"),
        InlineKeyboardButton("🔗 Open PR", url=pr_url),
    ],
]
reply_markup = InlineKeyboardMarkup(keyboard)

await update.message.reply_text(
    "⚠️ Approval needed for `git push`",
    reply_markup=reply_markup,
    parse_mode="Markdown"
)
```

### Callback Query Handling

```python
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # REQUIRED - stops loading animation

    action, job_id = query.data.split(":")

    if action == "approve":
        # Process approval
        await query.edit_message_text("✅ Approved!")
    elif action == "deny":
        await query.edit_message_text("❌ Denied.")
```

### Multi-Selection Pattern

```python
# Track selected options in user_data
selected = context.user_data.get("selected", set())

if item_id in selected:
    selected.remove(item_id)
    icon = "⬜"
else:
    selected.add(item_id)
    icon = "✅"

# Update keyboard with new icons
await query.edit_message_reply_markup(new_keyboard)
```

**Sources:**
- [Telegram Buttons Documentation](https://core.telegram.org/api/bots/buttons)
- [InlineKeyboardButton - python-telegram-bot](https://docs.python-telegram-bot.org/en/v21.5/telegram.inlinekeyboardbutton.html)
- [Multi-selection Keyboards Guide](https://medium.com/@moraneus/enhancing-user-engagement-with-multiselection-inline-keyboards-in-telegram-bots-7cea9a371b8d)

---

## 2. Reply Keyboards

Custom keyboards that replace the standard keyboard.

### Key Parameters

| Parameter | Description |
|-----------|-------------|
| `resize_keyboard` | Fit keyboard to content height |
| `one_time_keyboard` | Hide after use |
| `is_persistent` | Always show (even when hidden) |
| `input_field_placeholder` | Placeholder text (1-64 chars) |
| `selective` | Show only to specific users |

### Python Implementation

```python
from telegram import ReplyKeyboardMarkup, KeyboardButton

keyboard = [
    [KeyboardButton("📂 Projects"), KeyboardButton("🔹 Sessions")],
    [KeyboardButton("📋 Tasks"), KeyboardButton("⚙️ Settings")],
]

reply_markup = ReplyKeyboardMarkup(
    keyboard,
    resize_keyboard=True,
    input_field_placeholder="Choose an option...",
)

await update.message.reply_text("Main Menu:", reply_markup=reply_markup)
```

### Special Button Types

```python
# Request phone number
KeyboardButton("📱 Share Phone", request_contact=True)

# Request location
KeyboardButton("📍 Share Location", request_location=True)

# Request poll
KeyboardButton("📊 Create Poll", request_poll=KeyboardButtonPollType())
```

**Sources:**
- [ReplyKeyboardMarkup - python-telegram-bot](https://docs.python-telegram-bot.org/en/stable/telegram.replykeyboardmarkup.html)

---

## 3. Reply-To Message Handling

**Critical for TeleVibeCode**: Smart message context tracking.

### How reply_to_message Works

When a user replies to a message, the incoming `Update` contains:
- `update.message.reply_to_message` - The original message being replied to
- `update.message.reply_to_message.message_id` - Original message ID
- `update.message.reply_to_message.text` - Original message text

### Threading Model

```
Message ID 420 (original)
├── Reply A (reply_to_message_id: 420, thread_id: 420)
├── Reply B (reply_to_message_id: 420, thread_id: 420)
└── Reply to Reply A (reply_to_message_id: A, thread_id: 420)
```

All replies maintain `thread_id` pointing to the root message.

### Python Pattern for Context Tracking

```python
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    # Check if this is a reply to our bot's message
    if message.reply_to_message and message.reply_to_message.from_user.is_bot:
        original_msg = message.reply_to_message

        # Extract context from original message
        # Option 1: Parse tags from message text
        session_id = extract_session_from_text(original_msg.text)

        # Option 2: Use stored message_id -> session_id mapping
        session_id = context.bot_data.get(f"msg:{original_msg.message_id}")

        if session_id:
            # Route to correct session
            await run_in_session(session_id, message.text)
            return

    # Not a reply - use active session or ask
    active = get_active_session(message.chat_id)
    ...
```

### Storing Message Context

```python
# When sending a message, store its context
sent_msg = await update.message.reply_text(
    f"📂 [project] 🔹 [S12] 🌿 feature-x\n\n{response}"
)

# Store message_id -> session mapping
context.bot_data[f"msg:{sent_msg.message_id}"] = {
    "session_id": "S12",
    "project_id": "project",
    "job_id": job_id,
}
```

### Replying to Specific Messages

```python
# Reply to specific message (maintains visual thread)
await context.bot.send_message(
    chat_id=chat_id,
    text="Job completed!",
    reply_to_message_id=original_message_id,
)

# With reply_parameters (newer API)
from telegram import ReplyParameters

await context.bot.send_message(
    chat_id=chat_id,
    text="Response",
    reply_parameters=ReplyParameters(
        message_id=original_message_id,
        allow_sending_without_reply=True,  # Don't fail if original deleted
    ),
)
```

### TeleVibeCode Reply Strategy

1. **Every bot response includes session context tags**:
   ```
   📂 [my-app] 🔹 [S12] 🌿 feature-auth
   🔧 Running: "implement login form"
   ```

2. **Store message→session mapping**:
   ```python
   # In-memory or database
   message_context = {
       message_id: {
           "session_id": "S12",
           "project_id": "my-app",
           "job_id": "job-123",
           "type": "job_status",
       }
   }
   ```

3. **When user replies to any bot message**:
   ```python
   if reply_to := update.message.reply_to_message:
       ctx = get_message_context(reply_to.message_id)
       if ctx:
           # Route to that session automatically
           session = ctx["session_id"]
           # User can just type "fix the bug" without specifying session
   ```

4. **Even if messages arrived in between**:
   - User replies to a specific message → that message's context is used
   - Works regardless of how many messages came after
   - Visual threading helps user see which message they're replying to

**Sources:**
- [Message Threading - Telegram API](https://core.telegram.org/api/threads)
- [Message Object - python-telegram-bot](https://docs.python-telegram-bot.org/en/v21.9/telegram.message.html)
- [ConversationHandler](https://docs.python-telegram-bot.org/en/v21.8/telegram.ext.conversationhandler.html)

---

## 4. Message Editing & Live Updates

Edit messages in place for progress updates.

### Basic Pattern

```python
# Send initial message
msg = await update.message.reply_text("🔧 Starting job...")

# Update progress
await msg.edit_text("🔧 Running... (25%)")
await asyncio.sleep(2)
await msg.edit_text("🔧 Running... (50%)")
await asyncio.sleep(2)
await msg.edit_text("✅ Complete!")
```

### Edit with Keyboard Updates

```python
# Update both text and keyboard
await query.edit_message_text(
    text="Select options:",
    reply_markup=updated_keyboard,
)
```

### Rate Limiting

- Telegram limits ~30 edits per minute per message
- Recommended: 1-2 second minimum between edits
- For long jobs: update every 5-10 seconds

### Progress Bar Pattern

```python
async def update_progress(msg, current, total):
    filled = int(20 * current / total)
    bar = "█" * filled + "░" * (20 - filled)
    percent = int(100 * current / total)

    await msg.edit_text(
        f"🔧 Processing...\n"
        f"[{bar}] {percent}%"
    )
```

**Sources:**
- [editMessageText - Telegram Bot API](https://core.telegram.org/bots/api#editmessagetext)

---

## 5. Menu Buttons & Commands

### Bot Menu Button Types

| Type | Behavior |
|------|----------|
| `commands` | Shows command list |
| `web_app` | Opens a Mini App |
| `default` | Default behavior |

### Setting Commands

```python
from telegram import BotCommand

commands = [
    BotCommand("projects", "List all projects"),
    BotCommand("sessions", "List active sessions"),
    BotCommand("new", "Create new session"),
    BotCommand("run", "Run instruction"),
    BotCommand("status", "Current job status"),
    BotCommand("help", "Show help"),
]

await app.bot.set_my_commands(commands)
```

### Per-Chat/User Commands

```python
from telegram import BotCommandScopeChat

# Different commands for specific chat
await app.bot.set_my_commands(
    commands=admin_commands,
    scope=BotCommandScopeChat(chat_id=admin_chat_id),
)
```

**Sources:**
- [Bot Menu Button](https://core.telegram.org/api/bots/menu)
- [MenuButton - python-telegram-bot](https://docs.python-telegram-bot.org/en/v21.5/telegram.menubutton.html)

---

## 6. Typing & Chat Actions

Show activity indicators while processing.

### Available Actions

| Action | Use Case |
|--------|----------|
| `typing` | Text response coming |
| `upload_photo` | Sending image |
| `upload_video` | Sending video |
| `upload_document` | Sending file |
| `record_voice` | Recording voice |
| `find_location` | Finding location |

### Usage Pattern

```python
async def long_running_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Show typing for duration of task
    async def keep_typing():
        while True:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action="typing"
            )
            await asyncio.sleep(4)  # Typing lasts ~5 seconds

    typing_task = asyncio.create_task(keep_typing())

    try:
        result = await do_long_task()  # May take 30+ seconds
    finally:
        typing_task.cancel()

    await update.message.reply_text(result)
```

### Callback Loading

```python
# For inline buttons - ALWAYS answer to stop loading animation
await query.answer()  # Required

# With notification
await query.answer("Processing...", show_alert=False)

# With alert popup
await query.answer("Error: Session not found", show_alert=True)
```

**Sources:**
- [sendChatAction - Telegram Bot API](https://core.telegram.org/bots/api#sendchataction)

---

## 7. Polls & Quizzes

Interactive voting and quizzes.

### Regular Poll

```python
await context.bot.send_poll(
    chat_id=chat_id,
    question="Which task should we work on next?",
    options=["T-123: Auth", "T-124: Dashboard", "T-125: API"],
    is_anonymous=False,  # Show who voted
    allows_multiple_answers=True,
)
```

### Quiz Mode

```python
await context.bot.send_poll(
    chat_id=chat_id,
    question="What does `git rebase` do?",
    options=[
        "Merge branches",
        "Reapply commits on top of another base",
        "Delete branches",
        "Create backup",
    ],
    type="quiz",
    correct_option_id=1,
    explanation="Rebase moves commits to a new base commit",
    open_period=30,  # 30 second timer
)
```

**Sources:**
- [Polls 2.0](https://telegram.org/blog/polls-2-0-vmq)
- [Poll - python-telegram-bot](https://docs.python-telegram-bot.org/en/v21.7/telegram.poll.html)

---

## 8. Media Groups & Albums

Send multiple images/videos as album.

```python
from telegram import InputMediaPhoto, InputMediaDocument

# Photo album
await context.bot.send_media_group(
    chat_id=chat_id,
    media=[
        InputMediaPhoto(
            media=open("screenshot1.png", "rb"),
            caption="Before changes"
        ),
        InputMediaPhoto(
            media=open("screenshot2.png", "rb"),
            caption="After changes"
        ),
    ],
)

# Document group
await context.bot.send_media_group(
    chat_id=chat_id,
    media=[
        InputMediaDocument(media=open("report.pdf", "rb")),
        InputMediaDocument(media=open("data.csv", "rb")),
    ],
)
```

**Note**: Albums support 2-10 items. Mixing types is limited.

**Sources:**
- [sendMediaGroup - Telegram Bot API](https://core.telegram.org/bots/api#sendmediagroup)

---

## 9. Reactions

Bots can react to messages with emoji.

```python
from telegram import ReactionTypeEmoji

await context.bot.set_message_reaction(
    chat_id=chat_id,
    message_id=message_id,
    reaction=[ReactionTypeEmoji(emoji="👍")],
)
```

### Available Reactions

Standard emoji reactions: 👍 👎 ❤️ 🔥 🥳 😢 🤔 👀 etc.

### Use Cases for TeleVibeCode

- ✅ on successful job completion
- ❌ on job failure
- 👀 when job starts
- 🔥 on first PR merged

**Sources:**
- [Message Reactions](https://core.telegram.org/api/reactions)
- [Reactions Guide - grammY](https://grammy.dev/guide/reactions)

---

## 10. Mini Apps / WebApps

Full web applications inside Telegram.

### 2024 Features

- Full-screen mode (portrait & landscape)
- Device storage & secure storage
- File downloads
- Emoji status management
- Media sharing to chats
- Secondary buttons

### Integration

```python
from telegram import WebAppInfo, InlineKeyboardButton

button = InlineKeyboardButton(
    text="Open Dashboard",
    web_app=WebAppInfo(url="https://your-app.com/dashboard"),
)
```

### Menu Button Web App

```python
from telegram import MenuButtonWebApp, WebAppInfo

await context.bot.set_chat_menu_button(
    chat_id=chat_id,
    menu_button=MenuButtonWebApp(
        text="Dashboard",
        web_app=WebAppInfo(url="https://your-app.com"),
    ),
)
```

**Sources:**
- [Telegram Mini Apps](https://core.telegram.org/bots/webapps)
- [Bot API Changelog](https://core.telegram.org/bots/api-changelog)

---

## 11. ForceReply & Input Placeholders

Force user to reply and show input hints.

### ForceReply

```python
from telegram import ForceReply

await update.message.reply_text(
    "What instruction should I run?",
    reply_markup=ForceReply(
        selective=True,
        input_field_placeholder="Type your instruction here..."
    ),
)
```

This opens the reply interface automatically, making it clear the user should respond.

### Input Placeholder

Available on both `ForceReply` and `ReplyKeyboardMarkup`:

```python
ReplyKeyboardMarkup(
    keyboard,
    input_field_placeholder="Enter project name...",
)
```

**Sources:**
- [ForceReply - Telegram Bot API](https://core.telegram.org/bots/api#forcereply)

---

## 12. Implementation Recommendations for TeleVibeCode

### Priority 1: Reply Context Handling

**Problem**: User replies to a message but other messages arrived in between.

**Solution**:
```python
# Store context with every bot message
class MessageContextStore:
    def __init__(self):
        self._contexts: dict[int, dict] = {}

    def store(self, message_id: int, context: dict):
        self._contexts[message_id] = context
        # Prune old entries (keep last 1000)
        if len(self._contexts) > 1000:
            oldest = sorted(self._contexts.keys())[:100]
            for k in oldest:
                del self._contexts[k]

    def get(self, message_id: int) -> dict | None:
        return self._contexts.get(message_id)

# Usage in handlers
async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if reply := update.message.reply_to_message:
        msg_ctx = context.bot_data["msg_store"].get(reply.message_id)
        if msg_ctx:
            # Route to correct session automatically
            session_id = msg_ctx["session_id"]
            await run_instruction(session_id, update.message.text)
            return

    # Fallback to active session
    ...
```

### Priority 2: Approval Buttons

```python
async def send_approval_request(job: Job, chat_id: int, context):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{job.job_id}"),
            InlineKeyboardButton("❌ Deny", callback_data=f"deny:{job.job_id}"),
        ],
        [
            InlineKeyboardButton("📋 View Details", callback_data=f"details:{job.job_id}"),
        ],
    ])

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=format_approval_message(job),
        reply_markup=keyboard,
        parse_mode="Markdown",
    )

    # Store context
    context.bot_data["msg_store"].store(msg.message_id, {
        "type": "approval",
        "job_id": job.job_id,
        "session_id": job.session_id,
    })
```

### Priority 3: Live Progress Updates

```python
async def run_job_with_updates(job: Job, chat_id: int, context):
    # Send initial message
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔧 {job.session_id}: Starting job...",
    )

    # Update progress periodically
    async def update_loop():
        while True:
            job = await db.get_job(job.job_id)
            if job.status in ("done", "failed", "canceled"):
                break

            await msg.edit_text(
                f"🔧 {job.session_id}: Running...\n"
                f"⏱️ {elapsed_time(job.started_at)}"
            )
            await asyncio.sleep(5)

    asyncio.create_task(update_loop())
```

### Priority 4: Session Quick-Switch Keyboard

```python
async def show_session_switcher(update: Update, context):
    sessions = await db.get_active_sessions()

    keyboard = [
        [InlineKeyboardButton(
            f"{'🟢' if s.state == 'idle' else '🔧'} {s.session_id} - {s.branch}",
            callback_data=f"switch:{s.session_id}"
        )]
        for s in sessions[:5]  # Max 5 sessions
    ]

    await update.message.reply_text(
        "Quick switch session:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
```

### Priority 5: Typing Indicator

```python
async def run_with_typing(chat_id: int, context, coro):
    """Run a coroutine while showing typing indicator."""
    async def keep_typing():
        while True:
            await context.bot.send_chat_action(chat_id, "typing")
            await asyncio.sleep(4)

    typing_task = asyncio.create_task(keep_typing())
    try:
        return await coro
    finally:
        typing_task.cancel()
```

---

## Summary

| Feature | Priority | Use Case |
|---------|----------|----------|
| Reply-to context | P1 | Smart session routing |
| Inline keyboard approvals | P1 | Approve/deny actions |
| Message editing | P2 | Live job progress |
| Typing indicator | P2 | Long-running feedback |
| ForceReply | P3 | Clear input prompts |
| Reactions | P3 | Quick status feedback |
| Polls | P4 | Task prioritization |
| Mini Apps | P5 | Future dashboard |
