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
from memory.memory_models import KNOWN_CATEGORIES, normalize_category
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

    def count(self) -> int:
        return len(self.data)

    def count_by_category(self, category: str) -> int:
        cat = normalize_category(category)
        return sum(1 for record in self.data if record.category == cat)

    def get(self, memory_id: int) -> MemoryRecord | None:
        for record in self.data:
            if record.id == memory_id:
                return record
        return None


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


# --- List truncation honesty (Phase 75, Batch 1) -------------------------------


def test_list_shows_exact_notice_when_more_memories_exist(
    tool: MemoryTool, memory: _FakeMemory
) -> None:
    for i in range(5):
        tool.run(_request(operation="save", content=f"memory {i}"))
    result = tool.run(_request(operation="list", limit=3))
    assert "[showing 3 of 5 memories; more memories exist]" in result.output


def test_list_category_filtered_notice_uses_category_specific_total(
    tool: MemoryTool, memory: _FakeMemory
) -> None:
    for i in range(4):
        tool.run(_request(operation="save", content=f"p{i}", category="project"))
    tool.run(_request(operation="save", content="g0", category="general"))
    result = tool.run(
        _request(operation="list", category="project", limit=2)
    )
    assert (
        "[showing 2 of 4 memories in category 'project'; more memories exist]"
        in result.output
    )
    # The notice must never use the global total (5), only the
    # category-specific one (4).
    assert "of 5 memories" not in result.output


def test_list_no_notice_when_fewer_than_limit(
    tool: MemoryTool, memory: _FakeMemory
) -> None:
    tool.run(_request(operation="save", content="only one"))
    result = tool.run(_request(operation="list", limit=10))
    assert "showing" not in result.output.lower()


def test_list_no_notice_when_shown_equals_total(
    tool: MemoryTool, memory: _FakeMemory
) -> None:
    for i in range(3):
        tool.run(_request(operation="save", content=f"memory {i}"))
    result = tool.run(_request(operation="list", limit=3))
    assert "showing" not in result.output.lower()


def test_list_empty_output_unchanged_by_batch_1(tool: MemoryTool) -> None:
    result = tool.run(_request(operation="list"))
    assert result.output == "Recent memories: none found."
    assert "showing" not in result.output.lower()


def test_list_notice_does_not_change_row_content_category_or_order(
    tool: MemoryTool, memory: _FakeMemory
) -> None:
    tool.run(_request(operation="save", content="first", category="project"))
    tool.run(_request(operation="save", content="second", category="personal"))
    tool.run(_request(operation="save", content="third", category="general"))
    result = tool.run(_request(operation="list", limit=2))
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert lines[0] == "Recent memories:"
    assert "third" in lines[1] and "(general)" in lines[1]
    assert "second" in lines[2] and "(personal)" in lines[2]
    assert lines[-1] == "[showing 2 of 3 memories; more memories exist]"


def test_list_truncation_does_not_mutate_memories(
    tool: MemoryTool, memory: _FakeMemory
) -> None:
    for i in range(5):
        tool.run(_request(operation="save", content=f"memory {i}"))
    before = list(memory.data)
    tool.run(_request(operation="list", limit=2))
    assert memory.data == before


def test_save_get_categories_search_unaffected_by_list_notice(
    tool: MemoryTool, memory: _FakeMemory
) -> None:
    """Batch 1 only touches the "list" operation - "save", "get",
    "categories", and "search" must all be completely unaffected."""
    for i in range(5):
        tool.run(_request(operation="save", content=f"memory {i}"))
    record_id = memory.data[0].id

    save_result = tool.run(_request(operation="save", content="new one"))
    get_result = tool.run(_request(operation="get", memory_id=record_id))
    categories_result = tool.run(_request(operation="categories"))
    search_result = tool.run(_request(operation="search", query="memory", limit=2))

    assert "showing" not in save_result.output.lower()
    assert "showing" not in get_result.output.lower()
    assert "showing" not in categories_result.output.lower()
    assert "showing" not in search_result.output.lower()


# --- Creation timestamp (Phase 70) --------------------------------------------


