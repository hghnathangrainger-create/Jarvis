"""
manager.py

High-level interface for the Jarvis Goals and Milestones system.

Responsibilities:
    - Provide a simple API for creating goals, adding milestones/tasks,
      completing items, and generating progress reports.
    - Detect overdue items.

Does NOT:
    - Talk to the database directly (it delegates to GoalStore).

The GoalManager is the layer the rest of Jarvis talks to.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from goals.models import Goal, Milestone, Task
from goals.store import GoalStore

logger = logging.getLogger(__name__)


class GoalManager:
    """Coordinates goal, milestone, and task operations.

    Wraps a GoalStore for persistence and provides high-level methods
    for creating, querying, and completing items with human-readable
    progress reports.

    Attributes:
        _store: The SQLite-backed goal store.
    """

    def __init__(self, store: GoalStore) -> None:
        """Initialise the manager.

        Args:
            store: The SQLite-backed goal store.
        """
        self._store = store

    def create_goal(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        target_date: datetime | None = None,
    ) -> Goal:
        """Create a new goal.

        Args:
            title: A short, descriptive title.
            description: A longer description.
            priority: One of "low", "medium", "high", "critical".
            target_date: Optional target completion date.

        Returns:
            The stored Goal with its assigned id.
        """
        return self._store.create_goal(
            title=title,
            description=description,
            priority=priority,
            target_date=target_date,
        )

    def add_milestone(
        self,
        goal_id: int,
        title: str,
        description: str = "",
        due_date: datetime | None = None,
    ) -> Milestone | None:
        """Add a milestone to a goal.

        Args:
            goal_id: The parent goal's id.
            title: A short, descriptive title.
            description: A longer description.
            due_date: Optional due date.

        Returns:
            The stored Milestone, or None if the goal does not exist.
        """
        return self._store.add_milestone(
            goal_id=goal_id,
            title=title,
            description=description,
            due_date=due_date,
        )

    def add_task(
        self,
        milestone_id: int,
        title: str,
        estimated_minutes: int | None = None,
    ) -> Task | None:
        """Add a task to a milestone.

        Args:
            milestone_id: The parent milestone's id.
            title: A short, descriptive title.
            estimated_minutes: Optional estimated time in minutes.

        Returns:
            The stored Task, or None if the milestone does not exist.
        """
        return self._store.add_task(
            milestone_id=milestone_id,
            title=title,
            estimated_minutes=estimated_minutes,
        )

    def mark_task_done(
        self, task_id: int, actual_minutes: int | None = None
    ) -> Task | None:
        """Mark a task as done.

        Args:
            task_id: The id of the task to complete.
            actual_minutes: Optional actual time spent in minutes.

        Returns:
            The updated Task, or None if not found.
        """
        return self._store.complete_task(task_id, actual_minutes=actual_minutes)

    def get_goal(self, goal_id: int) -> Goal | None:
        """Return a single goal by id."""
        return self._store.get_goal(goal_id)

    def list_active_goals(self) -> list[Goal]:
        """Return all goals with status 'active'."""
        return self._store.list_goals(status_filter="active")

    def update_goal(self, goal_id: int, **fields: object) -> Goal | None:
        """Update fields of a goal.

        Returns:
            The updated Goal, or None if not found.
        """
        return self._store.update_goal(goal_id, fields)

    def delete_goal(self, goal_id: int) -> bool:
        """Delete a goal and all its milestones and tasks.

        Returns:
            True if the goal was deleted.
        """
        return self._store.delete_goal(goal_id)

    def get_progress_report(self, goal_id: int) -> str:
        """Generate a human-readable progress report for a goal.

        Returns a multi-line string with:
            - Goal title and status
            - Milestone breakdown
            - Task completion percentages
            - Overall progress

        Args:
            goal_id: The id of the goal.

        Returns:
            A formatted progress report string.
        """
        goal = self._store.get_goal(goal_id)
        if goal is None:
            return f"No goal found with id {goal_id}."

        progress = self._store.get_progress(goal_id)
        milestones = self._store.list_milestones(goal_id)

        lines = [
            f"Goal: {goal.title} [{goal.status}] (priority: {goal.priority})",
            f"  {goal.description}" if goal.description else "",
            f"  Overall progress: {progress['completed_tasks']}/{progress['total_tasks']} tasks "
            f"({progress['percentage']:.1f}%)",
            f"  Milestones: {progress['completed_milestones']}/{progress['total_milestones']} completed",
            "",
        ]

        if not milestones:
            lines.append("  No milestones defined yet.")
        else:
            for milestone in milestones:
                ms_status = "✓" if milestone.status == "completed" else "○"
                due_str = ""
                if milestone.due_date:
                    due_str = f" (due: {milestone.due_date.strftime('%Y-%m-%d')})"
                lines.append(f"  {ms_status} {milestone.title}{due_str}")

                # Show tasks under this milestone.
                if milestone.id is not None:
                    tasks = self._store._session_factory  # noqa: access tasks
                    from sqlalchemy import text

                    with self._store._session_factory() as session:
                        task_rows = session.execute(
                            text(
                                "SELECT * FROM tasks WHERE milestone_id = :mid ORDER BY id ASC"
                            ),
                            {"mid": milestone.id},
                        ).mappings().all()
                    task_list = [GoalStore._row_to_task(r) for r in task_rows]
                    if not task_list:
                        lines.append("    No tasks defined.")
                    for task in task_list:
                        task_status = "✓" if task.status == "done" else ("►" if task.status == "in_progress" else "○")
                        lines.append(f"    {task_status} {task.title}")
                lines.append("")

        target_str = ""
        if goal.target_date:
            target_str = f"\n  Target date: {goal.target_date.strftime('%Y-%m-%d')}"
        if goal.completed_at:
            target_str += f"\n  Completed: {goal.completed_at.strftime('%Y-%m-%d %H:%M')}"
        lines.append(target_str)

        return "\n".join(line for line in lines if line is not None)

    def get_overdue_items(self) -> dict[str, list]:
        """Return tasks and milestones past their due date.

        Returns:
            A dict with "overdue_tasks" and "overdue_milestones" lists.
        """
        return self._store.get_overdue_items()

    def count(self) -> int:
        """Return the total number of goals."""
        return len(self._store.list_goals())
