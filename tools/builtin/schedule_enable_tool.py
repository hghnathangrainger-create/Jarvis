"""
schedule_enable_tool.py

A guarded tool that re-enables a previously disabled web-search-summary
schedule (Phase 21, Batch 1).

ScheduleEnableTool is a YELLOW tool: re-enabling a schedule resumes
unattended runs, so it is classified YELLOW and runs only after explicit
approval through the normal Tool Executor and Approval Manager path.

This tool does not execute scheduled work, perform a web search, call
AI, or write an Inbox entry - it only flips one boolean flag via
ScheduleStore.enable().
"""

from __future__ import annotations

from scheduling.schedule_store import ScheduleStore
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class ScheduleEnableTool(BaseTool):
    """Re-enables a schedule by id. Sensitive (YELLOW).

    Attributes:
        _schedules: The ScheduleStore used to enable the schedule.
    """

    def __init__(self, schedules: ScheduleStore) -> None:
        """Initialise the tool with a ScheduleStore.

        Args:
            schedules: The store used to enable the schedule.
        """
        self._schedules = schedules

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "schedule_enable".
        """
        return "schedule_enable"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return "Re-enables a schedule by id. Sensitive: requires approval."

    def action_for(self, request: ToolRequest) -> str:
        """Return the action string used for security classification.

        Args:
            request: The request being handled.

        Returns:
            "enable schedule" - classified YELLOW.
        """
        return "enable schedule"

    def run(self, request: ToolRequest) -> ToolResult:
        """Enable a single schedule identified by id.

        Args:
            request: The request. Recognised input keys:
                schedule_id: the id of the schedule to enable (required).

        Returns:
            A successful ToolResult when enabled, or a failed result if
            the id is missing or unknown.
        """
        schedule_id = self._parse_id(request.input_data.get("schedule_id"))
        if schedule_id is None:
            return self.fail(
                "Enabling a schedule requires a valid numeric 'schedule_id'."
            )

        record = self._schedules.enable(schedule_id)
        if record is None:
            return self.fail(f"No schedule found with id {schedule_id}.")

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=f"Enabled schedule {schedule_id}.",
            metadata={"schedule_id": str(schedule_id)},
        )

    @staticmethod
    def _parse_id(raw: object) -> int | None:
        """Parse a schedule id from raw input.

        Args:
            raw: The raw id value, which may be an int or a numeric string.

        Returns:
            The id as an int, or None if it cannot be parsed.
        """
        if isinstance(raw, bool):
            return None
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.strip().isdigit():
            return int(raw.strip())
        return None
