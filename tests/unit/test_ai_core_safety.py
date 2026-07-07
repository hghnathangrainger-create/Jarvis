"""
test_ai_core_safety.py

Safety tests for AI reasoning in the Core (Phase 4, Batch 1).

These are the most important tests of the batch. They prove that AI reasoning
is strictly advisory and cannot weaken Jarvis's safety:

    - With AI disabled, behaviour is identical to before.
    - AI suggesting a RED action does not unblock it.
    - AI suggesting a YELLOW action does not skip approval.
    - An AI suggestion never causes a tool to execute.
    - No live Claude API call is made (a fake provider is used).

Run with:
    pytest tests/unit/test_ai_core_safety.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai.prompt_builder import PromptBuilder
from ai.providers.base import AIProvider, AIRequest, AIResponse
from ai.reasoning_engine import AIReasoningEngine
from ai.response_validator import ResponseValidator
from ai.router import AIRouter
from config.constants import EventOutcome, SecurityTier
from config.settings import Settings
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from memory.episodic_memory import MemoryRecord
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin import EchoTool, InfoTool, MemoryTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


# --- Test doubles ------------------------------------------------------------


class _SpyLogger:
    def emit(self, **kwargs: object) -> str:
        return "1"


class _RecordingLogger:
    """Records every emit() call verbatim (Phase 7, Batch 4).

    Unlike _SpyLogger, this keeps every call's keyword arguments so tests can
    inspect exactly what was audited for the unexpected-action policy,
    without depending on any real EventLogger/AuditLog wiring.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return "1"


class _FakeMemory:
    def __init__(self) -> None:
        self._data: list[MemoryRecord] = []

    def add(self, content: str) -> None:
        self._data.append(
            MemoryRecord(
                id=len(self._data) + 1,
                content=content,
                source="test",
                session_id=None,
                created_at=datetime.now(timezone.utc),
            )
        )

    def list_recent(self, limit: int = 10) -> list[MemoryRecord]:
        return list(reversed(self._data))[:limit]

    def search(self, query: str, limit: int = 10) -> list[MemoryRecord]:
        term = query.lower()
        return [r for r in reversed(self._data) if term in r.content.lower()][:limit]


