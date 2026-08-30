"""
goal_create_tool.py

A YELLOW tool that creates new goals in the Jarvis Goals system.

GoalCreateTool is a guarded write tool. It persists a new goal
(and optionally its first milestone) to SQLite.

This tool is classified YELLOW because it modifies durable state,
requiring user confirmation before execution.
"""

from __future__ import annotations

from goals.manager import GoalManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class GoalCreateTool(BaseTool):
    """Creates a new goal in the Goals system.

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
        return "goal_create"

    @property
    def description(self) -> str:
        """Return a short description of the tool."""
        return "Creates a new goal with optional milestones and tasks."

    def run(self, request: ToolRequest) -> ToolResult:
        """Create a new goal.

        Args:
            request: The request. Recognised input keys:
                title: The goal title (required).
                description: Optional description.
                priority: Optional priority ("low", "medium", "high", "critical").
                target_date: Optional target date string (ISO format).

        Returns:
            A ToolResult confirming creation or failing on missing input.
        """
        title = request.input_data.get("title")
        if not isinstance(title, str) or not title.strip():
            return self.fail("Creating a goal requires a non-empty 'title'.")

        description = str(request.input_data.get("description", "") or "")
        priority = str(request.input_data.get("priority", "medium") or "medium").strip().lower()
        if priority not in ("low", "medium", "high", "critical"):
            priority = "medium"

        target_date = None
        raw_date = request.input_data.get("target_date")
        if isinstance(raw_date, str) and raw_date.strip():
            try:
                from datetime import datetime, timezone
                target_date = datetime.fromisoformat(raw_date.strip()).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                return self.fail(f"Invalid target_date format: '{raw_date}'. Use ISO format (e.g. 2026-12-31).")

        goal = self._manager.create_goal(
            title=title.strip(),
            description=description.strip(),
            priority=priority,
            target_date=target_date,
        )

        target_str = ""
        if target_date:
            target_str = f", target: {target_date.strftime('%Y-%m-%d')}"

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Created goal [{goal.id}]: {goal.title} "
                f"(priority: {goal.priority}, status: {goal.status}{target_str})"
            ),
            metadata={
                "operation": "create_goal",
                "goal_id": str(goal.id),
                "priority": goal.priority,
            },
        )
