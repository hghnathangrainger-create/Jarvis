"""
knowledge

Structured reference knowledge library for Jarvis — a personal encyclopedia
that Jarvis can query for semantic and keyword-based retrieval.

Public API:
    - KnowledgeEntry: The data model for a single knowledge article.
    - KnowledgeStore: SQLite-backed persistence for knowledge entries.
    - KnowledgeIndexer: ChromaDB-backed vector index for semantic search.
    - KnowledgeManager: High-level interface combining store + indexer.
"""

from knowledge.indexer import KnowledgeIndexer
from knowledge.manager import KnowledgeManager
from knowledge.models import KnowledgeEntry
from knowledge.store import KnowledgeStore

__all__ = [
    "KnowledgeEntry",
    "KnowledgeIndexer",
    "KnowledgeManager",
    "KnowledgeStore",
]
