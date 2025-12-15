"""Configuration for job tracker message display."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class TrackerConfig:
    """Configuration for which events to display in tracker message."""

    # ═══════════════════════════════════════════════════════════════
    # Category-level toggles
    # ═══════════════════════════════════════════════════════════════

    show_ai_speech: bool = True
    """Show Claude's text responses."""

    show_ai_thinking: bool = False
    """Show extended thinking content (verbose)."""

    show_tool_start: bool = True
    """Show when tools begin execution."""

    show_tool_result: bool = False
    """Show tool execution results."""

    show_tool_errors: bool = True
    """Always show tool errors."""

    show_approvals: bool = True
    """Show when waiting for approval."""

    # ═══════════════════════════════════════════════════════════════
    # Tool-specific filters
    # ═══════════════════════════════════════════════════════════════

    tool_whitelist: list[str] | None = None
    """Only show these tools. None = show all."""

    tool_blacklist: list[str] = field(default_factory=list)
    """Never show these tools."""

    show_result_for_tools: list[str] = field(
        default_factory=lambda: ["Bash", "Edit"]
    )
    """Show results for these tools even if show_tool_result=False."""

    # ═══════════════════════════════════════════════════════════════
    # Display options
    # ═══════════════════════════════════════════════════════════════

    ai_speech_max_length: int = 150
    """Max characters per AI speech (0 = unlimited)."""

    tool_display_mode: Literal["minimal", "normal", "detailed"] = "normal"
    """
    minimal: Icon only
    normal:  Icon + tool + target
    detailed: Icon + tool + target + details
    """

    show_file_paths: bool = True
    """Show file paths for file operations."""

    truncate_paths: bool = True
    """Truncate long paths."""

    path_max_length: int = 40
    """Max path length before truncation."""

    show_bash_commands: bool = True
    """Show command for Bash operations."""

    bash_command_max_length: int = 50
    """Max command length."""

    # ═══════════════════════════════════════════════════════════════
    # Result parsing
    # ═══════════════════════════════════════════════════════════════

    parse_test_output: bool = True
    """Parse pytest/jest output for pass/fail counts."""

    result_max_length: int = 100
    """Max characters for tool result display."""

    # ═══════════════════════════════════════════════════════════════
    # Progress/Stats
    # ═══════════════════════════════════════════════════════════════

    show_progress_bar: bool = True
    """Show progress bar."""

    show_elapsed_time: bool = True
    show_file_count: bool = True
    show_turn_count: bool = True
    show_token_count: bool = False
    show_cost: bool = False

    # ═══════════════════════════════════════════════════════════════
    # Event buffer
    # ═══════════════════════════════════════════════════════════════

    max_events_displayed: int = 10
    """Max events to show (older scroll off)."""

    collapse_repeated_tools: bool = True
    """Collapse repeated same-tool events."""

    # ═══════════════════════════════════════════════════════════════
    # Rate limiting
    # ═══════════════════════════════════════════════════════════════

    update_interval_ms: int = 1500
    """Minimum time between message updates."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "show_ai_speech": self.show_ai_speech,
            "show_ai_thinking": self.show_ai_thinking,
            "show_tool_start": self.show_tool_start,
            "show_tool_result": self.show_tool_result,
            "show_tool_errors": self.show_tool_errors,
            "show_approvals": self.show_approvals,
            "tool_whitelist": self.tool_whitelist,
            "tool_blacklist": self.tool_blacklist,
            "show_result_for_tools": self.show_result_for_tools,
            "ai_speech_max_length": self.ai_speech_max_length,
            "tool_display_mode": self.tool_display_mode,
            "show_file_paths": self.show_file_paths,
            "truncate_paths": self.truncate_paths,
            "path_max_length": self.path_max_length,
            "show_bash_commands": self.show_bash_commands,
            "bash_command_max_length": self.bash_command_max_length,
            "parse_test_output": self.parse_test_output,
            "result_max_length": self.result_max_length,
            "show_progress_bar": self.show_progress_bar,
            "show_elapsed_time": self.show_elapsed_time,
            "show_file_count": self.show_file_count,
            "show_turn_count": self.show_turn_count,
            "show_token_count": self.show_token_count,
            "show_cost": self.show_cost,
            "max_events_displayed": self.max_events_displayed,
            "collapse_repeated_tools": self.collapse_repeated_tools,
            "update_interval_ms": self.update_interval_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrackerConfig:
        """Create from dictionary."""
        return cls(
            show_ai_speech=data.get("show_ai_speech", True),
            show_ai_thinking=data.get("show_ai_thinking", False),
            show_tool_start=data.get("show_tool_start", True),
            show_tool_result=data.get("show_tool_result", False),
            show_tool_errors=data.get("show_tool_errors", True),
            show_approvals=data.get("show_approvals", True),
            tool_whitelist=data.get("tool_whitelist"),
            tool_blacklist=data.get("tool_blacklist", []),
            show_result_for_tools=data.get("show_result_for_tools", ["Bash", "Edit"]),
            ai_speech_max_length=data.get("ai_speech_max_length", 150),
            tool_display_mode=data.get("tool_display_mode", "normal"),
            show_file_paths=data.get("show_file_paths", True),
            truncate_paths=data.get("truncate_paths", True),
            path_max_length=data.get("path_max_length", 40),
            show_bash_commands=data.get("show_bash_commands", True),
            bash_command_max_length=data.get("bash_command_max_length", 50),
            parse_test_output=data.get("parse_test_output", True),
            result_max_length=data.get("result_max_length", 100),
            show_progress_bar=data.get("show_progress_bar", True),
            show_elapsed_time=data.get("show_elapsed_time", True),
            show_file_count=data.get("show_file_count", True),
            show_turn_count=data.get("show_turn_count", True),
            show_token_count=data.get("show_token_count", False),
            show_cost=data.get("show_cost", False),
            max_events_displayed=data.get("max_events_displayed", 10),
            collapse_repeated_tools=data.get("collapse_repeated_tools", True),
            update_interval_ms=data.get("update_interval_ms", 1500),
        )


# ═══════════════════════════════════════════════════════════════════
# Presets
# ═══════════════════════════════════════════════════════════════════

TRACKER_PRESETS: dict[str, TrackerConfig] = {
    "minimal": TrackerConfig(
        show_ai_speech=False,
        show_tool_start=True,
        show_tool_result=False,
        tool_display_mode="minimal",
        max_events_displayed=5,
        show_progress_bar=True,
        show_turn_count=False,
    ),
    "normal": TrackerConfig(
        show_ai_speech=True,
        ai_speech_max_length=100,
        show_tool_start=True,
        show_tool_result=False,
        show_result_for_tools=["Bash"],
        tool_display_mode="normal",
        max_events_displayed=8,
    ),
    "verbose": TrackerConfig(
        show_ai_speech=True,
        ai_speech_max_length=200,
        show_tool_start=True,
        show_tool_result=True,
        tool_display_mode="detailed",
        max_events_displayed=15,
        show_token_count=True,
    ),
    "debug": TrackerConfig(
        show_ai_speech=True,
        show_ai_thinking=True,
        ai_speech_max_length=0,
        show_tool_start=True,
        show_tool_result=True,
        tool_display_mode="detailed",
        max_events_displayed=20,
        show_token_count=True,
        show_cost=True,
    ),
    "speech": TrackerConfig(
        show_ai_speech=True,
        ai_speech_max_length=0,
        show_tool_start=False,
        show_tool_result=False,
        max_events_displayed=5,
        show_progress_bar=False,
    ),
    "tools": TrackerConfig(
        show_ai_speech=False,
        show_tool_start=True,
        show_tool_result=True,
        tool_display_mode="detailed",
        max_events_displayed=12,
    ),
}


def get_preset(name: str) -> TrackerConfig:
    """Get a preset config by name.

    Args:
        name: Preset name (minimal, normal, verbose, debug, speech, tools).

    Returns:
        TrackerConfig for the preset.
    """
    preset = TRACKER_PRESETS.get(name.lower())
    if preset:
        # Return a copy
        return TrackerConfig.from_dict(preset.to_dict())
    return TrackerConfig()


def list_presets() -> list[str]:
    """List available preset names."""
    return list(TRACKER_PRESETS.keys())


# Configurable settings that can be toggled via Telegram
TOGGLEABLE_SETTINGS: dict[str, str] = {
    "ai": "show_ai_speech",
    "speech": "show_ai_speech",
    "thinking": "show_ai_thinking",
    "tools": "show_tool_start",
    "results": "show_tool_result",
    "errors": "show_tool_errors",
    "approvals": "show_approvals",
    "progress": "show_progress_bar",
    "time": "show_elapsed_time",
    "files": "show_file_count",
    "turns": "show_turn_count",
    "tokens": "show_token_count",
    "cost": "show_cost",
    "paths": "show_file_paths",
    "commands": "show_bash_commands",
    "tests": "parse_test_output",
}

# Display mode options
DISPLAY_MODES: list[str] = ["minimal", "normal", "detailed"]
