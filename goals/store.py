"""
store.py

SQLite-backed store for the Jarvis Goals and Milestones system.

Responsibilities:
    - Persist goals, milestones, and tasks in SQLite.
    - Expose CRUD and progress-calculation methods.

Does NOT:
    - Coordinate reporting or overdue detection (see manager.py).

The GoalStore owns all database access. GoalManager wraps it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session as OrmSession, sessionmaker

from goals.models import Goal, Milestone, Task

logger = logging.getLogger(__name__)


def _ensure_goals_tables(session_factory: sessionmaker[OrmSession]) -> None:
    """Create the goals, milestones, and tasks tables if they do not exist.

    This is idempotent and safe to call on every startup.
    """
    from sqlalchemy import text

    with session_factory() as session:
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS goals ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  title TEXT NOT NULL DEFAULT '',"
                "  description TEXT NOT NULL DEFAULT '',"
                "  status VARCHAR(16) NOT NULL DEFAULT 'active',"
                "  priority VARCHAR(16) NOT NULL DEFAULT 'medium',"
                "  created_at TIMESTAMP NOT NULL,"
                "  target_date TIMESTAMP,"
                "  completed_at TIMESTAMP"
                ")"
            )
        )
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS milestones ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  goal_id INTEGER NOT NULL,"
                "  title TEXT NOT NULL DEFAULT '',"
                "  description TEXT NOT NULL DEFAULT '',"
                "  status VARCHAR(16) NOT NULL DEFAULT 'pending',"
                "  due_date TIMESTAMP,"
                "  completed_at TIMESTAMP,"
                "  FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE"
                ")"
            )
        )
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS tasks ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  milestone_id INTEGER NOT NULL,"
                "  title TEXT NOT NULL DEFAULT '',"
                "  status VARCHAR(16) NOT NULL DEFAULT 'pending',"
                "  estimated_minutes INTEGER,"
                "  actual_minutes INTEGER,"
                "  completed_at TIMESTAMP,"
                "  FOREIGN KEY (milestone_id) REFERENCES milestones(id) ON DELETE CASCADE"
                ")"
            )
        )
        session.commit()


class GoalStore:
    """SQLite-backed store for goals, milestones, and tasks.

    Uses raw SQL via SQLAlchemy session for reads and writes.

    Attributes:
        _session_factory: SQLAlchemy session factory.
    """

    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        """Initialise the store.

        Args:
            session_factory: SQLAlchemy session factory for database access.
        """
        self._session_factory = session_factory
        _ensure_goals_tables(session_factory)

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------

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
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            from sqlalchemy import text

            cursor = session.execute(
                text(
                    "INSERT INTO goals "
                    "(title, description, status, priority, created_at, target_date, completed_at) "
                    "VALUES (:title, :description, 'active', :priority, :created_at, :target_date, NULL)"
                ),
                {
                    "title": title,
                    "description": description,
                    "priority": priority,
                    "created_at": now,
                    "target_date": target_date,
                },
            )
            session.commit()
            goal_id = cursor.lastrowid

        return Goal(
            id=goal_id,
            title=title,
            description=description,
            status="active",
            priority=priority,
            created_at=now,
            target_date=target_date,
        )

    def get_goal(self, goal_id: int) -> Goal | None:
        """Return a single goal by id, or None if not found."""
        from sqlalchemy import text

        with self._session_factory() as session:
            row = session.execute(
                text("SELECT * FROM goals WHERE id = :id"),
                {"id": goal_id},
            ).mappings().first()

        if row is None:
            return None
        return self._row_to_goal(row)

    def list_goals(self, status_filter: str | None = None) -> list[Goal]:
        """Return goals, optionally filtered by status.

        Args:
            status_filter: Optional status to filter by ("active", "completed", "abandoned").
                When None, returns all goals.

        Returns:
            A list of Goal objects, newest first.
        """
        from sqlalchemy import text

        with self._session_factory() as session:
            if status_filter:
                rows = session.execute(
                    text(
                        "SELECT * FROM goals WHERE status = :status "
                        "ORDER BY created_at DESC"
                    ),
                    {"status": status_filter},
                ).mappings().all()
            else:
                rows = session.execute(
                    text("SELECT * FROM goals ORDER BY created_at DESC")
                ).mappings().all()
        return [self._row_to_goal(r) for r in rows]

    def update_goal(self, goal_id: int, fields: dict[str, Any]) -> Goal | None:
        """Update specific fields of a goal.

        Args:
            goal_id: The id of the goal to update.
            fields: A dict of field names to new values. Supported keys:
                title, description, status, priority, target_date.

        Returns:
            The updated Goal, or None if not found.
        """
        existing = self.get_goal(goal_id)
        if existing is None:
            return None

        from sqlalchemy import text

        updates: dict[str, Any] = {}
        for key in ("title", "description", "status", "priority", "target_date", "completed_at"):
            if key in fields:
                updates[key] = fields[key]

        if not updates:
            return existing

        set_parts = [f"{k} = :{k}" for k in updates]
        updates["id"] = goal_id
        with self._session_factory() as session:
            session.execute(
                text(f"UPDATE goals SET {', '.join(set_parts)} WHERE id = :id"),
                updates,
            )
            session.commit()

        return self.get_goal(goal_id)

    def delete_goal(self, goal_id: int) -> bool:
        """Delete a goal and all its milestones and tasks (via CASCADE).

        Args:
            goal_id: The id of the goal to delete.

        Returns:
            True if a row was deleted.
        """
        from sqlalchemy import text

        with self._session_factory() as session:
            cursor = session.execute(
                text("DELETE FROM goals WHERE id = :id"),
                {"id": goal_id},
            )
            session.commit()
            return cursor.rowcount > 0

    def complete_goal(self, goal_id: int) -> Goal | None:
        """Mark a goal as completed with a timestamp.

        Returns:
            The updated Goal, or None if not found.
        """
        return self.update_goal(goal_id, {"status": "completed", "completed_at": datetime.now(timezone.utc)})

    # ------------------------------------------------------------------
    # Milestones
    # ------------------------------------------------------------------

    def add_milestone(
        self,
        goal_id: int,
        title: str,
        description: str = "",
        due_date: datetime | None = None,
    ) -> Milestone | None:
        """Add a milestone to a goal.

        Returns:
            The stored Milestone, or None if the goal does not exist.
        """
        goal = self.get_goal(goal_id)
        if goal is None:
            return None

        from sqlalchemy import text

        with self._session_factory() as session:
            cursor = session.execute(
                text(
                    "INSERT INTO milestones "
                    "(goal_id, title, description, status, due_date, completed_at) "
                    "VALUES (:goal_id, :title, :description, 'pending', :due_date, NULL)"
                ),
                {
                    "goal_id": goal_id,
                    "title": title,
                    "description": description,
                    "due_date": due_date,
                },
            )
            session.commit()
            milestone_id = cursor.lastrowid

        return Milestone(
            id=milestone_id,
            goal_id=goal_id,
            title=title,
            description=description,
            status="pending",
            due_date=due_date,
        )

    def get_milestone(self, milestone_id: int) -> Milestone | None:
        """Return a single milestone by id, or None."""
        from sqlalchemy import text

        with self._session_factory() as session:
            row = session.execute(
                text("SELECT * FROM milestones WHERE id = :id"),
                {"id": milestone_id},
            ).mappings().first()

        if row is None:
            return None
        return self._row_to_milestone(row)

    def list_milestones(self, goal_id: int) -> list[Milestone]:
        """Return all milestones for a goal, in insertion order."""
        from sqlalchemy import text

        with self._session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT * FROM milestones WHERE goal_id = :goal_id "
                    "ORDER BY id ASC"
                ),
                {"goal_id": goal_id},
            ).mappings().all()
        return [self._row_to_milestone(r) for r in rows]

    def complete_milestone(self, milestone_id: int) -> Milestone | None:
        """Mark a milestone as completed with a timestamp.

        Returns:
            The updated Milestone, or None if not found.
        """
        existing = self.get_milestone(milestone_id)
        if existing is None:
            return None

        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            session.execute(
                text(
                    "UPDATE milestones SET status = 'completed', completed_at = :now "
                    "WHERE id = :id"
                ),
                {"id": milestone_id, "now": now},
            )
            session.commit()

        return self.get_milestone(milestone_id)

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def add_task(
        self,
        milestone_id: int,
        title: str,
        estimated_minutes: int | None = None,
    ) -> Task | None:
        """Add a task to a milestone.

        Returns:
            The stored Task, or None if the milestone does not exist.
        """
        milestone = self.get_milestone(milestone_id)
        if milestone is None:
            return None

        from sqlalchemy import text

        with self._session_factory() as session:
            cursor = session.execute(
                text(
                    "INSERT INTO tasks "
                    "(milestone_id, title, status, estimated_minutes, actual_minutes, completed_at) "
                    "VALUES (:milestone_id, :title, 'pending', :estimated_minutes, NULL, NULL)"
                ),
                {
                    "milestone_id": milestone_id,
                    "title": title,
                    "estimated_minutes": estimated_minutes,
                },
            )
            session.commit()
            task_id = cursor.lastrowid

        return Task(
            id=task_id,
            milestone_id=milestone_id,
            title=title,
            status="pending",
            estimated_minutes=estimated_minutes,
        )

    def get_task(self, task_id: int) -> Task | None:
        """Return a single task by id, or None."""
        from sqlalchemy import text

        with self._session_factory() as session:
            row = session.execute(
                text("SELECT * FROM tasks WHERE id = :id"),
                {"id": task_id},
            ).mappings().first()

        if row is None:
            return None
        return self._row_to_task(row)

    def complete_task(self, task_id: int, actual_minutes: int | None = None) -> Task | None:
        """Mark a task as done with a timestamp.

        Args:
            task_id: The id of the task to complete.
            actual_minutes: Optional actual time spent in minutes.

        Returns:
            The updated Task, or None if not found.
        """
        existing = self.get_task(task_id)
        if existing is None:
            return None

        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            session.execute(
                text(
                    "UPDATE tasks SET status = 'done', completed_at = :now, "
                    "actual_minutes = COALESCE(:actual_minutes, actual_minutes) "
                    "WHERE id = :id"
                ),
                {"id": task_id, "now": now, "actual_minutes": actual_minutes},
            )
            session.commit()

        return self.get_task(task_id)

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    def get_progress(self, goal_id: int) -> dict[str, Any]:
        """Calculate progress for a goal based on task completion.

        Returns a dict with:
            - total_tasks: Total number of tasks across all milestones.
            - completed_tasks: Number of tasks with status "done".
            - percentage: Float 0.0-100.0 representing completion.
            - total_milestones: Total number of milestones.
            - completed_milestones: Number of milestones with status "completed".
        """
        from sqlalchemy import text

        milestones = self.list_milestones(goal_id)
        total_milestones = len(milestones)
        completed_milestones = sum(1 for m in milestones if m.status == "completed")

        total_tasks = 0
        completed_tasks = 0
        for milestone in milestones:
            if milestone.id is None:
                continue
            with self._session_factory() as session:
                row = session.execute(
                    text(
                        "SELECT COUNT(*) as total, "
                        "SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done_count "
                        "FROM tasks WHERE milestone_id = :milestone_id"
                    ),
                    {"milestone_id": milestone.id},
                ).mappings().first()
                if row:
                    total_tasks += row["total"] or 0
                    completed_tasks += row["done_count"] or 0

        percentage = 0.0
        if total_tasks > 0:
            percentage = (completed_tasks / total_tasks) * 100.0

        return {
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "percentage": percentage,
            "total_milestones": total_milestones,
            "completed_milestones": completed_milestones,
        }

    # ------------------------------------------------------------------
    # Overdue
    # ------------------------------------------------------------------

    def get_overdue_items(self) -> dict[str, list[Any]]:
        """Return tasks and milestones past their due date.

        Returns a dict with:
            - overdue_tasks: List of Task objects past due.
            - overdue_milestones: List of Milestone objects past due.
        """
        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        overdue_tasks: list[Task] = []
        overdue_milestones: list[Milestone] = []

        with self._session_factory() as session:
            task_rows = session.execute(
                text(
                    "SELECT t.* FROM tasks t "
                    "JOIN milestones m ON t.milestone_id = m.id "
                    "JOIN goals g ON m.goal_id = g.id "
                    "WHERE t.status != 'done' AND m.due_date IS NOT NULL AND m.due_date < :now "
                    "AND g.status = 'active'"
                ),
                {"now": now},
            ).mappings().all()
            overdue_tasks = [self._row_to_task(r) for r in task_rows]

            milestone_rows = session.execute(
                text(
                    "SELECT m.* FROM milestones m "
                    "JOIN goals g ON m.goal_id = g.id "
                    "WHERE m.status != 'completed' AND m.due_date IS NOT NULL AND m.due_date < :now "
                    "AND g.status = 'active'"
                ),
                {"now": now},
            ).mappings().all()
            overdue_milestones = [self._row_to_milestone(r) for r in milestone_rows]

        return {
            "overdue_tasks": overdue_tasks,
            "overdue_milestones": overdue_milestones,
        }

    # ------------------------------------------------------------------
    # Row converters
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_goal(row: dict) -> Goal:
        """Convert a database row mapping to a Goal."""
        return Goal(
            id=row["id"],
            title=row.get("title", ""),
            description=row.get("description", ""),
            status=row.get("status", "active"),
            priority=row.get("priority", "medium"),
            created_at=row.get("created_at", datetime.now(timezone.utc)),
            target_date=row.get("target_date"),
            completed_at=row.get("completed_at"),
        )

    @staticmethod
    def _row_to_milestone(row: dict) -> Milestone:
        """Convert a database row mapping to a Milestone."""
        return Milestone(
            id=row["id"],
            goal_id=row.get("goal_id"),
            title=row.get("title", ""),
            description=row.get("description", ""),
            status=row.get("status", "pending"),
            due_date=row.get("due_date"),
            completed_at=row.get("completed_at"),
        )

    @staticmethod
    def _row_to_task(row: dict) -> Task:
        """Convert a database row mapping to a Task."""
        return Task(
            id=row["id"],
            milestone_id=row.get("milestone_id"),
            title=row.get("title", ""),
            status=row.get("status", "pending"),
            estimated_minutes=row.get("estimated_minutes"),
            actual_minutes=row.get("actual_minutes"),
            completed_at=row.get("completed_at"),
        )
