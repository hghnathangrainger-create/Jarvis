"""
episodic_memory.py

Data-access layer for episodic memories in the Jarvis AI Operating System.

Responsibilities:
    - Save a memory entry to the existing episodic_memories table.
    - List the most recent memory entries.
    - Search memory entries by a simple case-insensitive text match.
    - Report a true, exact total count of memories matching a search
      query (count_matching(), Phase 75, Batch 2), mirroring search()'s
      own filter semantics via a COUNT query - never fetching rows.

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
from memory.memory_models import DEFAULT_CATEGORY, normalize_category


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
        category: The organisational label for the memory (e.g. "general").
        created_at: UTC timestamp marking when the memory was stored.
    """

    id: int
    content: str
    source: str
    session_id: int | None
    created_at: datetime
    category: str = DEFAULT_CATEGORY


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
        category: str | None = None,
    ) -> MemoryRecord:
        """Persist a single memory entry.

        Args:
            content: The memory text to store.
            source: Where the memory originated. Defaults to "conversation".
            session_id: Optional session the memory belongs to.
            category: Optional organisational label. Unknown or blank values
                fall back to "general".

        Returns:
            A detached MemoryRecord describing the stored entry.
        """
        safe_category = normalize_category(category)
        with session_scope(self._session_factory) as db:
            entry = EpisodicMemory(
                content=content,
                source=source,
                session_id=session_id,
                category=safe_category,
            )
            db.add(entry)
            db.flush()  # populate id and created_at before the scope commits
            return self._to_record(entry)

    def list_recent(
        self, limit: int = 20, *, category: str | None = None
    ) -> list[MemoryRecord]:
        """Return the most recent memories, newest first.

        Args:
            limit: Maximum number of memories to return. Defaults to 20.
            category: Optional category to filter by. When given, only memories
                in that (normalised) category are returned. When None, all
                categories are returned.

        Returns:
            A list of MemoryRecord objects ordered from newest to oldest.
        """
        with session_scope(self._session_factory) as db:
            query = db.query(EpisodicMemory)
            if category is not None:
                query = query.filter(
                    EpisodicMemory.category == normalize_category(category)
                )
            rows = (
                query.order_by(
                    EpisodicMemory.created_at.desc(),
                    EpisodicMemory.id.desc(),
                )
                .limit(limit)
                .all()
            )
            return [self._to_record(row) for row in rows]

    def search(
        self, query: str, limit: int = 20, *, category: str | None = None
    ) -> list[MemoryRecord]:
        """Return memories whose content contains the query text.

        The match is a simple case-insensitive substring match. No embeddings
        or semantic search are used.

        Args:
            query: The text to search for within memory content.
            limit: Maximum number of memories to return. Defaults to 20.
            category: Optional category to further filter matches by.

        Returns:
            A list of matching MemoryRecord objects, newest first. An empty or
            whitespace-only query returns an empty list.
        """
        term = query.strip()
        if not term:
            return []

        pattern = f"%{term}%"
        with session_scope(self._session_factory) as db:
            db_query = db.query(EpisodicMemory).filter(
                EpisodicMemory.content.ilike(pattern)
            )
            if category is not None:
                db_query = db_query.filter(
                    EpisodicMemory.category == normalize_category(category)
                )
            rows = (
                db_query.order_by(
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

    def count_by_category(self, category: str) -> int:
        """Return the number of stored memories in a category.

        Args:
            category: The category to count. It is normalised before counting,
                so unknown or blank values count the "general" category.

        Returns:
            The number of memories in the (normalised) category.
        """
        safe_category = normalize_category(category)
        with session_scope(self._session_factory) as db:
            return (
                db.query(EpisodicMemory)
                .filter(EpisodicMemory.category == safe_category)
                .count()
            )

    def count_matching(self, query: str, *, category: str | None = None) -> int:
        """Return the true, exact number of memories matching a search
        query (Phase 75, Batch 2).

        Mirrors search()'s own filtering semantics exactly - the same
        case-insensitive substring match against content, the same
        optional category filter - but issues a COUNT query instead of
        fetching and counting rows in Python, and never applies a
        limit. This exists solely so callers (MemoryTool) can disclose
        an honest, exact "N of M matches" truncation notice, without
        ever fetching more rows than search()'s own limit already
        returns.

        Args:
            query: The text to search for within memory content - the
                same case-insensitive substring match search() uses.
            category: Optional category to further filter matches by,
                identical to search()'s own category filter.

        Returns:
            The true, exact count of matching memories. An empty or
            whitespace-only query returns 0, mirroring search()'s own
            empty-query behaviour (which returns an empty list, never
            an unfiltered count of everything).
        """
        term = query.strip()
        if not term:
            return 0

        pattern = f"%{term}%"
        with session_scope(self._session_factory) as db:
            db_query = db.query(EpisodicMemory).filter(
                EpisodicMemory.content.ilike(pattern)
            )
            if category is not None:
                db_query = db_query.filter(
                    EpisodicMemory.category == normalize_category(category)
                )
            return db_query.count()

    def get_by_id(self, memory_id: int) -> MemoryRecord | None:
        """Return a single memory by its id, or None if it does not exist.

        Args:
            memory_id: The primary key of the memory to fetch.

        Returns:
            The matching MemoryRecord, or None when no memory has that id.
        """
        with session_scope(self._session_factory) as db:
            entry = db.get(EpisodicMemory, memory_id)
            if entry is None:
                return None
            return self._to_record(entry)

    def update_content(
        self, memory_id: int, new_content: str
    ) -> MemoryRecord | None:
        """Replace the content of an existing memory.

        Args:
            memory_id: The id of the memory to update.
            new_content: The new content text. Leading and trailing whitespace
                is stripped.

        Returns:
            The updated MemoryRecord, or None if no memory has that id.
        """
        text = new_content.strip()
        with session_scope(self._session_factory) as db:
            entry = db.get(EpisodicMemory, memory_id)
            if entry is None:
                return None
            entry.content = text
            db.flush()
            return self._to_record(entry)

    def update_category(
        self, memory_id: int, new_category: str
    ) -> MemoryRecord | None:
        """Change the category of an existing memory.

        Args:
            memory_id: The id of the memory to move.
            new_category: The new category. Unknown or blank values normalise to
                "general".

        Returns:
            The updated MemoryRecord, or None if no memory has that id.
        """
        safe_category = normalize_category(new_category)
        with session_scope(self._session_factory) as db:
            entry = db.get(EpisodicMemory, memory_id)
            if entry is None:
                return None
            entry.category = safe_category
            db.flush()
            return self._to_record(entry)

    def delete(self, memory_id: int) -> bool:
        """Delete a single memory by its id.

        Args:
            memory_id: The id of the memory to delete.

        Returns:
            True if a memory was deleted, False if no memory had that id.
        """
        with session_scope(self._session_factory) as db:
            entry = db.get(EpisodicMemory, memory_id)
            if entry is None:
                return False
            db.delete(entry)
            return True

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
            category=entry.category,
            created_at=entry.created_at,
        )