"""
test_memory_change_tools.py

Unit tests for the guarded memory-change tools (Phase 5, Batch 3).

MemoryUpdateTool (update content, move category) and MemoryForgetTool (forget
one memory by id) are YELLOW tools. These tests exercise them in isolation with
a fake Memory Manager - no database - covering the happy paths, every refusal
path (missing id, unknown id, empty value), the honest YELLOW/RED action
strings, and the refusal of any bulk forget.

Run with:
    pytest tests/unit/test_memory_change_tools.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from memory.episodic_memory import MemoryRecord
from memory.memory_models import normalize_category
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.builtin import MemoryForgetTool, MemoryUpdateTool


class _FakeMemory:
    """A minimal in-memory stand-in for the Memory Manager."""

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

    def get(self, memory_id: int) -> MemoryRecord | None:
        return self.data.get(memory_id)

    def update_content(
        self, memory_id: int, new_content: str
    ) -> MemoryRecord | None:
        record = self.data.get(memory_id)
        if record is None:
            return None
        updated = MemoryRecord(
            id=record.id,
            content=new_content.strip(),
            source=record.source,
            session_id=record.session_id,
            category=record.category,
            created_at=record.created_at,
        )
        self.data[memory_id] = updated
        return updated

    def move_category(
        self, memory_id: int, new_category: str
    ) -> MemoryRecord | None:
        record = self.data.get(memory_id)
        if record is None:
            return None
        updated = MemoryRecord(
            id=record.id,
            content=record.content,
            source=record.source,
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


def _update_request(**data: object) -> ToolRequest:
    return ToolRequest(tool_name="memory_update", input_data=data)


def _forget_request(**data: object) -> ToolRequest:
    return ToolRequest(tool_name="memory_forget", input_data=data)


# --- Classification ----------------------------------------------------------


def test_update_and_move_classify_yellow(memory: _FakeMemory) -> None:
    security = SecurityManager()
    tool = MemoryUpdateTool(memory)
    assert (
        security.classify_action(
            tool.action_for(_update_request(operation="update"))
        ).tier.name
        == "YELLOW"
    )
    assert (
        security.classify_action(
            tool.action_for(_update_request(operation="move"))
        ).tier.name
        == "YELLOW"
    )


def test_forget_one_classifies_yellow(memory: _FakeMemory) -> None:
    security = SecurityManager()
    tool = MemoryForgetTool(memory)
    action = tool.action_for(_forget_request(memory_id=1))
    assert security.classify_action(action).tier.name == "YELLOW"


def test_forget_all_classifies_red(memory: _FakeMemory) -> None:
    security = SecurityManager()
    tool = MemoryForgetTool(memory)
    action = tool.action_for(_forget_request(all=True))
    assert security.classify_action(action).tier.name == "RED"


# --- Update content ----------------------------------------------------------


def test_update_changes_content(memory: _FakeMemory) -> None:
    mid = memory.add("old content")
    tool = MemoryUpdateTool(memory)
    result = tool.run(_update_request(memory_id=mid, content="new content"))
    assert result.success is True
    assert memory.get(mid).content == "new content"


# --- Update confirmation detail (Phase 79) ------------------------------------


def test_update_confirmation_includes_id_category_old_and_new_content(
    memory: _FakeMemory,
) -> None:
    mid = memory.add("old content", category="project")
    tool = MemoryUpdateTool(memory)
    result = tool.run(_update_request(memory_id=mid, content="new content"))
    assert result.output == (
        f"Updated memory [{mid}] (project) old content -> new content"
    )


def test_update_confirmation_reflects_record_fetched_before_mutation(
    memory: _FakeMemory,
) -> None:
    """The success message must show the real, pre-mutation old content -
    not an empty or generic placeholder - proving the record was read
    before update_content() overwrote it."""
    mid = memory.add("distinctive old value", category="personal")
    tool = MemoryUpdateTool(memory)
    result = tool.run(_update_request(memory_id=mid, content="distinctive new value"))
    assert "distinctive old value" in result.output
    assert "distinctive new value" in result.output
    assert "personal" in result.output
    assert str(mid) in result.output


def test_update_unknown_id_fails(memory: _FakeMemory) -> None:
    tool = MemoryUpdateTool(memory)
    result = tool.run(_update_request(memory_id=999, content="x"))
    assert result.success is False
    assert result.error == "No memory found with id 999."


def test_update_missing_id_fails(memory: _FakeMemory) -> None:
    tool = MemoryUpdateTool(memory)
    result = tool.run(_update_request(content="x"))
    assert result.success is False
    assert result.error == (
        "Updating a memory requires a valid numeric 'memory_id'."
    )


def test_update_empty_content_fails(memory: _FakeMemory) -> None:
    mid = memory.add("keep")
    tool = MemoryUpdateTool(memory)
    result = tool.run(_update_request(memory_id=mid, content="   "))
    assert result.success is False
    assert result.error == "Updating a memory requires non-empty 'content'."
    assert memory.get(mid).content == "keep"


# --- Move category -----------------------------------------------------------


def test_move_changes_category(memory: _FakeMemory) -> None:
    mid = memory.add("note", category="general")
    tool = MemoryUpdateTool(memory)
    result = tool.run(
        _update_request(operation="move", memory_id=mid, category="project")
    )
    assert result.success is True
    assert memory.get(mid).category == "project"


def test_move_unknown_category_normalizes(memory: _FakeMemory) -> None:
    mid = memory.add("note")
    tool = MemoryUpdateTool(memory)
    tool.run(
        _update_request(operation="move", memory_id=mid, category="banana")
    )
    assert memory.get(mid).category == "general"


# --- Move confirmation detail (Phase 79) --------------------------------------


def test_move_confirmation_includes_id_old_and_new_category(
    memory: _FakeMemory,
) -> None:
    mid = memory.add("note", category="general")
    tool = MemoryUpdateTool(memory)
    result = tool.run(
        _update_request(operation="move", memory_id=mid, category="project")
    )
    assert result.output == f"Moved memory [{mid}] from 'general' to 'project'."


def test_move_confirmation_reflects_record_fetched_before_mutation(
    memory: _FakeMemory,
) -> None:
    """The success message must show the real, pre-mutation old category -
    not an empty or generic placeholder - proving the record was read
    before move_category() overwrote it."""
    mid = memory.add("note", category="personal")
    tool = MemoryUpdateTool(memory)
    result = tool.run(
        _update_request(operation="move", memory_id=mid, category="preference")
    )
    assert "personal" in result.output
    assert "preference" in result.output
    assert str(mid) in result.output


def test_move_missing_category_fails(memory: _FakeMemory) -> None:
    mid = memory.add("note")
    tool = MemoryUpdateTool(memory)
    result = tool.run(_update_request(operation="move", memory_id=mid))
    assert result.success is False
    assert result.error == "Moving a memory requires a non-empty 'category'."


def test_move_unknown_id_fails(memory: _FakeMemory) -> None:
    tool = MemoryUpdateTool(memory)
    result = tool.run(
        _update_request(operation="move", memory_id=999, category="project")
    )
    assert result.success is False
    assert result.error == "No memory found with id 999."


# --- Forget ------------------------------------------------------------------


def test_forget_removes_memory(memory: _FakeMemory) -> None:
    mid = memory.add("bye")
    tool = MemoryForgetTool(memory)
    result = tool.run(_forget_request(memory_id=mid))
    assert result.success is True
    assert memory.get(mid) is None


# --- Forget confirmation detail (Phase 78, Batch 1) --------------------------


def test_forget_confirmation_includes_id_category_and_content(
    memory: _FakeMemory,
) -> None:
    mid = memory.add("buy milk", category="project")
    tool = MemoryForgetTool(memory)
    result = tool.run(_forget_request(memory_id=mid))
    assert result.success is True
    assert result.output == f"Forgot memory [{mid}] (project) buy milk."


def test_forget_confirmation_uses_default_category_when_none_given(
    memory: _FakeMemory,
) -> None:
    mid = memory.add("no category given")
    tool = MemoryForgetTool(memory)
    result = tool.run(_forget_request(memory_id=mid))
    assert result.output == f"Forgot memory [{mid}] (general) no category given."


def test_forget_confirmation_reflects_the_record_fetched_before_deletion(
    memory: _FakeMemory,
) -> None:
    """The success message must come from the real, fetched record - not
    an empty or generic placeholder - proving the record was read before
    forget() removed it."""
    mid = memory.add("distinctive content xyz", category="personal")
    tool = MemoryForgetTool(memory)
    result = tool.run(_forget_request(memory_id=mid))
    assert "distinctive content xyz" in result.output
    assert "personal" in result.output
    assert str(mid) in result.output


def test_forget_unknown_id_fails(memory: _FakeMemory) -> None:
    tool = MemoryForgetTool(memory)
    result = tool.run(_forget_request(memory_id=999))
    assert result.success is False
    assert "no memory found" in result.error.lower()


def test_forget_missing_id_fails(memory: _FakeMemory) -> None:
    tool = MemoryForgetTool(memory)
    result = tool.run(_forget_request())
    assert result.success is False
    assert "memory_id" in result.error.lower()


def test_forget_all_is_refused_even_if_reached(memory: _FakeMemory) -> None:
    # Defensive: even if a bulk request reaches run(), it must refuse and delete
    # nothing. (In practice the Security Manager blocks it first.)
    memory.add("one")
    memory.add("two")
    tool = MemoryForgetTool(memory)
    result = tool.run(_forget_request(all=True))
    assert result.success is False
    assert len(memory.data) == 2