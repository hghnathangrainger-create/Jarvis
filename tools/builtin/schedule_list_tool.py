"""
schedule_list_tool.py

A safe, read-only tool that lists Nathan's configured web-search-summary
schedules (Phase 21, Batch 1; extended Phase 72, Batch 1 with a real,
honest enabled/disabled count in the list header).

ScheduleListTool is a GREEN tool. It only reads from a ScheduleStore and
never creates, enables, disables, claims, or runs anything.
"""

from __future__ import annotations

from scheduling.schedule_store import ScheduleRecord, ScheduleStore
from tools.base_tool import BaseTool, ToolRequest, ToolResult

_DEFAULT_LIMIT = 50


class ScheduleListTool(BaseTool):
    """Lists configured web-search-summary schedules. Read-only and safe.

    Attributes:
        _schedules: The ScheduleStore used for read-only access.
    """

    def __init__(self, schedules: ScheduleStore) -> None:
        """Initialise the tool with a ScheduleStore.

        Args:
            schedules: The store providing read access to schedules.
        """
        self._schedules = schedules

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "schedule_list".
        """
        return "schedule_list"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return "Lists configured web-search-summary schedules. Read-only and safe."

    def action_for(self, request: ToolRequest) -> str:
        """Return the action string used for security classification.

        Args:
            request: The request being handled.

        Returns:
            "list schedules" - classified GREEN via the existing,
            unchanged "list" rule; no new Security Manager rule was
            needed for this tool.
        """
        return "list schedules"

    def run(self, request: ToolRequest) -> ToolResult:
        """List all configured schedules.

        Args:
            request: The request (no recognised input keys).

        Returns:
            A ToolResult containing the formatted schedule list.
        """
        records = self._schedules.list_all(limit=_DEFAULT_LIMIT)
        return self.ok(self._format_many(records))

    @staticmethod
    def _format_many(records: list[ScheduleRecord]) -> str:
        """Format a list of schedules into readable text.

        The header reports a real, honest enabled/disabled count (Phase
        72, Batch 1), tallied from this same already-fetched `records`
        list - no new ScheduleStore method or query is used, and
        schedules are never reordered or re-fetched to compute it.

        Args:
            records: The schedules to format.

        Returns:
            A formatted, multi-line string. Reports when there are none.
        """
        if not records:
            return "Schedules: none configured."
        enabled_count = sum(1 for record in records if record.enabled)
        disabled_count = len(records) - enabled_count
        lines = [f"Schedules ({enabled_count} enabled, {disabled_count} disabled):"]
        for record in records:
            lines.append(ScheduleListTool._format_entry(record))
        return "\n".join(lines)

    @staticmethod
    def _format_entry(record: ScheduleRecord) -> str:
        """Format a single schedule as a compact, complete line.

        Args:
            record: The schedule to format.

        Returns:
            A single-line summary of the schedule.
        """
        label = f" ({record.name})" if record.name else ""
        state = "enabled" if record.enabled else "disabled"
        last_run = (
            record.last_run_at.isoformat(timespec="seconds")
            if record.last_run_at is not None
            else "never"
        )
        return (
            f"  [{record.id}]{label} '{record.query}' at {record.time_of_day} "
            f"daily - {state}, last run: {last_run}"
        )
