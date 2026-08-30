"""
project_create_tool.py

A YELLOW tool that creates projects and adds tasks/notes in the
Jarvis Project Management system.

YELLOW because it modifies durable state (creates projects, tasks,
notes), requiring user confirmation before execution.

Supported operations (via the 'action' input):
    - "create_project": Create a new project.
    - "add_task": Add a task to a project.
    - "add_note": Add a note to a project.
"""

from __future__ import annotations

from datetime import datetime, timezone

from projects.manager import ProjectManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class ProjectCreateTool(BaseTool):
    """Creates projects, tasks, and notes in the Project Management system.

    Attributes:
        _manager: The ProjectManager providing write access.
    """

    def __init__(self, manager: ProjectManager) -> None:
        """Initialise the tool with a ProjectManager.

        Args:
            manager: The ProjectManager providing write access.
        """
        self._manager = manager

    @property
    def name(self) -> str:
        return "project_create"

    @property
    def description(self) -> str:
        return "Create projects, add tasks and notes to the project management system."

    def run(self, request: ToolRequest) -> ToolResult:
        """Handle a project management write request.

        Args:
            request: The request with input_data containing:
                - action (str): "create_project", "add_task", or "add_note".
                - Other fields depend on the action.

        Returns:
            A ToolResult with confirmation or error.
        """
        action = str(request.input_data.get("action", "create_project")).strip().lower()

        if action == "create_project":
            return self._create_project(request)
        elif action == "add_task":
            return self._add_task(request)
        elif action == "add_note":
            return self._add_note(request)
        else:
            return self.fail(
                f"Unknown action '{action}'. Use 'create_project', 'add_task', or 'add_note'."
            )

    def _create_project(self, request: ToolRequest) -> ToolResult:
        """Create a new project."""
        name = str(request.input_data.get("name", "")).strip()
        if not name:
            return self.fail("No project name provided. Usage: name='My Project'")

        description = str(request.input_data.get("description", "") or "").strip()
        status = str(request.input_data.get("status", "planning") or "planning").strip().lower()
        if status not in ("planning", "active", "paused", "completed", "archived"):
            status = "planning"

        target_date = None
        raw_date = request.input_data.get("target_date")
        if isinstance(raw_date, str) and raw_date.strip():
            try:
                target_date = datetime.fromisoformat(raw_date.strip()).replace(
                    tzinfo=timezone.utc
                )
            except (ValueError, TypeError):
                return self.fail(
                    f"Invalid target_date format: '{raw_date}'. Use ISO format."
                )

        goal_id = None
        raw_goal = request.input_data.get("goal_id")
        if raw_goal is not None:
            try:
                goal_id = int(raw_goal)
            except (ValueError, TypeError):
                return self.fail(f"Invalid goal_id: '{raw_goal}'. Must be an integer.")

        project = self._manager.create_project(
            name=name,
            description=description,
            status=status,
            target_date=target_date,
            goal_id=goal_id,
        )

        goal_str = f", linked to goal #{goal_id}" if goal_id else ""
        target_str = f", target: {target_date.strftime('%Y-%m-%d')}" if target_date else ""

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Created project [{project.id}]: {project.name} "
                f"(status: {project.status}{target_str}{goal_str})"
            ),
            metadata={"operation": "create_project", "project_id": str(project.id)},
        )

    def _add_task(self, request: ToolRequest) -> ToolResult:
        """Add a task to a project."""
        project_id = request.input_data.get("project_id")
        if project_id is None:
            return self.fail("No project_id provided. Usage: project_id=1")
        try:
            project_id = int(project_id)
        except (ValueError, TypeError):
            return self.fail(f"Invalid project_id: '{project_id}'")

        title = str(request.input_data.get("title", "")).strip()
        if not title:
            return self.fail("No task title provided. Usage: title='Implement feature'")

        description = str(request.input_data.get("description", "") or "").strip()
        priority = str(request.input_data.get("priority", "medium") or "medium").strip().lower()
        if priority not in ("low", "medium", "high", "critical"):
            priority = "medium"

        assigned_to = request.input_data.get("assigned_to")
        if assigned_to is not None:
            assigned_to = str(assigned_to).strip() or None

        estimated_hours = None
        raw_hours = request.input_data.get("estimated_hours")
        if raw_hours is not None:
            try:
                estimated_hours = float(raw_hours)
            except (ValueError, TypeError):
                return self.fail(f"Invalid estimated_hours: '{raw_hours}'")

        due_date = None
        raw_due = request.input_data.get("due_date")
        if isinstance(raw_due, str) and raw_due.strip():
            try:
                due_date = datetime.fromisoformat(raw_due.strip()).replace(
                    tzinfo=timezone.utc
                )
            except (ValueError, TypeError):
                return self.fail(f"Invalid due_date format: '{raw_due}'. Use ISO format.")

        task = self._manager.add_task(
            project_id=project_id,
            title=title,
            description=description,
            priority=priority,
            assigned_to=assigned_to,
            estimated_hours=estimated_hours,
            due_date=due_date,
        )

        if task is None:
            return self.fail(f"Project {project_id} not found.")

        assignee_str = f", assigned to {assigned_to}" if assigned_to else ""
        hours_str = f", est. {estimated_hours}h" if estimated_hours else ""

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Added task [{task.id}] to project {project_id}: {task.title} "
                f"(priority: {task.priority}{assignee_str}{hours_str})"
            ),
            metadata={"operation": "add_task", "task_id": str(task.id)},
        )

    def _add_note(self, request: ToolRequest) -> ToolResult:
        """Add a note to a project."""
        project_id = request.input_data.get("project_id")
        if project_id is None:
            return self.fail("No project_id provided. Usage: project_id=1")
        try:
            project_id = int(project_id)
        except (ValueError, TypeError):
            return self.fail(f"Invalid project_id: '{project_id}'")

        content = str(request.input_data.get("content", "")).strip()
        if not content:
            return self.fail("No note content provided. Usage: content='Meeting notes...'")

        task_id = None
        raw_task = request.input_data.get("task_id")
        if raw_task is not None:
            try:
                task_id = int(raw_task)
            except (ValueError, TypeError):
                return self.fail(f"Invalid task_id: '{raw_task}'")

        note = self._manager.add_note(
            project_id=project_id,
            content=content,
            task_id=task_id,
        )

        if note is None:
            return self.fail(f"Project {project_id} not found.")

        task_str = f" (task #{task_id})" if task_id else ""

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=f"Added note [{note.id}] to project {project_id}{task_str}.",
            metadata={"operation": "add_note", "note_id": str(note.id)},
        )
