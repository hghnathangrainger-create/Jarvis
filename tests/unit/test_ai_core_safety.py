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


def _build(reasoning: AIReasoningEngine | None = None) -> JarvisOrchestrator:
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