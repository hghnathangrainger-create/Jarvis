"""
test_memory_summary_ai_availability_consistency.py

Cross-handler behavioural proof for Retrieval Workflow Maintenance, Batch 2:
the five memory-summary workflows (Phase 10 explicit-id, Phase 11 query,
Phase 12 category, Phase 13 fixed-recent, Phase 14 bounded-recent-count)
now share one AI-reasoning-not-enabled message and one AI-reasoning-
unavailable message (core/orchestrator.py's
_MEMORY_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE and
_MEMORY_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE), replacing five
byte-identical, independently-declared copies of each.

This does not test the private constant names as an API, and does not
search source text for them - it drives each of the five real commands
through the public handle_request() entry point, under equivalent
reasoning-not-enabled and reasoning-unavailable configurations, and
compares the actual resulting user-visible message content. This is the
one piece of protection the existing per-phase workflow test files did not
already provide: each of them proves its own handler says "not enabled" /
does not fabricate a summary, but none of them proves that all five
handlers say the *same* thing.

Run with:
    pytest tests/unit/test_memory_summary_ai_availability_consistency.py
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
from config.settings import Settings
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry

# --- Test doubles (same conventions as the Phase 10-14 workflow tests) -----


class _RecordingLogger:
    def emit(self, **kwargs: object) -> str:
        return "1"


class _FakeProvider(AIProvider):
    def __init__(self, *, available: bool = True, fail: bool = False) -> None:
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
        return AIResponse(text="A summary.", model="fake-model", provider="fake")

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


def _engine(*, available: bool = True) -> AIReasoningEngine:
    provider = _FakeProvider(available=available)
    router = AIRouter(
        provider=provider,
        prompt_builder=PromptBuilder(),
        validator=ResponseValidator(),
        logger=_RecordingLogger(),  # type: ignore[arg-type]
        settings=_settings(),
    )
    return AIReasoningEngine(router=router, enabled=True)


def _memory_manager() -> MemoryManager:
    from sqlalchemy import create_engine

    from storage.database import create_session_factory, initialize_database

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return MemoryManager(EpisodicMemoryStore(factory))


def _orchestrator(reasoning: AIReasoningEngine | None, memory: MemoryManager) -> JarvisOrchestrator:
    security = SecurityManager()
    registry = ToolRegistry()
    logger = _RecordingLogger()
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
        memory_manager=memory,
        logger=logger,  # type: ignore[arg-type]
    )


def _save(memory: MemoryManager, content: str, **kwargs: object) -> int:
    record = memory.save(content=content, category="project", **kwargs)  # type: ignore[arg-type]
    assert record is not None
    return record.id


def _requests_for(memory: MemoryManager) -> dict[str, str]:
    id_a = _save(memory, "Alpha content")
    return {
        "phase_10": f"summarise memories {id_a}",
        "phase_11": "summarise memories about alpha",
        "phase_12": "summarise memories in project",
        "phase_13": "summarise recent memories",
        "phase_14": "summarise latest 3 memories",
    }


# --- Reasoning not enabled: all five must share one message ----------------


def test_all_five_handlers_share_the_same_not_enabled_message() -> None:
    memory = _memory_manager()
    requests = _requests_for(memory)
    orchestrator = _orchestrator(reasoning=None, memory=memory)

    bodies = set()
    for phase, request_text in requests.items():
        response = orchestrator.handle_request(request_text)
        assert response.success is False
        # The not-enabled response carries no advisory label at all (it
        # never reaches AI reasoning), so the full message is compared
        # directly rather than stripped.
        bodies.add(response.message)

    assert len(bodies) == 1
    assert "not enabled" in next(iter(bodies)).lower()


# --- Reasoning unavailable: all five must share one message ----------------


def test_all_five_handlers_share_the_same_unavailable_message() -> None:
    memory = _memory_manager()
    requests = _requests_for(memory)
    engine = _engine(available=False)
    orchestrator = _orchestrator(reasoning=engine, memory=memory)

    bodies = set()
    for phase, request_text in requests.items():
        response = orchestrator.handle_request(request_text)
        assert response.success is False
        bodies.add(response.message)

    assert len(bodies) == 1
    body = next(iter(bodies))
    assert "not enabled" not in body.lower()
    assert "could not produce a summary" in body.lower()


def test_shared_messages_are_distinct_from_each_other() -> None:
    """Sanity check on the two fixtures themselves: the not-enabled and
    unavailable paths must not collapse into the same wording."""
    memory = _memory_manager()
    requests = _requests_for(memory)

    not_enabled_orchestrator = _orchestrator(reasoning=None, memory=memory)
    not_enabled_response = not_enabled_orchestrator.handle_request(
        requests["phase_10"]
    )

    memory2 = _memory_manager()
    requests2 = _requests_for(memory2)
    unavailable_orchestrator = _orchestrator(
        reasoning=_engine(available=False), memory=memory2
    )
    unavailable_response = unavailable_orchestrator.handle_request(
        requests2["phase_10"]
    )

    assert not_enabled_response.message != unavailable_response.message
