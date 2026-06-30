"""
test_memory.py

Tests for the Jarvis memory layer:
    memory/memory_manager.py
    memory/episodic_memory.py

The MemoryManager policy is tested with a fake store (no database needed).
The EpisodicMemoryStore is tested against a real temporary SQLite database.

Run with:
    pytest tests/unit/test_memory.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from config.settings import Settings
from memory.episodic_memory import EpisodicMemoryStore, MemoryRecord
from memory.memory_manager import MemoryManager
from storage.database import (
    create_database_engine,
    create_session_factory,
    initialize_database,
)


# --- MemoryManager policy (fake store) ---------------------------------------


class _FakeStore:
    """In-memory stand-in for EpisodicMemoryStore used to test policy only."""

    def __init__(self) -> None:
        self.saved: list[MemoryRecord] = []
        self._id = 0

    def save(
        self, *, content: str, source: str = "conversation", session_id: int | None = None
    ) -> MemoryRecord:
        self._id += 1
        record = MemoryRecord(
            id=self._id,
            content=content,
            source=source,
            session_id=session_id,
            created_at=datetime.now(timezone.utc),
        )
        self.saved.append(record)
        return record

    def list_recent(self, limit: int = 20) -> list[MemoryRecord]:
        return list(reversed(self.saved))[:limit]

    def search(self, query: str, limit: int = 20) -> list[MemoryRecord]:
        term = query.strip().lower()
        if not term:
            return []
        return [r for r in reversed(self.saved) if term in r.content.lower()][:limit]

    def count(self) -> int:
        return len(self.saved)


def test_normal_memory_is_saved() -> None:
    manager = MemoryManager(_FakeStore())
    assert manager.save("Nathan prefers concise answers.") is not None


def test_do_not_remember_exact_phrase_blocks_storage() -> None:
    manager = MemoryManager(_FakeStore())
    assert manager.save("Do not remember this secret.") is None


def test_do_not_remember_natural_phrasing_blocks_storage() -> None:
    manager = MemoryManager(_FakeStore())
    assert manager.save("Please DO NOT REMEMBER my password idea.") is None


def test_empty_content_is_not_saved() -> None:
    manager = MemoryManager(_FakeStore())
    assert manager.save("   ") is None
    assert manager.save("") is None


def test_search_is_case_insensitive_substring() -> None:
    manager = MemoryManager(_FakeStore())
    manager.save("Nathan is learning trading.")
    assert len(manager.search("TRADING")) == 1


def test_should_skip_helper() -> None:
    assert MemoryManager.should_skip("do not remember this") is True
    assert MemoryManager.should_skip("remember this") is False


# --- EpisodicMemoryStore (real SQLite) ---------------------------------------


def _store(tmp_path: Path) -> EpisodicMemoryStore:
    settings = Settings(
        anthropic_api_key="sk-test",
        ai_model="claude-sonnet-4-6",
        ai_max_tokens=1024,
        database_path=tmp_path / "test_jarvis.db",
        log_level="INFO",
        approval_timeout_seconds=60,
        debug=False,
    )
    engine = create_database_engine(settings)
    initialize_database(engine)
    return EpisodicMemoryStore(create_session_factory(engine))


def test_store_save_and_list(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(content="first memory")
    store.save(content="second memory")
    recent = store.list_recent()
    assert len(recent) == 2
    assert recent[0].content == "second memory"  # newest first


def test_store_search(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(content="Nathan likes Python.")
    store.save(content="Nathan likes coffee.")
    store.save(content="The weather is cold.")
    results = store.search("nathan")
    assert len(results) == 2


def test_store_count(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.count() == 0
    store.save(content="one")
    assert store.count() == 1