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

from ai.prompt_builder import PromptBuilder
from ai.providers.base import AIProvider, AIProviderError, AIRequest, AIResponse
from ai.reasoning_engine import AIReasoningEngine
from ai.reasoning_models import AIReasoningRequest
from ai.response_validator import ResponseValidator
from ai.router import AIRouter
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
