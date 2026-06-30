"""
memory_tool.py

A safe tool that lists and searches stored memories.

MemoryTool is a GREEN tool: it only reads from the Memory Engine. It performs
no writes and cannot delete or modify memories. It delegates entirely to the
existing MemoryManager, adding no storage logic of its own.

Supported operations (via the 'operation' input):
    - "list":   return the most recent memories.
    - "search": return memories matching the 'query' input.
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
        """Return a read-only action string for security classification.

        The action is phrased as a search or list so that the Security Manager
        classifies it GREEN. The tool never performs write operations.

        Args:
            request: The request being handled.

        Returns:
            A read-only action string.
        """
        operation = str(request.input_data.get("operation", "list")).strip().lower()
        if operation == "search":
            return "search memories"
        return "list memories"

    def run(self, request: ToolRequest) -> ToolResult:
        """List or search memories according to the requested operation.

        Args:
            request: The request. Recognised input keys:
                operation: "list" (default) or "search".
                query: the search text, required when operation is "search".
                limit: optional maximum number of results.

        Returns:
            A ToolResult containing the formatted memories, or a failed result
            if the operation is unknown or a search query is missing.
        """
        operation = str(request.input_data.get("operation", "list")).strip().lower()
        limit = self._clamp_limit(request.input_data.get("limit", _DEFAULT_LIMIT))

        if operation == "list":
            records = self._memory.list_recent(limit=limit)
            return self.ok(self._format(records, "Recent memories"))

        if operation == "search":
            query = request.input_data.get("query")
            if not isinstance(query, str) or not query.strip():
                return self.fail("Search requires a non-empty 'query' string.")
            records = self._memory.search(query, limit=limit)
            return self.ok(self._format(records, f"Memories matching '{query.strip()}'"))

        return self.fail(
            f"Unknown operation '{operation}'. Use 'list' or 'search'."
        )

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
            lines.append(f"  [{record.id}] {record.content}")
        return "\n".join(lines)