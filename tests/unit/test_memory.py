"""
test_memory.py

Baseline unit tests for the memory store and the backward-compatibility of the
category column (Phase 5, Batch 1).

These confirm the core memory behaviour (save, list, search, count) still works
exactly as before and now carries a category, and that an older database created
without the category column is safely upgraded on initialisation.

Run with:
    pytest tests/unit/test_memory.py
"""

from __future__ import annotations

import sqlite3

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")


@pytest.fixture()
def store():
    """Build an EpisodicMemoryStore backed by a fresh in-memory database."""
    from sqlalchemy import create_engine

    from memory.episodic_memory import EpisodicMemoryStore
    from storage.database import create_session_factory, initialize_database

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return EpisodicMemoryStore(factory)


# --- Core behaviour still works ----------------------------------------------


def test_save_and_list(store) -> None:
    store.save(content="first memory")
    store.save(content="second memory")
    records = store.list_recent()
    # Newest first.
    assert records[0].content == "second memory"
    assert records[1].content == "first memory"


def test_search_matches_content(store) -> None:
    store.save(content="Nathan likes Python")
    store.save(content="the sky is blue")
    results = store.search("python")
    assert len(results) == 1
    assert results[0].content == "Nathan likes Python"


def test_search_empty_query_returns_nothing(store) -> None:
    store.save(content="anything")
    assert store.search("") == []
    assert store.search("   ") == []


def test_count(store) -> None:
    assert store.count() == 0
    store.save(content="a")
    store.save(content="b")
    assert store.count() == 2


def test_every_record_has_a_category(store) -> None:
    store.save(content="no category given")
    record = store.list_recent()[0]
    assert record.category == "general"


# --- Backward compatibility: an old database without the category column -----


def test_initialize_upgrades_old_database(tmp_path) -> None:
    """A pre-Phase-5 database gains the category column, backfilled to general."""
    from sqlalchemy import create_engine

    from memory.episodic_memory import EpisodicMemoryStore
    from storage.database import create_session_factory, initialize_database

    db_file = tmp_path / "old.db"

    # Build an OLD schema by hand: episodic_memories WITHOUT a category column.
    con = sqlite3.connect(db_file)
    con.execute(
        """
        CREATE TABLE episodic_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            content TEXT NOT NULL,
            source VARCHAR(64) NOT NULL DEFAULT 'conversation',
            created_at TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        "INSERT INTO episodic_memories (content, source, created_at) "
        "VALUES ('legacy memory', 'conversation', '2026-01-01 00:00:00')"
    )
    con.commit()
    con.close()

    # Initialise through the real code path: this should add the column.
    engine = create_engine(f"sqlite:///{db_file}")
    initialize_database(engine)

    # The legacy row now loads and carries the default category.
    factory = create_session_factory(engine)
    store = EpisodicMemoryStore(factory)
    records = store.list_recent()
    assert len(records) == 1
    assert records[0].content == "legacy memory"
    assert records[0].category == "general"


def test_initialize_is_idempotent(tmp_path) -> None:
    """Initialising twice does not fail or duplicate the column."""
    from sqlalchemy import create_engine

    from storage.database import initialize_database

    db_file = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{db_file}")
    initialize_database(engine)
    # Second call must be a no-op, not an error.
    initialize_database(engine)