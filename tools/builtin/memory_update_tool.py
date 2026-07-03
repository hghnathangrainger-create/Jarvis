"""
memory_update_tool.py

A guarded tool that updates an existing memory (Phase 5, Batch 3).

MemoryUpdateTool is a YELLOW tool. It changes a stored memory, so its action is
classified YELLOW and it runs only after explicit approval through the normal
Tool Executor and Approval Manager path. It handles two closely-related changes:

    - "update":  replace the content of an existing memory by id.
    - "move":    change the category of an existing memory by id.

It never creates or deletes a memory, and it only ever affects one specific
memory identified by id. It delegates to the Memory Manager and adds no storage
logic of its own.

Supported input (via input_data):
    operation: "update" (default) or "move".
    memory_id: the id of the memory to change (required).
    content:   the new content text (required for "update").
    category:  the new category (required for "move").

Safety note:
    This tool does not enforce approval itself. Approval is enforced by the Tool
    Executor, which classifies this tool's action ("update memory" or "move
    memory") as YELLOW and withholds it until an approved decision is supplied.
    A declined action never reaches run(), so nothing is changed.
"""

from __future__ import annotations

from tools.base_tool import BaseTool, ToolRequest, ToolResult


class MemoryUpdateTool(BaseTool):
    """Updates a memory's content or category. Sensitive (YELLOW)."""

    def __init__(self, memory) -> None:  # type: ignore[no-untyped-def]
        """Initialise the tool with a Memory Manager.

        Args:
            memory: The Memory Manager used to apply the change.
        """
        self._memory = memory

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "memory_update".
        """
        return "memory_update"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Updates the content or category of an existing memory by id. "
            "Sensitive: requires approval."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return the action string used for security classification.

        Args:
            request: The request being handled.

        Returns:
            "move memory" for a category move, otherwise "update memory". Both
            classify YELLOW.
        """
        operation = str(request.input_data.get("operation", "update")).strip().lower()
        if operation == "move":
            return "move memory"
        return "update memory"

    def run(self, request: ToolRequest) -> ToolResult:
        """Apply the requested update to a single memory.

        Args:
            request: The request. Recognised input keys:
                operation: "update" (default) or "move".
                memory_id: the id of the memory to change (required).
                content: the new content (required for "update").
                category: the new category (required for "move").

        Returns:
            A successful ToolResult describing the change, or a failed result if
            the id is missing or unknown, or the required new value is missing.
        """
        operation = str(request.input_data.get("operation", "update")).strip().lower()

        memory_id = self._parse_id(request.input_data.get("memory_id"))
        if memory_id is None:
            return self.fail(
                "Updating a memory requires a valid numeric 'memory_id'."
            )

        if operation == "move":
            return self._run_move(request, memory_id)
        return self._run_update(request, memory_id)

    def _run_update(self, request: ToolRequest, memory_id: int) -> ToolResult:
        """Replace a memory's content.

        Args:
            request: The request carrying the new 'content'.
            memory_id: The id of the memory to update.

        Returns:
            A ToolResult describing the outcome.
        """
        content = request.input_data.get("content")
        if not isinstance(content, str) or not content.strip():
            return self.fail("Updating a memory requires non-empty 'content'.")

        record = self._memory.update_content(memory_id, content)
        if record is None:
            return self.fail(f"No memory found with id {memory_id}.")

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=f"Updated memory {record.id}: {record.content}",
            metadata={
                "operation": "update",
                "memory_id": str(record.id),
                "category": record.category,
            },
        )

    def _run_move(self, request: ToolRequest, memory_id: int) -> ToolResult:
        """Change a memory's category.

        Args:
            request: The request carrying the new 'category'.
            memory_id: The id of the memory to move.

        Returns:
            A ToolResult describing the outcome.
        """
        category = request.input_data.get("category")
        if not isinstance(category, str) or not category.strip():
            return self.fail("Moving a memory requires a non-empty 'category'.")

        record = self._memory.move_category(memory_id, category)
        if record is None:
            return self.fail(f"No memory found with id {memory_id}.")

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=f"Moved memory {record.id} to '{record.category}'.",
            metadata={
                "operation": "move",
                "memory_id": str(record.id),
                "category": record.category,
            },
        )

    @staticmethod
    def _parse_id(raw: object) -> int | None:
        """Parse a memory id from raw input.

        Args:
            raw: The raw id value, which may be an int or a numeric string.

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