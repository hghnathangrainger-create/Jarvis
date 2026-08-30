"""
manager.py

High-level knowledge interface for the Jarvis AI Operating System.

Responsibilities:
    - Provide a single, simple API for adding, searching, updating,
      and deleting knowledge entries.
    - Coordinate SQLite (keyword search) and ChromaDB (semantic search)
      for hybrid search with deduplication.

Does NOT:
    - Talk to the database directly (it delegates to KnowledgeStore).
    - Use vector databases directly (it delegates to KnowledgeIndexer).
    - Implement AI logic.

The KnowledgeManager is the layer the rest of Jarvis talks to. It owns
knowledge policy; the KnowledgeStore beneath it owns persistence, and
the KnowledgeIndexer owns vector indexing.
"""

from __future__ import annotations

import logging

from knowledge.indexer import KnowledgeIndexer
from knowledge.models import KnowledgeEntry
from knowledge.store import KnowledgeStore

logger = logging.getLogger(__name__)


class KnowledgeManager:
    """Coordinates knowledge storage, indexing, and retrieval.

    Wraps a KnowledgeStore (SQLite) and a KnowledgeIndexer (ChromaDB).
    All new entries are automatically indexed for semantic search.
    Searches can be keyword-only, semantic-only, or hybrid (combined
    with deduplication).

    Attributes:
        _store: The SQLite-backed knowledge store.
        _indexer: The ChromaDB-backed vector indexer.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        indexer: KnowledgeIndexer | None = None,
    ) -> None:
        """Initialise the manager.

        Args:
            store: The SQLite-backed knowledge store.
            indexer: Optional ChromaDB-backed indexer for semantic search.
                When None, semantic and hybrid search modes raise an error.
        """
        self._store = store
        self._indexer = indexer

    def add_knowledge(
        self,
        title: str,
        content: str,
        category: str = "general",
        tags: list[str] | None = None,
        source: str = "manual",
    ) -> KnowledgeEntry:
        """Add a new knowledge entry to both SQLite and ChromaDB.

        Args:
            title: A short, descriptive title.
            content: The full text content.
            category: An organisational label. Defaults to "general".
            tags: Optional list of tags for flexible categorisation.
            source: Where this knowledge came from. Defaults to "manual".

        Returns:
            The stored KnowledgeEntry with its assigned id.
        """
        entry = KnowledgeEntry(
            title=title,
            content=content,
            category=category,
            tags=tags or [],
            source=source,
        )
        stored = self._store.add(entry)

        # Index in ChromaDB for semantic search.
        if self._indexer is not None and self._indexer.available:
            try:
                self._indexer.add(
                    id=str(stored.id),
                    text=f"{stored.title} {stored.content}",
                    metadata={
                        "category": stored.category,
                        "source": stored.source,
                        "tags": ",".join(stored.tags),
                    },
                )
            except Exception:
                logger.warning(
                    "Failed to index knowledge entry %d in vector store",
                    stored.id,
                )

        return stored

    def get_knowledge(self, entry_id: int) -> KnowledgeEntry | None:
        """Return a single knowledge entry by id.

        Args:
            entry_id: The primary key of the entry.

        Returns:
            The matching KnowledgeEntry, or None.
        """
        return self._store.get(entry_id)

    def search_knowledge(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 10,
        category: str | None = None,
    ) -> list[KnowledgeEntry]:
        """Search the knowledge library.

        Args:
            query: The search text.
            mode: One of "keyword", "semantic", or "hybrid".
                - "keyword": SQLite substring match on title/content.
                - "semantic": ChromaDB vector similarity search.
                - "hybrid": Combines both with deduplication, semantic
                  results ranked first.
            top_k: Maximum number of results. Defaults to 10.
            category: Optional category filter for keyword search.

        Returns:
            A list of matching KnowledgeEntry objects.

        Raises:
            RuntimeError: If semantic/hybrid mode is requested but no
                indexer is configured.
        """
        mode = mode.strip().lower()

        if mode == "keyword":
            return self._keyword_search(query, top_k=top_k, category=category)

        if mode == "semantic":
            return self._semantic_search(query, top_k=top_k)

        if mode == "hybrid":
            return self._hybrid_search(query, top_k=top_k, category=category)

        raise ValueError(
            f"Unknown search mode '{mode}'. Use 'keyword', 'semantic', or 'hybrid'."
        )

    def update_knowledge(
        self, entry_id: int, **fields: object
    ) -> KnowledgeEntry | None:
        """Update fields of an existing knowledge entry.

        Re-indexes the entry in ChromaDB after updating.

        Args:
            entry_id: The id of the entry to update.
            **fields: Fields to update (title, content, category, tags, source).

        Returns:
            The updated KnowledgeEntry, or None if not found.
        """
        updated = self._store.update(entry_id, fields)
        if updated is None:
            return None

        # Re-index in ChromaDB.
        if self._indexer is not None and self._indexer.available:
            try:
                self._indexer.add(
                    id=str(updated.id),
                    text=f"{updated.title} {updated.content}",
                    metadata={
                        "category": updated.category,
                        "source": updated.source,
                        "tags": ",".join(updated.tags),
                    },
                )
            except Exception:
                logger.warning(
                    "Failed to re-index knowledge entry %d", updated.id
                )

        return updated

    def delete_knowledge(self, entry_id: int) -> bool:
        """Delete a knowledge entry from both SQLite and ChromaDB.

        Args:
            entry_id: The id of the entry to delete.

        Returns:
            True if the entry was deleted.
        """
        deleted = self._store.delete(entry_id)
        if deleted and self._indexer is not None and self._indexer.available:
            try:
                self._indexer.delete(id=str(entry_id))
            except Exception:
                logger.warning(
                    "Failed to remove knowledge entry %d from vector store",
                    entry_id,
                )
        return deleted

    def count(self) -> int:
        """Return the total number of knowledge entries.

        Returns:
            The count of stored entries.
        """
        return self._store.count()

    def _keyword_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        category: str | None = None,
    ) -> list[KnowledgeEntry]:
        """Keyword-based search via SQLite substring match."""
        if category:
            # First filter by category, then by query.
            entries = self._store.search_by_category(category, limit=top_k)
            if query and query.strip():
                pattern = query.strip().lower()
                entries = [
                    e for e in entries
                    if pattern in e.title.lower() or pattern in e.content.lower()
                ]
            return entries[:top_k]
        return self._store.search(query, limit=top_k)

    def _semantic_search(
        self, query: str, *, top_k: int = 10
    ) -> list[KnowledgeEntry]:
        """Semantic search via ChromaDB vector similarity."""
        if self._indexer is None or not self._indexer.available:
            raise RuntimeError(
                "Semantic search requires chromadb to be installed and "
                "a knowledge indexer to be configured."
            )

        results = self._indexer.search(query, top_k=top_k)
        entries: list[KnowledgeEntry] = []
        for result in results:
            entry_id_str = result.get("id")
            if entry_id_str is not None:
                try:
                    entry_id = int(entry_id_str)
                except (ValueError, TypeError):
                    continue
                entry = self._store.get(entry_id)
                if entry is not None:
                    entries.append(entry)
        return entries

    def _hybrid_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        category: str | None = None,
    ) -> list[KnowledgeEntry]:
        """Combine keyword and semantic results with deduplication.

        Semantic results are ranked first (most relevant), then keyword
        results fill the remaining slots.
        """
        seen_ids: set[int] = set()
        combined: list[KnowledgeEntry] = []

        # Semantic results first (higher relevance).
        if self._indexer is not None and self._indexer.available:
            try:
                semantic = self._semantic_search(query, top_k=top_k)
                for entry in semantic:
                    if entry.id is not None and entry.id not in seen_ids:
                        seen_ids.add(entry.id)
                        combined.append(entry)
            except Exception:
                logger.warning("Semantic search failed during hybrid search")

        # Keyword results fill remaining slots.
        remaining = top_k - len(combined)
        if remaining > 0:
            keyword = self._keyword_search(
                query, top_k=remaining + len(seen_ids), category=category
            )
            for entry in keyword:
                if entry.id is not None and entry.id not in seen_ids:
                    if len(combined) >= top_k:
                        break
                    seen_ids.add(entry.id)
                    combined.append(entry)

        return combined[:top_k]
