"""Tests for the AI intent classification layer."""

import pytest

from televibecode.ai.intent import (
    IntentClassifier,
    IntentType,
)


@pytest.fixture
def classifier():
    """Create a classifier without AI (pattern-only)."""
    return IntentClassifier(use_ai=False)


class TestPatternMatching:
    """Test pattern-based intent classification."""

    async def test_help_intent(self, classifier: IntentClassifier):
        """Test help intent recognition."""
        result = await classifier.classify("help")
        assert result.intent == IntentType.HELP

        result = await classifier.classify("what commands are available")
        assert result.intent == IntentType.HELP

    async def test_list_sessions_intent(self, classifier: IntentClassifier):
        """Test list sessions intent."""
        result = await classifier.classify("show sessions")
        assert result.intent == IntentType.LIST_SESSIONS

        result = await classifier.classify("list all sessions")
        assert result.intent == IntentType.LIST_SESSIONS

    async def test_create_session_intent(self, classifier: IntentClassifier):
        """Test create session intent."""
        result = await classifier.classify("start a new session")
        assert result.intent == IntentType.CREATE_SESSION

        result = await classifier.classify("create session")
        assert result.intent == IntentType.CREATE_SESSION

    async def test_switch_session_intent(self, classifier: IntentClassifier):
        """Test switch session intent with entity extraction."""
        result = await classifier.classify("switch to S5")
        assert result.intent == IntentType.SWITCH_SESSION
        assert result.entities.get("session_id") == "S5"

        result = await classifier.classify("use session s12")
        assert result.intent == IntentType.SWITCH_SESSION
        assert result.entities.get("session_id").upper() == "S12"

    async def test_close_session_intent(self, classifier: IntentClassifier):
        """Test close session intent."""
        result = await classifier.classify("close the session")
        assert result.intent == IntentType.CLOSE_SESSION

    async def test_list_tasks_intent(self, classifier: IntentClassifier):
        """Test list tasks intent."""
        result = await classifier.classify("show tasks")
        assert result.intent == IntentType.LIST_TASKS

        result = await classifier.classify("next tasks")
        assert result.intent == IntentType.LIST_TASKS

    async def test_claim_task_intent(self, classifier: IntentClassifier):
        """Test claim task intent with entity extraction."""
        result = await classifier.classify("claim T-123")
        assert result.intent == IntentType.CLAIM_TASK
        assert result.entities.get("task_id") == "T-123"

        result = await classifier.classify("take task T456")
        assert result.intent == IntentType.CLAIM_TASK

    async def test_sync_backlog_intent(self, classifier: IntentClassifier):
        """Test sync backlog intent."""
        result = await classifier.classify("sync the backlog")
        assert result.intent == IntentType.SYNC_BACKLOG

    async def test_job_status_intent(self, classifier: IntentClassifier):
        """Test job status intent."""
        result = await classifier.classify("job status")
        assert result.intent == IntentType.CHECK_JOB_STATUS

    async def test_view_logs_intent(self, classifier: IntentClassifier):
        """Test view logs intent."""
        result = await classifier.classify("show logs")
        assert result.intent == IntentType.VIEW_JOB_LOGS

    async def test_cancel_job_intent(self, classifier: IntentClassifier):
        """Test cancel job intent."""
        result = await classifier.classify("cancel the job")
        assert result.intent == IntentType.CANCEL_JOB

    async def test_approval_intents(self, classifier: IntentClassifier):
        """Test approval-related intents."""
        result = await classifier.classify("approve")
        assert result.intent == IntentType.APPROVE_ACTION

        result = await classifier.classify("deny")
        assert result.intent == IntentType.DENY_ACTION

        result = await classifier.classify("pending approvals")
        assert result.intent == IntentType.LIST_APPROVALS

    async def test_project_intents(self, classifier: IntentClassifier):
        """Test project-related intents."""
        result = await classifier.classify("list projects")
        assert result.intent == IntentType.LIST_PROJECTS

        result = await classifier.classify("scan for projects")
        assert result.intent == IntentType.SCAN_PROJECTS

    async def test_run_instruction_intent(self, classifier: IntentClassifier):
        """Test run instruction intent."""
        result = await classifier.classify("run add tests for auth module")
        assert result.intent == IntentType.RUN_INSTRUCTION
        assert "add tests" in result.entities.get("instruction", "").lower()

    async def test_unknown_intent(self, classifier: IntentClassifier):
        """Test unknown intent for unrecognized input."""
        result = await classifier.classify("foobar gibberish xyz")
        assert result.intent == IntentType.UNKNOWN


class TestSuggestedCommands:
    """Test suggested command generation."""

    async def test_suggested_command_for_help(self, classifier: IntentClassifier):
        """Test suggested command for help."""
        result = await classifier.classify("help")
        assert result.suggested_command == "/help"

    async def test_suggested_command_for_sessions(self, classifier: IntentClassifier):
        """Test suggested command for sessions."""
        result = await classifier.classify("show sessions")
        assert result.suggested_command == "/sessions"

    async def test_suggested_command_with_entity(self, classifier: IntentClassifier):
        """Test suggested command includes entity."""
        result = await classifier.classify("use S5")
        assert result.suggested_command is not None
        assert "S5" in result.suggested_command


class TestConfidenceScores:
    """Test confidence scoring."""

    async def test_pattern_match_confidence(self, classifier: IntentClassifier):
        """Test that pattern matches have high confidence."""
        result = await classifier.classify("show sessions")
        assert result.confidence >= 0.8

    async def test_unknown_low_confidence(self, classifier: IntentClassifier):
        """Test that unknown intents have zero confidence."""
        result = await classifier.classify("random nonsense")
        assert result.confidence == 0.0


class TestIsLikelyInstruction:
    """Test the is_likely_instruction helper."""

    def test_coding_keywords(self, classifier: IntentClassifier):
        """Test detection of coding keywords."""
        assert classifier.is_likely_instruction("add a new function")
        assert classifier.is_likely_instruction("fix the bug in auth")
        assert classifier.is_likely_instruction("implement feature X")
        assert classifier.is_likely_instruction("refactor the module")

    def test_non_coding_text(self, classifier: IntentClassifier):
        """Test non-coding text."""
        assert not classifier.is_likely_instruction("hello world")
        assert not classifier.is_likely_instruction("how are you")
