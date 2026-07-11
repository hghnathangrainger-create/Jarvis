"""
schedule_create_tool.py

A guarded tool that creates a new daily web-search-summary schedule
(Phase 21, Batch 1).

ScheduleCreateTool is a YELLOW tool: creating a schedule commits Jarvis
to running an unattended action in the future, so it is classified
YELLOW and runs only after explicit approval through the normal Tool
Executor and Approval Manager path, exactly like every other
state-changing tool.

This tool does not execute scheduled work itself. It does not perform a
web search, call AI, or write an Inbox entry - it only validates and
persists one new row via ScheduleStore.create(). The action of actually
running a schedule is implemented by a separate runner, added in a later
batch, which this tool has no dependency on.

Supported input (via input_data):
    query: the search query to run (required).
    time_of_day: the scheduled time, 24-hour "HH:MM" (required).
    name: an optional display label.
"""

from __future__ import annotations

from scheduling.schedule_store import ScheduleStore, ScheduleValidationError
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class ScheduleCreateTool(BaseTool):
    """Creates a new daily web-search-summary schedule. Sensitive (YELLOW)."""

    def __init__(self, schedules: ScheduleStore) -> None:
        """Initialise the tool with a ScheduleStore.

        Args:
            schedules: The store used to persist the new schedule.
        """
        self._schedules = schedules

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "schedule_create".
        """
        return "schedule_create"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Creates a daily web-search-summary schedule. Sensitive: "
            "requires approval. Does not run the search itself."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return the action string used for security classification.

        Args:
            request: The request being handled.

        Returns:
            "schedule web search" - classified YELLOW.
        """
        return "schedule web search"

    def run(self, request: ToolRequest) -> ToolResult:
        """Create one new schedule from the request's query and time.

        Args:
            request: The request. Recognised input keys:
                query: the search query to run (required).
                time_of_day: 24-hour "HH:MM" (required).
                name: an optional display label.

        Returns:
            A successful ToolResult describing the new schedule, or a
            failed result if query/time_of_day are invalid.
        """
        raw_query = request.input_data.get("query")
        raw_time = request.input_data.get("time_of_day")
        raw_name = request.input_data.get("name")

        if not isinstance(raw_query, str) or not raw_query.strip():
            return self.fail("Creating a schedule requires a non-empty 'query'.")
        if not isinstance(raw_time, str) or not raw_time.strip():
            return self.fail(
                "Creating a schedule requires a 'time_of_day' in 24-hour "
                "'HH:MM' format."
            )

        name = raw_name if isinstance(raw_name, str) else None

        try:
            record = self._schedules.create(
                query=raw_query, time_of_day=raw_time, name=name
            )
        except ScheduleValidationError as exc:
            return self.fail(str(exc))

        label = f" ({record.name})" if record.name else ""
        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Created schedule {record.id}{label}: '{record.query}' "
                f"at {record.time_of_day} daily."
            ),
            metadata={"schedule_id": str(record.id)},
        )
