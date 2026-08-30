"""
store.py

SQLite-backed store for the Jarvis Knowledge Library.

Responsibilities:
    - Persist knowledge entries in SQLite for structured queries.
    - Expose add, get, search, update, delete, list_all, count operations.
    - Handle JSON serialisation of the tags list.

Does NOT:
    - Perform semantic search (see indexer.py).
    - Coordinate indexing or hybrid search (see manager.py).

The KnowledgeStore owns structured, keyword-based access to knowledge
entries. Semantic search lives in the KnowledgeIndexer, which wraps
ChromaDB.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import Integer, String, Text, text
from sqlalchemy.orm import Mapped, Session as OrmSession, mapped_column, sessionmaker

from knowledge.models import KnowledgeEntry

logger = logging.getLogger(__name__)


class _KnowledgeEntryRow:
    """Lightweight ORM-style row for the knowledge_entries table.

    Uses raw SQLAlchemy Core via the session for simplicity — mirrors
    the pattern used by EpisodicMemoryStore.
    """

    pass


def _ensure_knowledge_table(session_factory: sessionmaker[OrmSession]) -> None:
    """Create the knowledge_entries table if it does not exist.

    This is idempotent and safe to call on every startup.
    """
    with session_factory() as session:
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS knowledge_entries ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  title TEXT NOT NULL DEFAULT '',"
                "  content TEXT NOT NULL DEFAULT '',"
                "  category VARCHAR(32) NOT NULL DEFAULT 'general',"
                "  tags TEXT NOT NULL DEFAULT '[]',"
                "  source VARCHAR(64) NOT NULL DEFAULT 'manual',"
                "  created_at TIMESTAMP NOT NULL,"
                "  updated_at TIMESTAMP NOT NULL"
                ")"
            )
        )
        session.commit()


class KnowledgeStore:
    """SQLite-backed store for knowledge entries.

    Uses raw SQL via SQLAlchemy session for reads and writes, matching
    the EpisodicMemoryStore pattern.

    Attributes:
        _session_factory: SQLAlchemy session factory.
    """

    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        """Initialise the store.

        Args:
            session_factory: SQLAlchemy session factory for database access.
        """
        self._session_factory = session_factory
        _ensure_knowledge_table(session_factory)

    def add(self, entry: KnowledgeEntry) -> KnowledgeEntry:
        """Insert a new knowledge entry.

        Args:
            entry: The KnowledgeEntry to store. The id field is set by
                the database on insert.

        Returns:
            The stored KnowledgeEntry with the assigned id and timestamps.
        """
        now = datetime.now(timezone.utc)
        tags_json = json.dumps(entry.tags)

        with self._session_factory() as session:
            cursor = session.execute(
                text(
                    "INSERT INTO knowledge_entries "
                    "(title, content, category, tags, source, created_at, updated_at) "
                    "VALUES (:title, :content, :category, :tags, :source, :created_at, :updated_at)"
                ),
                {
                    "title": entry.title,
                    "content": entry.content,
                    "category": entry.category,
                    "tags": tags_json,
                    "source": entry.source,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            session.commit()
            entry_id = cursor.lastrowid

        return KnowledgeEntry(
            id=entry_id,
            title=entry.title,
            content=entry.content,
            category=entry.category,
            tags=list(entry.tags),
            source=entry.source,
            created_at=now,
            updated_at=now,
        )

    def get(self, entry_id: int) -> KnowledgeEntry | None:
        """Return a single knowledge entry by id, or None if not found.

        Args:
            entry_id: The primary key of the entry.

        Returns:
            The matching KnowledgeEntry, or None.
        """
        with self._session_factory() as session:
            row = session.execute(
                text("SELECT * FROM knowledge_entries WHERE id = :id"),
                {"id": entry_id},
            ).mappings().first()

        if row is None:
            return None
        return self._row_to_entry(row)

    def search(self, query: str, limit: int = 20) -> list[KnowledgeEntry]:
        """Return entries whose title or content matches the query (case-insensitive substring).

        Args:
            query: The text to search for.
            limit: Maximum number of results. Defaults to 20.

        Returns:
            A list of matching KnowledgeEntry objects, newest first.
        """
        if not query or not query.strip():
            return []
        pattern = f"%{query.strip()}%"
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT * FROM knowledge_entries "
                    "WHERE title LIKE :pattern OR content LIKE :pattern "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"pattern": pattern, "limit": limit},
            ).mappings().all()
        return [self._row_to_entry(r) for r in rows]

    def search_by_category(self, category: str, limit: int = 20) -> list[KnowledgeEntry]:
        """Return entries in a specific category.

        Args:
            category: The category to filter by.
            limit: Maximum number of results. Defaults to 20.

        Returns:
            A list of matching KnowledgeEntry objects, newest first.
        """
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT * FROM knowledge_entries "
                    "WHERE category = :category "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"category": category, "limit": limit},
            ).mappings().all()
        return [self._row_to_entry(r) for r in rows]

    def search_by_tags(self, tags: list[str], limit: int = 20) -> list[KnowledgeEntry]:
        """Return entries that contain any of the specified tags.

        Tags are stored as a JSON array. This performs a substring match
        on the serialised JSON, which is simple and effective for small
        tag sets.

        Args:
            tags: The tags to search for.
            limit: Maximum number of results. Defaults to 20.

        Returns:
            A list of matching KnowledgeEntry objects, newest first.
        """
        if not tags:
            return []
        # Build OR conditions for each tag.
        conditions = []
        params: dict[str, str | int] = {"limit": limit}
        for i, tag in enumerate(tags):
            key = f"tag_{i}"
            conditions.append(f"tags LIKE :{key}")
            params[key] = f"%{tag}%"
        where_clause = " OR ".join(conditions)
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    f"SELECT * FROM knowledge_entries "
                    f"WHERE {where_clause} "
                    f"ORDER BY created_at DESC LIMIT :limit"
                ),
                params,
            ).mappings().all()
        return [self._row_to_entry(r) for r in rows]

    def update(self, entry_id: int, fields: dict[str, object]) -> KnowledgeEntry | None:
        """Update specific fields of a knowledge entry.

        Args:
            entry_id: The id of the entry to update.
            fields: A dict of field names to new values. Supported keys:
                title, content, category, tags, source.

        Returns:
            The updated KnowledgeEntry, or None if no entry has that id.
        """
        existing = self.get(entry_id)
        if existing is None:
            return None

        # Build update values.
        updates: dict[str, object] = {}
        for key in ("title", "content", "category", "source"):
            if key in fields:
                updates[key] = fields[key]
        if "tags" in fields:
            updates["tags"] = json.dumps(fields["tags"])
        updates["updated_at"] = datetime.now(timezone.utc)

        set_parts = [f"{k} = :{k}" for k in updates]
        updates["id"] = entry_id
        with self._session_factory() as session:
            session.execute(
                text(f"UPDATE knowledge_entries SET {', '.join(set_parts)} WHERE id = :id"),
                updates,
            )
            session.commit()

        return self.get(entry_id)

    def delete(self, entry_id: int) -> bool:
        """Delete a knowledge entry by id.

        Args:
            entry_id: The id of the entry to delete.

        Returns:
            True if a row was deleted.
        """
        with self._session_factory() as session:
            cursor = session.execute(
                text("DELETE FROM knowledge_entries WHERE id = :id"),
                {"id": entry_id},
            )
            session.commit()
            return cursor.rowcount > 0

    def list_all(self, limit: int = 50) -> list[KnowledgeEntry]:
        """Return all knowledge entries, newest first.

        Args:
            limit: Maximum number of results. Defaults to 50.

        Returns:
            A list of KnowledgeEntry objects.
        """
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT * FROM knowledge_entries "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).mappings().all()
        return [self._row_to_entry(r) for r in rows]

    def count(self) -> int:
        """Return the total number of knowledge entries.

        Returns:
            The count of stored entries.
        """
        with self._session_factory() as session:
            row = session.execute(
                text("SELECT COUNT(*) as cnt FROM knowledge_entries")
            ).mappings().first()
        return row["cnt"] if row else 0

    @staticmethod
    def _row_to_entry(row: dict) -> KnowledgeEntry:
        """Convert a database row mapping to a KnowledgeEntry.

        Args:
            row: A row mapping from SQLAlchemy.

        Returns:
            A KnowledgeEntry instance.
        """
        tags_raw = row.get("tags", "[]")
        try:
            tags = json.loads(tags_raw) if isinstance(tags_raw, str) else []
        except (json.JSONDecodeError, TypeError):
            tags = []

        return KnowledgeEntry(
            id=row["id"],
            title=row.get("title", ""),
            content=row.get("content", ""),
            category=row.get("category", "general"),
            tags=tags,
            source=row.get("source", "manual"),
            created_at=row.get("created_at", datetime.now(timezone.utc)),
            updated_at=row.get("updated_at", datetime.now(timezone.utc)),
        )
