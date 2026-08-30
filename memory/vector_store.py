"""
vector_store.py

ChromaDB-backed vector store for semantic memory search in Jarvis.

Responsibilities:
    - Maintain an in-memory ChromaDB collection for vector-based retrieval.
    - Expose add, search, delete, and count operations.
    - Use ChromaDB's default embedding function (no external API needed).
    - Gracefully handle a missing chromadb package so Jarvis still works
      when the dependency is not installed.

Does NOT:
    - Persist to disk (in-memory by default, optionally persistent).
    - Call any external APIs for embeddings.
    - Make policy decisions about what to store (that's MemoryManager's job).

The VectorStore is a companion to the SQLite-backed EpisodicMemoryStore.
The MemoryManager writes to both stores on save and reads from ChromaDB
for semantic (meaning-based) searches.
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


class VectorStore:
    """Thin wrapper around a ChromaDB collection for semantic memory search.

    Uses an in-memory collection by default. The collection is created
    automatically on first access. ChromaDB's default embedding function
    handles text-to-vector conversion internally — no external API key
    is required.

    Attributes:
        _collection_name: The name of the ChromaDB collection.
        _client: The ChromaDB client instance.
        _collection: The ChromaDB collection, created lazily.
    """

    def __init__(
        self,
        collection_name: str = "jarvis_memories",
        persist_directory: str | None = None,
    ) -> None:
        """Initialise the vector store.

        Args:
            collection_name: Name of the ChromaDB collection.
                Defaults to "jarvis_memories".
            persist_directory: Optional filesystem path for persistent
                storage. When None, the collection lives in memory only
                and is lost when the process exits.
        """
        self._collection_name = collection_name
        self._client: Any = None
        self._collection: Any = None
        self._persist_directory = persist_directory

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

        if self._persist_directory:
            self._client = chromadb.PersistentClient(
                path=self._persist_directory
            )
        else:
            self._client = chromadb.Client()

        self._collection = self._client.get_or_create_collection(
            name=self._collection_name
        )
        return self._collection

    def add(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        id: str | None = None,
    ) -> str:
        """Add a document to the vector store.

        Args:
            text: The text content to store and embed.
            metadata: Optional metadata dictionary. Common fields include
                "category", "source", "created_at", and any custom fields.
            id: Optional unique identifier. If None, ChromaDB generates one.

        Returns:
            The document ID (either the one provided or ChromaDB-generated).
        """
        collection = self._ensure_collection()

        # Ensure metadata values are strings (ChromaDB requirement).
        safe_metadata: dict[str, str] = {}
        if metadata:
            for key, value in metadata.items():
                safe_metadata[key] = str(value) if value is not None else ""

        # ChromaDB requires at least one document before queries work.
        # Store an empty-collection marker if the collection is empty.
        if collection.count() == 0 and not text:
            return id

        if id is None:
            import uuid

            id = uuid.uuid4().hex

        collection.add(
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
        """Search for documents most semantically similar to the query.

        Args:
            query: The natural-language query to search for.
            top_k: Number of results to return. Defaults to 5.
            where: Optional ChromaDB where-filter for metadata. Example:
                {"category": "project"}.

        Returns:
            A list of result dicts, each containing "id", "text",
            "metadata", and "distance" (lower = more similar).
        """
        collection = self._ensure_collection()

        if not query or not query.strip():
            return []

        # Clamp top_k to the number of documents in the collection.
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

        # Unpack the ChromaDB response format.
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
        """Delete a document by its ID.

        Args:
            id: The unique identifier of the document to delete.

        Returns:
            True if a document was deleted. (ChromaDB's delete does not
            raise if the ID is absent, so this always returns True when
            the collection is available.)
        """
        collection = self._ensure_collection()
        collection.delete(ids=[id])
        return True

    def count(self) -> int:
        """Return the number of documents in the vector store.

        Returns:
            The total count of stored documents.
        """
        collection = self._ensure_collection()
        return collection.count()
