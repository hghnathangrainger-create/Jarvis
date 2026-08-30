"""
task_complete_tool.py

A YELLOW tool that marks tasks as done in the Jarvis Goals system.

TaskCompleteTool is a guarded write tool. It marks a task as completed
and records the actual time spent.

This tool is classified YELLOW because it modifies durable state,
requiring user confirmation before execution.
"""

from __future__ import annotations

from goals.manager import GoalManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class TaskCompleteTool(BaseTool):
    """Marks tasks as done in the Goals system.

    Attributes:
        _manager: The GoalManager providing write access.
    """

    def __init__(self, manager: GoalManager) -> None:
        """Initialise the tool with a GoalManager.

        Args:
            manager: The GoalManager providing write access.
        """
        self._manager = manager

    @property
    def name(self) -> str:
        """Return the tool name."""
        return "task_complete"

    @property
    def description(self) -> str:
        """Return a short description of the tool."""
        return "Marks a task as done with optional actual time tracking."

    def run(self, request: ToolRequest) -> ToolResult:
        """Mark a task as done.

        Args:
            request: The request. Recognised input keys:
                task_id: The id of the task to complete (required).
                actual_minutes: Optional actual time spent in minutes.

        Returns:
            A ToolResult confirming completion or failing on missing input.
        """
        task_id = self._parse_id(request.input_data.get("task_id"))
        if task_id is None:
            return self.fail("Completing a task requires a numeric 'task_id'.")

        actual_minutes = None
        raw_minutes = request.input_data.get("actual_minutes")
        if raw_minutes is not None:
            try:
                actual_minutes = int(raw_minutes)
            except (TypeError, ValueError):
                return self.fail(f"Invalid actual_minutes: '{raw_minutes}'. Must be an integer.")

        task = self._manager.mark_task_done(task_id, actual_minutes=actual_minutes)
        if task is None:
            return self.fail(f"No task found with id {task_id}.")

        time_str = ""
        if actual_minutes is not None:
            time_str = f" ({actual_minutes} min)"

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=f"Task [{task.id}] marked as done: {task.title}{time_str}",
            metadata={
                "operation": "complete_task",
                "task_id": str(task.id),
            },
        )

    @staticmethod
    def _parse_id(raw: object) -> int | None:
        """Parse an id from raw input."""
        if isinstance(raw, bool):
            return None
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.strip().isdigit():
            return int(raw.strip())
        return None
