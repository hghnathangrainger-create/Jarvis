"""
episodic_memory.py

Data-access layer for episodic memories in the Jarvis AI Operating System.

Responsibilities:
    - Save a memory entry to the existing episodic_memories table.
    - List the most recent memory entries.
    - Search memory entries by a simple case-insensitive text match.

Does NOT:
    - Decide whether a memory should be stored (see memory_manager.py for the
      "do not remember" policy).
    - Use vector databases, embeddings, or any AI calls.
    - Modify or rewrite the storage layer or the ORM models.

This module is a thin, focused wrapper over the EpisodicMemory model. It owns
how episodic memories are read from and written to the database, and nothing
more. All policy decisions live one layer up, in the Memory Manager.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from storage.database import session_scope
from storage.models import EpisodicMemory


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """A plain, detached view of a stored episodic memory.

    The store returns these instead of live ORM objects so that callers never
    depend on an open database session. The data is safe to read after the
    session that produced it has closed.

    Attributes:
        id: The primary key of the stored memory.
        content: The memory text.
        source: Where the memory originated (e.g. "conversation").
        session_id: The session the memory belongs to, if any.
        created_at: UTC timestamp marking when the memory was stored.
    """

    id: int
    content: str
    source: str
    session_id: int | None
    created_at: datetime


class EpisodicMemoryStore:
    """Reads and writes episodic memories using the existing storage layer.

    Attributes:
        _session_factory: Factory used to open database sessions for each
            operation.
    """

    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        """Initialise the store with a database session factory.

        Args:
            session_factory: The factory used to create sessions, typically
                produced by storage.database.create_session_factory.
        """
        self._session_factory = session_factory

    def save(
        self,
        *,
        content: str,
        source: str = "conversation",
        session_id: int | None = None,
    ) -> MemoryRecord:
        """Persist a single memory entry.

        Args:
            content: The memory text to store.
            source: Where the memory originated. Defaults to "conversation".
            session_id: Optional session the memory belongs to.

        Returns:
            A detached MemoryRecord describing the stored entry.
        """
        with session_scope(self._session_factory) as db:
            entry = EpisodicMemory(
                content=content,
                source=source,
                session_id=session_id,
            )
            db.add(entry)
            db.flush()  # populate id and created_at before the scope commits
            return self._to_record(entry)

    def list_recent(self, limit: int = 20) -> list[MemoryRecord]:
        """Return the most recent memories, newest first.

        Args:
            limit: Maximum number of memories to return. Defaults to 20.

        Returns:
            A list of MemoryRecord objects ordered from newest to oldest.
        """
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(EpisodicMemory)
                .order_by(
                    EpisodicMemory.created_at.desc(),
                    EpisodicMemory.id.desc(),
                )
                .limit(limit)
                .all()
            )
            return [self._to_record(row) for row in rows]

    def search(self, query: str, limit: int = 20) -> list[MemoryRecord]:
        """Return memories whose content contains the query text.

        The match is a simple case-insensitive substring match. No embeddings
        or semantic search are used in Phase 1.

        Args:
            query: The text to search for within memory content.
            limit: Maximum number of memories to return. Defaults to 20.

        Returns:
            A list of matching MemoryRecord objects, newest first. An empty or
            whitespace-only query returns an empty list.
        """
        term = query.strip()
        if not term:
            return []

        pattern = f"%{term}%"
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(EpisodicMemory)
                .filter(EpisodicMemory.content.ilike(pattern))
                .order_by(
                    EpisodicMemory.created_at.desc(),
                    EpisodicMemory.id.desc(),
                )
                .limit(limit)
                .all()
            )
            return [self._to_record(row) for row in rows]

    def count(self) -> int:
        """Return the total number of stored memories.

        Returns:
            The total count of episodic memory entries.
        """
        with session_scope(self._session_factory) as db:
            return db.query(EpisodicMemory).count()

    @staticmethod
    def _to_record(entry: EpisodicMemory) -> MemoryRecord:
        """Convert an ORM entry into a detached MemoryRecord.

        Args:
            entry: The ORM EpisodicMemory instance to convert.

        Returns:
            A detached MemoryRecord with the entry's data copied out.
        """
        return MemoryRecord(
            id=entry.id,
            content=entry.content,
            source=entry.source,
            session_id=entry.session_id,
            created_at=entry.created_at,
        )