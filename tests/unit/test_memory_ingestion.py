"""
test_memory_ingestion.py

Unit tests for ai/memory_ingestion.py (Phase 9, Batch 1).

These prove:
    - A successful acquisition returns an AIContextBlock: UNTRUSTED, carrying
      the memory's actual content, labelled with the RETURNED record's own
      id - never the caller-supplied memory_id substituted in its place.
    - ingest_memory_for_ai() itself is the caller of
      MemoryManager.get(memory_id) - acquisition is not duplicated, bypassed,
      or routed through ToolExecutor/MemoryTool.
    - The function's signature has no seam for supplying content, a source
      label, or a trust level independently, and no seam for handing it a
      pre-existing MemoryRecord or ToolResult to relabel - provenance is
      established by construction, not by caller discipline.
    - MemoryRecord.source (capture-origin metadata) never influences
      ContentTrust - every record ingested here becomes UNTRUSTED regardless
      of its stored .source value.
    - A failed acquisition (no memory with that id) never produces a context
      block, and the failure text is returned as an error, never mistaken
      for real memory content.
    - Truncation affects only record.content; metadata is never flattened
      into the AI-facing text; a represented failure never claims truncation.

Run with:
    pytest tests/unit/test_memory_ingestion.py
"""

from __future__ import annotations

import dataclasses
import inspect
from datetime import datetime, timezone

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from ai.context_models import AIContextBlock
from ai.memory_ingestion import MemoryIngestionResult, ingest_memory_for_ai
from config.constants import ContentTrust
from memory.episodic_memory import EpisodicMemoryStore, MemoryRecord
from memory.memory_manager import MemoryManager


class _SpyMemoryManager:
    """Wraps a real MemoryManager, recording every get() call's arguments.

    Used only where direct call-count/argument observation is needed; every
    MemoryRecord it returns still comes from the real, wrapped MemoryManager.
    """

    def __init__(self, real: MemoryManager) -> None:
        self._real = real
        self.get_calls: list[int] = []

    def get(self, memory_id: int) -> MemoryRecord | None:
        self.get_calls.append(memory_id)
        return self._real.get(memory_id)

    def save(self, *args: object, **kwargs: object) -> MemoryRecord | None:
        return self._real.save(*args, **kwargs)  # type: ignore[arg-type]


@pytest.fixture()
def memory_manager() -> MemoryManager:
    """Build a MemoryManager backed by a fresh in-memory database."""
    from sqlalchemy import create_engine

    from storage.database import create_session_factory, initialize_database

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return MemoryManager(EpisodicMemoryStore(factory))


def _fake_record(*, id: int, content: str, source: str = "conversation") -> MemoryRecord:
    return MemoryRecord(
        id=id,
        content=content,
        source=source,
        session_id=None,
        created_at=datetime.now(timezone.utc),
        category="general",
    )


# --- Successful acquisition ---------------------------------------------------


def test_successful_acquisition_returns_untrusted_context(
    memory_manager: MemoryManager,
) -> None:
    record = memory_manager.save(content="Hello Jarvis! This is real memory content.")
    assert record is not None

    result = ingest_memory_for_ai(memory_manager, record.id)

    assert result.success is True
    assert result.error is None
    assert result.context is not None
    assert result.context.trust is ContentTrust.UNTRUSTED


def test_successful_acquisition_contains_the_actual_memory_content(
    memory_manager: MemoryManager,
) -> None:
    record = memory_manager.save(content="Nathan likes Python")
    assert record is not None

    result = ingest_memory_for_ai(memory_manager, record.id)

    assert result.context is not None
    assert result.context.text == "Nathan likes Python"


def test_source_label_identifies_the_returned_record_id(
    memory_manager: MemoryManager,
) -> None:
    record = memory_manager.save(content="a note")
    assert record is not None

    result = ingest_memory_for_ai(memory_manager, record.id)

    assert result.context is not None
    assert result.context.source == f"memory:{record.id}"


def test_ingestion_never_produces_jarvis_trusted(
    memory_manager: MemoryManager,
) -> None:
    record = memory_manager.save(content="a note")
    assert record is not None

    result = ingest_memory_for_ai(memory_manager, record.id)

    assert result.context is not None
    assert result.context.trust is not ContentTrust.JARVIS_TRUSTED


# --- Provenance is derived from the RETURNED record, never the caller id ----


def test_source_label_derives_from_the_returned_record_id_not_the_requested_id() -> None:
    """Even if a caller requests id 42, the source label must reflect the
    RETURNED record's own id - proven with a fake whose get() deliberately
    returns a record carrying a different id than what was asked for."""

    returned_record = _fake_record(id=999, content="some content")

    class _FakeManager:
        def get(self, memory_id: int) -> MemoryRecord | None:
            return returned_record

    result = ingest_memory_for_ai(_FakeManager(), memory_id=42)  # type: ignore[arg-type]

    assert result.context is not None
    assert result.context.source == "memory:999"
    assert "42" not in result.context.source


