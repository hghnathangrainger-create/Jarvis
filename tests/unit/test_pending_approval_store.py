"""
test_pending_approval_store.py

Unit tests for PendingApprovalStore (Phase 27, Batch 1).

These use a real in-memory SQLite database (not a fake), exercising the
same storage layer Jarvis uses at runtime: saving a row's pending
execution state, listing/getting it back, replacing it, and deleting it.
A key set of tests locks in this table's own safety boundary: a corrupt
metadata_json/tool_input_json value is reported via the record's
`corrupt` flag rather than raising or silently losing every other row.

These tests use a real database, so they are skipped automatically if
SQLAlchemy is not importable.

Run with:
    pytest tests/unit/test_pending_approval_store.py
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.pending_approval_store import PendingApprovalStore, SCHEMA_VERSION
from storage.database import create_session_factory, initialize_database
from storage.models import PendingApprovalState


@pytest.fixture()
def session_factory():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


@pytest.fixture()
def store(session_factory) -> PendingApprovalStore:
    return PendingApprovalStore(session_factory)


# --- save / round-trip -----------------------------------------------------


def test_save_with_tool_state_round_trips(store: PendingApprovalStore) -> None:
    record = store.save(
        request_id="req-1",
        action="copy file",
        reason="Copying a file creates new state.",
        security_tier="yellow",
        session_id=7,
        metadata={"workflow_id": "wf-1"},
        tool_name="file_copy",
        tool_input={"source": "a.txt", "destination": "b.txt"},
    )
    assert record.request_id == "req-1"
    assert record.action == "copy file"
    assert record.reason == "Copying a file creates new state."
    assert record.security_tier == "yellow"
    assert record.session_id == 7
    assert record.metadata == {"workflow_id": "wf-1"}
    assert record.tool_name == "file_copy"
    assert record.tool_input == {"source": "a.txt", "destination": "b.txt"}
    assert record.schema_version == SCHEMA_VERSION
    assert record.corrupt is False
    assert record.created_at is not None


def test_save_without_tool_state_persists_null_tool_fields(
    store: PendingApprovalStore,
) -> None:
    """A plan-only confirmation with no backing tool at all."""
    record = store.save(
        request_id="req-2",
        action="some plan-only action",
        reason="Needs confirmation.",
        security_tier="yellow",
    )
    assert record.tool_name is None
    assert record.tool_input is None
    assert record.metadata == {}


def test_save_replaces_an_existing_row_for_the_same_request_id(
    store: PendingApprovalStore,
) -> None:
    store.save(
        request_id="req-3",
        action="move file",
        reason="r1",
        security_tier="yellow",
        tool_name="file_move",
        tool_input={"source": "a.txt", "destination": "b.txt"},
    )
    store.save(
        request_id="req-3",
        action="move file",
        reason="r2 - replaced",
        security_tier="yellow",
        tool_name="file_move",
        tool_input={"source": "c.txt", "destination": "d.txt"},
    )

    record = store.get("req-3")
    assert record is not None
    assert record.reason == "r2 - replaced"
    assert record.tool_input == {"source": "c.txt", "destination": "d.txt"}


def test_get_returns_none_for_unknown_request_id(
    store: PendingApprovalStore,
) -> None:
    assert store.get("does-not-exist") is None


def test_list_all_returns_every_row_oldest_first(
    store: PendingApprovalStore,
) -> None:
    store.save(
        request_id="req-a", action="a", reason="r", security_tier="yellow"
    )
    store.save(
        request_id="req-b", action="b", reason="r", security_tier="yellow"
    )
    store.save(
        request_id="req-c", action="c", reason="r", security_tier="yellow"
    )

    records = store.list_all()
    assert [r.request_id for r in records] == ["req-a", "req-b", "req-c"]


def test_list_all_on_empty_table_returns_empty_list(
    store: PendingApprovalStore,
) -> None:
    assert store.list_all() == []


# --- delete -----------------------------------------------------------------


def test_delete_removes_the_row(store: PendingApprovalStore) -> None:
    store.save(request_id="req-1", action="a", reason="r", security_tier="yellow")
    store.delete("req-1")
    assert store.get("req-1") is None


def test_delete_is_a_no_op_for_an_unknown_request_id(
    store: PendingApprovalStore,
) -> None:
    store.delete("never-existed")  # must not raise
    assert store.list_all() == []


# --- corrupt-row isolation ---------------------------------------------------


def test_corrupt_metadata_json_is_reported_not_raised(
    store: PendingApprovalStore, session_factory
) -> None:
    from storage.database import session_scope

    store.save(request_id="req-1", action="a", reason="r", security_tier="yellow")

    # Hand-craft an invalid metadata_json value directly at the storage
    # layer, simulating on-disk corruption or a manual edit.
    with session_scope(session_factory) as db:
        entry = (
            db.query(PendingApprovalState)
            .filter(PendingApprovalState.request_id == "req-1")
            .one()
        )
        entry.metadata_json = "{not valid json"

    record = store.get("req-1")
    assert record is not None
    assert record.corrupt is True
    assert record.metadata == {}


def test_corrupt_tool_input_json_is_reported_not_raised(
    store: PendingApprovalStore, session_factory
) -> None:
    from storage.database import session_scope

    store.save(
        request_id="req-1",
        action="a",
        reason="r",
        security_tier="yellow",
        tool_name="file_copy",
        tool_input={"source": "a.txt", "destination": "b.txt"},
    )

    with session_scope(session_factory) as db:
        entry = (
            db.query(PendingApprovalState)
            .filter(PendingApprovalState.request_id == "req-1")
            .one()
        )
        entry.tool_input_json = "[1, 2, this is not json"

    record = store.get("req-1")
    assert record is not None
    assert record.corrupt is True
    assert record.tool_input is None


def test_one_corrupt_row_does_not_prevent_other_valid_rows_from_listing(
    store: PendingApprovalStore, session_factory
) -> None:
    from storage.database import session_scope

    store.save(request_id="req-good-1", action="a", reason="r", security_tier="yellow")
    store.save(request_id="req-bad", action="b", reason="r", security_tier="yellow")
    store.save(request_id="req-good-2", action="c", reason="r", security_tier="yellow")

    with session_scope(session_factory) as db:
        entry = (
            db.query(PendingApprovalState)
            .filter(PendingApprovalState.request_id == "req-bad")
            .one()
        )
        entry.metadata_json = "not json at all {{{"

    records = store.list_all()
    by_id = {r.request_id: r for r in records}
    assert len(records) == 3
    assert by_id["req-good-1"].corrupt is False
    assert by_id["req-good-2"].corrupt is False
    assert by_id["req-bad"].corrupt is True


def test_non_dict_json_is_treated_as_corrupt(
    store: PendingApprovalStore, session_factory
) -> None:
    from storage.database import session_scope

    store.save(request_id="req-1", action="a", reason="r", security_tier="yellow")

    with session_scope(session_factory) as db:
        entry = (
            db.query(PendingApprovalState)
            .filter(PendingApprovalState.request_id == "req-1")
            .one()
        )
        entry.metadata_json = "[1, 2, 3]"  # valid JSON, but not an object

    record = store.get("req-1")
    assert record is not None
    assert record.corrupt is True
    assert record.metadata == {}
