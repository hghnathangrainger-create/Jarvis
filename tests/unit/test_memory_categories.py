"""
test_memory_categories.py

Unit tests for memory categories (Phase 5, Batch 1).

These cover the category vocabulary and normalisation in memory_models, and the
category-carrying behaviour of the memory store through a real in-memory SQLite
database: a default category of "general", custom categories preserved through
save/list/search, category filtering, counting by category, and safe fallback
for unknown or blank categories.

Run with:
    pytest tests/unit/test_memory_categories.py
"""

from __future__ import annotations

import pytest

from memory.memory_models import (
    DEFAULT_CATEGORY,
    KNOWN_CATEGORIES,
    is_known_category,
    normalize_category,
)


# --- normalize_category ------------------------------------------------------


def test_default_category_is_general() -> None:
    assert DEFAULT_CATEGORY == "general"
    assert "general" in KNOWN_CATEGORIES


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("personal", "personal"),
        ("PERSONAL", "personal"),
        ("  Project  ", "project"),
        ("note", "note"),
        ("preference", "preference"),
        ("general", "general"),
    ],
)
def test_normalize_known_categories(raw: str, expected: str) -> None:
    assert normalize_category(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "banana", "xyz", "123"])
def test_normalize_unknown_or_blank_falls_back(raw: str | None) -> None:
    assert normalize_category(raw) == "general"


def test_is_known_category() -> None:
    assert is_known_category("personal") is True
    assert is_known_category("  NOTE ") is True
    assert is_known_category("banana") is False
    assert is_known_category(None) is False


# --- Store behaviour (real in-memory SQLite) ---------------------------------
#
# These tests use a real SQLite database so the ORM column and filtering are
# genuinely exercised. They are skipped automatically if SQLAlchemy is not
# importable in the current environment.

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


def test_save_defaults_to_general(store) -> None:
    record = store.save(content="a plain memory")
    assert record.category == "general"


def test_save_preserves_custom_category(store) -> None:
    record = store.save(content="a project note", category="project")
    assert record.category == "project"


def test_save_normalizes_unknown_category(store) -> None:
    record = store.save(content="odd category", category="banana")
    assert record.category == "general"


def test_list_preserves_category(store) -> None:
    store.save(content="personal thing", category="personal")
    records = store.list_recent()
    assert records[0].category == "personal"


def test_search_preserves_category(store) -> None:
    store.save(content="find me here", category="note")
    results = store.search("find me")
    assert len(results) == 1
    assert results[0].category == "note"


def test_list_filters_by_category(store) -> None:
    store.save(content="p1", category="project")
    store.save(content="g1", category="general")
    store.save(content="p2", category="project")
    projects = store.list_recent(category="project")
    assert {r.content for r in projects} == {"p1", "p2"}


def test_search_filters_by_category(store) -> None:
    store.save(content="shared word alpha", category="project")
    store.save(content="shared word beta", category="personal")
    results = store.search("shared word", category="personal")
    assert len(results) == 1
    assert results[0].content == "shared word beta"


def test_count_by_category(store) -> None:
    store.save(content="a", category="project")
    store.save(content="b", category="project")
    store.save(content="c", category="general")
    assert store.count_by_category("project") == 2
    assert store.count_by_category("general") == 1
    # Unknown category normalises to general for counting.
    assert store.count_by_category("banana") == 1