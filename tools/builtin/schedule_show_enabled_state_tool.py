"""
schedule_show_enabled_state_tool.py

A real, public, read-only tool that reports one schedule's current
enabled state by its exact id (Phase 99, Batch 1 -
docs/phase_99_second_compound_template_planning.md, Section 3.6).

Closes a genuine gap in the existing schedule command surface: before
this tool, the only way to check a schedule's state was
`schedule_list`, whose fixed 50-row, ascending-id output cannot
guarantee an arbitrary schedule's presence once more than 50 schedules
exist (see the planning document's Section 3.5 for the full proof).
This tool instead performs a direct primary-key lookup
(`ScheduleStore.get(schedule_id)`), which has no ordering, limit, or
pagination dimension at all - it either finds the exact row or
definitively does not.

ScheduleShowEnabledStateTool is a GREEN tool: read-only, no mutation,
no approval, no verifier call, and no workflow of any kind - a single,
direct store read, exactly mirroring ScheduleVerifyEnabledStateTool's
own read (Phase 94, Batch 2), except this one is genuinely public:
unlike that internal-only sibling, this tool is intended to be shown to
the user as a real result and is reachable through the existing,
unmodified generic "ask jarvis to: <request>" single-capability path -
it is not internal_only, and has its own entry in
intelligence/capability_catalog.py and its own line in
_TRUSTED_PLANNING_INSTRUCTION.

This tool has no CommandRouter grammar entry of its own (Phase 99,
Batch 1 deliberately adds none) - it is reachable only via "ask jarvis
to:", never via a typed deterministic command.
"""

from __future__ import annotations

from scheduling.schedule_store import ScheduleStore
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class ScheduleShowEnabledStateTool(BaseTool):
    """Shows one schedule's current enabled state by its exact id.
    Read-only and safe.

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
            The string "schedule_show_enabled_state".
        """
        return "schedule_show_enabled_state"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Shows whether one schedule, by its exact id, is currently "
            "enabled or disabled. Read-only and safe."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return the action string used for security classification.

        Args:
            request: The request being handled.

        Returns:
            "show schedule enabled state" - classified GREEN via the
            existing, generic "show" rule (the same rule
            ScheduleVerifyEnabledStateTool's own action string already
            classifies through) - no new SecurityManager rule needed.
        """
        return "show schedule enabled state"

    def run(self, request: ToolRequest) -> ToolResult:
        """Report one schedule's current enabled state.

        Args:
            request: The request. Recognised input key:
                schedule_id: the id of the schedule to read (required,
                    an int or a numeric string).

        Returns:
            A successful ToolResult whose output identifies the exact
            schedule id and clearly states "enabled" or "disabled", or
            a failed result (never fabricating "disabled") if
            schedule_id is missing/invalid or no schedule exists with
            that id.
        """
        schedule_id = self._parse_id(request.input_data.get("schedule_id"))
        if schedule_id is None:
            return self.fail(
                "Showing a schedule's enabled state requires a valid "
                "numeric 'schedule_id'."
            )

        record = self._schedules.get(schedule_id)
        if record is None:
            return self.fail(f"No schedule found with id {schedule_id}.")

        state = "enabled" if record.enabled else "disabled"
        return ToolResult(
            tool_name=self.name,
            success=True,
            output=f"Schedule {record.id} is currently {state}.",
            metadata={"schedule_id": record.id, "enabled": record.enabled},
        )

    @staticmethod
    def _parse_id(raw: object) -> int | None:
        """Parse a schedule id from raw input.

        Mirrors ScheduleEnableTool's/ScheduleDisableTool's/
        ScheduleVerifyEnabledStateTool's own established _parse_id
        exactly, for consistency.

        Args:
            raw: The raw id value, which may be an int or a numeric
                string.

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
