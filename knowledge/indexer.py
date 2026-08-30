"""
indexer.py

ChromaDB-backed indexer for semantic knowledge search in Jarvis.

Responsibilities:
    - Maintain a dedicated ChromaDB collection ("knowledge") for
      vector-based retrieval of knowledge entries.
    - Expose add, search, delete operations for the vector index.
    - Gracefully handle a missing chromadb package.

Does NOT:
    - Store structured knowledge data (see store.py).
    - Coordinate keyword + semantic search (see manager.py).

The KnowledgeIndexer is a companion to the SQLite-backed KnowledgeStore.
The KnowledgeManager writes to both stores on add/update and reads from
ChromaDB for semantic searches.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import chromadb

    _CHROMA_AVAILABLE = True
except ImportError:
    chromadb = None  # type: ignore[assignment]
    _CHROMA_AVAILABLE = False

logger = logging.getLogger(__name__)


class KnowledgeIndexer:
    """Thin wrapper around a ChromaDB collection for semantic knowledge search.

    Uses an in-memory collection by default. The collection is created
    automatically on first access. ChromaDB's default embedding function
    handles text-to-vector conversion internally — no external API key
    is required.

    Attributes:
        _client: The ChromaDB client instance.
        _collection: The ChromaDB collection, created lazily.
    """

    def __init__(self) -> None:
        """Initialise the indexer with a dedicated 'knowledge' collection."""
        self._client: Any = None
        self._collection: Any = None

    @property
    def available(self) -> bool:
        """Whether the chromadb package is installed and usable."""
        return _CHROMA_AVAILABLE

    def _ensure_collection(self) -> Any:
        """Lazily create the ChromaDB client and collection.

        Returns:
            The ChromaDB collection.

        Raises:
            RuntimeError: If the chromadb package is not installed.
        """
        if self._collection is not None:
            return self._collection

        if not _CHROMA_AVAILABLE:
            raise RuntimeError(
                "chromadb package is not installed. "
                "Install it with: pip install chromadb"
            )

        self._client = chromadb.Client()
        self._collection = self._client.get_or_create_collection(
            name="knowledge"
        )
        return self._collection

    def add(
        self,
        id: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Index a knowledge entry for semantic search.

        Args:
            id: The knowledge entry id (as a string).
            text: The text to index (typically title + content).
            metadata: Optional metadata dict (all values must be strings).

        Returns:
            The document ID.
        """
        collection = self._ensure_collection()

        safe_metadata: dict[str, str] = {}
        if metadata:
            for key, value in metadata.items():
                safe_metadata[key] = str(value) if value is not None else ""

        collection.upsert(
            documents=[text],
            metadatas=[safe_metadata] if safe_metadata else None,
            ids=[id],
        )
        return id

    def search(
        self,
        query: str,
        top_k: int = 5,
        where: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search for knowledge entries most semantically similar to the query.

        Args:
            query: The natural-language query to search for.
            top_k: Number of results to return. Defaults to 5.
            where: Optional ChromaDB where-filter for metadata.

        Returns:
            A list of result dicts with "id", "text", "metadata", "distance".
        """
        collection = self._ensure_collection()

        if not query or not query.strip():
            return []

        count = collection.count()
        if count == 0:
            return []
        effective_k = min(top_k, count)

        kwargs: dict[str, Any] = {
            "query_texts": [query],
            "n_results": effective_k,
        }
        if where:
            kwargs["where"] = where

        results = collection.query(**kwargs)

        documents = results.get("documents") or [[]]
        metadatas = results.get("metadatas") or [[]]
        ids = results.get("ids") or [[]]
        distances = results.get("distances") or [[]]

        out: list[dict[str, Any]] = []
        for i in range(len(ids[0])):
            out.append({
                "id": ids[0][i],
                "text": documents[0][i],
                "metadata": metadatas[0][i] if metadatas[0] else {},
                "distance": distances[0][i] if distances[0] else 0.0,
            })
        return out

    def delete(self, id: str) -> bool:
        """Remove a knowledge entry from the vector index.

        Args:
            id: The knowledge entry id (as a string).

        Returns:
            True if the delete was executed.
        """
        collection = self._ensure_collection()
        collection.delete(ids=[id])
        return True

    def count(self) -> int:
        """Return the number of indexed knowledge entries.

        Returns:
            The total count of indexed documents.
        """
        collection = self._ensure_collection()
        return collection.count()
