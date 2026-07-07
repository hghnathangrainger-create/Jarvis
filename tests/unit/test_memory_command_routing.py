"""
test_memory_command_routing.py

Unit tests for routing the six memory commands through the orchestrator
(Phase 5, Batch 2).

These confirm that each command shape maps to the correct memory-tool input
(operation, category, query), that an unknown category is left for the tool to
normalise, and that every memory command comes back GREEN - running
automatically with no approval prompt.

Run with:
    pytest tests/unit/test_memory_command_routing.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from memory.episodic_memory import MemoryRecord
from memory.memory_models import normalize_category
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin import MemoryTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


class _SpyLogger:
    def emit(self, **kwargs: object) -> str:
        return "1"


class _FakeMemory:
    def __init__(self) -> None:
        self.data: list[MemoryRecord] = []
        self._id = 0

    def save(
        self,
        content: str,
        *,
        source: str = "conversation",
        session_id: int | None = None,
        category: str | None = None,
    ) -> MemoryRecord | None:
        text = content.strip()
        if not text or "do not remember" in text.lower():
            return None
        self._id += 1
        record = MemoryRecord(
            id=self._id,
            content=text,
            source=source,
            session_id=session_id,
            category=normalize_category(category),
            created_at=datetime.now(timezone.utc),
        )
        self.data.append(record)
        return record

    def list_recent(
        self, limit: int = 10, category: str | None = None
    ) -> list[MemoryRecord]:
        rows = list(reversed(self.data))
        if category is not None:
            cat = normalize_category(category)
            rows = [r for r in rows if r.category == cat]
        return rows[:limit]

    def search(
        self, query: str, limit: int = 10, category: str | None = None
    ) -> list[MemoryRecord]:
        rows = [r for r in reversed(self.data) if query.lower() in r.content.lower()]
        if category is not None:
            cat = normalize_category(category)
            rows = [r for r in rows if r.category == cat]
        return rows[:limit]


@pytest.fixture()
def memory() -> _FakeMemory:
    return _FakeMemory()


@pytest.fixture()
def orchestrator(memory: _FakeMemory) -> JarvisOrchestrator:
    security = SecurityManager()
    registry = ToolRegistry()
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
    )


# --- Routing to the right input ----------------------------------------------


def test_remember_this_routes_to_save_general() -> None:
    result = CommandRouter._build_memory_input("remember this: buy milk")
    assert result == {"operation": "save", "content": "buy milk"}


def test_remember_as_category_routes_to_save_with_category() -> None:
    result = CommandRouter._build_memory_input(
        "remember this as project: ship the release"
    )
    assert result == {
        "operation": "save",
        "content": "ship the release",
        "category": "project",
    }


def test_show_memories_routes_to_list() -> None:
    result = CommandRouter._build_memory_input("show memories")
    assert result == {"operation": "list"}


def test_show_memories_in_category_routes_to_filtered_list() -> None:
    result = CommandRouter._build_memory_input("show memories in personal")
    assert result == {"operation": "list", "category": "personal"}


def test_search_memories_routes_to_search() -> None:
    result = CommandRouter._build_memory_input("search memories for milk")
    assert result == {"operation": "search", "query": "milk"}


def test_search_memories_in_category_routes_to_filtered_search() -> None:
    result = CommandRouter._build_memory_input(
        "search memories in project for deadline"
    )
    assert result == {
        "operation": "search",
        "query": "deadline",
        "category": "project",
    }


# --- Every command is GREEN (no approval) ------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "remember this: buy milk",
        "remember this as project: ship the release",
        "show memories",
        "show memories in personal",
        "search memories for milk",
        "search memories in project for deadline",
    ],
)
def test_all_memory_commands_run_green(
    orchestrator: JarvisOrchestrator, command: str
) -> None:
    response = orchestrator.handle_request(command)
    assert response.success is True
    assert response.requires_confirmation is False
    assert response.approval_request is None
    assert response.blocked is False


# --- Unknown category is accepted and normalised downstream ------------------


def test_unknown_category_is_saved_as_general(
    orchestrator: JarvisOrchestrator, memory: _FakeMemory
) -> None:
    orchestrator.handle_request("remember this as banana: odd note")
    assert memory.data[-1].category == "general"


# --- The do-not-remember rule still applies through routing ------------------


def test_do_not_remember_is_not_stored(
    orchestrator: JarvisOrchestrator, memory: _FakeMemory
) -> None:
    response = orchestrator.handle_request(
        "remember this: do not remember my secret"
    )
    assert response.success is True
    assert len(memory.data) == 0