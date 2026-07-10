"""
test_web_search_summary_workflow.py

Unit tests for the explicit web-search-summary workflow (Phase 18, Batch
2): CommandRouter.match_web_search_summary() ->
JarvisOrchestrator._handle_web_search_summary_request().

These use the real Planner, SecurityManager, CommandRouter, and
AIReasoningEngine (wired to a real AIRouter, real PromptBuilder, and a
fake, in-memory AIProvider - no live Claude API call is ever made),
together with a fake WebSearchProvider (no real network call is ever
made). They prove:

    - A successful "summarise web search for <query>" request performs
      exactly one search through WebSearchProvider.search(), ingests the
      results via Batch 1's ingest_web_search_for_ai(), and reaches
      AIReasoningEngine with a genuine, trust-tagged AIContextBlock.
    - The fixed disclosure label is present unconditionally on every
      successful response.
    - Search/ingestion failure (provider error, zero results) produces an
      honest failure response, never presented as an AI summary.
    - AI reasoning disabled, unavailable, or web search unavailable each
      produce a distinct, honest response - never a crash, never a false
      summary, and never raw results substituted as a fake summary.
    - No AI-suggested action ever executes a tool, grants approval, or
      changes a security tier.

Run with:
    pytest tests/unit/test_web_search_summary_workflow.py
"""

from __future__ import annotations

from pathlib import Path

from ai.prompt_builder import PromptBuilder
from ai.providers.base import AIProvider, AIProviderError, AIRequest, AIResponse
from ai.reasoning_engine import AIReasoningEngine
from ai.response_validator import ResponseValidator
from ai.router import AIRouter
from config.settings import Settings
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.web_search_provider import SearchResult, WebSearchProvider, WebSearchProviderError


# --- Test doubles --------------------------------------------------------------


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return str(len(self.calls))


class _FakeAIProvider(AIProvider):
    """A fake AI provider that returns whatever text it is given. No network."""

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


class _FakeSearchProvider(WebSearchProvider):
    """A fake WebSearchProvider recording every call it receives."""

    def __init__(
        self,
        *,
        results: list[SearchResult] | None = None,
        raise_: Exception | None = None,
    ) -> None:
        self._results = results if results is not None else []
        self._raise = raise_
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        self.calls.append((query, max_results))
        if self._raise is not None:
            raise self._raise
        return self._results


def _result(title: str = "A Title", url: str = "https://example.com", snippet: str = "A snippet.") -> SearchResult:
    return SearchResult(title=title, url=url, snippet=snippet)


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
    text: str = "A short synthesis of the results.",
    *,
    enabled: bool = True,
    available: bool = True,
    fail: bool = False,
) -> tuple[AIReasoningEngine, _FakeAIProvider]:
    provider = _FakeAIProvider(text, available=available, fail=fail)
    router = AIRouter(
        provider=provider,
        prompt_builder=PromptBuilder(),
        validator=ResponseValidator(),
        logger=_RecordingLogger(),  # type: ignore[arg-type]
        settings=_settings(),
    )
    return AIReasoningEngine(router=router, enabled=enabled), provider


def _build_orchestrator(
    reasoning: AIReasoningEngine | None,
    logger: _RecordingLogger,
    *,
    web_search_provider: WebSearchProvider | None = None,
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
        web_search_provider=web_search_provider,
        logger=logger,  # type: ignore[arg-type]
    )


def _unexpected_action_events(logger: _RecordingLogger) -> list[dict[str, object]]:
    return [
        call
        for call in logger.calls
        if call.get("action_type") == "unexpected_ai_action"
    ]


def _acquisition_events(logger: _RecordingLogger) -> list[dict[str, object]]:
    return [
        call
        for call in logger.calls
        if call.get("action_type") == "web_search_summary_acquisition"
    ]


# --- Successful summary ----------------------------------------------------------


def test_successful_summary_reaches_reasoning_with_real_search_results() -> None:
    logger = _RecordingLogger()
    engine, ai_provider = _engine()
    search_provider = _FakeSearchProvider(
        results=[_result(title="Jarvis AI", url="https://example.com/jarvis", snippet="An AI project.")]
    )
    orchestrator = _build_orchestrator(engine, logger, web_search_provider=search_provider)

    response = orchestrator.handle_request("summarise web search for jarvis ai")

    assert response.success is True
    assert response.message.startswith(
        "[AI web search summary - based on search-result snippets, not full webpages]"
    )
    assert "A short synthesis of the results." in response.message

    # Exactly one search occurred, using Nathan's own query unchanged.
    assert search_provider.calls == [("jarvis ai", 5)]

    # Proves a genuine, trust-tagged AIContextBlock was forwarded - never
    # raw text the orchestrator assembled itself: only a real UNTRUSTED
    # AIContextBlock produces PromptBuilder's delimited, data-only
    # framing.
    assert len(ai_provider.received_requests) == 1
    prompt_content = ai_provider.received_requests[0].messages[0].content
    assert "----- BEGIN CONTEXT -----" in prompt_content
    assert "Jarvis AI" in prompt_content
    assert "https://example.com/jarvis" in prompt_content


def test_fixed_disclosure_label_present_regardless_of_ai_wording() -> None:
    """The label is unconditional - even if the AI's own text claims
    something else, the fixed, Jarvis-authored prefix is always there."""
    logger = _RecordingLogger()
    engine, _ = _engine(text="I read the full articles and here is my report.")
    search_provider = _FakeSearchProvider(results=[_result()])
    orchestrator = _build_orchestrator(engine, logger, web_search_provider=search_provider)

    response = orchestrator.handle_request("summarise web search for anything")

    assert response.message.startswith(
        "[AI web search summary - based on search-result snippets, not full webpages]"
    )