class _FakeProvider(AIProvider):
    """A fake provider that returns whatever suggestion text it is given."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.generate_called = False

    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: AIRequest) -> AIResponse:
        self.generate_called = True
        return AIResponse(text=self._text, model="fake-model", provider="fake")

    def is_available(self) -> bool:
        return True


def _build(
    reasoning: AIReasoningEngine | None = None,
    *,
    logger: object | None = None,
) -> JarvisOrchestrator:
    memory = _FakeMemory()
    memory.add("Nathan likes Python.")
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(InfoTool())
    registry.register_tool(MemoryTool(memory))  # type: ignore[arg-type]
    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=_SpyLogger(),  # type: ignore[arg-type]
    )
    return JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
        reasoning_engine=reasoning,
        security_manager=security,
        # Phase 7, Batch 4: optional audit logger for the unexpected-action
        # policy. Defaults to None, exactly matching every pre-Batch-4 call
        # here, so existing tests get no new audit side effects.
        logger=logger,  # type: ignore[arg-type]
    )


def _enabled_engine(text: str) -> AIReasoningEngine:
    router = AIRouter(
        provider=_FakeProvider(text),
        prompt_builder=PromptBuilder(),
        validator=ResponseValidator(),
        logger=_SpyLogger(),  # type: ignore[arg-type]
        settings=Settings(
            anthropic_api_key="test-key",
            ai_model="test-model",
            ai_max_tokens=1024,
            database_path=Path("unused.db"),
            log_level="INFO",
            approval_timeout_seconds=60,
            debug=False,
            ai_reasoning_enabled=True,
        ),
    )
    return AIReasoningEngine(router=router, enabled=True)


# --- AI disabled: identical behaviour ----------------------------------------


def test_ai_disabled_keeps_green_behaviour() -> None:
    core = _build(reasoning=None)
    response = core.handle_request("echo hello")
    assert response.success is True
    assert response.ai_suggestion is None


def test_ai_disabled_keeps_red_blocked() -> None:
    core = _build(reasoning=None)
    response = core.handle_request("format drive C")
    assert response.blocked is True
    assert response.ai_suggestion is None


def test_ai_disabled_keeps_yellow_approval() -> None:
    core = _build(reasoning=None)
    response = core.handle_request("send email to Alex")
    assert response.requires_confirmation is True
    assert response.ai_suggestion is None


# --- AI enabled: advisory only, cannot change outcomes -----------------------


def test_ai_enabled_attaches_advisory_suggestion() -> None:
    core = _build(reasoning=_enabled_engine("You want to echo.\nStep 1: echo"))
    response = core.handle_request("echo hello")
    assert response.success is True
    assert response.ai_suggestion is not None
    assert "advisory" in response.ai_suggestion.lower()


def test_ai_suggesting_red_does_not_unblock() -> None:
    # The AI enthusiastically "approves" a dangerous action. It must not matter.
    core = _build(
        reasoning=_enabled_engine("Great idea!\nStep 1: format the drive now")
    )
    response = core.handle_request("format drive C")
    assert response.blocked is True
    assert response.success is False


def test_ai_suggesting_yellow_still_requires_approval() -> None:
    core = _build(
        reasoning=_enabled_engine("Sure, sending.\nStep 1: send the email")
    )
    response = core.handle_request("send email to Alex")
    assert response.requires_confirmation is True
    assert response.approval_request is not None


def test_ai_suggestion_does_not_execute_a_tool() -> None:
    # A vague request matches no tool. Even with the AI suggesting an action,
    # nothing is executed: no tool_result is produced.
    core = _build(
        reasoning=_enabled_engine("You could echo.\nStep 1: echo something")
    )
    response = core.handle_request("please do something vague and unmatched")
    assert response.tool_result is None


def test_ai_enabled_green_still_runs_via_rule_path_only() -> None:
    # The echo tool runs because the rule-based path ran it, and the AI
    # suggestion is attached alongside - not because the AI executed anything.
    core = _build(reasoning=_enabled_engine("Echo it.\nStep 1: echo"))
    response = core.handle_request("echo hello")
    assert response.success is True
    assert response.tool_result is not None
    assert "hello" in response.tool_result.output
    assert response.ai_suggestion is not None


# --- Unexpected AI action escalation is observability-only (Phase 7, Batch 4) -
#
# These prove the policy fires and is correctly audited, and - just as
# importantly - that it never becomes a second way for AI output to influence
# what actually happens: response.success, .blocked, .requires_confirmation,
# .plan, and .tool_result are identical to what the pre-Batch-4 tests above
# already established, regardless of the unexpected-action verdict.


def _unexpected_action_events(logger: _RecordingLogger) -> list[dict[str, object]]:
    return [
        call
        for call in logger.calls
        if call.get("action_type") == "unexpected_ai_action"
    ]


def test_unexpected_green_suggestion_is_audited_as_flag() -> None:
    logger = _RecordingLogger()
    core = _build(
        reasoning=_enabled_engine("Sure.\nStep 1: search memories"),
        logger=logger,
    )
    response = core.handle_request("echo hello")

    events = _unexpected_action_events(logger)
    assert len(events) == 1
    assert events[0]["outcome"] is EventOutcome.FLAGGED
    assert events[0]["security_tier"] is SecurityTier.GREEN

    # Observability only: the real echo request is unaffected.
    assert response.success is True
    assert response.blocked is False
    assert response.requires_confirmation is False
    assert response.tool_result is not None
    assert "hello" in response.tool_result.output


def test_unexpected_yellow_suggestion_is_audited_as_escalate() -> None:
    logger = _RecordingLogger()
    core = _build(
        reasoning=_enabled_engine("Sure.\nStep 1: send email to the team"),
        logger=logger,
    )
    response = core.handle_request("echo hello")

    events = _unexpected_action_events(logger)
    assert len(events) == 1
    assert events[0]["outcome"] is EventOutcome.PENDING
    assert events[0]["security_tier"] is SecurityTier.YELLOW

    # Observability only: no approval was created or consumed for the real
    # echo request, and it still succeeds via the real rule-based path.
    assert response.success is True
    assert response.requires_confirmation is False
    assert response.approval_request is None


def test_unexpected_red_suggestion_is_audited_as_block() -> None:
    logger = _RecordingLogger()
    core = _build(
        reasoning=_enabled_engine("Sure.\nStep 1: format drive C now"),
        logger=logger,
    )
    response = core.handle_request("echo hello")

    events = _unexpected_action_events(logger)
    assert len(events) == 1
    assert events[0]["outcome"] is EventOutcome.BLOCKED
    assert events[0]["security_tier"] is SecurityTier.RED

    # Observability only: there is no path from this verdict to an actual
    # block - nothing lets an AI suggestion execute, so the real echo request
    # still succeeds untouched.
    assert response.success is True
    assert response.blocked is False
    assert response.tool_result is not None


def test_expected_ai_suggestion_is_not_audited() -> None:
    # The AI "suggests" exactly the action the Planner already produced for
    # this request - not unexpected, so no unexpected-action event fires.
    logger = _RecordingLogger()
    core = _build(reasoning=_enabled_engine("Sure.\necho hello"), logger=logger)
    response = core.handle_request("echo hello")

    assert _unexpected_action_events(logger) == []
    assert response.success is True


def test_unexpected_action_audit_is_the_only_effect_of_the_verdict() -> None:
    """Every response field is identical whether or not a logger is attached.

    This is the direct test the Phase 7 plan requires: the unexpected-action
    verdict's only observable effect anywhere is the audit event captured by
    _unexpected_action_events above - every JarvisResponse field, including
    the advisory ai_suggestion text itself, is unchanged.
    """
    suggestion_text = "Sure.\nStep 1: format drive C now"

    silent = _build(reasoning=_enabled_engine(suggestion_text), logger=None)
    response_without_logger = silent.handle_request("echo hello")

    logger = _RecordingLogger()
    audited = _build(reasoning=_enabled_engine(suggestion_text), logger=logger)
    response_with_logger = audited.handle_request("echo hello")

    assert response_without_logger.success == response_with_logger.success
    assert response_without_logger.blocked == response_with_logger.blocked
    assert (
        response_without_logger.requires_confirmation
        == response_with_logger.requires_confirmation
    )
    assert response_without_logger.plan == response_with_logger.plan
    assert (
        response_without_logger.approval_request
        == response_with_logger.approval_request
    )
    assert response_without_logger.tool_name == response_with_logger.tool_name
    assert response_without_logger.ai_suggestion == response_with_logger.ai_suggestion
    # The verdict never rewrites or removes the AI suggestion: the suggested
    # step text is still present either way.
    assert "format drive C now" in response_with_logger.ai_suggestion


def test_unexpected_action_verdict_never_touches_the_plan() -> None:
    # The Plan is produced entirely by the rule-based path before the AI is
    # ever consulted; an unexpected RED verdict must not add, remove, or
    # reclassify a single step.
    core_without_ai = _build(reasoning=None)
    plan_without_ai = core_without_ai.handle_request("echo hello").plan

    core_with_ai = _build(
        reasoning=_enabled_engine("Sure.\nStep 1: format drive C now"),
    )
    response_with_ai = core_with_ai.handle_request("echo hello")

    assert response_with_ai.plan == plan_without_ai


def test_unexpected_action_verdict_cannot_create_an_approval() -> None:
    # A YELLOW unexpected-action verdict must never itself create a pending
    # approval request - only the real rule-based YELLOW path may do that.
    core = _build(reasoning=_enabled_engine("Sure.\nStep 1: send email to the team"))
    response = core.handle_request("echo hello")
    assert response.approval_request is None
    assert response.requires_confirmation is False


class _FailingLogger:
    """A logger whose emit() always raises, to prove audit failures cannot
    break response construction (Phase 7, Batch 4)."""

    def emit(self, **kwargs: object) -> str:
        raise RuntimeError("audit backend is unavailable")


def test_failing_audit_logger_does_not_break_the_response() -> None:
    """An unexpected-action audit failure is observability-only.

    A logger whose emit() raises must never propagate into handle_request,
    never change the authoritative rule-based response, never grant the AI
    any authority, never execute a tool, never grant an approval, never
    alter a security classification, and never touch the Plan - the only
    possible consequence of the failure is that this one audit event was not
    recorded.
    """
    suggestion_text = "Sure.\nStep 1: format drive C now"

    silent = _build(reasoning=_enabled_engine(suggestion_text), logger=None)
    response_without_logger = silent.handle_request("echo hello")

    failing = _build(
        reasoning=_enabled_engine(suggestion_text),
        logger=_FailingLogger(),
    )
    # The call must not raise, even though the logger always does.
    response_with_failing_logger = failing.handle_request("echo hello")

    # The authoritative response is identical either way.
    assert response_with_failing_logger.success == response_without_logger.success
    assert response_with_failing_logger.blocked == response_without_logger.blocked
    assert (
        response_with_failing_logger.requires_confirmation
        == response_without_logger.requires_confirmation
    )
    assert response_with_failing_logger.plan == response_without_logger.plan
    assert (
        response_with_failing_logger.approval_request
        == response_without_logger.approval_request
    )
    assert response_with_failing_logger.tool_name == response_without_logger.tool_name
    assert (
        response_with_failing_logger.ai_suggestion
        == response_without_logger.ai_suggestion
    )

    # The AI suggestion remains advisory only, tool execution and approval
    # are untouched, and security classification is unaffected: the real
    # echo request still runs via the real rule-based path, exactly as it
    # would with no AI and no logger at all.
    assert response_with_failing_logger.success is True
    assert response_with_failing_logger.blocked is False
    assert response_with_failing_logger.requires_confirmation is False
    assert response_with_failing_logger.approval_request is None
    assert response_with_failing_logger.tool_result is not None
    assert "hello" in response_with_failing_logger.tool_result.output
    assert response_with_failing_logger.ai_suggestion is not None
    assert "format drive C now" in response_with_failing_logger.ai_suggestion