def test_list_output_includes_created_timestamp(
    tool: MemoryTool, memory: _FakeMemory
) -> None:
    tool.run(_request(operation="save", content="buy milk"))
    result = tool.run(_request(operation="list"))
    record = memory.data[0]
    expected = record.created_at.isoformat(timespec="seconds")
    assert f"(created: {expected})" in result.output


def test_search_output_includes_created_timestamp(
    tool: MemoryTool, memory: _FakeMemory
) -> None:
    tool.run(_request(operation="save", content="Nathan likes Python"))
    result = tool.run(_request(operation="search", query="python"))
    record = memory.data[0]
    expected = record.created_at.isoformat(timespec="seconds")
    assert f"(created: {expected})" in result.output


def test_get_output_includes_created_timestamp(
    tool: MemoryTool, memory: _FakeMemory
) -> None:
    tool.run(_request(operation="save", content="ship it"))
    record = memory.data[0]
    result = tool.run(_request(operation="get", memory_id=record.id))
    assert result.success is True
    expected = record.created_at.isoformat(timespec="seconds")
    assert f"(created: {expected})" in result.output


def test_get_output_is_unknown_operation_free_of_regression(
    tool: MemoryTool, memory: _FakeMemory
) -> None:
    """Confirms the 'get' operation's full row shape - id, category,
    content, and the new timestamp - all still appear together, not
    just the timestamp in isolation."""
    tool.run(_request(operation="save", content="ship it", category="project"))
    record = memory.data[0]
    result = tool.run(_request(operation="get", memory_id=record.id))
    assert f"[{record.id}]" in result.output
    assert "(project)" in result.output
    assert "ship it" in result.output
    assert "(created:" in result.output


# --- Category breakdown (Phase 71, Batch 1) -----------------------------------


def test_categories_action_string_is_honest(tool: MemoryTool) -> None:
    assert tool.action_for(_request(operation="categories")) == "show memory categories"


def test_categories_classifies_green(tool: MemoryTool) -> None:
    security = SecurityManager()
    action = tool.action_for(_request(operation="categories"))
    assert security.classify_action(action).tier.name == "GREEN"


def test_categories_includes_every_known_category(tool: MemoryTool) -> None:
    result = tool.run(_request(operation="categories"))
    assert result.success is True
    for category in KNOWN_CATEGORIES:
        assert f"{category}:" in result.output


def test_categories_empty_store_shows_every_category_at_zero(
    tool: MemoryTool,
) -> None:
    result = tool.run(_request(operation="categories"))
    for category in KNOWN_CATEGORIES:
        assert f"{category}: 0" in result.output


def test_categories_reports_real_counts(tool: MemoryTool) -> None:
    tool.run(_request(operation="save", content="a", category="project"))
    tool.run(_request(operation="save", content="b", category="project"))
    tool.run(_request(operation="save", content="c", category="personal"))
    result = tool.run(_request(operation="categories"))
    assert "project: 2" in result.output
    assert "personal: 1" in result.output
    assert "general: 0" in result.output


def test_categories_preserves_known_order_not_sorted_by_count(
    tool: MemoryTool,
) -> None:
    """Categories must never be reordered by count - this would visually
    imply a ranking/importance the data does not actually carry."""
    last_category = KNOWN_CATEGORIES[-1]
    for _ in range(5):
        tool.run(_request(operation="save", content="x", category=last_category))
    result = tool.run(_request(operation="categories"))

    lines = [
        line.strip().split(":")[0]
        for line in result.output.splitlines()[1:]
        if line.strip()
    ]
    assert lines == list(KNOWN_CATEGORIES)


def test_categories_does_not_involve_ai_or_estimation(tool: MemoryTool) -> None:
    """Structural sanity check: the categories output never resembles an
    AI disclaimer/advisory marker, since count_by_category() is a plain,
    deterministic count with no AI involvement."""
    result = tool.run(_request(operation="categories"))
    assert "[AI suggestion" not in result.output
    assert "advisory only" not in result.output.lower()
    assert "estimate" not in result.output.lower()