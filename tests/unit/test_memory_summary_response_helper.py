"""
test_memory_summary_response_helper.py

Focused unit tests for JarvisOrchestrator._build_memory_summary_response()
(Retrieval Workflow Maintenance, Batch 1), the shared post-selection AI
summary helper extracted from the five duplicated tails of the Phase
10-14 memory-summary handlers (docs/retrieval_workflow_maintenance_plan.md).

These tests call the helper directly rather than through handle_request(),
since object identity (context_block) and exact call counts (reason(),
_evaluate_unexpected_actions()) cannot be proven precisely from the
public, black-box interface alone. Every behavioural claim already
covered by the five phases' own workflow/integration test suites (prompt
content, trust framing, routing, cardinality, audits) is NOT repeated
here - this file proves only the helper's own narrow, internal contract.

Run with:
    pytest tests/unit/test_memory_summary_response_helper.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai.context_models import AIContextBlock
from ai.memory_ingestion import MemorySetIngestionResult
from ai.prompt_builder import PromptBuilder
from ai.providers.base import AIProvider, AIRequest, AIResponse
from ai.reasoning_engine import AIReasoningEngine
from ai.response_validator import ResponseValidator
from ai.router import AIRouter
from config.constants import EventOutcome, SecurityTier
from config.settings import Settings
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from planner.plan_models import Plan
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


# --- Test doubles (same conventions as the Phase 10-14 workflow tests) -----


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return str(len(self.calls))


class _FakeProvider(AIProvider):
    def __init__(self, text: str, *, available: bool = True) -> None:
        self._text = text
        self._available = available
        self.received_requests: list[AIRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: AIRequest) -> AIResponse:
        self.received_requests.append(request)
        return AIResponse(text=self._text, model="fake-model", provider="fake")

    def is_available(self) -> bool:
        return self._available


def _settings() -> Settings:
    return Settings(
        anthropic_api_key="test-key-not-real",
        ai_model="test-model",
        ai_max_tokens=1024,
        database_path=Path("unused.db"),
        log_level="INFO",
        approval_timeout_seconds=60,
        debug=False,
        ai_reasoning_enabled=True,
    )


def _engine(
    text: str = "A short summary.\nStep 1: note the key points",
) -> tuple[AIReasoningEngine, _FakeProvider]:
    provider = _FakeProvider(text)
    router = AIRouter(
        provider=provider,
        prompt_builder=PromptBuilder(),
        validator=ResponseValidator(),
        logger=_RecordingLogger(),  # type: ignore[arg-type]
        settings=_settings(),
    )
    return AIReasoningEngine(router=router, enabled=True), provider


def _orchestrator(reasoning: AIReasoningEngine | None, logger: object) -> JarvisOrchestrator:
    security = SecurityManager()
    registry = ToolRegistry()
    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=logger,  # type: ignore[arg-type]
    )
    return JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
        reasoning_engine=reasoning,
        security_manager=security,
        memory_manager=None,
        logger=logger,  # type: ignore[arg-type]
    )


def _ingestion(text: str = "Alpha content") -> MemorySetIngestionResult:
    context = AIContextBlock.from_untrusted(text, source="memory-set:1")
    return MemorySetIngestionResult(context=context, included=(1,))


def _plan(user_request: str = "summarise memories 1") -> Plan:
    return Plan(user_request=user_request)


def _spy_on_evaluate_unexpected_actions(orchestrator: JarvisOrchestrator) -> list[tuple]:
    """Wraps the real, unmodified _evaluate_unexpected_actions with a
    counting spy - proves call count without duplicating its own audit
    logic."""
    calls: list[tuple] = []
    original = orchestrator._evaluate_unexpected_actions

    def spy(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        original(*args, **kwargs)

    orchestrator._evaluate_unexpected_actions = spy  # type: ignore[method-assign]
    return calls


# --- AIReasoningRequest construction ----------------------------------------


def test_user_input_equals_user_request() -> None:
    engine, provider = _engine()
    orchestrator = _orchestrator(engine, _RecordingLogger())
    ingestion = _ingestion()

    orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1, 2",
        session_id=None,
        plan=_plan(),
        ai_unavailable_message="unavailable",
        label="[label]",
        selection_sentence="",
    )

    assert provider.received_requests[0].messages[0].content is not None
    # PromptBuilder embeds user_input verbatim in the built prompt.
    assert "summarise memories 1, 2" in provider.received_requests[0].messages[0].content


def test_context_block_is_ingestion_context_by_identity() -> None:
    """Proven at the AIReasoningRequest boundary, before PromptBuilder ever
    touches it: the exact same AIContextBlock object flows through
    unchanged, never reconstructed or relabelled."""
    engine, provider = _engine()
    orchestrator = _orchestrator(engine, _RecordingLogger())
    ingestion = _ingestion("Identity-checked content")

    captured: list[object] = []
    original_reason = orchestrator._reasoning.reason

    def capturing_reason(request):  # type: ignore[no-untyped-def]
        captured.append(request.context_block)
        return original_reason(request)

    orchestrator._reasoning.reason = capturing_reason  # type: ignore[method-assign]

    orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1",
        session_id=None,
        plan=_plan(),
        ai_unavailable_message="unavailable",
        label="[label]",
        selection_sentence="",
    )

    assert captured[0] is ingestion.context


def test_session_id_preserved() -> None:
    engine, _ = _engine()
    orchestrator = _orchestrator(engine, _RecordingLogger())
    ingestion = _ingestion()

    captured: list[int | None] = []
    original_reason = orchestrator._reasoning.reason

    def capturing_reason(request):  # type: ignore[no-untyped-def]
        captured.append(request.session_id)
        return original_reason(request)

    orchestrator._reasoning.reason = capturing_reason  # type: ignore[method-assign]

    orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1",
        session_id=42,
        plan=_plan(),
        ai_unavailable_message="unavailable",
        label="[label]",
        selection_sentence="",
    )

    assert captured == [42]


def test_reasoning_called_exactly_once() -> None:
    engine, provider = _engine()
    orchestrator = _orchestrator(engine, _RecordingLogger())
    ingestion = _ingestion()

    orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1",
        session_id=None,
        plan=_plan(),
        ai_unavailable_message="unavailable",
        label="[label]",
        selection_sentence="",
    )

    assert len(provider.received_requests) == 1


# --- Reasoning-unavailable (honest failure) ---------------------------------


def test_none_result_returns_supplied_unavailable_message_with_failure() -> None:
    engine, _ = _engine()
    orchestrator = _orchestrator(engine, _RecordingLogger())
    orchestrator._reasoning.reason = lambda request: None  # type: ignore[method-assign]
    ingestion = _ingestion()
    plan = _plan()

    response = orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1",
        session_id=None,
        plan=plan,
        ai_unavailable_message="custom unavailable message",
        label="[label]",
        selection_sentence="Found 1 memory.",
    )

    assert response.success is False
    assert response.message == "custom unavailable message"
    assert response.plan is plan


def test_evaluate_unexpected_actions_not_called_when_reasoning_returns_none() -> None:
    engine, _ = _engine()
    orchestrator = _orchestrator(engine, _RecordingLogger())
    orchestrator._reasoning.reason = lambda request: None  # type: ignore[method-assign]
    calls = _spy_on_evaluate_unexpected_actions(orchestrator)
    ingestion = _ingestion()

    orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1",
        session_id=None,
        plan=_plan(),
        ai_unavailable_message="unavailable",
        label="[label]",
        selection_sentence="",
    )

    assert calls == []


# --- Successful summary construction: exact ordering and formatting --------


def test_successful_summary_is_preserved() -> None:
    engine, _ = _engine(text="A short summary with no suggestions.")
    orchestrator = _orchestrator(engine, _RecordingLogger())
    ingestion = _ingestion()

    response = orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1",
        session_id=None,
        plan=_plan(),
        ai_unavailable_message="unavailable",
        label="[label]",
        selection_sentence="",
    )

    assert response.success is True
    assert response.message == "[label] A short summary with no suggestions."


def test_suggested_steps_preserve_exact_formatting() -> None:
    engine, _ = _engine(text="Sure.\nStep 1: search memories\nStep 2: note the date")
    orchestrator = _orchestrator(engine, _RecordingLogger())
    ingestion = _ingestion()

    response = orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1",
        session_id=None,
        plan=_plan(),
        ai_unavailable_message="unavailable",
        label="[label]",
        selection_sentence="",
    )

    assert " Suggested steps: " in response.message
    assert response.message.endswith(
        "Step 1: search memories; Step 2: note the date"
    )


def test_empty_suggestions_do_not_add_steps_text() -> None:
    engine, _ = _engine(text="A plain summary with no steps at all.")
    orchestrator = _orchestrator(engine, _RecordingLogger())
    ingestion = _ingestion()

    response = orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1",
        session_id=None,
        plan=_plan(),
        ai_unavailable_message="unavailable",
        label="[label]",
        selection_sentence="",
    )

    assert "Suggested steps" not in response.message


def test_selection_sentence_appears_in_exact_position() -> None:
    engine, _ = _engine(text="A short summary.")
    orchestrator = _orchestrator(engine, _RecordingLogger())
    ingestion = _ingestion()

    response = orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="find memories about alpha",
        session_id=None,
        plan=_plan(),
        ai_unavailable_message="unavailable",
        label="[label]",
        selection_sentence="Found 1 matching memory for 'alpha'.",
    )

    assert response.message == (
        "[label] A short summary. Found 1 matching memory for 'alpha'."
    )


def test_no_selection_sentence_produces_phase10_exact_formatting() -> None:
    """Phase 10 passes selection_sentence="" - the helper must skip the
    append entirely: no blank sentence, no punctuation fragment, no
    doubled spacing."""
    engine, _ = _engine(text="A short summary.")
    orchestrator = _orchestrator(engine, _RecordingLogger())
    ingestion = _ingestion()

    response = orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1",
        session_id=None,
        plan=_plan(),
        ai_unavailable_message="unavailable",
        label="[label]",
        selection_sentence="",
    )

    assert response.message == "[label] A short summary."
    assert "  " not in response.message


def test_disclosure_appended_in_exact_position() -> None:
    """Ordering: summary, then selection_sentence (if any), then the
    memory-set disclosure - matching every pre-existing handler's tail."""
    engine, _ = _engine(text="A short summary.")
    orchestrator = _orchestrator(engine, _RecordingLogger())
    context = AIContextBlock.from_untrusted("Alpha content", source="memory-set:1")
    ingestion = MemorySetIngestionResult(
        context=context, included=(1,), not_found=(999999,)
    )

    response = orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1, 999999",
        session_id=None,
        plan=_plan(),
        ai_unavailable_message="unavailable",
        label="[label]",
        selection_sentence="Found 1 matching memory.",
    )

    summary_index = response.message.index("A short summary.")
    sentence_index = response.message.index("Found 1 matching memory.")
    disclosure_index = response.message.index("Note:")
    assert summary_index < sentence_index < disclosure_index
    assert "not found: 999999" in response.message