# --- The function itself performs acquisition (no bypass, no duplication) ---


def test_ingestion_itself_invokes_memory_manager_get(
    memory_manager: MemoryManager,
) -> None:
    record = memory_manager.save(content="a note")
    assert record is not None
    spy = _SpyMemoryManager(memory_manager)

    ingest_memory_for_ai(spy, record.id)  # type: ignore[arg-type]

    assert spy.get_calls == [record.id]


def test_retrieval_occurs_exactly_once(memory_manager: MemoryManager) -> None:
    record = memory_manager.save(content="a note")
    assert record is not None
    spy = _SpyMemoryManager(memory_manager)

    ingest_memory_for_ai(spy, record.id)  # type: ignore[arg-type]

    assert len(spy.get_calls) == 1


def test_a_missing_id_still_goes_through_a_single_get_call(
    memory_manager: MemoryManager,
) -> None:
    spy = _SpyMemoryManager(memory_manager)

    ingest_memory_for_ai(spy, 999_999)  # type: ignore[arg-type]

    assert spy.get_calls == [999_999]


# --- Provenance established by construction, not by caller discipline -------


def test_signature_has_no_seam_for_independent_content_source_or_trust() -> None:
    """The only external content-location input is memory_id. There is no
    parameter through which a caller could supply memory text, a source
    label, or a trust level independently, so none can ever describe
    something different from what memory_manager.get() actually returned."""
    params = set(inspect.signature(ingest_memory_for_ai).parameters)
    assert params == {"memory_manager", "memory_id", "max_chars"}
    assert "content" not in params
    assert "text" not in params
    assert "source" not in params
    assert "trust" not in params
    assert "context_trust" not in params


def test_signature_does_not_accept_a_pre_existing_record_or_tool_result() -> None:
    """The function cannot be used to relabel arbitrary pre-existing content
    as memory provenance, because it never accepts a MemoryRecord or a
    ToolResult at all - only a memory_id it looks up itself."""
    params = inspect.signature(ingest_memory_for_ai).parameters
    assert "record" not in params
    assert "memory_record" not in params
    assert "tool_result" not in params
    assert "result" not in params


def test_same_memory_id_always_produces_the_same_source_label(
    memory_manager: MemoryManager,
) -> None:
    record = memory_manager.save(content="a note")
    assert record is not None

    first = ingest_memory_for_ai(memory_manager, record.id)
    second = ingest_memory_for_ai(memory_manager, record.id)

    assert first.context is not None
    assert second.context is not None
    assert first.context.source == second.context.source == f"memory:{record.id}"


# --- MemoryRecord.source never influences ContentTrust ----------------------


def test_record_with_source_user_still_becomes_untrusted(
    memory_manager: MemoryManager,
) -> None:
    record = memory_manager.save(content="a note", source="user")
    assert record is not None
    assert record.source == "user"

    result = ingest_memory_for_ai(memory_manager, record.id)

    assert result.context is not None
    assert result.context.trust is ContentTrust.UNTRUSTED


def test_record_with_source_conversation_still_becomes_untrusted(
    memory_manager: MemoryManager,
) -> None:
    record = memory_manager.save(content="a note", source="conversation")
    assert record is not None
    assert record.source == "conversation"

    result = ingest_memory_for_ai(memory_manager, record.id)

    assert result.context is not None
    assert result.context.trust is ContentTrust.UNTRUSTED


# --- Failure is represented as data, never as a raised exception ------------


def test_missing_memory_id_does_not_raise_and_produces_no_context(
    memory_manager: MemoryManager,
) -> None:
    result = ingest_memory_for_ai(memory_manager, 999_999)

    assert result.success is False
    assert result.context is None
    assert result.error is not None
    assert "999999" in result.error


def test_failure_text_is_never_mistaken_for_memory_content(
    memory_manager: MemoryManager,
) -> None:
    """The error string belongs in MemoryIngestionResult.error, never wrapped
    into an AIContextBlock as if it were the memory's own content."""
    result = ingest_memory_for_ai(memory_manager, 999_999)

    assert result.context is None
    assert isinstance(result.error, str)


def test_failure_never_reports_truncated(memory_manager: MemoryManager) -> None:
    result = ingest_memory_for_ai(memory_manager, 999_999)

    assert result.truncated is False


# --- Truncation behaviour -----------------------------------------------------


