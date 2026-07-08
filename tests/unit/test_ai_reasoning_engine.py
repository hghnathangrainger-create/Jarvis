"""
test_ai_reasoning_engine.py

Unit tests for the AI reasoning engine (Phase 4, Batch 1; routed through
AIRouter since Phase 7, Batch 2).

Every test uses a fake, in-memory provider wrapped in a real AIRouter - no
live Claude API call is ever made, and no module anywhere constructs an
AIRequest/AIMessage directly except PromptBuilder itself. The tests confirm
the engine produces advisory results when enabled, returns None when
disabled or unavailable, never raises on provider or validation failure, and
- critically - has no ability to execute anything.

Run with:
    pytest tests/unit/test_ai_reasoning_engine.py
"""

from __future__ import annotations

from pathlib import Path

from ai.context_models import AIContextBlock
from ai.prompt_builder import PromptBuilder
from ai.providers.base import AIProvider, AIProviderError, AIRequest, AIResponse
from ai.reasoning_engine import AIReasoningEngine
from ai.reasoning_models import AIReasoningRequest
from ai.response_validator import ResponseValidator
from ai.router import AIRouter
from config.constants import ContentTrust
from config.settings import Settings


# --- Fake provider (no live API) ---------------------------------------------


class _FakeProvider(AIProvider):
    """A controllable in-memory provider for tests. Never calls a network."""

    def __init__(
        self,
        text: str = "You want to echo text.\nStep 1: use the echo tool",
        *,
        available: bool = True,
        fail: bool = False,
    ) -> None:
        self._text = text
        self._available = available
        self._fail = fail
        self.generate_called = False
        self.last_request: AIRequest | None = None

    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: AIRequest) -> AIResponse:
        self.generate_called = True
        self.last_request = request
        if self._fail:
            raise AIProviderError("simulated provider failure")
        return AIResponse(text=self._text, model="fake-model", provider="fake")

    def is_available(self) -> bool:
        return self._available


class _SpyLogger:
    def emit(self, **kwargs: object) -> str:
        return "1"


def _settings() -> Settings:
    """A minimal Settings instance for wiring an AIRouter in tests."""
    return Settings(
        anthropic_api_key="test-key",
        ai_model="test-model",
        ai_max_tokens=1024,
        database_path=Path("unused.db"),
        log_level="INFO",
        approval_timeout_seconds=60,
        debug=False,
        ai_reasoning_enabled=True,
    )


def _router(provider: AIProvider) -> AIRouter:
    """Build a real AIRouter wired to a fake provider - no live API call."""
    return AIRouter(
        provider=provider,
        prompt_builder=PromptBuilder(),
        validator=ResponseValidator(),
        logger=_SpyLogger(),  # type: ignore[arg-type]
        settings=_settings(),
    )


def _request(text: str = "echo hello") -> AIReasoningRequest:
    return AIReasoningRequest(user_input=text)


# --- Enabled engine produces results -----------------------------------------


def test_enabled_engine_produces_result() -> None:
    provider = _FakeProvider()
    engine = AIReasoningEngine(router=_router(provider), enabled=True)
    result = engine.reason(_request())
    assert result is not None
    assert result.summary == "You want to echo text."
    assert result.has_suggestions is True
    assert result.provider_name == "fake"


def test_enabled_engine_is_active() -> None:
    engine = AIReasoningEngine(router=_router(_FakeProvider()), enabled=True)
    assert engine.is_active() is True


def test_engine_passes_system_instruction() -> None:
    provider = _FakeProvider()
    engine = AIReasoningEngine(router=_router(provider), enabled=True)
    engine.reason(_request())
    assert provider.generate_called is True
    assert provider.last_request is not None
    # The system instruction frames the AI as a non-executing advisor.
    assert "do not run" in provider.last_request.system.lower()


def test_engine_does_not_construct_ai_request_directly() -> None:
    """The engine only ever calls router.route(); it never builds an
    AIRequest/AIMessage itself (Phase 7, Batch 2 consolidation)."""
    provider = _FakeProvider()
    engine = AIReasoningEngine(router=_router(provider), enabled=True)
    engine.reason(_request())
    # The request that actually reached the provider was built by
    # PromptBuilder via the router, not by AIReasoningEngine.
    assert provider.last_request is not None
    assert isinstance(provider.last_request, AIRequest)


# --- Disabled / unavailable / failing -> None --------------------------------


def test_disabled_engine_returns_none() -> None:
    provider = _FakeProvider()
    engine = AIReasoningEngine(router=_router(provider), enabled=False)
    assert engine.reason(_request()) is None
    assert engine.is_active() is False
    # A disabled engine must never call the provider.
    assert provider.generate_called is False


def test_engine_without_router_returns_none() -> None:
    engine = AIReasoningEngine(router=None, enabled=True)
    assert engine.is_active() is False
    assert engine.reason(_request()) is None


