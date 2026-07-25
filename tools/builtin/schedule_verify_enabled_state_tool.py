"""
schedule_verify_enabled_state_tool.py

An internal-only, read-only tool that reports one durable schedule's
current enabled state in a structured (not human-parsed) form (Phase
94, Batch 2 - docs/phase_94_implementation_plan.md, Section 13/14).
Phase 99, Batch 1 (docs/phase_99_second_compound_template_planning.md,
Section 8.1) adds one additive metadata key, "enabled_str" - a
canonical "true"/"false" string mirror of the existing "enabled"
boolean, derived from the exact same observation, needed only so a
future compound template's Step 3 gate (WorkflowEngine's existing,
unmodified, string-only verification-gate primitive) can be evaluated
against this tool's result. The existing "enabled" boolean, and every
existing reader of it, is completely unchanged.

ScheduleVerifyEnabledStateTool exists solely so the "ask jarvis to:
enable schedule <id>" workflow can read back the schedule's real,
durable enabled state as ToolResult.metadata, for exact-boolean-
equality verification - never by parsing ScheduleEnableTool's or
ScheduleListTool's own human-readable output text. It is a GREEN tool:
it only ever reads ScheduleStore.get(), never writes anything, never
calls git, a subprocess, or any AI provider.

This tool is internal-only by convention, enforced in two independent
places, exactly mirroring tools/builtin/project_state_verify_tool.py's
own established pattern:
    - It has no CommandRouter grammar entry anywhere, so it is never
      reachable by a user-typed command.
    - It is marked internal_only=True in
      intelligence/capability_catalog.py's CAPABILITY_CATALOG, and
      intelligence/structured_output.py's parser rejects any AI
      response that names it - it is reachable only as the fixed,
      deterministically-constructed second step of the one
      schedule-enable-and-verify workflow.

It is still registered in ToolRegistry (main.py's own wiring, sharing
the identical, already-constructed ScheduleStore every other schedule
tool uses) so that WorkflowEngine/ToolExecutor can execute and audit
it exactly like any other real tool call - never bypassing that
existing security/audit path, and never observing a different durable
state than the write step it verifies.
"""

from __future__ import annotations

from scheduling.schedule_store import ScheduleStore
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class ScheduleVerifyEnabledStateTool(BaseTool):
    """Reads back one schedule's enabled state as structured metadata,
    for exact-value verification. Internal-only; never a user-facing
    command.

    Read-only and safe; classifies GREEN through the existing, generic
    "show" rule, needing no new SecurityManager rule.
    """

    def __init__(self, schedules: ScheduleStore) -> None:
        """Initialise the tool with an already-constructed store.

        Args:
            schedules: The already-constructed ScheduleStore. Only
                get() is ever called - this tool never writes.
        """
        self._schedules = schedules

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "schedule_verify_enabled_state".
        """
        return "schedule_verify_enabled_state"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Internal-only: reads back one schedule's current enabled "
            "state as structured data, for verifying a prior enable. "
            "Never selectable by AI, never a user command."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return a fixed, read-only action string describing this
        tool's own real behavior for security classification.

        Phase 94, Batch 3: previously reused ScheduleListTool's own
        "list schedules" action string verbatim - but this tool does
        not list schedules; it reads exactly one schedule's enabled
        state. "list schedules" was an inaccurate description, chosen
        only to reuse an already-GREEN rule rather than to honestly
        describe this tool's behavior. "show schedule enabled state"
        is both an honest description of what this tool does and
        classifies GREEN through the existing, generic "show" rule
        (SecurityManager's `_Rule("show", SecurityTier.GREEN, ...)`) -
        so still no new SecurityManager rule is required.

        Args:
            request: The request being handled.

        Returns:
            The fixed string "show schedule enabled state", classified
            GREEN via the existing generic "show" rule.
        """
        return "show schedule enabled state"

    def run(self, request: ToolRequest) -> ToolResult:
        """Return one schedule's current enabled state as structured
        metadata, plus a short, honest human-readable line.

        For data minimization, only the two fields the schedule-enable
        verification workflow actually needs are returned - never
        query, time_of_day, name, or last_run_at, since no concrete
        consumer requires them here.

        Args:
            request: The request. Recognised input key:
                schedule_id: the id of the schedule to read back
                    (required, a real int - always trusted, already-
                    durable input threaded through by the workflow-
                    builder, never a second model-supplied value).

        Returns:
            A successful ToolResult whose metadata carries the real
            "schedule_id" and real "enabled" boolean, or a failed
            result if schedule_id is missing/invalid or no schedule
            exists with that id. Never fails as a side effect of
            reading - only when the target genuinely cannot be found
            or identified.
        """
        schedule_id = self._parse_id(request.input_data.get("schedule_id"))
        if schedule_id is None:
            return self.fail(
                "Verifying a schedule's enabled state requires a valid "
                "numeric 'schedule_id'."
            )

        record = self._schedules.get(schedule_id)
        if record is None:
            return self.fail(f"No schedule found with id {schedule_id}.")

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Schedule {record.id} is currently "
                f"{'enabled' if record.enabled else 'disabled'}."
            ),
            metadata={
                "schedule_id": record.id,
                "enabled": record.enabled,
                # Phase 99, Batch 1 (docs/phase_99_second_compound_template_planning.md,
                # Section 8.1): an additive, canonical string mirror of
                # the same, already-observed "enabled" boolean above -
                # computed from the exact same `record.enabled` value,
                # in this same expression, so the two can never diverge.
                # Needed only because WorkflowEngine's own
                # _verification_gate_failure_reason() (and
                # PlanStep.verification_expected_value) compare a
                # string, never a bool - this key exists solely to
                # satisfy that existing, unmodified, string-only gate
                # for a future compound template; every existing reader
                # of this tool's metadata (verify_schedule_enabled_state(),
                # both schedule enable/disable workflow response
                # translators) continues reading only the unchanged
                # "enabled" boolean above and never this key.
                "enabled_str": "true" if record.enabled else "false",
            },
        )

    @staticmethod
    def _parse_id(raw: object) -> int | None:
        """Parse a schedule id from raw input.

        Mirrors ScheduleEnableTool's/ScheduleDisableTool's own
        established _parse_id exactly, for consistency - though in
        practice this tool only ever receives a real int, already
        threaded through by the trusted workflow-builder from the
        write step's own already-validated tool_input.

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
