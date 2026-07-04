"""
test_approval_history_store.py

Unit tests for ApprovalHistoryStore (Phase 6, Batch 1).

These use a real in-memory SQLite database (not a fake), exercising the same
storage layer Jarvis uses at runtime: recording a pending request, recording
its eventual decision, and querying history by recency, by status, and by id.

A key test locks in the Phase 6 Batch 1 safety boundary at the data-model
level: a returned record never carries a tool_name or tool_input, because
neither the table nor the record type has such a field.

These tests use a real database, so they are skipped automatically if
SQLAlchemy is not importable.

Run with:
    pytest tests/unit/test_approval_history_store.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_history_store import ApprovalHistoryStore
from storage.database import create_session_factory, initialize_database


def _make_store() -> ApprovalHistoryStore:
    """Build an ApprovalHistoryStore backed by a fresh in-memory database."""
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return ApprovalHistoryStore(factory)


@pytest.fixture()
def store() -> ApprovalHistoryStore:
    return _make_store()


# --- record_request ------------------------------------------------------


def test_record_request_creates_pending_row(store: ApprovalHistoryStore) -> None:
    record = store.record_request(
        request_id="req-1",
        action="update memory 3",
        reason="Updating a memory changes stored content.",
        security_tier="yellow",
    )
    assert record.request_id == "req-1"
    assert record.action == "update memory 3"
    assert record.security_tier == "yellow"
    assert record.status == "pending"
    assert record.decided_at is None
    assert record.decided_by is None
    assert record.decision_reason is None


def test_record_request_stores_session_id(store: ApprovalHistoryStore) -> None:
    record = store.record_request(
        request_id="req-1",
        action="delete file old.txt",
        reason="Deletion changes state.",
        security_tier="yellow",
        session_id=7,
    )
    assert record.session_id == 7


def test_history_row_has_no_tool_fields(store: ApprovalHistoryStore) -> None:
    """Structural guarantee: nothing stored here can ever be replayed.

    The schema has no tool_name / tool_input columns at all, so this asserts
    the returned record type has no such attributes either. This is a
    deliberate Phase 6 Batch 1 boundary, not an omission to be "completed"
    later without a fresh safety review.
    """
    record = store.record_request(
        request_id="req-1",
        action="update memory 3",
        reason="Updating a memory changes stored content.",
        security_tier="yellow",
    )
    assert not hasattr(record, "tool_name")
    assert not hasattr(record, "tool_input")


# --- record_decision -------------------------------------------------------


def test_record_decision_approved_updates_row(store: ApprovalHistoryStore) -> None:
    store.record_request(
        request_id="req-1",
        action="forget memory 9",
        reason="Forgetting a memory removes it.",
        security_tier="yellow",
    )
    decided_at = datetime.now(timezone.utc)
    updated = store.record_decision(
        request_id="req-1",
        approved=True,
        decided_by="user",
        decided_at=decided_at,
        reason="looks right",
    )
    assert updated is not None
    assert updated.status == "approved"
    assert updated.decided_by == "user"
    assert updated.decision_reason == "looks right"
    assert updated.decided_at == decided_at


def test_record_decision_declined_updates_row(store: ApprovalHistoryStore) -> None:
    store.record_request(
        request_id="req-2",
        action="move memory 4 to personal",
        reason="Moving a memory changes it.",
        security_tier="yellow",
    )
    updated = store.record_decision(
        request_id="req-2",
        approved=False,
        decided_by="user",
        decided_at=datetime.now(timezone.utc),
    )
    assert updated is not None
    assert updated.status == "declined"
    assert updated.decision_reason is None


def test_record_decision_unknown_request_id_returns_none(
    store: ApprovalHistoryStore,
) -> None:
    result = store.record_decision(
        request_id="does-not-exist",
        approved=True,
        decided_by="user",
        decided_at=datetime.now(timezone.utc),
    )
    assert result is None


# --- list_recent -----------------------------------------------------------


def test_list_recent_orders_newest_first(store: ApprovalHistoryStore) -> None:
    store.record_request(
        request_id="req-1", action="a", reason="r", security_tier="yellow"
    )
    store.record_request(
        request_id="req-2", action="b", reason="r", security_tier="yellow"
    )
    records = store.list_recent(limit=10)
    assert [r.request_id for r in records] == ["req-2", "req-1"]


def test_list_recent_respects_limit(store: ApprovalHistoryStore) -> None:
    for i in range(5):
        store.record_request(
            request_id=f"req-{i}", action="a", reason="r", security_tier="yellow"
        )
    records = store.list_recent(limit=2)
    assert len(records) == 2


def test_list_recent_clamps_limit_to_max(store: ApprovalHistoryStore) -> None:
    for i in range(3):
        store.record_request(
            request_id=f"req-{i}", action="a", reason="r", security_tier="yellow"
        )
    records = store.list_recent(limit=999)
    assert len(records) == 3  # fewer rows than the clamp ceiling, so unaffected


def test_list_recent_clamps_limit_to_minimum(store: ApprovalHistoryStore) -> None:
    for i in range(3):
        store.record_request(
            request_id=f"req-{i}", action="a", reason="r", security_tier="yellow"
        )
    records = store.list_recent(limit=0)
    assert len(records) == 1


# --- list_by_status ----------------------------------------------------------


def test_list_by_status_filters_correctly(store: ApprovalHistoryStore) -> None:
    store.record_request(
        request_id="req-1", action="a", reason="r", security_tier="yellow"
    )
    store.record_request(
        request_id="req-2", action="b", reason="r", security_tier="yellow"
    )
    store.record_decision(
        request_id="req-1",
        approved=True,
        decided_by="user",
        decided_at=datetime.now(timezone.utc),
    )
    approved = store.list_by_status("approved")
    pending = store.list_by_status("pending")
    declined = store.list_by_status("declined")
    assert [r.request_id for r in approved] == ["req-1"]
    assert [r.request_id for r in pending] == ["req-2"]
    assert declined == []


def test_list_by_status_unknown_status_matches_nothing(
    store: ApprovalHistoryStore,
) -> None:
    store.record_request(
        request_id="req-1", action="a", reason="r", security_tier="yellow"
    )
    assert store.list_by_status("not-a-real-status") == []


# --- get ---------------------------------------------------------------------


def test_get_returns_matching_record(store: ApprovalHistoryStore) -> None:
    store.record_request(
        request_id="req-1", action="a", reason="r", security_tier="yellow"
    )
    record = store.get("req-1")
    assert record is not None
    assert record.request_id == "req-1"


def test_get_returns_none_for_unknown_id(store: ApprovalHistoryStore) -> None:
    assert store.get("nope") is None