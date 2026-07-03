"""
test_memory_tool.py

Unit tests for the extended MemoryTool (Phase 5, Batch 2).

MemoryTool now supports three operations: list, search, and an explicit,
user-requested save. These tests exercise the tool in isolation with a fake
Memory Manager - no database - covering save (including the "do not remember"
rule and category normalisation), list and search with optional category
filtering, unknown-operation handling, and the honest GREEN action strings.

Run with:
    pytest tests/unit/test_memory_tool.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from memory.episodic_memory import MemoryRecord
from memory.memory_models import normalize_category
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.builtin import MemoryTool


class _FakeMemory:
    """A minimal in-memory stand-in for the Memory Manager."""

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
def tool(memory: _FakeMemory) -> MemoryTool:
    return MemoryTool(memory)  # type: ignore[arg-type]


def _request(**input_data: object) -> ToolRequest:
    return ToolRequest(tool_name="memory", input_data=input_data)


# --- Classification (honest GREEN action strings) ----------------------------


def test_all_operations_classify_green(tool: MemoryTool) -> None:
    security = SecurityManager()
    for operation in ("list", "search", "save"):
        action = tool.action_for(_request(operation=operation))
        assert security.classify_action(action).tier.name == "GREEN", operation


def test_save_action_string_is_honest(tool: MemoryTool) -> None:
    # The action names what it does; it is not disguised to force GREEN.
    assert tool.action_for(_request(operation="save")) == "save memory"


# --- Save --------------------------------------------------------------------


def test_save_stores_content(tool: MemoryTool, memory: _FakeMemory) -> None:
    result = tool.run(_request(operation="save", content="buy milk"))
    assert result.success is True
    assert len(memory.data) == 1
    assert memory.data[0].content == "buy milk"
    assert memory.data[0].category == "general"


def test_save_uses_category(tool: MemoryTool, memory: _FakeMemory) -> None:
    result = tool.run(
        _request(operation="save", content="ship it", category="project")
    )
    assert result.success is True
    assert memory.data[0].category == "project"
    assert result.metadata["category"] == "project"


def test_save_normalizes_unknown_category(
    tool: MemoryTool, memory: _FakeMemory
) -> None:
    tool.run(_request(operation="save", content="x", category="banana"))
    assert memory.data[0].category == "general"


def test_save_respects_do_not_remember(
    tool: MemoryTool, memory: _FakeMemory
) -> None:
    result = tool.run(
        _request(operation="save", content="do not remember my password")
    )
    # The command succeeds, but nothing is stored.
    assert result.success is True
    assert len(memory.data) == 0
    assert "did not save" in result.output.lower()


def test_save_requires_content(tool: MemoryTool) -> None:
    result = tool.run(_request(operation="save"))
    assert result.success is False
    assert "content" in result.error.lower()


def test_save_rejects_empty_content(tool: MemoryTool, memory: _FakeMemory) -> None:
    result = tool.run(_request(operation="save", content="   "))
    assert result.success is False
    assert len(memory.data) == 0


# --- List and search ---------------------------------------------------------


def test_list_returns_memories(tool: MemoryTool, memory: _FakeMemory) -> None:
    tool.run(_request(operation="save", content="first"))
    tool.run(_request(operation="save", content="second"))
    result = tool.run(_request(operation="list"))
    assert result.success is True
    assert "first" in result.output
    assert "second" in result.output


def test_list_filters_by_category(tool: MemoryTool) -> None:
    tool.run(_request(operation="save", content="p", category="project"))
    tool.run(_request(operation="save", content="g", category="general"))
    result = tool.run(_request(operation="list", category="project"))
    assert "p" in result.output
    assert result.output.count("[") == 1  # only one record shown


def test_search_matches(tool: MemoryTool) -> None:
    tool.run(_request(operation="save", content="Nathan likes Python"))
    result = tool.run(_request(operation="search", query="python"))
    assert result.success is True
    assert "Nathan likes Python" in result.output


def test_search_filters_by_category(tool: MemoryTool) -> None:
    tool.run(_request(operation="save", content="shared alpha", category="project"))
    tool.run(_request(operation="save", content="shared beta", category="personal"))
    result = tool.run(
        _request(operation="search", query="shared", category="personal")
    )
    assert "beta" in result.output
    assert "alpha" not in result.output


def test_search_requires_query(tool: MemoryTool) -> None:
    result = tool.run(_request(operation="search"))
    assert result.success is False
    assert "query" in result.error.lower()


def test_unknown_operation_fails(tool: MemoryTool) -> None:
    result = tool.run(_request(operation="destroy"))
    assert result.success is False
    assert "unknown operation" in result.error.lower()


def test_listing_shows_category(tool: MemoryTool) -> None:
    tool.run(_request(operation="save", content="note here", category="note"))
    result = tool.run(_request(operation="list"))
    assert "(note)" in result.output