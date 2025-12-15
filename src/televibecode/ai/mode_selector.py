"""Execution mode selector for TeleVibeCode sessions.

Provides pattern-based auto-suggestion for choosing between worktree
and direct execution modes based on task context.
"""

import re
from dataclasses import dataclass

from televibecode.db.models import ExecutionMode

# Patterns that suggest direct mode (quick fixes, minor changes)
DIRECT_PATTERNS = [
    # Quick fixes
    r"\bquick\s*fix\b",
    r"\bfix\s*typo\b",
    r"\btypo\b",
    r"\bhotfix\b",
    r"\bminor\s*fix\b",
    r"\bsmall\s*fix\b",
    r"\bquickly\b",
    r"\bfast\b",
    # Version/config updates
    r"\bbump\s*version\b",
    r"\bupdate\s*version\b",
    r"\bchange\s*version\b",
    r"\bupdate\s*readme\b",
    r"\bupdate\s*changelog\b",
    r"\bupdate\s*config\b",
    # Simple edits
    r"\bone\s*line\b",
    r"\bsimple\s*change\b",
    r"\bsimple\s*edit\b",
    r"\bsmall\s*change\b",
    r"\bminor\s*change\b",
    r"\btweak\b",
    # Immediate needs
    r"\burgent\b",
    r"\basap\b",
    r"\bright\s*now\b",
    r"\bimmediately\b",
]

# Patterns that suggest worktree mode (feature work, experiments)
WORKTREE_PATTERNS = [
    # New feature work
    r"\bnew\s*feature\b",
    r"\badd\s*feature\b",
    r"\bimplement\b",
    r"\bcreate\s*new\b",
    r"\bbuild\s*new\b",
    # Major changes
    r"\brefactor\b",
    r"\brestructure\b",
    r"\bmajor\s*change\b",
    r"\bbig\s*change\b",
    r"\boverhaul\b",
    r"\brewrite\b",
    r"\barchitect\b",
    # Experimental work
    r"\bexperiment\b",
    r"\btry\s*out\b",
    r"\bprototype\b",
    r"\bpoc\b",
    r"\bspike\b",
    # Long-running tasks
    r"\bmulti\s*step\b",
    r"\bmultiple\s*files\b",
    r"\bacross\s*files\b",
    r"\bcomprehensive\b",
    # Risky operations
    r"\bmigrat\b",  # Matches migration, migrate
    r"\bdelete\s*all\b",
    r"\bremove\s*all\b",
    r"\bdrop\b",
]

# Strong indicators (higher weight)
STRONG_DIRECT = [
    r"\bjust\s*fix\b",
    r"\bonly\s*change\b",
    r"\bquick\s*typo\b",
]

STRONG_WORKTREE = [
    r"\bbranch\b",
    r"\bfeature\s*branch\b",
    r"\bisolat\b",  # Matches isolated, isolation
]


@dataclass
class ModeRecommendation:
    """Recommendation for execution mode."""

    mode: ExecutionMode
    confidence: float  # 0.0 to 1.0
    reason: str
    patterns_matched: list[str]


def suggest_execution_mode(
    instruction: str,
    context: str | None = None,
) -> ModeRecommendation:
    """Suggest an execution mode based on instruction content.

    Analyzes the instruction text to determine whether the task
    is better suited for worktree (isolated) or direct mode.

    Args:
        instruction: The task instruction or description.
        context: Optional additional context (conversation history).

    Returns:
        ModeRecommendation with suggested mode and confidence.
    """
    text = instruction.lower()
    if context:
        text = f"{context.lower()} {text}"

    # Score both modes
    direct_score = 0.0
    worktree_score = 0.0
    direct_matches: list[str] = []
    worktree_matches: list[str] = []

    # Check strong indicators first (weight: 2.0)
    for pattern in STRONG_DIRECT:
        if re.search(pattern, text, re.IGNORECASE):
            direct_score += 2.0
            direct_matches.append(pattern)

    for pattern in STRONG_WORKTREE:
        if re.search(pattern, text, re.IGNORECASE):
            worktree_score += 2.0
            worktree_matches.append(pattern)

    # Check regular patterns (weight: 1.0)
    for pattern in DIRECT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            direct_score += 1.0
            direct_matches.append(pattern)

    for pattern in WORKTREE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            worktree_score += 1.0
            worktree_matches.append(pattern)

    # Calculate confidence based on score difference
    total_score = direct_score + worktree_score
    if total_score == 0:
        # No patterns matched - default to worktree (safer)
        return ModeRecommendation(
            mode=ExecutionMode.WORKTREE,
            confidence=0.5,
            reason="No specific patterns detected, defaulting to worktree for safety",
            patterns_matched=[],
        )

    # Determine winner
    if direct_score > worktree_score:
        score_ratio = direct_score / total_score
        confidence = min(0.5 + (score_ratio * 0.5), 0.95)
        return ModeRecommendation(
            mode=ExecutionMode.DIRECT,
            confidence=confidence,
            reason=_format_reason("direct", direct_matches),
            patterns_matched=direct_matches,
        )
    elif worktree_score > direct_score:
        score_ratio = worktree_score / total_score
        confidence = min(0.5 + (score_ratio * 0.5), 0.95)
        return ModeRecommendation(
            mode=ExecutionMode.WORKTREE,
            confidence=confidence,
            reason=_format_reason("worktree", worktree_matches),
            patterns_matched=worktree_matches,
        )
    else:
        # Tie - prefer worktree (safer)
        return ModeRecommendation(
            mode=ExecutionMode.WORKTREE,
            confidence=0.5,
            reason="Equal indicators for both modes, defaulting to worktree for safety",
            patterns_matched=direct_matches + worktree_matches,
        )


def _format_reason(mode: str, patterns: list[str]) -> str:
    """Format a human-readable reason for the recommendation."""
    if not patterns:
        return f"Recommended {mode} mode"

    # Clean up patterns for display
    clean_patterns = []
    for p in patterns[:3]:  # Limit to 3
        # Remove regex characters
        clean = p.replace(r"\b", "").replace(r"\s*", " ").strip()
        clean_patterns.append(f'"{clean}"')

    if len(patterns) > 3:
        return f"Detected {', '.join(clean_patterns)} and {len(patterns) - 3} more"
    return f"Detected {', '.join(clean_patterns)}"


def format_mode_choice_prompt(recommendation: ModeRecommendation) -> str:
    """Format a prompt for user to confirm mode choice.

    Args:
        recommendation: The mode recommendation.

    Returns:
        Formatted prompt string.
    """
    mode_name = recommendation.mode.value
    other_mode = "worktree" if mode_name == "direct" else "direct"

    if recommendation.confidence >= 0.8:
        # High confidence - brief prompt
        return (
            f"Suggested mode: **{mode_name}** ({recommendation.reason})\n"
            f"Use `--{other_mode}` to override."
        )
    else:
        # Lower confidence - offer choice
        conf = f"{recommendation.confidence:.0%}"
        return (
            f"Mode suggestion: **{mode_name}** (confidence: {conf})\n"
            f"{recommendation.reason}\n\n"
            f"Options:\n"
            f"- **worktree**: Isolated branch, safe for experiments\n"
            f"- **direct**: Run in project folder, faster for quick fixes\n"
        )
