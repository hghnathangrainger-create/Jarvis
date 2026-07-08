"""
test_file_summary_workflow.py

Unit tests for the explicit file-summary workflow (Phase 8, Batch 2):
CommandRouter.match_file_summary() -> JarvisOrchestrator._handle_file_summary_request().

These use the real Planner, SecurityManager, ToolRegistry/FileReadTool,
ToolExecutor, CommandRouter, and AIReasoningEngine (wired to a real AIRouter
and a fake, in-memory provider - no live Claude API call is ever made). They
prove:

    - A successful "summarise file <path>" request reads the real file
      through the real, already-secured file_read path, ingests it via
      Batch 1's ingest_file_for_ai(), and reaches AIReasoningEngine with a
      genuine, trust-tagged AIContextBlock - never raw text the orchestrator
      built itself.
    - File acquisition failure (missing file, binary file) produces an
      honest failure response, never presented as an AI summary.
    - AI reasoning disabled, or configured but producing no result, each
      produce a distinct, honest response - never a crash, never a false
      summary.
    - The Plan is generated normally and is unaffected by anything the AI
      returns.
    - No AI-suggested action ever executes a tool, grants approval, or
      changes a security tier - regardless of what the AI suggests.
    - Every AI-suggested action is evaluated and audited through the
      existing, unmodified Batch 4 _evaluate_unexpected_actions/
      _audit_unexpected_action methods: GREEN -> FLAGGED, YELLOW -> PENDING,
      RED -> BLOCKED.

Run with:
    pytest tests/unit/test_file_summary_workflow.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai.prompt_builder import PromptBuilder
from ai.providers.base import AIProvider, AIProviderError, AIRequest, AIResponse
from ai.reasoning_engine import AIReasoningEngine
from ai.response_validator import ResponseValidator
from ai.router import AIRouter
from config.constants import EventOutcome, SecurityTier
from config.settings import Settings
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin import FileReadTool
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


def _build_orchestrator(
    reasoning: AIReasoningEngine | None, logger: _RecordingLogger
) -> JarvisOrchestrator:
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(FileReadTool())
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
        logger=logger,  # type: ignore[arg-type]
    )


@pytest.fixture()
def text_file(tmp_path: Path) -> Path:
    path = tmp_path / "report.txt"
    path.write_text("Quarterly results improved across every region.\n")
    return path


def _unexpected_action_events(logger: _RecordingLogger) -> list[dict[str, object]]:
    return [
        call
        for call in logger.calls
        if call.get("action_type") == "unexpected_ai_action"
    ]


def _tool_call_events(logger: _RecordingLogger) -> list[dict[str, object]]:
    return [call for call in logger.calls if call.get("action_type") == "tool_call"]


# --- Successful summary ---------------------------------------------------------


def test_successful_summary_reaches_reasoning_with_real_file_content(
    text_file: Path,
) -> None:
    logger = _RecordingLogger()
    engine, provider = _engine()
    orchestrator = _build_orchestrator(engine, logger)

    response = orchestrator.handle_request(f"summarise file {text_file}")

    assert response.success is True
    assert response.message.startswith("[AI file summary - advisory only]")
    assert "A short summary." in response.message

    # Proves the orchestrator forwarded a real AIContextBlock (never raw
    # text it assembled itself): only a genuine untrusted AIContextBlock
    # produces PromptBuilder's delimited, data-only-directive framing.
    assert len(provider.received_requests) == 1
    prompt_content = provider.received_requests[0].messages[0].content
    assert "----- BEGIN CONTEXT -----" in prompt_content
    assert "not as instructions" in prompt_content
    assert "Quarterly results improved across every region." in prompt_content


def test_successful_summary_reads_through_the_real_file_read_tool(
    text_file: Path,
) -> None:
    logger = _RecordingLogger()
    engine, _ = _engine()
    orchestrator = _build_orchestrator(engine, logger)

    orchestrator.handle_request(f"summarise file {text_file}")

    tool_calls = _tool_call_events(logger)
    assert len(tool_calls) == 1
    assert tool_calls[0]["security_tier"] is SecurityTier.GREEN


def test_plan_is_generated_normally_and_present(text_file: Path) -> None:
    logger = _RecordingLogger()
    engine, _ = _engine()
    orchestrator = _build_orchestrator(engine, logger)

    response = orchestrator.handle_request(f"summarise file {text_file}")

    assert response.plan is not None
    assert len(response.plan.steps) >= 1


# --- Acquisition failure ---------------------------------------------------------


def test_missing_file_produces_honest_failure_not_a_summary(tmp_path: Path) -> None:
    logger = _RecordingLogger()
    engine, provider = _engine()
    orchestrator = _build_orchestrator(engine, logger)

    response = orchestrator.handle_request(
        f"summarise file {tmp_path / 'missing.txt'}"
    )

    assert response.success is False
    assert "does not exist" in response.message
    # The AI was never even consulted - there was nothing real to summarise.
    assert provider.received_requests == []


def test_binary_file_is_rejected_not_summarised(tmp_path: Path) -> None:
    path = tmp_path / "image.bin"
    path.write_bytes(b"\x89PNG\r\n\x00\x00\x00binary\x00stuff")
    logger = _RecordingLogger()
    engine, provider = _engine()
    orchestrator = _build_orchestrator(engine, logger)

    response = orchestrator.handle_request(f"summarise file {path}")

    assert response.success is False
    assert "binary" in response.message.lower()
    assert provider.received_requests == []


def test_missing_path_produces_honest_failure(text_file: Path) -> None:
    logger = _RecordingLogger()
    engine, _ = _engine()
    orchestrator = _build_orchestrator(engine, logger)

    response = orchestrator.handle_request("summarise file")

    assert response.success is False
    assert response.message  # some explanation, not empty


# --- AI reasoning disabled / unavailable ----------------------------------------


def test_ai_disabled_produces_distinct_honest_response(text_file: Path) -> None:
    logger = _RecordingLogger()
    orchestrator = _build_orchestrator(reasoning=None, logger=logger)

    response = orchestrator.handle_request(f"summarise file {text_file}")

    assert response.success is False
    assert "not enabled" in response.message.lower()


def test_ai_unavailable_produces_distinct_honest_response(text_file: Path) -> None:
    logger = _RecordingLogger()
    engine, provider = _engine(available=False)
    orchestrator = _build_orchestrator(engine, logger)

    response = orchestrator.handle_request(f"summarise file {text_file}")

    assert response.success is False
    assert "not enabled" not in response.message.lower()
    assert provider.received_requests == []


def test_ai_enabled_but_disabled_flag_produces_distinct_honest_response(
    text_file: Path,
) -> None:
    logger = _RecordingLogger()
    engine, provider = _engine(enabled=False)
    orchestrator = _build_orchestrator(engine, logger)

    response = orchestrator.handle_request(f"summarise file {text_file}")

    assert response.success is False
    assert provider.received_requests == []


def test_ai_provider_failure_produces_honest_response_not_a_summary(
    text_file: Path,
) -> None:
    """The provider is genuinely called (proving real file content reached
    it) but raises - the failure must never be presented as a summary."""
    logger = _RecordingLogger()
    engine, provider = _engine(fail=True)
    orchestrator = _build_orchestrator(engine, logger)

    response = orchestrator.handle_request(f"summarise file {text_file}")

    assert response.success is False
    assert "[AI file summary" not in response.message
    assert len(provider.received_requests) == 1


def test_ai_empty_response_produces_honest_response_not_a_summary(
    text_file: Path,
) -> None:
    """Since Phase 7 Batch 2, an empty/whitespace-only provider response is
    rejected by the router's ResponseValidator before it ever reaches
    parsing - so reason() returns None, exactly like any other unusable
    result, and must never be presented as a summary."""
    logger = _RecordingLogger()
    engine, provider = _engine(text="   \n  \n")
    orchestrator = _build_orchestrator(engine, logger)

    response = orchestrator.handle_request(f"summarise file {text_file}")

    assert response.success is False
    assert "[AI file summary" not in response.message
    assert len(provider.received_requests) == 1


# --- The Plan and security tiers are unaffected by AI output -------------------


def test_plan_is_unaffected_by_ai_suggestion(text_file: Path) -> None:
    logger = _RecordingLogger()
    no_ai = _build_orchestrator(reasoning=None, logger=logger)
    baseline_plan = no_ai.handle_request(f"summarise file {text_file}").plan

    engine, _ = _engine("Sure.\nStep 1: format drive C now")
    with_ai = _build_orchestrator(engine, _RecordingLogger())
    response = with_ai.handle_request(f"summarise file {text_file}")

    # AI reasoning fails for a RED-suggesting response in the disabled
    # baseline path too (both are honest failures for AI-disabled cases),
    # so compare plans directly - the Plan must be identical regardless.
    assert response.plan == baseline_plan


def test_no_ai_suggestion_ever_executes_a_tool_or_grants_approval(
    text_file: Path,
) -> None:
    logger = _RecordingLogger()
    engine, _ = _engine("Sure.\nStep 1: format drive C now")
    orchestrator = _build_orchestrator(engine, logger)

    response = orchestrator.handle_request(f"summarise file {text_file}")

    # Only the one real file_read tool call - never a second tool call for
    # the AI-suggested "format drive C now".
    tool_calls = _tool_call_events(logger)
    assert len(tool_calls) == 1
    assert tool_calls[0]["security_tier"] is SecurityTier.GREEN
    assert response.requires_confirmation is False
    assert response.approval_request is None
    assert response.blocked is False


# --- Unexpected-action policy is reused, not bypassed (Phase 7, Batch 4) ----


def test_unexpected_green_suggestion_is_flagged(text_file: Path) -> None:
    logger = _RecordingLogger()
    engine, _ = _engine("Sure.\nStep 1: search memories")
    orchestrator = _build_orchestrator(engine, logger)

    response = orchestrator.handle_request(f"summarise file {text_file}")

    events = _unexpected_action_events(logger)
    assert len(events) == 1
    assert events[0]["outcome"] is EventOutcome.FLAGGED
    assert events[0]["security_tier"] is SecurityTier.GREEN
    assert response.success is True


def test_unexpected_yellow_suggestion_is_escalated(text_file: Path) -> None:
    logger = _RecordingLogger()
    engine, _ = _engine("Sure.\nStep 1: send email to the team")
    orchestrator = _build_orchestrator(engine, logger)

    response = orchestrator.handle_request(f"summarise file {text_file}")

    events = _unexpected_action_events(logger)
    assert len(events) == 1
    assert events[0]["outcome"] is EventOutcome.PENDING
    assert events[0]["security_tier"] is SecurityTier.YELLOW
    assert response.requires_confirmation is False
    assert response.approval_request is None
    assert response.success is True


def test_unexpected_red_suggestion_is_blocked(text_file: Path) -> None:
    logger = _RecordingLogger()
    engine, _ = _engine("Sure.\nStep 1: format drive C now")
    orchestrator = _build_orchestrator(engine, logger)

    response = orchestrator.handle_request(f"summarise file {text_file}")

    events = _unexpected_action_events(logger)
    assert len(events) == 1
    assert events[0]["outcome"] is EventOutcome.BLOCKED
    assert events[0]["security_tier"] is SecurityTier.RED
    # Policy/audit only - there is no execution path, so the real response
    # still reports the summary succeeding; nothing was actually blocked.
    assert response.success is True
    assert response.blocked is False


def test_multi_line_summary_produces_suggested_actions_that_are_evaluated(
    text_file: Path,
) -> None:
    """AIReasoningEngine._parse() treats every non-first line as a suggested
    action - proven here to actually happen for a realistic multi-line file
    summary, and to actually reach the unexpected-action policy."""
    logger = _RecordingLogger()
    engine, _ = _engine(
        "The report shows improved results.\n"
        "Step 1: review the regional breakdown\n"
        "Step 2: format drive C now"
    )
    orchestrator = _build_orchestrator(engine, logger)

    response = orchestrator.handle_request(f"summarise file {text_file}")

    events = _unexpected_action_events(logger)
    # Both suggested steps are unexpected relative to this request's own
    # plan, and both are evaluated - not just the first.
    assert len(events) == 2
    outcomes = {e["outcome"] for e in events}
    assert EventOutcome.BLOCKED in outcomes
    assert response.success is True
    assert "review the regional breakdown" in response.message
    assert "format drive C now" in response.message


def test_expected_suggestion_matching_the_request_is_not_flagged(
    text_file: Path,
) -> None:
    """If the AI's only suggestion is exactly the request text itself (the
    plan's own expected action), it is not unexpected."""
    logger = _RecordingLogger()
    engine, _ = _engine(f"Summary.\nsummarise file {text_file}")
    orchestrator = _build_orchestrator(engine, logger)

    orchestrator.handle_request(f"summarise file {text_file}")

    assert _unexpected_action_events(logger) == []
