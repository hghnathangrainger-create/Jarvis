"""
manager.py

High-level interface for the Jarvis Project Management system.

Responsibilities:
    - Provide a simple API for creating projects, adding tasks/notes,
      updating status, and generating reports.
    - Link projects to goals via the goal_id field.
    - Detect overdue tasks.

Does NOT:
    - Talk to the database directly (it delegates to ProjectStore).

The ProjectManager is the layer the rest of Jarvis talks to.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from projects.models import Project, ProjectNote, ProjectTask
from projects.store import ProjectStore

logger = logging.getLogger(__name__)


class ProjectManager:
    """Coordinates project, task, and note operations.

    Wraps a ProjectStore for persistence and provides high-level methods
    for creating, querying, and managing projects with human-readable
    reports.

    Attributes:
        _store: The SQLite-backed project store.
    """

    def __init__(self, store: ProjectStore) -> None:
        """Initialise the manager.

        Args:
            store: The SQLite-backed project store.
        """
        self._store = store

    def create_project(
        self,
        name: str,
        description: str = "",
        status: str = "planning",
        target_date: datetime | None = None,
        goal_id: int | None = None,
    ) -> Project:
        """Create a new project.

        Args:
            name: A short, descriptive name.
            description: A longer description.
            status: Initial status.
            target_date: Optional target completion date.
            goal_id: Optional link to a Goal in the goals system.

        Returns:
            The stored Project with its assigned id.
        """
        return self._store.create_project(
            name=name,
            description=description,
            status=status,
            target_date=target_date,
            goal_id=goal_id,
        )

    def add_task(
        self,
        project_id: int,
        title: str,
        description: str = "",
        priority: str = "medium",
        assigned_to: str | None = None,
        estimated_hours: float | None = None,
        due_date: datetime | None = None,
    ) -> ProjectTask | None:
        """Add a task to a project.

        Returns:
            The stored ProjectTask, or None if the project does not exist.
        """
        return self._store.add_task(
            project_id=project_id,
            title=title,
            description=description,
            priority=priority,
            assigned_to=assigned_to,
            estimated_hours=estimated_hours,
            due_date=due_date,
        )

    def add_note(
        self,
        project_id: int,
        content: str,
        task_id: int | None = None,
    ) -> ProjectNote | None:
        """Add a note to a project (optionally attached to a task).

        Returns:
            The stored ProjectNote, or None if the project does not exist.
        """
        return self._store.add_note(
            project_id=project_id,
            content=content,
            task_id=task_id,
        )

    def update_task_status(
        self,
        task_id: int,
        status: str,
        actual_hours: float | None = None,
    ) -> ProjectTask | None:
        """Update a task's status.

        Returns:
            The updated ProjectTask, or None if not found.
        """
        return self._store.update_task_status(
            task_id=task_id, status=status, actual_hours=actual_hours
        )

    def update_project(
        self, project_id: int, **fields: object
    ) -> Project | None:
        """Update fields of a project.

        Returns:
            The updated Project, or None if not found.
        """
        return self._store.update_project(project_id, fields)

    def archive_project(self, project_id: int) -> Project | None:
        """Archive a project.

        Returns:
            The updated Project, or None if not found.
        """
        return self._store.archive_project(project_id)

    def get_project(self, project_id: int) -> Project | None:
        """Return a single project by id."""
        return self._store.get_project(project_id)

    def list_projects(self, status_filter: str | None = None) -> list[Project]:
        """Return projects, optionally filtered by status."""
        return self._store.list_projects(status_filter=status_filter)

    def search_tasks(self, query: str) -> list[ProjectTask]:
        """Search tasks by title or description substring."""
        return self._store.search_tasks(query)

    def get_overdue_tasks(self) -> list[ProjectTask]:
        """Return tasks past their due date."""
        return self._store.get_overdue_tasks()

    def get_project_stats(self, project_id: int) -> dict:
        """Get stats for a project."""
        return self._store.get_project_stats(project_id)

    def get_project_report(self, project_id: int) -> str:
        """Generate a human-readable project report.

        Returns a multi-line string with project info, task breakdown,
        and stats.

        Args:
            project_id: The id of the project.

        Returns:
            A formatted report string.
        """
        project = self._store.get_project(project_id)
        if project is None:
            return f"No project found with id {project_id}."

        stats = self._store.get_project_stats(project_id)
        tasks = self._store.list_tasks(project_id)

        lines = [
            f"Project: {project.name} [{project.status}]",
            f"  {project.description}" if project.description else "",
            f"  Progress: {stats['done']}/{stats['total_tasks']} tasks "
            f"({stats['completion_pct']}%)",
            f"  Tasks: {stats['todo']} todo, {stats['in_progress']} in progress, "
            f"{stats['done']} done, {stats['blocked']} blocked",
            f"  Hours: {stats['total_actual_hours']:.1f} / "
            f"{stats['total_estimated_hours']:.1f} (actual / estimated)",
            f"  Notes: {stats['total_notes']}",
            "",
        ]

        if project.goal_id is not None:
            lines.append(f"  Linked to Goal: #{project.goal_id}")

        if project.target_date:
            lines.append(
                f"  Target date: {project.target_date.strftime('%Y-%m-%d')}"
            )

        lines.append("")

        if tasks:
            lines.append("  Tasks:")
            for t in tasks:
                status_icon = {
                    "todo": "○",
                    "in_progress": "►",
                    "done": "✓",
                    "blocked": "■",
                }.get(t.status, "?")
                priority_str = f" [{t.priority}]" if t.priority != "medium" else ""
                assignee_str = f" ({t.assigned_to})" if t.assigned_to else ""
                due_str = ""
                if t.due_date:
                    due_str = f" due {t.due_date.strftime('%Y-%m-%d')}"
                lines.append(
                    f"    {status_icon} {t.title}{priority_str}{assignee_str}{due_str}"
                )
        else:
            lines.append("  No tasks yet.")

        overdue = self._store.get_overdue_tasks()
        overdue_in_project = [t for t in overdue if t.project_id == project_id]
        if overdue_in_project:
            lines.append("")
            lines.append(f"  ⚠ {len(overdue_in_project)} overdue task(s)!")

        return "\n".join(line for line in lines if line is not None)

    def count(self, status_filter: str | None = None) -> int:
        """Return the number of projects (optionally filtered by status)."""
        return len(self._store.list_projects(status_filter=status_filter))
