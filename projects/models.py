"""
models.py

Data models for the Jarvis Project Management system.

Responsibilities:
    - Define Project, ProjectTask, and ProjectNote dataclasses.

Does NOT:
    - Store or retrieve data (see store.py).
    - Coordinate reporting or goal linking (see manager.py).

These are pure value objects with no storage or AI logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Project:
    """A project grouping related tasks.

    Attributes:
        id: Auto-incrementing primary key (set by the store on insert).
        name: A short, descriptive name.
        description: A longer description of the project.
        status: One of "planning", "active", "paused", "completed", "archived".
        created_at: When this project was created (UTC).
        updated_at: When this project was last updated (UTC).
        target_date: Optional target completion date (UTC).
        goal_id: Optional link to a Goal in the goals system.
    """

    id: int | None = None
    name: str = ""
    description: str = ""
    status: str = "planning"
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    target_date: datetime | None = None
    goal_id: int | None = None


@dataclass(frozen=True, slots=True)
class ProjectTask:
    """A task within a project.

    Attributes:
        id: Auto-incrementing primary key.
        project_id: The parent project's id.
        title: A short, descriptive title.
        description: A longer description.
        status: One of "todo", "in_progress", "done", "blocked".
        priority: One of "low", "medium", "high", "critical".
        assigned_to: Optional assignee name/identifier.
        estimated_hours: Estimated hours to complete.
        actual_hours: Actual hours spent.
        due_date: Optional due date (UTC).
        completed_at: When this task was completed (UTC), or None.
    """

    id: int | None = None
    project_id: int | None = None
    title: str = ""
    description: str = ""
    status: str = "todo"
    priority: str = "medium"
    assigned_to: str | None = None
    estimated_hours: float | None = None
    actual_hours: float | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProjectNote:
    """A note attached to a project (optionally to a task).

    Attributes:
        id: Auto-incrementing primary key.
        project_id: The parent project's id.
        task_id: Optional task id this note is attached to.
        content: The note text.
        created_at: When this note was created (UTC).
    """

    id: int | None = None
    project_id: int | None = None
    task_id: int | None = None
    content: str = ""
    created_at: datetime = field(default_factory=_utc_now)