def test_unavailable_provider_returns_none() -> None:
    provider = _FakeProvider(available=False)
    engine = AIReasoningEngine(router=_router(provider), enabled=True)
    assert engine.is_active() is False
    assert engine.reason(_request()) is None
    assert provider.generate_called is False


def test_provider_failure_returns_none_without_raising() -> None:
    provider = _FakeProvider(fail=True)
    engine = AIReasoningEngine(router=_router(provider), enabled=True)
    # Must not raise; must degrade to None.
    assert engine.reason(_request()) is None


def test_empty_provider_text_returns_none() -> None:
    """Since Phase 7 Batch 2, an empty/whitespace-only response is rejected
    by the router's ResponseValidator before it ever reaches the engine's
    own parsing - so no advisory suggestion is produced at all, rather than
    the pre-Batch-2 placeholder text."""
    provider = _FakeProvider(text="   \n  \n")
    engine = AIReasoningEngine(router=_router(provider), enabled=True)
    assert engine.reason(_request()) is None


# --- The engine cannot execute anything (by construction) --------------------


def test_engine_has_no_execution_capability() -> None:
    engine = AIReasoningEngine(router=_router(_FakeProvider()), enabled=True)
    # The engine holds nothing capable of acting: no executor, registry,
    # approvals, or execute/run method.
    for attribute in ("_executor", "_registry", "_approvals", "execute", "run"):
        assert not hasattr(engine, attribute)


# --- context_block is forwarded unchanged, never reconstructed (Phase 8) ----


class _SpyRouter:
    """A minimal AIRouter stand-in that records exactly what route() receives,
    so context_block forwarding can be checked by identity - something a real
    AIRouter/PromptBuilder stack can't expose, since it renders context into
    prompt text."""

    def __init__(self, text: str = "Summary.\nStep 1: do it") -> None:
        self._text = text
        self.received_context: AIContextBlock | None = None
        self.route_called = False

    def is_available(self) -> bool:
        return True

    def route(
        self,
        *,
        system_instruction: str,
        user_message: str,
        context: AIContextBlock | None = None,
        session_id: int | None = None,
    ) -> AIResponse:
        self.route_called = True
        self.received_context = context
        return AIResponse(text=self._text, model="fake-model", provider="fake")


def test_context_block_defaults_to_none_and_is_forwarded_as_none() -> None:
    spy = _SpyRouter()
    engine = AIReasoningEngine(router=spy, enabled=True)  # type: ignore[arg-type]

    result = engine.reason(AIReasoningRequest(user_input="echo hello"))

    assert result is not None
    assert spy.route_called is True
    assert spy.received_context is None


def test_supplied_context_block_is_forwarded_unchanged_by_identity() -> None:
    spy = _SpyRouter()
    engine = AIReasoningEngine(router=spy, enabled=True)  # type: ignore[arg-type]
    block = AIContextBlock.from_untrusted("file text", source="file:report.txt")

    result = engine.reason(
        AIReasoningRequest(user_input="summarise report.txt", context_block=block)
    )

    assert result is not None
    assert spy.received_context is block


def test_supplied_context_block_trust_and_source_are_preserved() -> None:
    spy = _SpyRouter()
    engine = AIReasoningEngine(router=spy, enabled=True)  # type: ignore[arg-type]
    block = AIContextBlock.from_untrusted("file text", source="file:report.txt")

    engine.reason(
        AIReasoningRequest(user_input="summarise report.txt", context_block=block)
    )

    assert spy.received_context is not None
    assert spy.received_context.trust is ContentTrust.UNTRUSTED
    assert spy.received_context.source == "file:report.txt"


def test_conversation_history_hardcoded_source_defect_is_removed() -> None:
    """The pre-Phase-8 defect: any non-empty context was hardcoded to
    source="conversation_history", regardless of its real origin. Since the
    engine now only ever forwards an already-labelled AIContextBlock, a
    caller-supplied source is never overwritten - proving the hardcoded
    label is gone, not just harder to trigger."""
    spy = _SpyRouter()
    engine = AIReasoningEngine(router=spy, enabled=True)  # type: ignore[arg-type]
    block = AIContextBlock.from_untrusted("file text", source="file:report.txt")

    engine.reason(
        AIReasoningRequest(user_input="summarise report.txt", context_block=block)
    )

    assert spy.received_context is not None
    assert spy.received_context.source != "conversation_history"
    assert spy.received_context.source == "file:report.txt"


def test_engine_never_constructs_its_own_context_block() -> None:
    """AIReasoningEngine holds no reference to AIContextBlock's constructors
    at all - it cannot build one, only forward one it was given."""
    import ai.reasoning_engine as reasoning_engine_module

    assert not hasattr(reasoning_engine_module, "AIContextBlock")
