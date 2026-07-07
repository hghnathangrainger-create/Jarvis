"""
test_ai_router.py

Unit tests for AIRouter (Phase 7, Batch 2: typed context passthrough and
is_available()).

These prove:
    - route() builds the request through the real PromptBuilder and passes
      it to the provider, returning the validated response.
    - A typed AIContextBlock passed as context reaches PromptBuilder intact.
    - Provider and validation failures are logged and re-raised, not
      swallowed.
    - is_available() passes through to the underlying provider and never
      raises, matching the same "never raise out" contract AIReasoningEngine
      depends on.
    - No live Claude API call is made anywhere (a fake provider is used).

Run with:
    pytest tests/unit/test_ai_router.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai.context_models import AIContextBlock
from ai.prompt_builder import PromptBuilder
from ai.providers.base import AIProvider, AIProviderError, AIRequest, AIResponse
from ai.response_validator import ResponseValidationError, ResponseValidator
from ai.router import AIRouter
from config.settings import Settings


class _SpyLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


class _FakeProvider(AIProvider):
    def __init__(
        self, text: str = "hello", *, available: bool = True, fail: bool = False
    ) -> None:
        self._text = text
        self._available = available
        self._fail = fail
        self.last_request: AIRequest | None = None

    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: AIRequest) -> AIResponse:
        self.last_request = request
        if self._fail:
            raise AIProviderError("simulated failure")
        return AIResponse(text=self._text, model="fake-model", provider="fake")

    def is_available(self) -> bool:
        if self._fail:
            raise RuntimeError("boom")
        return self._available


def _settings() -> Settings:
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


def _router(provider: AIProvider, logger: _SpyLogger | None = None) -> AIRouter:
    return AIRouter(
        provider=provider,
        prompt_builder=PromptBuilder(),
        validator=ResponseValidator(),
        logger=logger or _SpyLogger(),  # type: ignore[arg-type]
        settings=_settings(),
    )


# --- Successful routing -------------------------------------------------------


def test_route_returns_provider_response() -> None:
    router = _router(_FakeProvider(text="a plan"))
    response = router.route(system_instruction="sys", user_message="hello")
    assert response.text == "a plan"
    assert response.provider == "fake"


def test_route_passes_typed_context_through_to_prompt_builder() -> None:
    provider = _FakeProvider()
    router = _router(provider)
    context = AIContextBlock.from_untrusted("external text", source="web")
    router.route(system_instruction="sys", user_message="summarise", context=context)
    assert provider.last_request is not None
    content = provider.last_request.messages[0].content
    assert "BEGIN CONTEXT" in content
    assert "external text" in content


def test_route_logs_success() -> None:
    logger = _SpyLogger()
    router = _router(_FakeProvider(), logger)
    router.route(system_instruction="sys", user_message="hello")
    assert len(logger.events) == 1
    assert logger.events[0]["outcome"].value == "success"


# --- Failures are logged and re-raised, not swallowed ------------------------


def test_route_reraises_provider_error_and_logs_failure() -> None:
    logger = _SpyLogger()
    router = _router(_FakeProvider(fail=True), logger)
    with pytest.raises(AIProviderError):
        router.route(system_instruction="sys", user_message="hello")
    assert len(logger.events) == 1
    assert logger.events[0]["outcome"].value == "failure"


def test_route_reraises_response_validation_error() -> None:
    router = _router(_FakeProvider(text="   "))
    with pytest.raises(ResponseValidationError):
        router.route(system_instruction="sys", user_message="hello")


# --- is_available() passthrough ----------------------------------------------


def test_is_available_true_when_provider_available() -> None:
    router = _router(_FakeProvider(available=True))
    assert router.is_available() is True


def test_is_available_false_when_provider_unavailable() -> None:
    router = _router(_FakeProvider(available=False))
    assert router.is_available() is False


def test_is_available_never_raises() -> None:
    router = _router(_FakeProvider(fail=True))
    # The fake's is_available() raises RuntimeError when fail=True; the
    # router must swallow it and report False, never propagate.
    assert router.is_available() is False
