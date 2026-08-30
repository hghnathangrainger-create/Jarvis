"""
goal_progress_tool.py

A GREEN tool that checks progress of goals in the Jarvis Goals system.

GoalProgressTool is a read-only tool. It supports listing goals,
viewing a detailed progress report, and checking overdue items.
"""

from __future__ import annotations

from goals.manager import GoalManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class GoalProgressTool(BaseTool):
    """Shows progress of goals, milestones, and tasks.

    Attributes:
        _manager: The GoalManager providing read access.
    """

    def __init__(self, manager: GoalManager) -> None:
        """Initialise the tool with a GoalManager.

        Args:
            manager: The GoalManager providing read access.
        """
        self._manager = manager

    @property
    def name(self) -> str:
        """Return the tool name."""
        return "goal_progress"

    @property
    def description(self) -> str:
        """Return a short description of the tool."""
        return "Shows goal progress, lists goals, and checks overdue items. Read-only and safe."

    def run(self, request: ToolRequest) -> ToolResult:
        """Show goal progress.

        Args:
            request: The request. Recognised input keys:
                operation: "list" (default), "report", or "overdue".
                goal_id: Required for "report" operation.

        Returns:
            A ToolResult with the requested information.
        """
        operation = str(request.input_data.get("operation", "list")).strip().lower()

        if operation == "list":
            return self._run_list()

        if operation == "report":
            return self._run_report(request)

        if operation == "overdue":
            return self._run_overdue()

        return self.fail(
            f"Unknown operation '{operation}'. Use 'list', 'report', or 'overdue'."
        )

    def _run_list(self) -> ToolResult:
        """List all goals with their status."""
        goals = self._manager._store.list_goals()
        if not goals:
            return self.ok("No goals found.")

        lines = ["Goals:"]
        for goal in goals:
            lines.append(self._format_goal(goal))
        return self.ok("\n".join(lines))

    def _run_report(self, request: ToolRequest) -> ToolResult:
        """Show a detailed progress report for a goal."""
        goal_id = self._parse_id(request.input_data.get("goal_id"))
        if goal_id is None:
            return self.fail("Progress report requires a numeric 'goal_id'.")

        report = self._manager.get_progress_report(goal_id)
        return self.ok(report)

    def _run_overdue(self) -> ToolResult:
        """Show overdue tasks and milestones."""
        items = self._manager.get_overdue_items()
        overdue_tasks = items.get("overdue_tasks", [])
        overdue_milestones = items.get("overdue_milestones", [])

        if not overdue_tasks and not overdue_milestones:
            return self.ok("No overdue items.")

        lines = []
        if overdue_milestones:
            lines.append(f"Overdue milestones ({len(overdue_milestones)}):")
            for m in overdue_milestones:
                due = m.due_date.strftime("%Y-%m-%d") if m.due_date else "unknown"
                lines.append(f"  [milestone {m.id}] {m.title} (was due: {due})")

        if overdue_tasks:
            lines.append(f"Overdue tasks ({len(overdue_tasks)}):")
            for t in overdue_tasks:
                lines.append(f"  [task {t.id}] {t.title} (milestone_id: {t.milestone_id})")

        return self.ok("\n".join(lines))

    @staticmethod
    def _format_goal(goal) -> str:
        """Format a single goal as one readable line."""
        target_str = ""
        if goal.target_date:
            target_str = f", target: {goal.target_date.strftime('%Y-%m-%d')}"
        return f"  [{goal.id}] ({goal.priority}) {goal.title} [{goal.status}]{target_str}"

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
