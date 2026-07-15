"""
test_core.py

Unit tests for the Jarvis Core orchestrator (core/orchestrator.py).

The orchestrator is exercised with the real Planner, Security Manager, Tool
Registry, and Tool Executor, plus a fake memory and a spy logger. No AI,
network, or live database is required, so the full request lifecycle is tested
end to end including the security gate.

Run with:
    pytest tests/unit/test_core.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from memory.episodic_memory import MemoryRecord
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin import EchoTool, InfoTool, MemoryTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


# --- Test doubles ------------------------------------------------------------


class _SpyLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


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

    def count(self) -> int:
        return len(self._data)


# --- Fixtures ----------------------------------------------------------------


@pytest.fixture()
def memory() -> _FakeMemory:
    mem = _FakeMemory()
    mem.add("Nathan likes Python.")
    mem.add("Nathan is learning trading.")
    return mem


@pytest.fixture()
def orchestrator(memory: _FakeMemory) -> JarvisOrchestrator:
    security = SecurityManager()
    planner = Planner(security)
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
        planner=planner,
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
    )


# --- Safe (GREEN) requests ---------------------------------------------------


def test_info_request(orchestrator: JarvisOrchestrator) -> None:
    response = orchestrator.handle_request("show me system info")
    assert response.success is True
    assert "Jarvis" in response.message
    assert response.plan is not None


def test_echo_request(orchestrator: JarvisOrchestrator) -> None:
    response = orchestrator.handle_request("echo hello world")
    assert response.success is True
    assert response.message == "echo hello world"
    assert response.plan is not None


def test_memory_list_request(orchestrator: JarvisOrchestrator) -> None:
    response = orchestrator.handle_request("show my memories")
    assert response.success is True
    assert "Nathan" in response.message


def test_memory_search_request(orchestrator: JarvisOrchestrator) -> None:
    response = orchestrator.handle_request("search memories for trading")
    assert response.success is True
    assert "trading" in response.message.lower()


# --- YELLOW and RED ----------------------------------------------------------


def test_yellow_request_requires_confirmation(
    orchestrator: JarvisOrchestrator,
) -> None:
    response = orchestrator.handle_request("send email to Alex")
    assert response.success is False
    assert response.requires_confirmation is True
    assert response.blocked is False
    assert response.plan is not None


def test_red_request_is_blocked(orchestrator: JarvisOrchestrator) -> None:
    response = orchestrator.handle_request("format drive C")
    assert response.success is False
    assert response.blocked is True
    assert response.requires_confirmation is False
    assert response.plan is not None


# --- Unknown / unsupported ---------------------------------------------------


def test_unknown_request_is_handled_safely(
    orchestrator: JarvisOrchestrator,
) -> None:
    response = orchestrator.handle_request("do a barrel roll")
    assert response.success is False
    assert response.plan is not None


def test_safe_but_unsupported_request_is_explained(
    orchestrator: JarvisOrchestrator,
) -> None:
    response = orchestrator.handle_request("calculate the meaning of life")
    assert response.success is False
    assert response.blocked is False
    assert response.plan is not None


def test_safe_but_unsupported_request_points_toward_help(
    orchestrator: JarvisOrchestrator,
) -> None:
    """Phase 45: the unmatched-GREEN fallback message must point the user
    toward the Phase 43 help command, so an unsupported request doesn't
    leave them guessing at another unsupported phrasing."""
    response = orchestrator.handle_request("calculate the meaning of life")
    assert "help" in response.message
    assert "list commands" in response.message
    assert "show commands" in response.message
    # The original meaning is preserved, not replaced.
    assert "does not yet have a tool to carry it out" in response.message
    assert "More capability will be added in a later phase" in response.message


def test_help_mention_does_not_leak_into_tool_backed_green_responses(
    orchestrator: JarvisOrchestrator,
) -> None:
    """Phase 45 regression: only the unmatched-GREEN fallback message
    changed - a request that a real tool actually handles must be
    completely unaffected."""
    response = orchestrator.handle_request("echo hello world")
    assert response.success is True
    assert "help" not in response.message
    assert response.message == "echo hello world"


def test_help_mention_does_not_leak_into_yellow_confirmation_response(
    orchestrator: JarvisOrchestrator,
) -> None:
    """Phase 45 regression: YELLOW confirmation-required behavior and
    message are completely unaffected by the unmatched-GREEN wording
    change."""
    response = orchestrator.handle_request("send email to Alex")
    assert response.requires_confirmation is True
    assert response.blocked is False
    assert "help" not in response.message


def test_help_mention_does_not_leak_into_red_blocked_response(
    orchestrator: JarvisOrchestrator,
) -> None:
    """Phase 45 regression: RED blocked behavior and message are
    completely unaffected by the unmatched-GREEN wording change."""
    response = orchestrator.handle_request("format drive C")
    assert response.blocked is True
    assert response.requires_confirmation is False
    assert "help" not in response.message


# --- Empty input -------------------------------------------------------------


def test_empty_request_fails_safely(orchestrator: JarvisOrchestrator) -> None:
    response = orchestrator.handle_request("   ")
    assert response.success is False
    assert "Empty request" in response.message


# --- Plan is always included -------------------------------------------------


@pytest.mark.parametrize(
    "request_text",
    ["echo hi", "send email", "format drive", "show memories"],
)
def test_plan_always_included(
    orchestrator: JarvisOrchestrator, request_text: str
) -> None:
    assert orchestrator.handle_request(request_text).plan is not None


# --- The Core does not bypass the ToolExecutor security gate -----------------


class _RedActionEcho(BaseTool):
    """A tool named 'echo' whose action classifies RED.

    If the Core routed to this tool directly instead of through the executor,
    its run method would raise. The executor must block it first.
    """

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo tool with a dangerous action, for the bypass test."

    def action_for(self, request: ToolRequest) -> str:
        return "format drive"

    def run(self, request: ToolRequest) -> ToolResult:
        raise AssertionError("The Core bypassed the ToolExecutor security gate.")


def test_core_does_not_bypass_tool_executor() -> None:
    security = SecurityManager()
    planner = Planner(security)
    registry = ToolRegistry()
    registry.register_tool(_RedActionEcho())
    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=_SpyLogger(),  # type: ignore[arg-type]
    )
    core = JarvisOrchestrator(
        planner=planner,
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
    )

    response = core.handle_request("echo something")
    assert response.success is False
    assert response.blocked is True