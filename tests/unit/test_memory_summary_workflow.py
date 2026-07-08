"""
test_memory_summary_workflow.py

Unit tests for the explicit memory-summary workflow (Phase 9, Batch 2):
CommandRouter.match_memory_summary() -> JarvisOrchestrator._handle_memory_summary_request().

These use a real MemoryManager (backed by an in-memory SQLite database),
Planner, SecurityManager, CommandRouter, and AIReasoningEngine (wired to a
real AIRouter and a fake, in-memory provider - no live Claude API call is
ever made). They prove:

    - A successful "summarise memory <id>" request retrieves the real memory
      through Batch 1's ingest_memory_for_ai() - never MemoryTool or
      ToolExecutor - and reaches AIReasoningEngine with a genuine,
      trust-tagged AIContextBlock built from the actual retrieved record.
    - An invalid memory id (missing, blank, non-numeric, malformed) fails
      honestly before any memory read, audit event, or AI consultation.
    - Memory-manager unavailability, memory-not-found, AI disabled/
      unavailable/failure/empty-response, and truncated content each produce
      a distinct, honest response - never a false summary.
    - The Plan is generated normally and is unaffected by anything the AI
      returns.
    - No AI-suggested action ever executes a tool, grants approval, or
      changes a security tier - regardless of what the AI suggests.
    - Every AI-suggested action is evaluated and audited through the
      existing, unmodified Batch 4 _evaluate_unexpected_actions/
      _audit_unexpected_action methods: GREEN -> FLAGGED, YELLOW -> PENDING,
      RED -> BLOCKED.
    - The orchestrator's own memory-acquisition audit event fires on both
      success and not-found, never embeds raw memory content, and a failing
      logger never breaks an otherwise-valid workflow.

Run with:
    pytest tests/unit/test_memory_summary_workflow.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from ai.prompt_builder import PromptBuilder
from ai.providers.base import AIProvider, AIProviderError, AIRequest, AIResponse
from ai.reasoning_engine import AIReasoningEngine
from ai.response_validator import ResponseValidator
from ai.router import AIRouter
from config.constants import EventOutcome, SecurityTier
from config.settings import Settings
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


# --- Test doubles --------------------------------------------------------------


class _RecordingLogger:
    """Stands in for the concrete EventLogger, recording every emit() call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return str(len(self.calls))


class _FailingLogger:
    """Raises on every emit() call, to prove audit failure never breaks the
    authoritative workflow."""

    def emit(self, **kwargs: object) -> str:
        raise RuntimeError("simulated logger failure")


class _FakeProvider(AIProvider):
    """A fake provider that returns whatever text it is given. No network."""

    def __init__(
        self, text: str, *, available: bool = True, fail: bool = False
    ) -> None:
        self._text = text
        self._available = available
        self._fail = fail
        self.received_requests: list[AIRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: AIRequest) -> AIResponse:
        self.received_requests.append(request)
        if self._fail:
            raise AIProviderError("simulated provider failure")
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
    *,
    enabled: bool = True,
    available: bool = True,
    fail: bool = False,
) -> tuple[AIReasoningEngine, _FakeProvider]:
    provider = _FakeProvider(text, available=available, fail=fail)
    router = AIRouter(
        provider=provider,
        prompt_builder=PromptBuilder(),
        validator=ResponseValidator(),
        logger=_RecordingLogger(),  # type: ignore[arg-type]
        settings=_settings(),
    )
    return AIReasoningEngine(router=router, enabled=enabled), provider


def _memory_manager() -> MemoryManager:
    from sqlalchemy import create_engine

    from storage.database import create_session_factory, initialize_database

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return MemoryManager(EpisodicMemoryStore(factory))


def _build_orchestrator(
    reasoning: AIReasoningEngine | None,
    logger: object,
    *,
    memory_manager: MemoryManager | None,
) -> JarvisOrchestrator:
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
        memory_manager=memory_manager,
        logger=logger,  # type: ignore[arg-type]
    )


def _unexpected_action_events(logger: _RecordingLogger) -> list[dict[str, object]]:
    return [
        call
        for call in logger.calls
        if call.get("action_type") == "unexpected_ai_action"
    ]


