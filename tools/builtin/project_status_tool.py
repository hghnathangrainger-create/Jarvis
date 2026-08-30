"""
project_status_tool.py

A GREEN tool that views project status, stats, and overdue tasks
in the Jarvis Project Management system.

GREEN because it is read-only — never mutates any state.

Supported operations (via the 'action' input):
    - "list": List all projects (default).
    - "status": Show details and stats for a specific project.
    - "overdue": Show all overdue tasks across projects.
    - "search": Search tasks by query string.
"""

from __future__ import annotations

from projects.manager import ProjectManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class ProjectStatusTool(BaseTool):
    """Views project status, stats, and overdue tasks.

    Attributes:
        _manager: The ProjectManager providing read access.
    """

    def __init__(self, manager: ProjectManager) -> None:
        """Initialise the tool with a ProjectManager.

        Args:
            manager: The ProjectManager providing read access.
        """
        self._manager = manager

    @property
    def name(self) -> str:
        return "project_status"

    @property
    def description(self) -> str:
        return "View project status, stats, overdue tasks, and search tasks."

    def run(self, request: ToolRequest) -> ToolResult:
        """Handle a project status query.

        Args:
            request: The request with input_data containing:
                - action (str): "list", "status", "overdue", or "search".
                - project_id (int): Required for "status".
                - query (str): Required for "search".

        Returns:
            A ToolResult with formatted project data.
        """
        action = str(request.input_data.get("action", "list")).strip().lower()

        if action == "list":
            return self._list_projects()
        elif action == "status":
            return self._project_status(request)
        elif action == "overdue":
            return self._overdue_tasks()
        elif action == "search":
            return self._search_tasks(request)
        else:
            return self.fail(
                f"Unknown action '{action}'. Use 'list', 'status', 'overdue', or 'search'."
            )

    def _list_projects(self) -> ToolResult:
        """List all projects."""
        projects = self._manager.list_projects()
        if not projects:
            return self.ok("No projects found.")

        lines = [f"Projects ({len(projects)}):", ""]
        for p in projects:
            stats = self._manager.get_project_stats(p.id)
            goal_str = f" [goal #{p.goal_id}]" if p.goal_id else ""
            lines.append(
                f"  [{p.id}] {p.name} ({p.status}){goal_str}"
            )
            lines.append(
                f"    {stats['done']}/{stats['total_tasks']} tasks "
                f"({stats['completion_pct']}%)"
            )
            if p.target_date:
                lines.append(f"    Target: {p.target_date.strftime('%Y-%m-%d')}")
            lines.append("")

        return self.ok("\n".join(lines))

    def _project_status(self, request: ToolRequest) -> ToolResult:
        """Show detailed status for a specific project."""
        project_id = request.input_data.get("project_id")
        if project_id is None:
            return self.fail("No project_id provided. Usage: project_id=1")
        try:
            project_id = int(project_id)
        except (ValueError, TypeError):
            return self.fail(f"Invalid project_id: '{project_id}'")

        report = self._manager.get_project_report(project_id)
        return self.ok(report)

    def _overdue_tasks(self) -> ToolResult:
        """Show all overdue tasks across projects."""
        tasks = self._manager.get_overdue_tasks()
        if not tasks:
            return self.ok("No overdue tasks. All on track!")

        lines = [f"Overdue Tasks ({len(tasks)}):", ""]
        for t in tasks:
            due_str = t.due_date.strftime("%Y-%m-%d") if t.due_date else "unknown"
            project = self._manager.get_project(t.project_id)
            project_name = project.name if project else f"#{t.project_id}"
            lines.append(
                f"  [{t.id}] {t.title} (project: {project_name}, "
                f"due: {due_str}, status: {t.status})"
            )

        return self.ok("\n".join(lines))

    def _search_tasks(self, request: ToolRequest) -> ToolResult:
        """Search tasks by query string."""
        query = str(request.input_data.get("query", "")).strip()
        if not query:
            return self.fail("No query provided. Usage: query='feature'")

        tasks = self._manager.search_tasks(query)
        if not tasks:
            return self.ok(f"No tasks matching '{query}'.")

        lines = [f"Tasks matching '{query}' ({len(tasks)}):", ""]
        for t in tasks:
            project = self._manager.get_project(t.project_id)
            project_name = project.name if project else f"#{t.project_id}"
            lines.append(
                f"  [{t.id}] {t.title} (project: {project_name}, "
                f"status: {t.status}, priority: {t.priority})"
            )

        return self.ok("\n".join(lines))
