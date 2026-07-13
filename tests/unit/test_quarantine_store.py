"""
test_quarantine_store.py

Unit tests for QuarantineStore (Phase 37, Batch 1): the durable,
write-once storage layer for quarantine metadata.

These use a real SQLite database (not a fake), exercising the same
storage layer Jarvis uses at runtime: recording a quarantine record and
retrieving it by quarantine_path.

A key set of tests locks in the Batch 1 safety boundary at the
API-model level: QuarantineStore exposes no update, delete, restore, or
cleanup method at all - proven structurally, not just by absence of a
test that calls one.

These tests use a real database, so they are skipped automatically if
SQLAlchemy is not importable.

Run with:
    pytest tests/unit/test_quarantine_store.py
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from quarantine.quarantine_store import QuarantineStore
from storage.database import create_session_factory, initialize_database


def _make_store() -> QuarantineStore:
    """Build a QuarantineStore backed by a fresh in-memory database."""
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return QuarantineStore(factory)


@pytest.fixture()
def store() -> QuarantineStore:
    return _make_store()


# --- record_quarantine ---------------------------------------------------------


def test_can_record_a_quarantine_record(store: QuarantineStore) -> None:
    record = store.record_quarantine(
        original_path="/home/nathan/notes.txt",
        quarantine_path="/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt",
    )
    assert record.id is not None


def test_records_original_path(store: QuarantineStore) -> None:
    record = store.record_quarantine(
        original_path="/home/nathan/notes.txt",
        quarantine_path="/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt",
    )
    assert record.original_path == "/home/nathan/notes.txt"


def test_records_quarantine_path(store: QuarantineStore) -> None:
    record = store.record_quarantine(
        original_path="/home/nathan/notes.txt",
        quarantine_path="/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt",
    )
    assert record.quarantine_path == "/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt"


def test_records_quarantined_at_timestamp(store: QuarantineStore) -> None:
    record = store.record_quarantine(
        original_path="/home/nathan/notes.txt",
        quarantine_path="/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt",
    )
    assert record.quarantined_at is not None


def test_records_optional_session_id(store: QuarantineStore) -> None:
    record = store.record_quarantine(
        original_path="/home/nathan/notes.txt",
        quarantine_path="/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt",
        session_id=7,
    )
    assert record.session_id == 7


def test_session_id_defaults_to_none(store: QuarantineStore) -> None:
    record = store.record_quarantine(
        original_path="/home/nathan/notes.txt",
        quarantine_path="/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt",
    )
    assert record.session_id is None


# --- get_by_quarantine_path ----------------------------------------------------


def test_can_retrieve_a_record_by_quarantine_path(store: QuarantineStore) -> None:
    store.record_quarantine(
        original_path="/home/nathan/notes.txt",
        quarantine_path="/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt",
    )
    retrieved = store.get_by_quarantine_path(
        "/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt"
    )
    assert retrieved is not None
    assert retrieved.original_path == "/home/nathan/notes.txt"


def test_missing_record_returns_none_not_an_error(store: QuarantineStore) -> None:
    """The expected, ordinary case for a file quarantined before this
    table existed - never a raised exception."""
    retrieved = store.get_by_quarantine_path("/nonexistent/path.txt")
    assert retrieved is None


def test_multiple_records_are_retrieved_independently(
    store: QuarantineStore,
) -> None:
    store.record_quarantine(
        original_path="/a/notes.txt",
        quarantine_path="/trash/notes__11111111.txt",
    )
    store.record_quarantine(
        original_path="/b/notes.txt",
        quarantine_path="/trash/notes__22222222.txt",
    )

    first = store.get_by_quarantine_path("/trash/notes__11111111.txt")
    second = store.get_by_quarantine_path("/trash/notes__22222222.txt")

    assert first is not None and first.original_path == "/a/notes.txt"
    assert second is not None and second.original_path == "/b/notes.txt"


# --- Uniqueness ------------------------------------------------------------


def test_duplicate_quarantine_path_raises_and_does_not_corrupt_existing_record(
    store: QuarantineStore,
) -> None:
    store.record_quarantine(
        original_path="/a/notes.txt",
        quarantine_path="/trash/notes__11111111.txt",
    )

    with pytest.raises(sqlalchemy.exc.SQLAlchemyError):
        store.record_quarantine(
            original_path="/b/other.txt",
            quarantine_path="/trash/notes__11111111.txt",
        )

    # The original record must still be intact and unchanged.
    original = store.get_by_quarantine_path("/trash/notes__11111111.txt")
    assert original is not None
    assert original.original_path == "/a/notes.txt"


# --- list_recent (Phase 39, Batch 1) --------------------------------------


def test_list_recent_returns_empty_list_when_no_records_exist(
    store: QuarantineStore,
) -> None:
    assert store.list_recent() == []


def test_list_recent_returns_recorded_quarantine_records(
    store: QuarantineStore,
) -> None:
    store.record_quarantine(
        original_path="/a/notes.txt",
        quarantine_path="/trash/notes__11111111.txt",
    )

    records = store.list_recent()

    assert len(records) == 1
    assert records[0].original_path == "/a/notes.txt"
    assert records[0].quarantine_path == "/trash/notes__11111111.txt"


def test_list_recent_orders_newest_first_by_id(store: QuarantineStore) -> None:
    """Records share created-in-the-same-instant timestamps in a fast
    test run, so id (not just quarantined_at) must break the tie -
    mirroring InboxStore.list_recent()'s own
    (created_at.desc(), id.desc()) ordering exactly."""
    store.record_quarantine(
        original_path="/a/first.txt", quarantine_path="/trash/first__1.txt"
    )
    store.record_quarantine(
        original_path="/b/second.txt", quarantine_path="/trash/second__2.txt"
    )
    store.record_quarantine(
        original_path="/c/third.txt", quarantine_path="/trash/third__3.txt"
    )

    records = store.list_recent()

    assert [record.original_path for record in records] == [
        "/c/third.txt",
        "/b/second.txt",
        "/a/first.txt",
    ]


def test_list_recent_respects_limit(store: QuarantineStore) -> None:
    for i in range(5):
        store.record_quarantine(
            original_path=f"/a/file{i}.txt",
            quarantine_path=f"/trash/file{i}__{i:08d}.txt",
        )

    records = store.list_recent(limit=2)

    assert len(records) == 2


def test_list_recent_clamps_limit_below_one(store: QuarantineStore) -> None:
    store.record_quarantine(
        original_path="/a/notes.txt",
        quarantine_path="/trash/notes__11111111.txt",
    )

    records = store.list_recent(limit=0)

    assert len(records) == 1


def test_list_recent_clamps_limit_above_max(store: QuarantineStore) -> None:
    for i in range(5):
        store.record_quarantine(
            original_path=f"/a/file{i}.txt",
            quarantine_path=f"/trash/file{i}__{i:08d}.txt",
        )

    records = store.list_recent(limit=10_000)

    assert len(records) == 5


def test_list_recent_does_not_modify_existing_records(
    store: QuarantineStore,
) -> None:
    original = store.record_quarantine(
        original_path="/a/notes.txt",
        quarantine_path="/trash/notes__11111111.txt",
        session_id=7,
    )

    store.list_recent()
    store.list_recent()

    unchanged = store.get_by_quarantine_path("/trash/notes__11111111.txt")
    assert unchanged is not None
    assert unchanged.id == original.id
    assert unchanged.original_path == original.original_path
    assert unchanged.quarantine_path == original.quarantine_path
    assert unchanged.session_id == original.session_id


# --- Structural: write-once, no update/delete/restore/cleanup surface ----------


def test_store_has_no_update_delete_restore_or_cleanup_methods() -> None:
    forbidden_methods = {
        "update",
        "delete",
        "remove",
        "restore",
        "cleanup",
        "empty",
        "purge",
    }
    public_methods = {
        name
        for name in dir(QuarantineStore)
        if not name.startswith("_") and callable(getattr(QuarantineStore, name))
    }
    assert not (public_methods & forbidden_methods), public_methods
