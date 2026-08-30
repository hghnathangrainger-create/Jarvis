"""
store.py

SQLite-backed store for the Jarvis Project Management system.

Responsibilities:
    - Persist projects, tasks, and notes in SQLite.
    - Expose CRUD, query, stats, and overdue detection methods.

Does NOT:
    - Coordinate reporting or goal linking (see manager.py).

The ProjectStore owns all database access. ProjectManager wraps it.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from projects.models import Project, ProjectNote, ProjectTask

logger = logging.getLogger(__name__)


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse a timestamp that may be a datetime or a string from SQLite.

    SQLite returns timestamps as strings; SQLAlchemy may return them as
    datetime objects. This helper handles both.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
    return None


def _ensure_project_tables(session_factory: sessionmaker[OrmSession]) -> None:
    """Create the projects, project_tasks, and project_notes tables
    if they do not exist. Idempotent and safe to call on every startup.
    """
    with session_factory() as session:
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS projects ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  name TEXT NOT NULL DEFAULT '',"
                "  description TEXT NOT NULL DEFAULT '',"
                "  status VARCHAR(16) NOT NULL DEFAULT 'planning',"
                "  created_at TIMESTAMP NOT NULL,"
                "  updated_at TIMESTAMP NOT NULL,"
                "  target_date TIMESTAMP,"
                "  goal_id INTEGER"
                ")"
            )
        )
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS project_tasks ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  project_id INTEGER NOT NULL,"
                "  title TEXT NOT NULL DEFAULT '',"
                "  description TEXT NOT NULL DEFAULT '',"
                "  status VARCHAR(16) NOT NULL DEFAULT 'todo',"
                "  priority VARCHAR(16) NOT NULL DEFAULT 'medium',"
                "  assigned_to TEXT,"
                "  estimated_hours REAL,"
                "  actual_hours REAL,"
                "  due_date TIMESTAMP,"
                "  completed_at TIMESTAMP,"
                "  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"
                ")"
            )
        )
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS project_notes ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  project_id INTEGER NOT NULL,"
                "  task_id INTEGER,"
                "  content TEXT NOT NULL DEFAULT '',"
                "  created_at TIMESTAMP NOT NULL,"
                "  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"
                ")"
            )
        )
        session.commit()


class ProjectStore:
    """SQLite-backed store for projects, tasks, and notes.

    Attributes:
        _session_factory: SQLAlchemy session factory.
    """

    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        """Initialise the store.

        Args:
            session_factory: SQLAlchemy session factory for database access.
        """
        self._session_factory = session_factory
        _ensure_project_tables(session_factory)

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

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
            goal_id: Optional link to a Goal.

        Returns:
            The stored Project with its assigned id.
        """
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            cursor = session.execute(
                text(
                    "INSERT INTO projects "
                    "(name, description, status, created_at, updated_at, target_date, goal_id) "
                    "VALUES (:name, :description, :status, :created_at, :updated_at, :target_date, :goal_id)"
                ),
                {
                    "name": name,
                    "description": description,
                    "status": status,
                    "created_at": now,
                    "updated_at": now,
                    "target_date": target_date,
                    "goal_id": goal_id,
                },
            )
            session.commit()
            project_id = cursor.lastrowid

        return Project(
            id=project_id,
            name=name,
            description=description,
            status=status,
            created_at=now,
            updated_at=now,
            target_date=target_date,
            goal_id=goal_id,
        )

    def get_project(self, project_id: int) -> Project | None:
        """Return a single project by id, or None if not found."""
        with self._session_factory() as session:
            row = session.execute(
                text("SELECT * FROM projects WHERE id = :id"),
                {"id": project_id},
            ).mappings().first()

        if row is None:
            return None
        return self._row_to_project(row)

    def list_projects(self, status_filter: str | None = None) -> list[Project]:
        """Return projects, optionally filtered by status.

        Args:
            status_filter: Optional status to filter by. None returns all.

        Returns:
            A list of Project objects, newest first.
        """
        with self._session_factory() as session:
            if status_filter:
                rows = session.execute(
                    text(
                        "SELECT * FROM projects WHERE status = :status "
                        "ORDER BY created_at DESC"
                    ),
                    {"status": status_filter},
                ).mappings().all()
            else:
                rows = session.execute(
                    text("SELECT * FROM projects ORDER BY created_at DESC")
                ).mappings().all()
        return [self._row_to_project(r) for r in rows]

    def update_project(
        self, project_id: int, fields: dict[str, Any]
    ) -> Project | None:
        """Update specific fields of a project.

        Returns:
            The updated Project, or None if not found.
        """
        existing = self.get_project(project_id)
        if existing is None:
            return None

        now = datetime.now(timezone.utc)
        updates: dict[str, Any] = {"updated_at": now}
        for key in ("name", "description", "status", "target_date", "goal_id"):
            if key in fields:
                updates[key] = fields[key]

        set_parts = [f"{k} = :{k}" for k in updates]
        updates["id"] = project_id
        with self._session_factory() as session:
            session.execute(
                text(f"UPDATE projects SET {', '.join(set_parts)} WHERE id = :id"),
                updates,
            )
            session.commit()

        return self.get_project(project_id)

    def archive_project(self, project_id: int) -> Project | None:
        """Archive a project (set status to 'archived').

        Returns:
            The updated Project, or None if not found.
        """
        return self.update_project(project_id, {"status": "archived"})

    def delete_project(self, project_id: int) -> bool:
        """Delete a project and all its tasks and notes (via CASCADE).

        Returns:
            True if a row was deleted.
        """
        with self._session_factory() as session:
            cursor = session.execute(
                text("DELETE FROM projects WHERE id = :id"),
                {"id": project_id},
            )
            session.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

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
        project = self.get_project(project_id)
        if project is None:
            return None

        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            cursor = session.execute(
                text(
                    "INSERT INTO project_tasks "
                    "(project_id, title, description, status, priority, assigned_to, "
                    "estimated_hours, actual_hours, due_date, completed_at) "
                    "VALUES (:project_id, :title, :description, 'todo', :priority, "
                    ":assigned_to, :estimated_hours, NULL, :due_date, NULL)"
                ),
                {
                    "project_id": project_id,
                    "title": title,
                    "description": description,
                    "priority": priority,
                    "assigned_to": assigned_to,
                    "estimated_hours": estimated_hours,
                    "due_date": due_date,
                },
            )
            session.commit()
            task_id = cursor.lastrowid

        return ProjectTask(
            id=task_id,
            project_id=project_id,
            title=title,
            description=description,
            status="todo",
            priority=priority,
            assigned_to=assigned_to,
            estimated_hours=estimated_hours,
            due_date=due_date,
        )

    def get_task(self, task_id: int) -> ProjectTask | None:
        """Return a single task by id, or None."""
        with self._session_factory() as session:
            row = session.execute(
                text("SELECT * FROM project_tasks WHERE id = :id"),
                {"id": task_id},
            ).mappings().first()

        if row is None:
            return None
        return self._row_to_task(row)

    def list_tasks(self, project_id: int) -> list[ProjectTask]:
        """Return all tasks for a project, in insertion order."""
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT * FROM project_tasks WHERE project_id = :project_id "
                    "ORDER BY id ASC"
                ),
                {"project_id": project_id},
            ).mappings().all()
        return [self._row_to_task(r) for r in rows]

    def update_task_status(
        self, task_id: int, status: str, actual_hours: float | None = None
    ) -> ProjectTask | None:
        """Update a task's status (and optionally actual hours).

        If status is "done", sets completed_at to now.

        Returns:
            The updated ProjectTask, or None if not found.
        """
        existing = self.get_task(task_id)
        if existing is None:
            return None

        now = datetime.now(timezone.utc)
        completed_at = now if status == "done" else None

        with self._session_factory() as session:
            session.execute(
                text(
                    "UPDATE project_tasks SET status = :status, "
                    "completed_at = :completed_at, "
                    "actual_hours = COALESCE(:actual_hours, actual_hours) "
                    "WHERE id = :id"
                ),
                {
                    "id": task_id,
                    "status": status,
                    "completed_at": completed_at,
                    "actual_hours": actual_hours,
                },
            )
            session.commit()

        return self.get_task(task_id)

    def search_tasks(self, query: str) -> list[ProjectTask]:
        """Search tasks by title or description substring.

        Args:
            query: The search substring (case-insensitive).

        Returns:
            Matching tasks, newest first.
        """
        if not query.strip():
            return []

        with self._session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT * FROM project_tasks "
                    "WHERE title LIKE :query OR description LIKE :query "
                    "ORDER BY id DESC"
                ),
                {"query": f"%{query}%"},
            ).mappings().all()
        return [self._row_to_task(r) for r in rows]

    def get_overdue_tasks(self) -> list[ProjectTask]:
        """Return tasks that are past their due date and not done."""
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT t.* FROM project_tasks t "
                    "JOIN projects p ON t.project_id = p.id "
                    "WHERE t.status != 'done' AND t.status != 'blocked' "
                    "AND t.due_date IS NOT NULL AND t.due_date < :now "
                    "AND p.status NOT IN ('completed', 'archived')"
                ),
                {"now": now},
            ).mappings().all()
        return [self._row_to_task(r) for r in rows]

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

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
        project = self.get_project(project_id)
        if project is None:
            return None

        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            cursor = session.execute(
                text(
                    "INSERT INTO project_notes "
                    "(project_id, task_id, content, created_at) "
                    "VALUES (:project_id, :task_id, :content, :created_at)"
                ),
                {
                    "project_id": project_id,
                    "task_id": task_id,
                    "content": content,
                    "created_at": now,
                },
            )
            session.commit()
            note_id = cursor.lastrowid

        return ProjectNote(
            id=note_id,
            project_id=project_id,
            task_id=task_id,
            content=content,
            created_at=now,
        )

    def list_notes(self, project_id: int) -> list[ProjectNote]:
        """Return all notes for a project, newest first."""
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT * FROM project_notes WHERE project_id = :project_id "
                    "ORDER BY created_at DESC"
                ),
                {"project_id": project_id},
            ).mappings().all()
        return [self._row_to_note(r) for r in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_project_stats(self, project_id: int) -> dict[str, Any]:
        """Calculate stats for a project.

        Returns a dict with:
            - total_tasks: Total number of tasks.
            - todo: Tasks with status "todo".
            - in_progress: Tasks with status "in_progress".
            - done: Tasks with status "done".
            - blocked: Tasks with status "blocked".
            - total_estimated_hours: Sum of estimated hours.
            - total_actual_hours: Sum of actual hours.
            - total_notes: Number of notes.
            - completion_pct: Float 0.0-100.0.
        """
        with self._session_factory() as session:
            row = session.execute(
                text(
                    "SELECT "
                    "  COUNT(*) as total, "
                    "  SUM(CASE WHEN status = 'todo' THEN 1 ELSE 0 END) as todo_count, "
                    "  SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as ip_count, "
                    "  SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done_count, "
                    "  SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) as blocked_count, "
                    "  COALESCE(SUM(estimated_hours), 0) as total_est, "
                    "  COALESCE(SUM(actual_hours), 0) as total_actual "
                    "FROM project_tasks WHERE project_id = :project_id"
                ),
                {"project_id": project_id},
            ).mappings().first()

            notes_row = session.execute(
                text(
                    "SELECT COUNT(*) as cnt FROM project_notes WHERE project_id = :project_id"
                ),
                {"project_id": project_id},
            ).mappings().first()

        if row is None:
            return {
                "total_tasks": 0,
                "todo": 0,
                "in_progress": 0,
                "done": 0,
                "blocked": 0,
                "total_estimated_hours": 0.0,
                "total_actual_hours": 0.0,
                "total_notes": 0,
                "completion_pct": 0.0,
            }

        total = row["total"] or 0
        done_count = row["done_count"] or 0
        completion_pct = (done_count / total * 100.0) if total > 0 else 0.0

        return {
            "total_tasks": total,
            "todo": row["todo_count"] or 0,
            "in_progress": row["ip_count"] or 0,
            "done": done_count,
            "blocked": row["blocked_count"] or 0,
            "total_estimated_hours": float(row["total_est"] or 0),
            "total_actual_hours": float(row["total_actual"] or 0),
            "total_notes": notes_row["cnt"] if notes_row else 0,
            "completion_pct": round(completion_pct, 1),
        }

    # ------------------------------------------------------------------
    # Row converters
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_project(row: dict) -> Project:
        return Project(
            id=row["id"],
            name=row.get("name", ""),
            description=row.get("description", ""),
            status=row.get("status", "planning"),
            created_at=_parse_timestamp(row.get("created_at")) or datetime.now(timezone.utc),
            updated_at=_parse_timestamp(row.get("updated_at")) or datetime.now(timezone.utc),
            target_date=_parse_timestamp(row.get("target_date")),
            goal_id=row.get("goal_id"),
        )

    @staticmethod
    def _row_to_task(row: dict) -> ProjectTask:
        return ProjectTask(
            id=row["id"],
            project_id=row.get("project_id"),
            title=row.get("title", ""),
            description=row.get("description", ""),
            status=row.get("status", "todo"),
            priority=row.get("priority", "medium"),
            assigned_to=row.get("assigned_to"),
            estimated_hours=row.get("estimated_hours"),
            actual_hours=row.get("actual_hours"),
            due_date=_parse_timestamp(row.get("due_date")),
            completed_at=_parse_timestamp(row.get("completed_at")),
        )

    @staticmethod
    def _row_to_note(row: dict) -> ProjectNote:
        return ProjectNote(
            id=row["id"],
            project_id=row.get("project_id"),
            task_id=row.get("task_id"),
            content=row.get("content", ""),
            created_at=row.get("created_at", datetime.now(timezone.utc)),
        )