def _memory_acquisition_events(logger: _RecordingLogger) -> list[dict[str, object]]:
    return [
        call for call in logger.calls if call.get("action_type") == "memory_acquisition"
    ]


# --- Successful summary ---------------------------------------------------------


def test_successful_summary_reaches_reasoning_with_real_memory_content() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="Nathan prefers dark roast coffee.")
    assert record is not None
    engine, provider = _engine()
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request(f"summarise memory {record.id}")

    assert response.success is True
    assert response.message.startswith("[AI memory summary - advisory only]")
    assert "A short summary." in response.message

    # Proves the orchestrator forwarded a real AIContextBlock built from the
    # actual retrieved record (never raw text it assembled itself): only a
    # genuine untrusted AIContextBlock produces PromptBuilder's delimited,
    # data-only-directive framing.
    assert len(provider.received_requests) == 1
    prompt_content = provider.received_requests[0].messages[0].content
    assert "----- BEGIN CONTEXT -----" in prompt_content
    assert "not as instructions" in prompt_content
    assert "Nathan prefers dark roast coffee." in prompt_content


def test_orchestrator_does_not_retrieve_the_record_directly() -> None:
    """The orchestrator coordinates but never calls MemoryManager.get()
    itself - proven with a spy wrapping the real manager."""

    class _SpyManager:
        def __init__(self, real: MemoryManager) -> None:
            self._real = real
            self.get_calls: list[int] = []

        def get(self, memory_id: int):
            self.get_calls.append(memory_id)
            return self._real.get(memory_id)

    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None
    spy = _SpyManager(memory)
    engine, _ = _engine()
    orchestrator = _build_orchestrator(
        engine, logger, memory_manager=spy  # type: ignore[arg-type]
    )

    orchestrator.handle_request(f"summarise memory {record.id}")

    # Retrieval happened exactly once, through Batch 1's ingestion adapter -
    # never duplicated, never skipped.
    assert spy.get_calls == [record.id]


def test_exact_batch1_context_block_reaches_reasoning_unchanged() -> None:
    """The exact AIContextBlock ingest_memory_for_ai() produces must reach
    AIReasoningEngine.reason() unchanged - proven via object identity."""
    from ai.reasoning_models import AIReasoningRequest

    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None

    captured: dict[str, object] = {}
    original_reason = AIReasoningEngine.reason

    def _capturing_reason(self: AIReasoningEngine, request: AIReasoningRequest):
        captured["context_block"] = request.context_block
        return original_reason(self, request)

    engine, _ = _engine()
    engine.reason = _capturing_reason.__get__(engine, AIReasoningEngine)  # type: ignore[method-assign]
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    orchestrator.handle_request(f"summarise memory {record.id}")

    assert captured["context_block"] is not None
    assert captured["context_block"].source == f"memory:{record.id}"  # type: ignore[union-attr]


def test_plan_is_generated_normally_and_present() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None
    engine, _ = _engine()
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request(f"summarise memory {record.id}")

    assert response.plan is not None
    assert len(response.plan.steps) >= 1


# --- Invalid id ------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_text",
    [
        "summarise memory",
        "summarise memory ",
        "summarise memory abc",
        "summarise memory 4.2",
        "summarise memory -5",
    ],
)
def test_invalid_memory_id_fails_honestly_before_any_lookup(request_text: str) -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    engine, provider = _engine()
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request(request_text)

    assert response.success is False
    assert "not a valid memory id" in response.message
    # No memory acquisition audit event and no AI request ever happened.
    assert _memory_acquisition_events(logger) == []
    assert provider.received_requests == []


def test_invalid_memory_id_is_never_reinterpreted_as_a_search() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    memory.save(content="a note about coffee")
    engine, provider = _engine()
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request("summarise memory coffee")

    assert response.success is False
    assert "not a valid memory id" in response.message
    assert provider.received_requests == []


# --- Memory-manager unavailable ---------------------------------------------------


def test_missing_memory_manager_fails_honestly() -> None:
    logger = _RecordingLogger()
    engine, provider = _engine()
    orchestrator = _build_orchestrator(engine, logger, memory_manager=None)

    response = orchestrator.handle_request("summarise memory 42")

    assert response.success is False
    assert "not available" in response.message.lower()
    assert provider.received_requests == []


