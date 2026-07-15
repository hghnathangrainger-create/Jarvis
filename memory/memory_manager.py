"""
memory_manager.py

High-level memory interface for the Jarvis AI Operating System.

Responsibilities:
    - Provide a single, simple API for saving, listing, and searching memories.
    - Enforce the "do not remember" policy: if the user signals that an
      exchange should not be stored, the manager declines to save it.

Does NOT:
    - Talk to the database directly (it delegates to EpisodicMemoryStore).
    - Use vector databases, embeddings, or any AI calls.
    - Implement planning, workflow, or tool logic.

The Memory Manager is the layer the rest of Jarvis talks to. It owns memory
policy; the EpisodicMemoryStore beneath it owns storage. Keeping policy and
storage separate keeps both simple and independently testable.
"""

from __future__ import annotations

from memory.episodic_memory import EpisodicMemoryStore, MemoryRecord

#: Core phrase that signals the user does not want an exchange stored.
#: Matched case-insensitively as a substring, so natural variations such as
#: "please do not remember my plan" are caught, not only an exact sentence.
_DO_NOT_REMEMBER_PHRASE = "do not remember"


class MemoryManager:
    """Coordinates memory storage and retrieval under a simple policy.

    Attributes:
        _store: The episodic memory store used for persistence.
    """

    def __init__(self, store: EpisodicMemoryStore) -> None:
        """Initialise the manager with an episodic memory store.

        Args:
            store: The store used to persist and retrieve memories.
        """
        self._store = store

    def save(
        self,
        content: str,
        *,
        source: str = "conversation",
        session_id: int | None = None,
        category: str | None = None,
    ) -> MemoryRecord | None:
        """Save a memory unless it is empty or marked not to be remembered.

        The memory is not stored when its content is empty, is whitespace-only,
        or contains the "do not remember" phrase. In those cases the method
        returns None so the caller can tell that nothing was saved.

        Args:
            content: The memory text to store.
            source: Where the memory originated. Defaults to "conversation".
            session_id: Optional session the memory belongs to.
            category: Optional organisational label. Unknown or blank values
                fall back to "general".

        Returns:
            The stored MemoryRecord, or None if the content was not stored.
        """
        text = content.strip()
        if not text:
            return None

        if self.should_skip(text):
            return None

        return self._store.save(
            content=text,
            source=source,
            session_id=session_id,
            category=category,
        )

    def list_recent(
        self, limit: int = 20, *, category: str | None = None
    ) -> list[MemoryRecord]:
        """Return the most recent memories, newest first.

        Args:
            limit: Maximum number of memories to return. Defaults to 20.
            category: Optional category to filter by. When None, all categories
                are returned.

        Returns:
            A list of MemoryRecord objects ordered from newest to oldest.
        """
        return self._store.list_recent(limit=limit, category=category)

    def list_by_category(
        self, category: str, limit: int = 20
    ) -> list[MemoryRecord]:
        """Return the most recent memories in a single category.

        Args:
            category: The category to filter by. Unknown or blank values fall
                back to "general".
            limit: Maximum number of memories to return. Defaults to 20.

        Returns:
            A list of MemoryRecord objects in that category, newest first.
        """
        return self._store.list_recent(limit=limit, category=category)

    def search(
        self, query: str, limit: int = 20, *, category: str | None = None
    ) -> list[MemoryRecord]:
        """Return memories whose content matches the query text.

        Args:
            query: The text to search for within memory content.
            limit: Maximum number of memories to return. Defaults to 20.
            category: Optional category to further filter matches by.

        Returns:
            A list of matching MemoryRecord objects, newest first.
        """
        return self._store.search(query, limit=limit, category=category)

    def count(self) -> int:
        """Return the total number of stored memories.

        Returns:
            The total count of stored memories.
        """
        return self._store.count()

    def count_by_category(self, category: str) -> int:
        """Return the number of stored memories in a single category.

        A thin passthrough to EpisodicMemoryStore.count_by_category()
        (Phase 63, Batch 1), mirroring count()'s own pattern exactly -
        this method holds no logic of its own beyond delegating.

        Args:
            category: The category to count. Normalised by the store
                before counting, so an unknown or blank value counts
                the "general" category.

        Returns:
            The number of memories in the (normalised) category.
        """
        return self._store.count_by_category(category)

    def get(self, memory_id: int) -> MemoryRecord | None:
        """Return a single memory by id, or None if it does not exist.

        Args:
            memory_id: The id of the memory to fetch.

        Returns:
            The matching MemoryRecord, or None.
        """
        return self._store.get_by_id(memory_id)

    def update_content(
        self, memory_id: int, new_content: str
    ) -> MemoryRecord | None:
        """Replace the content of an existing memory.

        Args:
            memory_id: The id of the memory to update.
            new_content: The new content text.

        Returns:
            The updated MemoryRecord, or None if no memory has that id.
        """
        return self._store.update_content(memory_id, new_content)

    def move_category(
        self, memory_id: int, new_category: str
    ) -> MemoryRecord | None:
        """Change the category of an existing memory.

        Args:
            memory_id: The id of the memory to move.
            new_category: The new category (normalised by the store).

        Returns:
            The updated MemoryRecord, or None if no memory has that id.
        """
        return self._store.update_category(memory_id, new_category)

    def forget(self, memory_id: int) -> bool:
        """Delete a single memory by id.

        Args:
            memory_id: The id of the memory to forget.

        Returns:
            True if a memory was deleted, False if no memory had that id.
        """
        return self._store.delete(memory_id)

    @staticmethod
    def should_skip(content: str) -> bool:
        """Report whether content should be excluded from storage.

        Content is skipped when it contains the configured "do not remember"
        phrase, matched case-insensitively.

        Args:
            content: The text to check.

        Returns:
            True if the content should not be stored, False otherwise.
        """
        return _DO_NOT_REMEMBER_PHRASE in content.casefold()