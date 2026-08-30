"""
test_projects.py

Unit tests for the Jarvis Project Management system.

Covers:
    - ProjectStore: CRUD, tasks, notes, stats, overdue, search
    - ProjectManager: high-level methods and reporting
    - ProjectCreateTool: create project, add task, add note
    - ProjectStatusTool: list, status, overdue, search

Run with:
    pytest tests/unit/test_projects.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine

from projects.manager import ProjectManager
from projects.models import Project, ProjectNote, ProjectTask
from projects.store import ProjectStore
from storage.database import create_session_factory, initialize_database
from tools.base_tool import ToolRequest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_factory():
    """Build a session factory backed by an in-memory SQLite database."""
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


@pytest.fixture()
def store(session_factory):
    """Build a ProjectStore backed by a fresh in-memory database."""
    return ProjectStore(session_factory)


@pytest.fixture()
def manager(store):
    """Build a ProjectManager wrapping the store."""
    return ProjectManager(store)


def _utc_now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# ProjectStore tests
# ---------------------------------------------------------------------------


class TestProjectStore:
    """Tests for ProjectStore CRUD and queries."""

    def test_create_and_get_project(self, store):
        """Create a project and retrieve it."""
        project = store.create_project(name="Test Project", description="A test")
        assert project.id is not None
        assert project.name == "Test Project"
        assert project.status == "planning"

        retrieved = store.get_project(project.id)
        assert retrieved is not None
        assert retrieved.name == "Test Project"
        assert retrieved.description == "A test"

    def test_get_nonexistent(self, store):
        """Getting a nonexistent project returns None."""
        assert store.get_project(999) is None

    def test_list_projects(self, store):
        """List returns projects newest first."""
        p1 = store.create_project(name="Alpha")
        p2 = store.create_project(name="Beta")
        projects = store.list_projects()
        assert len(projects) == 2
        assert projects[0].name == "Beta"
        assert projects[1].name == "Alpha"

    def test_list_projects_filtered(self, store):
        """List with status filter works."""
        store.create_project(name="A", status="active")
        store.create_project(name="B", status="planning")
        store.create_project(name="C", status="active")
        active = store.list_projects(status_filter="active")
        assert len(active) == 2

    def test_update_project(self, store):
        """Update specific fields."""
        p = store.create_project(name="Original")
        updated = store.update_project(p.id, {"name": "Updated", "status": "active"})
        assert updated.name == "Updated"
        assert updated.status == "active"

    def test_update_nonexistent(self, store):
        """Updating nonexistent returns None."""
        assert store.update_project(999, {"name": "X"}) is None

    def test_archive_project(self, store):
        """Archive sets status to 'archived'."""
        p = store.create_project(name="To Archive")
        archived = store.archive_project(p.id)
        assert archived.status == "archived"

    def test_delete_project(self, store):
        """Delete removes the project."""
        p = store.create_project(name="Delete Me")
        assert store.delete_project(p.id) is True
        assert store.get_project(p.id) is None

    def test_delete_nonexistent(self, store):
        """Deleting nonexistent returns False."""
        assert store.delete_project(999) is False

    def test_goal_id_linking(self, store):
        """Projects can be linked to goals."""
        p = store.create_project(name="Linked", goal_id=42)
        assert p.goal_id == 42
        retrieved = store.get_project(p.id)
        assert retrieved.goal_id == 42

    def test_target_date(self, store):
        """Projects can have target dates."""
        target = datetime(2026, 12, 31, tzinfo=timezone.utc)
        p = store.create_project(name="Dated", target_date=target)
        assert p.target_date == target


# ---------------------------------------------------------------------------
# Task tests
# ---------------------------------------------------------------------------


class TestProjectTasks:
    """Tests for project task management."""

    def test_add_and_get_task(self, store):
        """Add a task to a project and retrieve it."""
        p = store.create_project(name="P")
        task = store.add_task(p.id, title="Build feature", priority="high")
        assert task.id is not None
        assert task.project_id == p.id
        assert task.title == "Build feature"
        assert task.priority == "high"
        assert task.status == "todo"

    def test_add_task_nonexistent_project(self, store):
        """Adding a task to a nonexistent project returns None."""
        assert store.add_task(999, title="Orphan") is None

    def test_list_tasks(self, store):
        """List returns tasks in order."""
        p = store.create_project(name="P")
        store.add_task(p.id, title="First")
        store.add_task(p.id, title="Second")
        tasks = store.list_tasks(p.id)
        assert len(tasks) == 2
        assert tasks[0].title == "First"
        assert tasks[1].title == "Second"

    def test_update_task_status(self, store):
        """Update task status."""
        p = store.create_project(name="P")
        task = store.add_task(p.id, title="Do it")
        updated = store.update_task_status(task.id, "in_progress")
        assert updated.status == "in_progress"

    def test_update_task_done_sets_completed_at(self, store):
        """Setting status to 'done' sets completed_at."""
        p = store.create_project(name="P")
        task = store.add_task(p.id, title="Done task")
        updated = store.update_task_status(task.id, "done")
        assert updated.status == "done"
        assert updated.completed_at is not None

    def test_update_task_with_actual_hours(self, store):
        """Update with actual hours."""
        p = store.create_project(name="P")
        task = store.add_task(p.id, title="Timed", estimated_hours=5.0)
        updated = store.update_task_status(task.id, "done", actual_hours=3.5)
        assert updated.actual_hours == 3.5

    def test_update_task_nonexistent(self, store):
        """Updating nonexistent task returns None."""
        assert store.update_task_status(999, "done") is None

    def test_search_tasks(self, store):
        """Search finds tasks by title."""
        p = store.create_project(name="P")
        store.add_task(p.id, title="Implement auth")
        store.add_task(p.id, title="Write tests")
        store.add_task(p.id, title="Deploy to prod")

        results = store.search_tasks("auth")
        assert len(results) == 1
        assert results[0].title == "Implement auth"

    def test_search_tasks_empty_query(self, store):
        """Empty query returns nothing."""
        p = store.create_project(name="P")
        store.add_task(p.id, title="Something")
        assert store.search_tasks("") == []
        assert store.search_tasks("  ") == []

    def test_search_by_description(self, store):
        """Search also checks description."""
        p = store.create_project(name="P")
        store.add_task(p.id, title="Task A", description="Use pytest")
        results = store.search_tasks("pytest")
        assert len(results) == 1

    def test_get_task(self, store):
        """Get single task by id."""
        p = store.create_project(name="P")
        task = store.add_task(p.id, title="Get me")
        retrieved = store.get_task(task.id)
        assert retrieved is not None
        assert retrieved.title == "Get me"

    def test_get_task_nonexistent(self, store):
        """Getting nonexistent task returns None."""
        assert store.get_task(999) is None


# ---------------------------------------------------------------------------
# Note tests
# ---------------------------------------------------------------------------


class TestProjectNotes:
    """Tests for project notes."""

    def test_add_and_list_notes(self, store):
        """Add a note and list it."""
        p = store.create_project(name="P")
        note = store.add_note(p.id, content="Meeting notes")
        assert note.id is not None
        assert note.content == "Meeting notes"
        assert note.project_id == p.id

        notes = store.list_notes(p.id)
        assert len(notes) == 1
        assert notes[0].content == "Meeting notes"

    def test_add_note_with_task(self, store):
        """Notes can be attached to tasks."""
        p = store.create_project(name="P")
        task = store.add_task(p.id, title="Task")
        note = store.add_note(p.id, content="Note on task", task_id=task.id)
        assert note.task_id == task.id

    def test_add_note_nonexistent_project(self, store):
        """Adding a note to nonexistent project returns None."""
        assert store.add_note(999, content="Lost") is None

    def test_list_notes_newest_first(self, store):
        """Notes are returned newest first."""
        p = store.create_project(name="P")
        store.add_note(p.id, content="First")
        store.add_note(p.id, content="Second")
        notes = store.list_notes(p.id)
        assert notes[0].content == "Second"
        assert notes[1].content == "First"


# ---------------------------------------------------------------------------
# Stats tests
# ---------------------------------------------------------------------------


class TestProjectStats:
    """Tests for project statistics calculation."""

    def test_stats_empty_project(self, store):
        """Stats for project with no tasks."""
        p = store.create_project(name="Empty")
        stats = store.get_project_stats(p.id)
        assert stats["total_tasks"] == 0
        assert stats["completion_pct"] == 0.0
        assert stats["total_notes"] == 0

    def test_stats_with_tasks(self, store):
        """Stats reflect task statuses."""
        p = store.create_project(name="P")
        t1 = store.add_task(p.id, title="A", estimated_hours=2.0)
        t2 = store.add_task(p.id, title="B", estimated_hours=3.0)
        t3 = store.add_task(p.id, title="C")
        store.update_task_status(t1.id, "done", actual_hours=1.5)
        store.update_task_status(t2.id, "in_progress")

        stats = store.get_project_stats(p.id)
        assert stats["total_tasks"] == 3
        assert stats["done"] == 1
        assert stats["in_progress"] == 1
        assert stats["todo"] == 1
        assert stats["total_estimated_hours"] == 5.0
        assert stats["total_actual_hours"] == 1.5
        assert stats["completion_pct"] == pytest.approx(33.3, abs=0.1)

    def test_stats_with_notes(self, store):
        """Stats count notes."""
        p = store.create_project(name="P")
        store.add_note(p.id, content="Note 1")
        store.add_note(p.id, content="Note 2")
        stats = store.get_project_stats(p.id)
        assert stats["total_notes"] == 2


# ---------------------------------------------------------------------------
# Overdue tests
# ---------------------------------------------------------------------------


class TestOverdueDetection:
    """Tests for overdue task detection."""

    def test_overdue_task_detected(self, store):
        """Past-due, non-done tasks are overdue."""
        p = store.create_project(name="P", status="active")
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        task = store.add_task(p.id, title="Late", due_date=yesterday)
        overdue = store.get_overdue_tasks()
        assert len(overdue) == 1
        assert overdue[0].id == task.id

    def test_done_task_not_overdue(self, store):
        """Completed tasks are not overdue."""
        p = store.create_project(name="P", status="active")
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        task = store.add_task(p.id, title="Done late", due_date=yesterday)
        store.update_task_status(task.id, "done")
        assert len(store.get_overdue_tasks()) == 0

    def test_future_task_not_overdue(self, store):
        """Future-due tasks are not overdue."""
        p = store.create_project(name="P", status="active")
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        store.add_task(p.id, title="On time", due_date=tomorrow)
        assert len(store.get_overdue_tasks()) == 0

    def test_archived_project_not_overdue(self, store):
        """Tasks in archived/completed projects are not overdue."""
        p = store.create_project(name="P", status="archived")
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        store.add_task(p.id, title="Old", due_date=yesterday)
        assert len(store.get_overdue_tasks()) == 0


# ---------------------------------------------------------------------------
# ProjectManager tests
# ---------------------------------------------------------------------------


class TestProjectManager:
    """Tests for ProjectManager high-level methods."""

    def test_create_and_report(self, manager):
        """Create a project and generate a report."""
        project = manager.create_project(name="Test", description="A test project")
        report = manager.get_project_report(project.id)
        assert "Test" in report
        assert "planning" in report

    def test_report_nonexistent(self, manager):
        """Report for nonexistent project returns error message."""
        report = manager.get_project_report(999)
        assert "No project found" in report

    def test_report_with_tasks(self, manager):
        """Report includes tasks."""
        project = manager.create_project(name="P")
        manager.add_task(project.id, title="Task 1", priority="high")
        manager.add_task(project.id, title="Task 2")
        report = manager.get_project_report(project.id)
        assert "Task 1" in report
        assert "Task 2" in report

    def test_report_with_goal_link(self, manager):
        """Report shows goal link."""
        project = manager.create_project(name="P", goal_id=7)
        report = manager.get_project_report(project.id)
        assert "Goal: #7" in report

    def test_count(self, manager):
        """Count returns total projects."""
        assert manager.count() == 0
        manager.create_project(name="A")
        manager.create_project(name="B")
        assert manager.count() == 2

    def test_count_filtered(self, manager):
        """Count with status filter."""
        manager.create_project(name="A", status="active")
        manager.create_project(name="B", status="planning")
        assert manager.count(status_filter="active") == 1


# ---------------------------------------------------------------------------
# ProjectCreateTool tests
# ---------------------------------------------------------------------------


class TestProjectCreateTool:
    """Tests for ProjectCreateTool."""

    def _make_tool(self, manager):
        from tools.builtin.project_create_tool import ProjectCreateTool
        return ProjectCreateTool(manager)

    def test_name_and_description(self, manager):
        tool = self._make_tool(manager)
        assert tool.name == "project_create"
        assert "project" in tool.description.lower()

    def test_create_project(self, manager):
        tool = self._make_tool(manager)
        result = tool.run(ToolRequest(
            tool_name="project_create",
            input_data={"action": "create_project", "name": "My Project"},
        ))
        assert result.success is True
        assert "My Project" in result.output

    def test_create_project_no_name(self, manager):
        tool = self._make_tool(manager)
        result = tool.run(ToolRequest(
            tool_name="project_create",
            input_data={"action": "create_project"},
        ))
        assert result.success is False

    def test_add_task(self, manager):
        tool = self._make_tool(manager)
        project = manager.create_project(name="P")
        result = tool.run(ToolRequest(
            tool_name="project_create",
            input_data={
                "action": "add_task",
                "project_id": project.id,
                "title": "Do stuff",
                "priority": "high",
            },
        ))
        assert result.success is True
        assert "Do stuff" in result.output

    def test_add_task_no_title(self, manager):
        tool = self._make_tool(manager)
        project = manager.create_project(name="P")
        result = tool.run(ToolRequest(
            tool_name="project_create",
            input_data={"action": "add_task", "project_id": project.id},
        ))
        assert result.success is False

    def test_add_task_nonexistent_project(self, manager):
        tool = self._make_tool(manager)
        result = tool.run(ToolRequest(
            tool_name="project_create",
            input_data={"action": "add_task", "project_id": 999, "title": "X"},
        ))
        assert result.success is False

    def test_add_note(self, manager):
        tool = self._make_tool(manager)
        project = manager.create_project(name="P")
        result = tool.run(ToolRequest(
            tool_name="project_create",
            input_data={
                "action": "add_note",
                "project_id": project.id,
                "content": "Some notes",
            },
        ))
        assert result.success is True

    def test_add_note_no_content(self, manager):
        tool = self._make_tool(manager)
        project = manager.create_project(name="P")
        result = tool.run(ToolRequest(
            tool_name="project_create",
            input_data={"action": "add_note", "project_id": project.id},
        ))
        assert result.success is False

    def test_unknown_action(self, manager):
        tool = self._make_tool(manager)
        result = tool.run(ToolRequest(
            tool_name="project_create",
            input_data={"action": "bogus"},
        ))
        assert result.success is False


# ---------------------------------------------------------------------------
# ProjectStatusTool tests
# ---------------------------------------------------------------------------


class TestProjectStatusTool:
    """Tests for ProjectStatusTool."""

    def _make_tool(self, manager):
        from tools.builtin.project_status_tool import ProjectStatusTool
        return ProjectStatusTool(manager)

    def test_name_and_description(self, manager):
        tool = self._make_tool(manager)
        assert tool.name == "project_status"
        assert "project" in tool.description.lower()

    def test_list_empty(self, manager):
        tool = self._make_tool(manager)
        result = tool.run(ToolRequest(tool_name="project_status", input_data={}))
        assert result.success is True
        assert "No projects" in result.output

    def test_list_with_projects(self, manager):
        manager.create_project(name="Alpha")
        manager.create_project(name="Beta")
        tool = self._make_tool(manager)
        result = tool.run(ToolRequest(tool_name="project_status", input_data={}))
        assert result.success is True
        assert "Alpha" in result.output
        assert "Beta" in result.output

    def test_project_status(self, manager):
        project = manager.create_project(name="P")
        manager.add_task(project.id, title="Task 1")
        tool = self._make_tool(manager)
        result = tool.run(ToolRequest(
            tool_name="project_status",
            input_data={"action": "status", "project_id": project.id},
        ))
        assert result.success is True
        assert "P" in result.output

    def test_project_status_no_id(self, manager):
        tool = self._make_tool(manager)
        result = tool.run(ToolRequest(
            tool_name="project_status",
            input_data={"action": "status"},
        ))
        assert result.success is False

    def test_overdue_empty(self, manager):
        tool = self._make_tool(manager)
        result = tool.run(ToolRequest(
            tool_name="project_status",
            input_data={"action": "overdue"},
        ))
        assert result.success is True
        assert "No overdue" in result.output

    def test_overdue_with_tasks(self, manager):
        project = manager.create_project(name="P", status="active")
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        manager.add_task(project.id, title="Late", due_date=yesterday)
        tool = self._make_tool(manager)
        result = tool.run(ToolRequest(
            tool_name="project_status",
            input_data={"action": "overdue"},
        ))
        assert result.success is True
        assert "Late" in result.output

    def test_search_tasks(self, manager):
        project = manager.create_project(name="P")
        manager.add_task(project.id, title="Implement auth")
        manager.add_task(project.id, title="Write docs")
        tool = self._make_tool(manager)
        result = tool.run(ToolRequest(
            tool_name="project_status",
            input_data={"action": "search", "query": "auth"},
        ))
        assert result.success is True
        assert "Implement auth" in result.output

    def test_search_no_query(self, manager):
        tool = self._make_tool(manager)
        result = tool.run(ToolRequest(
            tool_name="project_status",
            input_data={"action": "search"},
        ))
        assert result.success is False

    def test_unknown_action(self, manager):
        tool = self._make_tool(manager)
        result = tool.run(ToolRequest(
            tool_name="project_status",
            input_data={"action": "bogus"},
        ))
        assert result.success is False
