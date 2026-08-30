"""
models.py

Value types for the Jarvis Knowledge Library.

Responsibilities:
    - Define the KnowledgeEntry dataclass that represents a single
      knowledge article.

Does NOT:
    - Store or retrieve knowledge (see store.py).
    - Index knowledge for semantic search (see indexer.py).
    - Coordinate search or indexing (see manager.py).

KnowledgeEntry is a pure value object with no storage or AI logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class KnowledgeEntry:
    """A single knowledge article in the Jarvis Knowledge Library.

    Attributes:
        id: Auto-incrementing primary key (set by the store on insert).
        title: A short, descriptive title for the entry.
        content: The full text content of the knowledge article.
        category: An organisational label (e.g. "general", "project").
        tags: A list of tags for flexible categorisation.
        source: Where this knowledge came from (e.g. "manual", "web", "ai").
        created_at: When this entry was created (UTC).
        updated_at: When this entry was last updated (UTC).
    """

    id: int | None = None
    title: str = ""
    content: str = ""
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    source: str = "manual"
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
