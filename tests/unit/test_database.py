"""
test_database.py

Unit tests for storage/database.py's SQLite concurrency configuration
(Phase 19, Batch 1): the journal_mode=WAL and busy_timeout pragmas added
to support a real second reader process (the local dashboard) alongside
the Jarvis CLI process.

These tests inspect the actual configured SQLAlchemy engine's real SQLite
connection - not a mock - via PRAGMA queries, exactly as the authorizing
instructions require ("Verify WAL and busy_timeout empirically").

Run with:
    pytest tests/unit/test_database.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text

from storage.database import (
    _SQLITE_BUSY_TIMEOUT_MS,
    create_session_factory,
    initialize_database,
    session_scope,
)
from storage.models import EpisodicMemory


def test_file_backed_database_resolves_to_wal_journal_mode(
    tmp_path: Path,
) -> None:
    """WAL is SQLite's own durable, per-file setting - it only takes
    effect for a real file-backed database, not ':memory:'."""
    db_path = tmp_path / "wal_check.db"
    engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(engine)

    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()

    assert mode is not None
    assert mode.lower() == "wal"


def test_busy_timeout_resolves_to_configured_value(tmp_path: Path) -> None:
    db_path = tmp_path / "busy_timeout_check.db"
    engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(engine)

    with engine.connect() as conn:
        timeout_ms = conn.execute(text("PRAGMA busy_timeout")).scalar()

    assert timeout_ms == _SQLITE_BUSY_TIMEOUT_MS


def test_in_memory_database_does_not_claim_wal() -> None:
    """Documented, honest limitation: SQLite ignores journal_mode=WAL for
    ':memory:' databases and always reports 'memory' regardless of what
    is requested. The pragma call itself must not error, and this test
    exists so that fact is proven, not merely asserted in a docstring."""
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)

    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()

    assert mode is not None
    assert mode.lower() == "memory"


def test_existing_memory_writes_still_persist_under_wal(tmp_path: Path) -> None:
    """The WAL/busy_timeout pragmas must not change durability: a write
    committed in one session must still be visible to a fresh session."""
    db_path = tmp_path / "durability_check.db"
    engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(engine)
    factory = create_session_factory(engine)

    with session_scope(factory) as db:
        db.add(EpisodicMemory(content="hello", source="conversation", category="general"))

    with session_scope(factory) as db:
        row = db.query(EpisodicMemory).one()
        assert row.content == "hello"


def test_foreign_key_enforcement_is_unaffected_by_new_listener(
    tmp_path: Path,
) -> None:
    """The pre-existing _enable_sqlite_foreign_keys listener must keep
    firing alongside the new _configure_sqlite_concurrency listener."""
    db_path = tmp_path / "fk_check.db"
    engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(engine)

    with engine.connect() as conn:
        fk_status = conn.execute(text("PRAGMA foreign_keys")).scalar()

    assert fk_status == 1