def test_content_under_the_limit_is_unchanged_and_not_truncated(
    memory_manager: MemoryManager,
) -> None:
    record = memory_manager.save(content="short note")
    assert record is not None

    result = ingest_memory_for_ai(memory_manager, record.id, max_chars=4000)

    assert result.context is not None
    assert result.context.text == "short note"
    assert result.truncated is False


def test_content_exactly_at_the_limit_is_unchanged_and_not_truncated(
    memory_manager: MemoryManager,
) -> None:
    content = "A" * 100
    record = memory_manager.save(content=content)
    assert record is not None

    result = ingest_memory_for_ai(memory_manager, record.id, max_chars=100)

    assert result.context is not None
    assert result.context.text == content
    assert result.truncated is False


def test_oversized_content_is_truncated_and_flagged(
    memory_manager: MemoryManager,
) -> None:
    record = memory_manager.save(content="A" * 200)
    assert record is not None

    result = ingest_memory_for_ai(memory_manager, record.id, max_chars=100)

    assert result.context is not None
    assert result.truncated is True
    assert result.context.text.startswith("A" * 100)
    assert "truncated" in result.context.text.lower()


def test_default_max_chars_is_4000(memory_manager: MemoryManager) -> None:
    record = memory_manager.save(content="A" * 10_000)
    assert record is not None

    result = ingest_memory_for_ai(memory_manager, record.id)

    assert result.context is not None
    assert result.truncated is True
    body = result.context.text.split("\n\n[")[0]
    assert len(body) == 4000


def test_truncation_affects_only_content_not_metadata(
    memory_manager: MemoryManager,
) -> None:
    """A distinguishing category value must never leak into the truncated
    AI-facing text - only record.content is ever part of the payload."""
    record = memory_manager.save(
        content="B" * 200, category="project", session_id=None
    )
    assert record is not None

    result = ingest_memory_for_ai(memory_manager, record.id, max_chars=50)

    assert result.context is not None
    assert "project" not in result.context.text
    assert str(record.id) not in result.context.text.replace(
        f"[... truncated: showing the first 50 characters", ""
    )


def test_truncation_notice_does_not_alter_provenance_or_trust(
    memory_manager: MemoryManager,
) -> None:
    record = memory_manager.save(content="C" * 200)
    assert record is not None

    result = ingest_memory_for_ai(memory_manager, record.id, max_chars=50)

    assert result.context is not None
    assert result.context.source == f"memory:{record.id}"
    assert result.context.trust is ContentTrust.UNTRUSTED


def test_invalid_max_chars_zero_raises(memory_manager: MemoryManager) -> None:
    record = memory_manager.save(content="a note")
    assert record is not None

    with pytest.raises(ValueError, match="positive integer"):
        ingest_memory_for_ai(memory_manager, record.id, max_chars=0)


def test_invalid_max_chars_negative_raises(memory_manager: MemoryManager) -> None:
    record = memory_manager.save(content="a note")
    assert record is not None

    with pytest.raises(ValueError, match="positive integer"):
        ingest_memory_for_ai(memory_manager, record.id, max_chars=-5)


# --- MemoryIngestionResult itself ---------------------------------------------


def test_result_is_frozen() -> None:
    result = MemoryIngestionResult(error="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.error = "y"  # type: ignore[misc]


def test_result_success_property_reflects_context_presence() -> None:
    assert MemoryIngestionResult(context=None, error="x").success is False
    block = AIContextBlock.from_untrusted("text", source="memory:1")
    assert MemoryIngestionResult(context=block).success is True


def test_result_rejects_both_context_and_error_set() -> None:
    block = AIContextBlock.from_untrusted("text", source="memory:1")
    with pytest.raises(ValueError, match="cannot carry both"):
        MemoryIngestionResult(context=block, error="also failed")


def test_result_rejects_neither_context_nor_error_set() -> None:
    with pytest.raises(ValueError, match="cannot represent neither"):
        MemoryIngestionResult()


def test_result_rejects_truncated_true_without_context() -> None:
    with pytest.raises(ValueError, match="truncated=True"):
        MemoryIngestionResult(error="not found", truncated=True)


def test_ingest_memory_for_ai_never_produces_a_contradictory_result(
    memory_manager: MemoryManager,
) -> None:
    """Both real code paths (success and failure) always satisfy the
    invariant - proven end to end, not just at the type level."""
    record = memory_manager.save(content="a note")
    assert record is not None

    success = ingest_memory_for_ai(memory_manager, record.id)
    assert (success.context is None) != (success.error is None)

    failure = ingest_memory_for_ai(memory_manager, 999_999)
    assert (failure.context is None) != (failure.error is None)
    assert failure.truncated is False
