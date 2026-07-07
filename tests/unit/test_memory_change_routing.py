"""
test_memory_change_routing.py

Unit tests for routing the memory review and change commands through the
orchestrator (Phase 5, Batch 3).

These confirm that each command maps to the correct tool and input, that
"show memory <id>" is GREEN, that update / move / forget are YELLOW (requiring
approval and not running immediately), and that "forget all memories" is blocked
RED with nothing removed.

Run with:
    pytest tests/unit/test_memory_change_routing.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from approval.approval_manager import ApprovalManager
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from memory.episodic_memory import MemoryRecord
from memory.memory_models import normalize_category
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin import MemoryForgetTool, MemoryTool, MemoryUpdateTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


class _SpyLogger:
    def emit(self, **kwargs: object) -> str:
        return "1"


class _FakeMemory:
    def __init__(self) -> None:
        self.data: dict[int, MemoryRecord] = {}
        self._id = 0

    def add(self, content: str, category: str = "general") -> int:
        self._id += 1
        self.data[self._id] = MemoryRecord(
            id=self._id,
            content=content,
            source="test",
            session_id=None,
            category=normalize_category(category),
            created_at=datetime.now(timezone.utc),
        )
        return self._id

    def list_recent(self, limit: int = 10, category: str | None = None):
        rows = sorted(self.data.values(), key=lambda r: -r.id)
        if category is not None:
            rows = [r for r in rows if r.category == normalize_category(category)]
        return rows[:limit]

    def search(self, query: str, limit: int = 10, category: str | None = None):
        rows = [
            r for r in sorted(self.data.values(), key=lambda r: -r.id)
            if query.lower() in r.content.lower()
        ]
        return rows[:limit]

    def get(self, memory_id: int):
        return self.data.get(memory_id)

    def update_content(self, memory_id: int, new_content: str):
        record = self.data.get(memory_id)
        if record is None:
            return None
        updated = MemoryRecord(
            id=record.id, content=new_content.strip(), source=record.source,
            session_id=record.session_id, category=record.category,
            created_at=record.created_at,
        )
        self.data[memory_id] = updated
        return updated

    def move_category(self, memory_id: int, new_category: str):
        record = self.data.get(memory_id)
        if record is None:
            return None
        updated = MemoryRecord(
            id=record.id, content=record.content, source=record.source,
            session_id=record.session_id,
            category=normalize_category(new_category),
            created_at=record.created_at,
        )
        self.data[memory_id] = updated
        return updated

    def forget(self, memory_id: int) -> bool:
        if memory_id in self.data:
            del self.data[memory_id]
            return True
        return False


@pytest.fixture()
def memory() -> _FakeMemory:
    return _FakeMemory()


@pytest.fixture()
def orchestrator(memory: _FakeMemory) -> JarvisOrchestrator:
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(MemoryTool(memory))  # type: ignore[arg-type]
    registry.register_tool(MemoryUpdateTool(memory))
    registry.register_tool(MemoryForgetTool(memory))
    logger = _SpyLogger()
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
        approval_manager=ApprovalManager(audit_logger=logger),  # type: ignore[arg-type]
    )


# --- Routing to the right tool and input -------------------------------------


def test_show_memory_routes_to_get() -> None:
    result = CommandRouter._build_memory_input("show memory 12")
    assert result == {"operation": "get", "memory_id": 12}


def test_update_routes_to_update_input() -> None:
    result = CommandRouter._build_memory_update_input(
        "update memory 12: the new text"
    )
    assert result == {
        "operation": "update",
        "memory_id": 12,
        "content": "the new text",
    }


def test_move_routes_to_move_input() -> None:
    result = CommandRouter._build_memory_update_input(
        "move memory 12 to personal"
    )
    assert result == {
        "operation": "move",
        "memory_id": 12,
        "category": "personal",
    }


# --- Tiers through the orchestrator ------------------------------------------


def test_show_memory_is_green(
    orchestrator: JarvisOrchestrator, memory: _FakeMemory
) -> None:
    mid = memory.add("hello there")
    response = orchestrator.handle_request(f"show memory {mid}")
    assert response.success is True
    assert response.approval_request is None
    assert "hello there" in response.message


def test_update_is_yellow(
    orchestrator: JarvisOrchestrator, memory: _FakeMemory
) -> None:
    mid = memory.add("old")
    response = orchestrator.handle_request(f"update memory {mid}: new")
    assert response.tool_name == "memory_update"
    assert response.requires_confirmation is True
    assert response.approval_request is not None
    assert memory.get(mid).content == "old"  # unchanged until approved


def test_move_is_yellow(
    orchestrator: JarvisOrchestrator, memory: _FakeMemory
) -> None:
    mid = memory.add("note", category="general")
    response = orchestrator.handle_request(f"move memory {mid} to project")
    assert response.tool_name == "memory_update"
    assert response.requires_confirmation is True
    assert memory.get(mid).category == "general"  # unchanged until approved


def test_forget_one_is_yellow(
    orchestrator: JarvisOrchestrator, memory: _FakeMemory
) -> None:
    mid = memory.add("bye")
    response = orchestrator.handle_request(f"forget memory {mid}")
    assert response.tool_name == "memory_forget"
    assert response.requires_confirmation is True
    assert memory.get(mid) is not None  # not deleted until approved


def test_forget_all_is_blocked_red(
    orchestrator: JarvisOrchestrator, memory: _FakeMemory
) -> None:
    memory.add("one")
    memory.add("two")
    response = orchestrator.handle_request("forget all memories")
    assert response.blocked is True
    assert response.approval_request is None
    assert len(memory.data) == 2  # nothing removed