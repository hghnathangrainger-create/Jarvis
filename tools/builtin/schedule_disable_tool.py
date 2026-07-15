"""
schedule_disable_tool.py

A guarded tool that disables a web-search-summary schedule (Phase 21,
Batch 1; extended Phase 78, Batch 2 so the success confirmation
identifies the disabled schedule's name (if any), query, and
time_of_day).

ScheduleDisableTool is a YELLOW tool: disabling changes durable state,
so it is classified YELLOW and runs only after explicit approval through
the normal Tool Executor and Approval Manager path, exactly like every
other state-changing tool.

Disabling is the only way to stop a schedule from running - there is no
delete method anywhere in this phase. This tool does not execute
scheduled work, perform a web search, call AI, or write an Inbox entry -
it only flips one boolean flag via ScheduleStore.disable().
"""

from __future__ import annotations

from scheduling.schedule_store import ScheduleStore
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class ScheduleDisableTool(BaseTool):
    """Disables a schedule by id. Sensitive (YELLOW).

    Attributes:
        _schedules: The ScheduleStore used to disable the schedule.
    """

    def __init__(self, schedules: ScheduleStore) -> None:
        """Initialise the tool with a ScheduleStore.

        Args:
            schedules: The store used to disable the schedule.
        """
        self._schedules = schedules

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "schedule_disable".
        """
        return "schedule_disable"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return "Disables a schedule by id. Sensitive: requires approval."

    def action_for(self, request: ToolRequest) -> str:
        """Return the action string used for security classification.

        Args:
            request: The request being handled.

        Returns:
            "disable schedule" - classified YELLOW.
        """
        return "disable schedule"

    def run(self, request: ToolRequest) -> ToolResult:
        """Disable a single schedule identified by id.

        Args:
            request: The request. Recognised input keys:
                schedule_id: the id of the schedule to disable (required).

        Returns:
            A successful ToolResult when disabled, whose output identifies
            the schedule's id, optional name, query, and time_of_day
            (Phase 78, Batch 2), or a failed result if the id is missing
            or unknown.
        """
        schedule_id = self._parse_id(request.input_data.get("schedule_id"))
        if schedule_id is None:
            return self.fail(
                "Disabling a schedule requires a valid numeric 'schedule_id'."
            )

        record = self._schedules.disable(schedule_id)
        if record is None:
            return self.fail(f"No schedule found with id {schedule_id}.")

        label = f" ({record.name})" if record.name else ""
        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Disabled schedule {record.id}{label}: '{record.query}' "
                f"at {record.time_of_day} daily."
            ),
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
