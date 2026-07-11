"""
test_scheduled_inbox_notice_store.py

Unit tests for ScheduledInboxNoticeStore (Phase 22, Batch 1): the single,
durable marker tracking which scheduled Inbox entries the CLI has
already reported.

These use a real SQLite database (not a fake), exercising the same
storage layer Jarvis uses at runtime. A key set of tests locks in the
single-row/upsert boundary at the API-model level: the store exposes
exactly two methods, and a second write never creates a second row.

Run with:
    pytest tests/unit/test_scheduled_inbox_notice_store.py
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from notice.scheduled_inbox_notice_store import ScheduledInboxNoticeStore
from storage.database import create_session_factory, initialize_database
from storage.models import ScheduledInboxNoticeState


def _make_store() -> ScheduledInboxNoticeStore:
    """Build a ScheduledInboxNoticeStore backed by a fresh in-memory database."""
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return ScheduledInboxNoticeStore(factory)


@pytest.fixture()
def store() -> ScheduledInboxNoticeStore:
    return _make_store()


# --- first-run / no-marker behavior --------------------------------------------


def test_get_on_empty_store_returns_none(store: ScheduledInboxNoticeStore) -> None:
    assert store.get_last_seen_entry_id() is None


# --- set / upsert behavior -------------------------------------------------------


def test_set_then_get_returns_the_stored_value(
    store: ScheduledInboxNoticeStore,
) -> None:
    store.set_last_seen_entry_id(5)
    assert store.get_last_seen_entry_id() == 5


def test_set_twice_updates_the_same_row_not_a_second_one(
    store: ScheduledInboxNoticeStore,
) -> None:
    store.set_last_seen_entry_id(5)
    store.set_last_seen_entry_id(9)
    assert store.get_last_seen_entry_id() == 9


def test_set_never_creates_a_second_row(store: ScheduledInboxNoticeStore) -> None:
    store.set_last_seen_entry_id(1)
    store.set_last_seen_entry_id(2)
    store.set_last_seen_entry_id(3)

    from storage.database import session_scope

    with session_scope(store._session_factory) as db:  # type: ignore[attr-defined]
        rows = db.query(ScheduledInboxNoticeState).all()
        assert len(rows) == 1
        assert rows[0].last_seen_entry_id == 3


def test_set_can_advance_to_a_lower_value_without_raising(
    store: ScheduledInboxNoticeStore,
) -> None:
    """The store itself has no opinion about monotonicity - that
    invariant is the caller's (build_scheduled_inbox_notice's) own
    responsibility, not enforced at the storage layer."""
    store.set_last_seen_entry_id(10)
    store.set_last_seen_entry_id(3)
    assert store.get_last_seen_entry_id() == 3


# --- persistence across sessions -------------------------------------------------


def test_marker_persists_across_database_reopens(tmp_path) -> None:
    from sqlalchemy import create_engine

    db_path = tmp_path / "notice_persistence_check.db"

    write_engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(write_engine)
    write_store = ScheduledInboxNoticeStore(create_session_factory(write_engine))
    write_store.set_last_seen_entry_id(42)
    write_engine.dispose()

    read_engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(read_engine)
    read_store = ScheduledInboxNoticeStore(create_session_factory(read_engine))
    assert read_store.get_last_seen_entry_id() == 42
    read_engine.dispose()


# --- structural: narrow, two-method API, no Inbox/Schedule access ----------------


def test_store_public_api_is_exactly_the_approved_two_methods() -> None:
    public_methods = {
        name
        for name in dir(ScheduledInboxNoticeStore)
        if not name.startswith("_") and callable(getattr(ScheduledInboxNoticeStore, name))
    }
    assert public_methods == {"get_last_seen_entry_id", "set_last_seen_entry_id"}


def test_store_module_never_imports_inbox_or_schedule_models() -> None:
    """Structural proof that this store's only concern is the marker
    itself - it never reads or writes InboxEntry/ScheduleEntry."""
    import ast
    import inspect

    import notice.scheduled_inbox_notice_store as store_module

    source = inspect.getsource(store_module)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    forbidden = {"InboxEntry", "ScheduleEntry", "InboxStore", "ScheduleStore"}
    assert imported_names & forbidden == set()


def test_table_is_created_by_the_existing_initialize_database_call() -> None:
    from sqlalchemy import create_engine, inspect

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    inspector = inspect(engine)
    assert "scheduled_inbox_notice_state" in inspector.get_table_names()
