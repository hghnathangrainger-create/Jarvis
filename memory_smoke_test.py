"""
memory_smoke_test.py

A standalone smoke test for the Jarvis memory layer.

Run this directly (no pytest needed) to confirm the memory engine works
end to end against a real SQLite database. It saves a few memories, exercises
the "do not remember" policy, lists recent memories, and searches them.

Place this file in the project root and run it from PowerShell:

    poetry run python memory_smoke_test.py
"""

from __future__ import annotations

from config.settings import load_settings
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from storage.database import (
    create_database_engine,
    create_session_factory,
    initialize_database,
)


def main() -> None:
    """Run the memory smoke test against the configured database."""
    settings = load_settings()

    engine = create_database_engine(settings)
    initialize_database(engine)
    factory = create_session_factory(engine)

    store = EpisodicMemoryStore(factory)
    memory = MemoryManager(store)

    print("--- Saving memories ---")
    for text in (
        "Nathan prefers concise answers.",
        "Nathan is learning trading.",
        "Nathan goes to the gym on Mondays.",
        "Do not remember this: a throwaway thought.",
        "Please do not remember my password idea.",
    ):
        record = memory.save(text, source="smoke_test")
        status = f"saved (id={record.id})" if record else "SKIPPED (do not remember)"
        print(f"  {status}: {text}")

    print("\n--- Recent memories (newest first) ---")
    for record in memory.list_recent(limit=10):
        print(f"  [{record.id}] {record.created_at.isoformat()}  {record.content}")

    print("\n--- Search: 'nathan' ---")
    for record in memory.search("nathan"):
        print(f"  [{record.id}] {record.content}")

    print("\n--- Search: 'trading' ---")
    for record in memory.search("trading"):
        print(f"  [{record.id}] {record.content}")

    print(f"\nTotal memories stored: {memory.count()}")
    print("Smoke test complete.")


if __name__ == "__main__":
    main()