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


# --- count_matching() (Phase 75, Batch 2) -------------------------------------


def test_count_matching_returns_real_total(store) -> None:
    store.save(content="Nathan likes Python")
    store.save(content="Python is great")
    store.save(content="the sky is blue")
    assert store.count_matching("python") == 2


def test_count_matching_mirrors_search_semantics_exactly(store) -> None:
    """count_matching() must count exactly the same rows search() would
    return if it had no limit - same case-insensitive substring match,
    same filter shape."""
    for i in range(30):
        store.save(content=f"memory match {i}")
    store.save(content="unrelated entry")

    unbounded = store.search("match", limit=1000)
    assert store.count_matching("match") == len(unbounded) == 30


def test_count_matching_is_category_specific(store) -> None:
    store.save(content="api deadline", category="project")
    store.save(content="api notes", category="project")
    store.save(content="api reminder", category="personal")
    assert store.count_matching("api") == 3
    assert store.count_matching("api", category="project") == 2
    assert store.count_matching("api", category="personal") == 1


def test_count_matching_empty_query_mirrors_search_behavior(store) -> None:
    store.save(content="anything")
    assert store.count_matching("") == 0
    assert store.count_matching("   ") == 0
    # search() also returns nothing for an empty/blank query - the two
    # must stay consistent with each other.
    assert store.search("") == []
    assert store.search("   ") == []


def test_count_matching_zero_when_nothing_matches(store) -> None:
    store.save(content="hello world")
    assert store.count_matching("nonexistent") == 0


def test_count_matching_does_not_mutate_or_fetch_rows(store) -> None:
    store.save(content="a match")
    store.save(content="another match")
    before = store.list_recent()
    store.count_matching("match")
    after = store.list_recent()
    assert before == after


# --- MemoryManager.count_matching() (Phase 75, Batch 2) -----------------------


def test_memory_manager_count_matching_passes_through_to_store(store) -> None:
    """MemoryManager.count_matching() is a thin passthrough to
    EpisodicMemoryStore.count_matching() - this proves the manager
    layer adds no logic of its own beyond delegating, mirroring
    count_by_category()'s own established precedent."""
    from memory.memory_manager import MemoryManager

    manager = MemoryManager(store)
    manager.save(content="api deadline", category="project")
    manager.save(content="api notes", category="project")
    manager.save(content="unrelated", category="personal")

    assert manager.count_matching("api") == 2
    assert manager.count_matching("api", category="project") == 2
    assert manager.count_matching("api", category="personal") == 0


def test_memory_manager_count_matching_empty_query_returns_zero(store) -> None:
    from memory.memory_manager import MemoryManager

    manager = MemoryManager(store)
    manager.save(content="anything")
    assert manager.count_matching("") == 0


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