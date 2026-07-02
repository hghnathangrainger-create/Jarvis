"""
test_ai_reasoning_engine.py

Unit tests for the AI reasoning engine (Phase 4, Batch 1).

Every test uses a fake, in-memory provider - no live Claude API call is ever
made. The tests confirm the engine produces advisory results when enabled,
returns None when disabled or unavailable, never raises on provider failure,
and - critically - has no ability to execute anything.

Run with:
    pytest tests/unit/test_ai_reasoning_engine.py
"""

from __future__ import annotations

from ai.providers.base import AIProvider, AIProviderError, AIRequest, AIResponse
from ai.reasoning_engine import AIReasoningEngine
from ai.reasoning_models import AIReasoningRequest


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


def _request(text: str = "echo hello") -> AIReasoningRequest:
    return AIReasoningRequest(user_input=text)


# --- Enabled engine produces results -----------------------------------------


def test_enabled_engine_produces_result() -> None:
    engine = AIReasoningEngine(provider=_FakeProvider(), enabled=True, model="m")
    result = engine.reason(_request())
    assert result is not None
    assert result.summary == "You want to echo text."
    assert result.has_suggestions is True
    assert result.provider_name == "fake"


def test_enabled_engine_is_active() -> None:
    engine = AIReasoningEngine(provider=_FakeProvider(), enabled=True, model="m")
    assert engine.is_active() is True


def test_engine_passes_system_instruction() -> None:
    provider = _FakeProvider()
    engine = AIReasoningEngine(provider=provider, enabled=True, model="m")
    engine.reason(_request())
    assert provider.generate_called is True
    assert provider.last_request is not None
    # The system instruction frames the AI as a non-executing advisor.
    assert "do not run" in provider.last_request.system.lower()


# --- Disabled / unavailable / failing -> None --------------------------------


def test_disabled_engine_returns_none() -> None:
    provider = _FakeProvider()
    engine = AIReasoningEngine(provider=provider, enabled=False, model="m")
    assert engine.reason(_request()) is None
    assert engine.is_active() is False
    # A disabled engine must never call the provider.
    assert provider.generate_called is False


def test_engine_without_provider_returns_none() -> None:
    engine = AIReasoningEngine(provider=None, enabled=True, model="m")
    assert engine.is_active() is False
    assert engine.reason(_request()) is None


def test_unavailable_provider_returns_none() -> None:
    provider = _FakeProvider(available=False)
    engine = AIReasoningEngine(provider=provider, enabled=True, model="m")
    assert engine.is_active() is False
    assert engine.reason(_request()) is None
    assert provider.generate_called is False


def test_provider_failure_returns_none_without_raising() -> None:
    provider = _FakeProvider(fail=True)
    engine = AIReasoningEngine(provider=provider, enabled=True, model="m")
    # Must not raise; must degrade to None.
    assert engine.reason(_request()) is None


def test_empty_provider_text_yields_placeholder_summary() -> None:
    provider = _FakeProvider(text="   \n  \n")
    engine = AIReasoningEngine(provider=provider, enabled=True, model="m")
    result = engine.reason(_request())
    assert result is not None
    assert result.has_suggestions is False
    assert result.summary  # some non-empty placeholder


# --- The engine cannot execute anything (by construction) --------------------


def test_engine_has_no_execution_capability() -> None:
    engine = AIReasoningEngine(provider=_FakeProvider(), enabled=True, model="m")
    # The engine holds nothing capable of acting: no executor, registry,
    # approvals, or execute/run method.
    for attribute in ("_executor", "_registry", "_approvals", "execute", "run"):
        assert not hasattr(engine, attribute)