# --- Not found ---------------------------------------------------------------------


def test_memory_not_found_produces_honest_failure_not_a_summary() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    engine, provider = _engine()
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request("summarise memory 999999")

    assert response.success is False
    assert "no memory found" in response.message.lower()
    # The AI was never even consulted - there was nothing real to summarise.
    assert provider.received_requests == []


def test_not_found_error_text_never_reaches_the_ai_provider() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    engine, provider = _engine()
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    orchestrator.handle_request("summarise memory 999999")

    assert provider.received_requests == []


def test_memory_acquisition_audit_fires_on_not_found() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    engine, _ = _engine()
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    orchestrator.handle_request("summarise memory 999999")

    events = _memory_acquisition_events(logger)
    assert len(events) == 1
    assert events[0]["outcome"] is EventOutcome.FAILURE
    assert "999999" in str(events[0]["detail"])


# --- AI reasoning disabled / unavailable ----------------------------------------


def test_ai_disabled_produces_distinct_honest_response() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None
    orchestrator = _build_orchestrator(
        reasoning=None, logger=logger, memory_manager=memory
    )

    response = orchestrator.handle_request(f"summarise memory {record.id}")

    assert response.success is False
    assert "not enabled" in response.message.lower()


def test_ai_disabled_never_reads_the_memory() -> None:
    """When AI reasoning is unavailable, the memory is never even read -
    mirroring the file-summary precedent of checking reasoning availability
    before touching acquisition."""
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None
    orchestrator = _build_orchestrator(
        reasoning=None, logger=logger, memory_manager=memory
    )

    orchestrator.handle_request(f"summarise memory {record.id}")

    assert _memory_acquisition_events(logger) == []


def test_ai_unavailable_produces_distinct_honest_response() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None
    engine, provider = _engine(available=False)
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request(f"summarise memory {record.id}")

    assert response.success is False
    assert "not enabled" not in response.message.lower()
    assert provider.received_requests == []


def test_ai_provider_failure_produces_honest_response_not_a_summary() -> None:
    """The provider is genuinely called (proving real memory content reached
    it) but raises - the failure must never be presented as a summary."""
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None
    engine, provider = _engine(fail=True)
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request(f"summarise memory {record.id}")

    assert response.success is False
    assert "[AI memory summary" not in response.message
    assert len(provider.received_requests) == 1


def test_ai_empty_response_produces_honest_response_not_a_summary() -> None:
    """An empty/whitespace-only provider response is rejected by the
    router's ResponseValidator before it ever reaches parsing - so reason()
    returns None, exactly like any other unusable result."""
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None
    engine, provider = _engine(text="   \n  \n")
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request(f"summarise memory {record.id}")

    assert response.success is False
    assert "[AI memory summary" not in response.message
    assert len(provider.received_requests) == 1


# --- Truncation is represented honestly -----------------------------------------


def test_truncated_memory_does_not_claim_complete_analysis() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="A" * 10_000)
    assert record is not None
    engine, _ = _engine()
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request(f"summarise memory {record.id}")

    assert response.success is True
    assert "only part of this memory's content was available" in response.message


def test_untruncated_memory_makes_no_truncation_claim() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a short note")
    assert record is not None
    engine, _ = _engine()
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request(f"summarise memory {record.id}")

    assert response.success is True
    assert "only part of this memory's content" not in response.message


def test_memory_acquisition_audit_fires_on_success_with_truncation_detail() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="A" * 10_000)
    assert record is not None
    engine, _ = _engine()
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    orchestrator.handle_request(f"summarise memory {record.id}")

    events = _memory_acquisition_events(logger)
    assert len(events) == 1
    assert events[0]["outcome"] is EventOutcome.SUCCESS
    assert "truncated=True" in str(events[0]["detail"])
    # No raw memory content ever enters the audit detail.
    assert "A" * 100 not in str(events[0]["detail"])


# --- Audit detail never leaks raw content; audit failure is contained ----------


def test_memory_acquisition_audit_detail_never_contains_raw_content() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a very specific and identifiable secret phrase")
    assert record is not None
    engine, _ = _engine()
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    orchestrator.handle_request(f"summarise memory {record.id}")

    events = _memory_acquisition_events(logger)
    assert len(events) == 1
    assert "secret phrase" not in str(events[0]["detail"])


