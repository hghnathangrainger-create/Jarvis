"""
models.py

Value types for the Jarvis Goals and Milestones system.

Responsibilities:
    - Define Goal, Milestone, and Task dataclasses.

Does NOT:
    - Store or retrieve data (see store.py).
    - Coordinate progress or reporting (see manager.py).

These are pure value objects with no storage or AI logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Goal:
    """A high-level goal to track progress towards.

    Attributes:
        id: Auto-incrementing primary key (set by the store on insert).
        title: A short, descriptive title.
        description: A longer description of what this goal entails.
        status: One of "active", "completed", or "abandoned".
        priority: One of "low", "medium", "high", or "critical".
        created_at: When this goal was created (UTC).
        target_date: Optional target completion date (UTC).
        completed_at: When this goal was completed (UTC), or None.
    """

    id: int | None = None
    title: str = ""
    description: str = ""
    status: str = "active"
    priority: str = "medium"
    created_at: datetime = field(default_factory=_utc_now)
    target_date: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Milestone:
    """A milestone within a goal, representing a significant checkpoint.

    Attributes:
        id: Auto-incrementing primary key.
        goal_id: The parent goal's id.
        title: A short, descriptive title.
        description: A longer description.
        status: One of "pending" or "completed".
        due_date: Optional due date (UTC).
        completed_at: When this milestone was completed (UTC), or None.
    """

    id: int | None = None
    goal_id: int | None = None
    title: str = ""
    description: str = ""
    status: str = "pending"
    due_date: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Task:
    """A concrete task within a milestone.

    Attributes:
        id: Auto-incrementing primary key.
        milestone_id: The parent milestone's id.
        title: A short, descriptive title.
        status: One of "pending", "in_progress", or "done".
        estimated_minutes: Estimated time to complete, in minutes.
        actual_minutes: Actual time spent, in minutes.
        completed_at: When this task was completed (UTC), or None.
    """

    id: int | None = None
    milestone_id: int | None = None
    title: str = ""
    status: str = "pending"
    estimated_minutes: int | None = None
    actual_minutes: int | None = None
    completed_at: datetime | None = None