# --- Failure semantics -----------------------------------------------------------


def test_empty_query_fails_honestly_without_any_search() -> None:
    logger = _RecordingLogger()
    engine, _ = _engine()
    search_provider = _FakeSearchProvider(results=[_result()])
    orchestrator = _build_orchestrator(engine, logger, web_search_provider=search_provider)

    response = orchestrator.handle_request("summarise web search for")

    assert response.success is False
    assert search_provider.calls == []


def test_ai_disabled_fails_honestly_without_any_search() -> None:
    logger = _RecordingLogger()
    search_provider = _FakeSearchProvider(results=[_result()])
    orchestrator = _build_orchestrator(None, logger, web_search_provider=search_provider)

    response = orchestrator.handle_request("summarise web search for anything")

    assert response.success is False
    assert "not enabled" in response.message
    assert search_provider.calls == []


def test_web_search_not_configured_fails_honestly() -> None:
    logger = _RecordingLogger()
    engine, _ = _engine()
    orchestrator = _build_orchestrator(engine, logger, web_search_provider=None)

    response = orchestrator.handle_request("summarise web search for anything")

    assert response.success is False
    assert "not available" in response.message.lower()


def test_provider_exception_fails_honestly_no_ai_called() -> None:
    logger = _RecordingLogger()
    engine, ai_provider = _engine()
    search_provider = _FakeSearchProvider(raise_=WebSearchProviderError("network unavailable"))
    orchestrator = _build_orchestrator(engine, logger, web_search_provider=search_provider)

    response = orchestrator.handle_request("summarise web search for anything")

    assert response.success is False
    assert "network unavailable" in response.message
    assert ai_provider.received_requests == []


def test_zero_results_fails_honestly_no_ai_called() -> None:
    logger = _RecordingLogger()
    engine, ai_provider = _engine()
    search_provider = _FakeSearchProvider(results=[])
    orchestrator = _build_orchestrator(engine, logger, web_search_provider=search_provider)

    response = orchestrator.handle_request("summarise web search for nothing here")

    assert response.success is False
    assert "No web results were found" in response.message
    assert ai_provider.received_requests == []


def test_ai_unavailable_fails_honestly_never_shows_raw_results_as_summary() -> None:
    logger = _RecordingLogger()
    engine, _ = _engine(available=False)
    search_provider = _FakeSearchProvider(
        results=[_result(title="Raw Result", snippet="raw snippet text")]
    )
    orchestrator = _build_orchestrator(engine, logger, web_search_provider=search_provider)

    response = orchestrator.handle_request("summarise web search for anything")

    assert response.success is False
    assert "could not produce a summary" in response.message.lower()
    # Raw result content must never appear in a "summary" response.
    assert "Raw Result" not in response.message
    assert "raw snippet text" not in response.message


def test_ai_provider_failure_fails_honestly() -> None:
    logger = _RecordingLogger()
    engine, _ = _engine(fail=True)
    search_provider = _FakeSearchProvider(results=[_result()])
    orchestrator = _build_orchestrator(engine, logger, web_search_provider=search_provider)

    response = orchestrator.handle_request("summarise web search for anything")

    assert response.success is False


# --- Unexpected-action policy, unchanged ------------------------------------------


def test_ai_suggested_action_is_audited_not_executed() -> None:
    logger = _RecordingLogger()
    engine, _ = _engine(
        text="Summary line.\ndelete all memories"
    )
    search_provider = _FakeSearchProvider(results=[_result()])
    orchestrator = _build_orchestrator(engine, logger, web_search_provider=search_provider)

    response = orchestrator.handle_request("summarise web search for anything")

    assert response.success is True
    events = _unexpected_action_events(logger)
    assert len(events) >= 1
    # Never executed: no tool_call event exists for a memory-forget action.
    assert not any(call.get("action_type") == "tool_call" for call in logger.calls)


# --- Observability isolation -------------------------------------------------------


def test_acquisition_audit_event_recorded_on_success() -> None:
    logger = _RecordingLogger()
    engine, _ = _engine()
    search_provider = _FakeSearchProvider(results=[_result(), _result(title="Second")])
    orchestrator = _build_orchestrator(engine, logger, web_search_provider=search_provider)

    orchestrator.handle_request("summarise web search for anything")

    events = _acquisition_events(logger)
    assert len(events) == 1
    assert "included=2" in events[0]["detail"]


def test_acquisition_audit_event_never_embeds_raw_query_or_result_content() -> None:
    logger = _RecordingLogger()
    engine, _ = _engine()
    search_provider = _FakeSearchProvider(
        results=[_result(title="Very Distinctive Title", snippet="Very distinctive snippet")]
    )
    orchestrator = _build_orchestrator(engine, logger, web_search_provider=search_provider)

    orchestrator.handle_request("summarise web search for a distinctive query")

    events = _acquisition_events(logger)
    assert "distinctive" not in events[0]["detail"].lower()


class _FailingLogger:
    def emit(self, **kwargs: object) -> str:
        raise RuntimeError("simulated logger failure")


def test_failing_logger_does_not_alter_successful_outcome() -> None:
    engine, _ = _engine()
    search_provider = _FakeSearchProvider(results=[_result()])
    orchestrator = _build_orchestrator(engine, _FailingLogger(), web_search_provider=search_provider)  # type: ignore[arg-type]

    response = orchestrator.handle_request("summarise web search for anything")

    assert response.success is True