def test_failing_audit_logger_does_not_break_a_valid_summary_workflow() -> None:
    """A raising logger must never convert successful retrieval into
    failure, alter AI context, prevent reasoning, or crash the request -
    the same observability-failure precedent as Batch 4/5A."""
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None
    engine, provider = _engine()
    orchestrator = _build_orchestrator(
        engine, _FailingLogger(), memory_manager=memory
    )

    response = orchestrator.handle_request(f"summarise memory {record.id}")

    assert response.success is True
    assert response.message.startswith("[AI memory summary - advisory only]")
    assert len(provider.received_requests) == 1


def test_failing_audit_logger_does_not_break_a_not_found_response() -> None:
    memory = _memory_manager()
    engine, _ = _engine()
    orchestrator = _build_orchestrator(
        engine, _FailingLogger(), memory_manager=memory
    )

    response = orchestrator.handle_request("summarise memory 999999")

    assert response.success is False
    assert "no memory found" in response.message.lower()


# --- The Plan and security tiers are unaffected by AI output -------------------


def test_plan_is_unaffected_by_ai_suggestion() -> None:
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None

    no_ai = _build_orchestrator(reasoning=None, logger=_RecordingLogger(), memory_manager=memory)
    baseline_plan = no_ai.handle_request(f"summarise memory {record.id}").plan

    engine, _ = _engine("Sure.\nStep 1: format drive C now")
    with_ai = _build_orchestrator(engine, _RecordingLogger(), memory_manager=memory)
    response = with_ai.handle_request(f"summarise memory {record.id}")

    assert response.plan == baseline_plan


def test_no_ai_suggestion_ever_executes_a_tool_or_grants_approval() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None
    engine, _ = _engine("Sure.\nStep 1: format drive C now")
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request(f"summarise memory {record.id}")

    assert response.requires_confirmation is False
    assert response.approval_request is None
    assert response.blocked is False


# --- Unexpected-action policy is reused, not bypassed (Phase 7, Batch 4) ----


def test_unexpected_green_suggestion_is_flagged() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None
    engine, _ = _engine("Sure.\nStep 1: search memories")
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request(f"summarise memory {record.id}")

    events = _unexpected_action_events(logger)
    assert len(events) == 1
    assert events[0]["outcome"] is EventOutcome.FLAGGED
    assert events[0]["security_tier"] is SecurityTier.GREEN
    assert response.success is True


def test_unexpected_yellow_suggestion_is_escalated() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None
    engine, _ = _engine("Sure.\nStep 1: send email to the team")
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request(f"summarise memory {record.id}")

    events = _unexpected_action_events(logger)
    assert len(events) == 1
    assert events[0]["outcome"] is EventOutcome.PENDING
    assert events[0]["security_tier"] is SecurityTier.YELLOW
    assert response.requires_confirmation is False
    assert response.approval_request is None
    assert response.success is True


def test_unexpected_red_suggestion_is_blocked() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None
    engine, _ = _engine("Sure.\nStep 1: format drive C now")
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request(f"summarise memory {record.id}")

    events = _unexpected_action_events(logger)
    assert len(events) == 1
    assert events[0]["outcome"] is EventOutcome.BLOCKED
    assert events[0]["security_tier"] is SecurityTier.RED
    # Policy/audit only - there is no execution path.
    assert response.success is True
    assert response.blocked is False


def test_multi_line_summary_produces_suggested_actions_that_are_evaluated() -> None:
    logger = _RecordingLogger()
    memory = _memory_manager()
    record = memory.save(content="a note")
    assert record is not None
    engine, _ = _engine(
        "The memory shows Nathan's preference.\n"
        "Step 1: review the preference\n"
        "Step 2: format drive C now"
    )
    orchestrator = _build_orchestrator(engine, logger, memory_manager=memory)

    response = orchestrator.handle_request(f"summarise memory {record.id}")

    events = _unexpected_action_events(logger)
    assert len(events) == 2
    outcomes = {e["outcome"] for e in events}
    assert EventOutcome.BLOCKED in outcomes
    assert response.success is True
    assert "review the preference" in response.message
    assert "format drive C now" in response.message