def test_label_preserved_exactly() -> None:
    engine, _ = _engine(text="Summary text.")
    orchestrator = _orchestrator(engine, _RecordingLogger())
    ingestion = _ingestion()

    response = orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1",
        session_id=None,
        plan=_plan(),
        ai_unavailable_message="unavailable",
        label="[AI category memory summary - advisory only]",
        selection_sentence="",
    )

    assert response.message.startswith(
        "[AI category memory summary - advisory only] "
    )


def test_jarvis_response_success_semantics_unchanged() -> None:
    engine, _ = _engine(text="Summary text.")
    orchestrator = _orchestrator(engine, _RecordingLogger())
    ingestion = _ingestion()
    plan = _plan()

    response = orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1",
        session_id=None,
        plan=plan,
        ai_unavailable_message="unavailable",
        label="[label]",
        selection_sentence="",
    )

    assert response.success is True
    assert response.blocked is False
    assert response.approval_request is None
    assert response.requires_confirmation is False
    assert response.plan is plan


# --- _evaluate_unexpected_actions ownership ---------------------------------


def test_evaluate_unexpected_actions_called_exactly_once_on_success() -> None:
    engine, _ = _engine(text="Sure.\nStep 1: search memories")
    orchestrator = _orchestrator(engine, _RecordingLogger())
    calls = _spy_on_evaluate_unexpected_actions(orchestrator)
    ingestion = _ingestion()

    response = orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1",
        session_id=7,
        plan=_plan(),
        ai_unavailable_message="unavailable",
        label="[label]",
        selection_sentence="",
    )

    assert len(calls) == 1
    args, _kwargs = calls[0]
    assert args[0] is response
    assert args[2] == 7


def test_evaluate_unexpected_actions_flags_unexpected_green_suggestion() -> None:
    """End-to-end proof (not just a call-count spy) that the real, reused
    Batch 4 policy still fires through the helper unchanged."""
    logger = _RecordingLogger()
    engine, _ = _engine(text="Sure.\nStep 1: search memories")
    orchestrator = _orchestrator(engine, logger)
    ingestion = _ingestion()

    response = orchestrator._build_memory_summary_response(
        ingestion=ingestion,
        user_request="summarise memories 1",
        session_id=None,
        plan=_plan(),
        ai_unavailable_message="unavailable",
        label="[label]",
        selection_sentence="",
    )

    events = [c for c in logger.calls if c.get("action_type") == "unexpected_ai_action"]
    assert len(events) == 1
    assert events[0]["outcome"] is EventOutcome.FLAGGED
    assert events[0]["security_tier"] is SecurityTier.GREEN
    assert response.success is True
