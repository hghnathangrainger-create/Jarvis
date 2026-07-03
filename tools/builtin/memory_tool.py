"""
memory_tool.py

A safe tool that saves, lists, and searches stored memories.

MemoryTool is a GREEN tool. It reads from the Memory Engine (list, search) and
performs one explicit, user-requested write: saving a memory the user directly
asked Jarvis to remember. It cannot update, delete, or forget memories - those
are separate, approval-gated tools. It delegates entirely to the existing
MemoryManager, adding no storage logic of its own, and it honours the
"do not remember" rule enforced by the manager.

Supported operations (via the 'operation' input):
    - "list":   return the most recent memories, optionally filtered by category.
    - "search": return memories matching the 'query' input, optionally filtered
                by category.
    - "save":   store the 'content' text the user explicitly asked to remember,
                under an optional 'category' (defaulting to "general").

Why "save" is GREEN:
    A manual save happens only when the user explicitly says "remember this".
    Nothing is overwritten or removed, the user sees exactly what will be
    stored, and the "do not remember" rule still applies. The Security Manager
    classifies "save memory" as GREEN for this reason. The AI never triggers a
    save; only an explicit user command does.
"""

from __future__ import annotations

from memory.memory_manager import MemoryManager
from memory.episodic_memory import MemoryRecord
from tools.base_tool import BaseTool, ToolRequest, ToolResult

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50


class MemoryTool(BaseTool):
    """Lists or searches stored memories using the Memory Engine.

    Attributes:
        _memory: The Memory Manager used for read-only memory access.
    """

    def __init__(self, memory_manager: MemoryManager) -> None:
        """Initialise the tool with a Memory Manager.

        Args:
            memory_manager: The Memory Manager providing read access.
        """
        self._memory = memory_manager

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "memory".
        """
        return "memory"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return "Lists or searches stored memories. Read-only and safe."

    def action_for(self, request: ToolRequest) -> str:
        """Return an honest action string for security classification.

        The action names what the operation actually does: "save memory" for a
        save, "search memories" for a search, and "list memories" for a list.
        The Security Manager classifies all three as GREEN - a manual save is a
        single, explicit, user-requested store, not a broad state change.

        Args:
            request: The request being handled.

        Returns:
            An action string describing the operation.
        """
        operation = str(request.input_data.get("operation", "list")).strip().lower()
        if operation == "save":
            return "save memory"
        if operation == "search":
            return "search memories"
        if operation == "get":
            return "show memory"
        return "list memories"

    def run(self, request: ToolRequest) -> ToolResult:
        """Save, list, or search memories according to the requested operation.

        Args:
            request: The request. Recognised input keys:
                operation: "list" (default), "search", or "save".
                query: the search text, required when operation is "search".
                content: the text to store, required when operation is "save".
                category: optional category for save/list/search filtering.
                limit: optional maximum number of results.

        Returns:
            A ToolResult containing the formatted memories or a save
            confirmation, or a failed result if the operation is unknown or its
            required input is missing.
        """
        operation = str(request.input_data.get("operation", "list")).strip().lower()
        limit = self._clamp_limit(request.input_data.get("limit", _DEFAULT_LIMIT))
        category = request.input_data.get("category")
        category = category if isinstance(category, str) and category.strip() else None

        if operation == "save":
            return self._run_save(request, category)

        if operation == "get":
            memory_id = self._parse_id(request.input_data.get("memory_id"))
            if memory_id is None:
                return self.fail(
                    "Showing a memory requires a valid numeric 'memory_id'."
                )
            record = self._memory.get(memory_id)
            if record is None:
                return self.fail(f"No memory found with id {memory_id}.")
            return self.ok(
                f"[{record.id}] ({record.category}) {record.content}"
            )

        if operation == "list":
            records = self._list_recent(limit=limit, category=category)
            header = "Recent memories"
            if category:
                header = f"Recent memories in '{category.strip().lower()}'"
            return self.ok(self._format(records, header))

        if operation == "search":
            query = request.input_data.get("query")
            if not isinstance(query, str) or not query.strip():
                return self.fail("Search requires a non-empty 'query' string.")
            records = self._search(query, limit=limit, category=category)
            header = f"Memories matching '{query.strip()}'"
            if category:
                header = (
                    f"Memories in '{category.strip().lower()}' "
                    f"matching '{query.strip()}'"
                )
            return self.ok(self._format(records, header))

        return self.fail(
            f"Unknown operation '{operation}'. Use 'list', 'search', or 'save'."
        )

    def _run_save(
        self, request: ToolRequest, category: str | None
    ) -> ToolResult:
        """Handle the explicit, user-requested save operation.

        The content is stored through the Memory Manager, which enforces the
        "do not remember" rule. When the manager declines to store (empty text
        or a "do not remember" signal), a clear, non-failing message is
        returned so the user knows nothing was saved.

        Args:
            request: The request carrying the 'content' to store.
            category: The optional category to store under.

        Returns:
            A ToolResult confirming the save, reporting that nothing was stored,
            or failing when no content was provided.
        """
        content = request.input_data.get("content")
        if not isinstance(content, str) or not content.strip():
            return self.fail("Saving a memory requires non-empty 'content'.")

        record = self._memory.save(content=content, category=category)
        if record is None:
            # The Memory Manager declined (empty or "do not remember").
            return self.ok("Understood - I did not save that to memory.")

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Saved to memory under '{record.category}': {record.content}"
            ),
            metadata={
                "operation": "save",
                "memory_id": str(record.id),
                "category": record.category,
            },
        )

    @staticmethod
    def _parse_id(raw: object) -> int | None:
        """Parse a memory id from raw input.

        Args:
            raw: The raw id value, an int or numeric string.

        Returns:
            The id as an int, or None if it cannot be parsed.
        """
        if isinstance(raw, bool):
            return None
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.strip().isdigit():
            return int(raw.strip())
        return None

    @staticmethod
    def _clamp_limit(value: object) -> int:
        """Coerce and clamp a limit input into a safe range.

        Args:
            value: The raw limit input, which may be of any type.

        Returns:
            An integer limit between 1 and the maximum allowed limit.
        """
        try:
            limit = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return _DEFAULT_LIMIT
        if limit < 1:
            return 1
        if limit > _MAX_LIMIT:
            return _MAX_LIMIT
        return limit

    def _list_recent(self, *, limit: int = 10, category: str | None = None):
        try:
            return self._memory.list_recent(limit=limit, category=category)
        except TypeError as exc:
            if "category" not in str(exc) and "unexpected keyword" not in str(exc):
                raise
            try:
                return self._memory.list_recent(limit=limit)
            except TypeError:
                return self._memory.list_recent()

    def _search(self, query: str, *, limit: int = 10, category: str | None = None):
        try:
            return self._memory.search(query=query, limit=limit, category=category)
        except TypeError as exc:
            if "category" not in str(exc) and "unexpected keyword" not in str(exc):
                raise
            try:
                return self._memory.search(query=query, limit=limit)
            except TypeError:
                try:
                    return self._memory.search(query=query)
                except TypeError:
                    return self._memory.search(query)

    @staticmethod
    def _format(records: list[MemoryRecord], header: str) -> str:
        """Format a list of memory records into readable text.

        Args:
            records: The memory records to format.
            header: A header line describing the result set.

        Returns:
            A formatted, multi-line string. Reports when there are no results.
        """
        if not records:
            return f"{header}: none found."
        lines = [f"{header}:"]
        for record in records:
            lines.append(f"  [{record.id}] ({record.category}) {record.content}")
        return "\n".join(lines)