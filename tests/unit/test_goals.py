"""
test_goals.py

Unit tests for the Jarvis Goals and Milestones system.

Covers:
    - Goal, Milestone, Task models
    - GoalStore (SQLite-backed CRUD, progress, overdue)
    - GoalManager (high-level API, progress reports)
    - GoalCreateTool, GoalProgressTool, TaskCompleteTool

Run with:
    pytest tests/unit/test_goals.py
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from goals.manager import GoalManager
from goals.models import Goal, Milestone, Task
from goals.store import GoalStore
from storage.database import create_session_factory, initialize_database


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
    """Build a GoalStore backed by a fresh in-memory database."""
    return GoalStore(session_factory)


@pytest.fixture()
def manager(store):
    """Build a GoalManager wrapping the store."""
    return GoalManager(store)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_goal_defaults():
    """Goal has sensible defaults."""
    goal = Goal()
    assert goal.id is None
    assert goal.title == ""
    assert goal.status == "active"
    assert goal.priority == "medium"
    assert goal.created_at is not None
    assert goal.target_date is None
    assert goal.completed_at is None


def test_milestone_defaults():
    """Milestone has sensible defaults."""
    ms = Milestone()
    assert ms.id is None
    assert ms.goal_id is None
    assert ms.status == "pending"
    assert ms.due_date is None


def test_task_defaults():
    """Task has sensible defaults."""
    task = Task()
    assert task.id is None
    assert task.milestone_id is None
    assert task.status == "pending"
    assert task.estimated_minutes is None
    assert task.actual_minutes is None


# ---------------------------------------------------------------------------
# GoalStore — Goal CRUD
# ---------------------------------------------------------------------------


def test_store_create_goal(store):
    """Create a goal and retrieve it."""
    goal = store.create_goal(title="Ship v2", description="Release version 2", priority="high")
    assert goal.id is not None
    assert goal.title == "Ship v2"
    assert goal.status == "active"
    assert goal.priority == "high"

    retrieved = store.get_goal(goal.id)
    assert retrieved is not None
    assert retrieved.title == "Ship v2"


def test_store_get_nonexistent_goal(store):
    """Getting a nonexistent goal returns None."""
    assert store.get_goal(99999) is None


def test_store_list_goals(store):
    """List goals returns all, optionally filtered by status."""
    store.create_goal(title="A", priority="low")
    store.create_goal(title="B", priority="high")
    store.complete_goal(store.get_goal(1).id if store.get_goal(1) else 1)

    all_goals = store.list_goals()
    assert len(all_goals) == 2

    active = store.list_goals(status_filter="active")
    assert len(active) == 1
    assert active[0].title == "B"

    completed = store.list_goals(status_filter="completed")
    assert len(completed) == 1


def test_store_update_goal(store):
    """Update changes specific fields."""
    goal = store.create_goal(title="Original")
    updated = store.update_goal(goal.id, {"title": "Updated", "priority": "critical"})
    assert updated is not None
    assert updated.title == "Updated"
    assert updated.priority == "critical"
    assert updated.status == "active"  # unchanged


def test_store_update_nonexistent(store):
    """Updating a nonexistent goal returns None."""
    assert store.update_goal(99999, {"title": "Nope"}) is None


def test_store_delete_goal(store):
    """Delete removes a goal and cascades to milestones/tasks."""
    goal = store.create_goal(title="X")
    ms = store.add_milestone(goal.id, title="M")
    assert ms is not None
    task = store.add_task(ms.id, title="T")
    assert task is not None

    assert store.delete_goal(goal.id) is True
    assert store.get_goal(goal.id) is None
    assert store.get_milestone(ms.id) is None
    assert store.get_task(task.id) is None


def test_store_delete_nonexistent(store):
    """Deleting a nonexistent goal returns False."""
    assert store.delete_goal(99999) is False


def test_store_complete_goal(store):
    """Complete goal sets status and completed_at."""
    goal = store.create_goal(title="X")
    completed = store.complete_goal(goal.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.completed_at is not None


# ---------------------------------------------------------------------------
# GoalStore — Milestones
# ---------------------------------------------------------------------------


def test_store_add_milestone(store):
    """Add a milestone to a goal."""
    goal = store.create_goal(title="G")
    ms = store.add_milestone(goal.id, title="M1", description="First milestone")
    assert ms is not None
    assert ms.goal_id == goal.id
    assert ms.title == "M1"
    assert ms.status == "pending"


def test_store_add_milestone_nonexistent_goal(store):
    """Adding a milestone to a nonexistent goal returns None."""
    assert store.add_milestone(99999, title="M") is None


def test_store_list_milestones(store):
    """List milestones for a goal, in insertion order."""
    goal = store.create_goal(title="G")
    store.add_milestone(goal.id, title="First")
    store.add_milestone(goal.id, title="Second")

    milestones = store.list_milestones(goal.id)
    assert len(milestones) == 2
    assert milestones[0].title == "First"
    assert milestones[1].title == "Second"


def test_store_complete_milestone(store):
    """Complete milestone sets status and completed_at."""
    goal = store.create_goal(title="G")
    ms = store.add_milestone(goal.id, title="M")
    completed = store.complete_milestone(ms.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.completed_at is not None


# ---------------------------------------------------------------------------
# GoalStore — Tasks
# ---------------------------------------------------------------------------


def test_store_add_task(store):
    """Add a task to a milestone."""
    goal = store.create_goal(title="G")
    ms = store.add_milestone(goal.id, title="M")
    task = store.add_task(ms.id, title="T1", estimated_minutes=30)
    assert task is not None
    assert task.milestone_id == ms.id
    assert task.title == "T1"
    assert task.status == "pending"
    assert task.estimated_minutes == 30


def test_store_add_task_nonexistent_milestone(store):
    """Adding a task to a nonexistent milestone returns None."""
    assert store.add_task(99999, title="T") is None


def test_store_complete_task(store):
    """Complete task sets status, completed_at, and actual_minutes."""
    goal = store.create_goal(title="G")
    ms = store.add_milestone(goal.id, title="M")
    task = store.add_task(ms.id, title="T")
    completed = store.complete_task(task.id, actual_minutes=25)
    assert completed is not None
    assert completed.status == "done"
    assert completed.completed_at is not None
    assert completed.actual_minutes == 25


def test_store_complete_task_without_minutes(store):
    """Complete task without actual_minutes preserves existing value."""
    goal = store.create_goal(title="G")
    ms = store.add_milestone(goal.id, title="M")
    task = store.add_task(ms.id, title="T", estimated_minutes=10)
    completed = store.complete_task(task.id)
    assert completed is not None
    assert completed.status == "done"
    assert completed.actual_minutes is None  # not set


# ---------------------------------------------------------------------------
# GoalStore — Progress
# ---------------------------------------------------------------------------


def test_store_get_progress(store):
    """Progress calculation is based on task completion."""
    goal = store.create_goal(title="G")
    ms1 = store.add_milestone(goal.id, title="M1")
    ms2 = store.add_milestone(goal.id, title="M2")

    store.add_task(ms1.id, title="T1")
    store.add_task(ms1.id, title="T2")
    store.add_task(ms2.id, title="T3")

    progress = store.get_progress(goal.id)
    assert progress["total_tasks"] == 3
    assert progress["completed_tasks"] == 0
    assert progress["percentage"] == 0.0
    assert progress["total_milestones"] == 2
    assert progress["completed_milestones"] == 0

    # Complete one task.
    store.complete_task(progress_task_id(store, ms1))
    progress = store.get_progress(goal.id)
    assert progress["completed_tasks"] == 1
    assert abs(progress["percentage"] - 33.33) < 0.1


def test_store_get_progress_all_done(store):
    """100% progress when all tasks are done."""
    goal = store.create_goal(title="G")
    ms = store.add_milestone(goal.id, title="M")
    t1 = store.add_task(ms.id, title="T1")
    t2 = store.add_task(ms.id, title="T2")

    store.complete_task(t1.id)
    store.complete_task(t2.id)

    progress = store.get_progress(goal.id)
    assert progress["percentage"] == 100.0
    assert progress["completed_tasks"] == 2


def test_store_get_progress_empty(store):
    """Progress is 0% when there are no tasks."""
    goal = store.create_goal(title="G")
    progress = store.get_progress(goal.id)
    assert progress["percentage"] == 0.0
    assert progress["total_tasks"] == 0


# ---------------------------------------------------------------------------
# GoalStore — Overdue
# ---------------------------------------------------------------------------


def test_store_get_overdue_items(store):
    """Overdue detection finds past-due milestones and tasks."""
    from datetime import datetime, timedelta, timezone

    goal = store.create_goal(title="G")
    past = datetime.now(timezone.utc) - timedelta(days=1)
    future = datetime.now(timezone.utc) + timedelta(days=1)

    ms_overdue = store.add_milestone(goal.id, title="Overdue", due_date=past)
    ms_ok = store.add_milestone(goal.id, title="OK", due_date=future)
    store.add_task(ms_overdue.id, title="Late task")
    store.add_task(ms_ok.id, title="On-time task")

    items = store.get_overdue_items()
    assert len(items["overdue_milestones"]) == 1
    assert items["overdue_milestones"][0].title == "Overdue"
    assert len(items["overdue_tasks"]) == 1


def test_store_get_overdue_completed_not_included(store):
    """Completed items are not considered overdue."""
    from datetime import datetime, timedelta, timezone

    goal = store.create_goal(title="G")
    past = datetime.now(timezone.utc) - timedelta(days=1)
    ms = store.add_milestone(goal.id, title="Done", due_date=past)
    store.complete_milestone(ms.id)

    items = store.get_overdue_items()
    assert len(items["overdue_milestones"]) == 0


def test_store_get_overdue_abandoned_goals_excluded(store):
    """Goals with 'abandoned' status are excluded from overdue."""
    from datetime import datetime, timedelta, timezone

    goal = store.create_goal(title="G")
    store.update_goal(goal.id, {"status": "abandoned"})
    past = datetime.now(timezone.utc) - timedelta(days=1)
    ms = store.add_milestone(goal.id, title="Abandoned milestone", due_date=past)

    items = store.get_overdue_items()
    assert len(items["overdue_milestones"]) == 0


# ---------------------------------------------------------------------------
# GoalManager
# ---------------------------------------------------------------------------


def test_manager_create_goal(manager):
    """Manager creates a goal."""
    goal = manager.create_goal(title="Ship v2", priority="high")
    assert goal.id is not None
    assert goal.title == "Ship v2"
    assert manager.count() == 1


def test_manager_add_milestone(manager):
    """Manager adds a milestone."""
    goal = manager.create_goal(title="G")
    ms = manager.add_milestone(goal.id, title="M1")
    assert ms is not None
    assert ms.goal_id == goal.id


def test_manager_add_task(manager):
    """Manager adds a task."""
    goal = manager.create_goal(title="G")
    ms = manager.add_milestone(goal.id, title="M")
    task = manager.add_task(ms.id, title="T1", estimated_minutes=15)
    assert task is not None


def test_manager_mark_task_done(manager):
    """Manager marks a task as done."""
    goal = manager.create_goal(title="G")
    ms = manager.add_milestone(goal.id, title="M")
    task = manager.add_task(ms.id, title="T")
    completed = manager.mark_task_done(task.id, actual_minutes=10)
    assert completed is not None
    assert completed.status == "done"


def test_manager_list_active_goals(manager):
    """Manager lists only active goals."""
    manager.create_goal(title="Active")
    goal2 = manager.create_goal(title="Done")
    manager._store.complete_goal(goal2.id)

    active = manager.list_active_goals()
    assert len(active) == 1
    assert active[0].title == "Active"


def test_manager_get_progress_report(manager):
    """Progress report is a human-readable string."""
    goal = manager.create_goal(title="Ship v2", description="Release v2")
    ms = manager.add_milestone(goal.id, title="M1")
    manager.add_task(ms.id, title="T1")

    report = manager.get_progress_report(goal.id)
    assert "Ship v2" in report
    assert "M1" in report
    assert "T1" in report
    assert "0.0%" in report


def test_manager_get_progress_report_nonexistent(manager):
    """Progress report for nonexistent goal returns error message."""
    report = manager.get_progress_report(99999)
    assert "No goal found" in report


def test_manager_get_overdue_items(manager):
    """Manager exposes overdue items."""
    items = manager.get_overdue_items()
    assert "overdue_tasks" in items
    assert "overdue_milestones" in items


def test_manager_delete_goal(manager):
    """Manager deletes a goal."""
    goal = manager.create_goal(title="X")
    assert manager.delete_goal(goal.id) is True
    assert manager.count() == 0


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def test_goal_create_tool(manager):
    """GoalCreateTool creates a goal."""
    from tools.builtin.goal_create_tool import GoalCreateTool
    from tools.base_tool import ToolRequest

    tool = GoalCreateTool(manager)
    result = tool.run(ToolRequest(
        tool_name="goal_create",
        input_data={"title": "Ship v2", "priority": "high"},
    ))
    assert result.success is True
    assert "Ship v2" in result.output
    assert manager.count() == 1


def test_goal_create_tool_missing_title(manager):
    """GoalCreateTool fails without title."""
    from tools.builtin.goal_create_tool import GoalCreateTool
    from tools.base_tool import ToolRequest

    tool = GoalCreateTool(manager)
    result = tool.run(ToolRequest(
        tool_name="goal_create",
        input_data={"description": "No title"},
    ))
    assert result.success is False
    assert "title" in result.error.lower()


def test_goal_create_tool_invalid_date(manager):
    """GoalCreateTool fails with invalid date."""
    from tools.builtin.goal_create_tool import GoalCreateTool
    from tools.base_tool import ToolRequest

    tool = GoalCreateTool(manager)
    result = tool.run(ToolRequest(
        tool_name="goal_create",
        input_data={"title": "G", "target_date": "not-a-date"},
    ))
    assert result.success is False
    assert "target_date" in result.error.lower()


def test_goal_create_tool_invalid_priority(manager):
    """GoalCreateTool falls back to medium for invalid priority."""
    from tools.builtin.goal_create_tool import GoalCreateTool
    from tools.base_tool import ToolRequest

    tool = GoalCreateTool(manager)
    result = tool.run(ToolRequest(
        tool_name="goal_create",
        input_data={"title": "G", "priority": "invalid"},
    ))
    assert result.success is True


def test_goal_progress_tool_list(manager):
    """GoalProgressTool lists goals."""
    from tools.builtin.goal_progress_tool import GoalProgressTool
    from tools.base_tool import ToolRequest

    manager.create_goal(title="A")
    tool = GoalProgressTool(manager)
    result = tool.run(ToolRequest(
        tool_name="goal_progress",
        input_data={"operation": "list"},
    ))
    assert result.success is True
    assert "A" in result.output


def test_goal_progress_tool_report(manager):
    """GoalProgressTool shows progress report."""
    from tools.builtin.goal_progress_tool import GoalProgressTool
    from tools.base_tool import ToolRequest

    goal = manager.create_goal(title="G")
    tool = GoalProgressTool(manager)
    result = tool.run(ToolRequest(
        tool_name="goal_progress",
        input_data={"operation": "report", "goal_id": goal.id},
    ))
    assert result.success is True
    assert "G" in result.output


def test_goal_progress_tool_report_missing_id(manager):
    """GoalProgressTool fails without goal_id for report."""
    from tools.builtin.goal_progress_tool import GoalProgressTool
    from tools.base_tool import ToolRequest

    tool = GoalProgressTool(manager)
    result = tool.run(ToolRequest(
        tool_name="goal_progress",
        input_data={"operation": "report"},
    ))
    assert result.success is False
    assert "goal_id" in result.error.lower()


def test_goal_progress_tool_overdue(manager):
    """GoalProgressTool shows overdue items."""
    from tools.builtin.goal_progress_tool import GoalProgressTool
    from tools.base_tool import ToolRequest

    tool = GoalProgressTool(manager)
    result = tool.run(ToolRequest(
        tool_name="goal_progress",
        input_data={"operation": "overdue"},
    ))
    assert result.success is True


def test_task_complete_tool(manager):
    """TaskCompleteTool marks a task as done."""
    from tools.builtin.task_complete_tool import TaskCompleteTool
    from tools.base_tool import ToolRequest

    goal = manager.create_goal(title="G")
    ms = manager.add_milestone(goal.id, title="M")
    task = manager.add_task(ms.id, title="T")

    tool = TaskCompleteTool(manager)
    result = tool.run(ToolRequest(
        tool_name="task_complete",
        input_data={"task_id": task.id, "actual_minutes": 15},
    ))
    assert result.success is True
    assert "done" in result.output.lower()


def test_task_complete_tool_missing_id(manager):
    """TaskCompleteTool fails without task_id."""
    from tools.builtin.task_complete_tool import TaskCompleteTool
    from tools.base_tool import ToolRequest

    tool = TaskCompleteTool(manager)
    result = tool.run(ToolRequest(
        tool_name="task_complete",
        input_data={},
    ))
    assert result.success is False
    assert "task_id" in result.error.lower()


def test_task_complete_tool_nonexistent(manager):
    """TaskCompleteTool fails for nonexistent task."""
    from tools.builtin.task_complete_tool import TaskCompleteTool
    from tools.base_tool import ToolRequest

    tool = TaskCompleteTool(manager)
    result = tool.run(ToolRequest(
        tool_name="task_complete",
        input_data={"task_id": 99999},
    ))
    assert result.success is False
    assert "No task found" in result.error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def progress_task_id(store, milestone):
    """Find the first task id for a milestone."""
    from sqlalchemy import text
    with store._session_factory() as session:
        row = session.execute(
            text("SELECT id FROM tasks WHERE milestone_id = :mid LIMIT 1"),
            {"mid": milestone.id},
        ).mappings().first()
    return row["id"] if row else None
