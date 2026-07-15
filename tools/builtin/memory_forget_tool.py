"""
memory_forget_tool.py

A guarded tool that forgets a single memory by id (Phase 5, Batch 3;
extended Phase 78, Batch 1 so the success confirmation identifies the
forgotten memory's id, category, and content).

MemoryForgetTool is a YELLOW tool. Forgetting removes a stored memory, so its
action is classified YELLOW and it runs only after explicit approval through the
normal Tool Executor and Approval Manager path. It is deliberately narrow:

    - It forgets exactly one memory, identified by id.
    - It has no bulk or "forget all" capability. A request to forget all
      memories is blocked at the Security Manager (RED) and never reaches a
      tool.

It delegates to the Memory Manager and adds no storage logic of its own.

Supported input (via input_data):
    memory_id: the id of the memory to forget (required).

Safety note:
    This tool does not enforce approval itself. Approval is enforced by the Tool
    Executor, which classifies this tool's action ("forget memory") as YELLOW
    and withholds it until an approved decision is supplied. A declined action
    never reaches run(), so nothing is removed.
"""

from __future__ import annotations

from tools.base_tool import BaseTool, ToolRequest, ToolResult


class MemoryForgetTool(BaseTool):
    """Forgets a single memory by id. Sensitive (YELLOW); no bulk delete."""

    def __init__(self, memory) -> None:  # type: ignore[no-untyped-def]
        """Initialise the tool with a Memory Manager.

        Args:
            memory: The Memory Manager used to forget the memory.
        """
        self._memory = memory

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "memory_forget".
        """
        return "memory_forget"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Forgets a single memory by id. Sensitive: requires approval. "
            "Cannot forget all memories."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return the action string used for security classification.

        Args:
            request: The request being handled.

        Returns:
            "forget all memories" (RED, blocked) when a bulk forget is
            requested, otherwise "forget memory" (YELLOW, approval-gated).
        """
        if request.input_data.get("all") is True:
            return "forget all memories"
        return "forget memory"

    def run(self, request: ToolRequest) -> ToolResult:
        """Forget a single memory identified by id.

        Args:
            request: The request. Recognised input keys:
                memory_id: the id of the memory to forget (required).

        Returns:
            A successful ToolResult when the memory is forgotten, whose
            output identifies the forgotten memory's id, category, and
            content (Phase 78, Batch 1), or a failed result if the id is
            missing or unknown.
        """
        memory_id = self._parse_id(request.input_data.get("memory_id"))
        if request.input_data.get("all") is True:
            # Defensive: bulk forget is blocked at the Security Manager and
            # should never reach here. Refuse outright if it somehow does.
            return self.fail(
                "Forgetting all memories is not allowed. Forget one memory at "
                "a time by id."
            )
        if memory_id is None:
            return self.fail(
                "Forgetting a memory requires a valid numeric 'memory_id'."
            )

        # Fetched before forget() - the record no longer exists afterward.
        record = self._memory.get(memory_id)
        forgotten = self._memory.forget(memory_id)
        if not forgotten:
            return self.fail(f"No memory found with id {memory_id}.")

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=f"Forgot memory [{record.id}] ({record.category}) {record.content}.",
            metadata={"operation": "forget", "memory_id": str(memory_id)},
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