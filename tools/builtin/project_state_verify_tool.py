"""
project_state_verify_tool.py

An internal-only, read-only tool that reports Jarvis's manually-
maintained project-state record in a structured (not human-parsed)
form (Phase 90, Batch 3 - Section 24.C.15/26; genericized in Phase 96
- docs/phase_96_implementation_plan.md - to also report "phase",
alongside the original "focus").

ProjectStateVerifyTool exists solely so the "ask jarvis to: update my
project focus to X and confirm it" workflow (and, since Phase 96, the
equivalent "...update my project phase to X..." workflow) can read
back the current focus/phase value as real ToolResult.metadata, for
exact-string-equality verification - never by parsing
ProjectStateShowTool's own human-readable output text. It is a GREEN
tool: it only ever reads ProjectStateStore.get(), never writes
anything, never calls git, a subprocess, or any AI provider.

Reporting both fields unconditionally (rather than accepting a
"which field" input) is a deliberate, minimal choice: this tool takes
no input at all (arguments=() in the catalog), always reads the one
existing singleton row, and ProjectStateShowTool - an equally-
privileged, already-model-selectable capability - already discloses
the entire record (branch, phase, commit, suite_result, focus) today,
so reporting one additional named field here exposes nothing that
capability doesn't already show.

This tool is internal-only by convention, enforced in two independent
places:
    - It has no CommandRouter grammar entry anywhere, so it is never
      reachable by a user-typed command.
    - It is marked internal_only=True in
      intelligence/capability_catalog.py's CAPABILITY_CATALOG, and
      intelligence/structured_output.py's parser rejects any AI
      response that names it - it is reachable only as the fixed,
      deterministically-constructed second step of the one Batch 3
      update-focus workflow.

It is still registered in ToolRegistry (Phase 90, Batch 3's own
main.py wiring) so that WorkflowEngine/ToolExecutor can execute and
audit it exactly like any other real tool call - never bypassing that
existing security/audit path.
"""

from __future__ import annotations

from datetime import datetime

from project_state.project_state_store import ProjectStateStore
from tools.base_tool import BaseTool, ToolRequest, ToolResult

#: Shown for the last-updated timestamp when the record has never been
#: written - mirrors ProjectStateShowTool's own honest placeholder.
_NOT_RECORDED = "not recorded yet"


class ProjectStateVerifyTool(BaseTool):
    """Reads back the project-state record's focus and phase fields as
    structured metadata, for exact-value verification. Internal-only;
    never a user-facing command.

    Read-only and safe; reuses the same GREEN action semantics
    ProjectStateShowTool already established, needing no new
    SecurityManager rule.
    """

    def __init__(self, project_state_store: ProjectStateStore) -> None:
        """Initialise the tool with an already-constructed store.

        Args:
            project_state_store: The already-constructed
                ProjectStateStore. Only get() is ever called - this
                tool never writes.
        """
        self._project_state_store = project_state_store

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "project_state_verify".
        """
        return "project_state_verify"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Internal-only: reads back the current manually-maintained "
            "focus and phase values as structured data, for verifying a "
            "prior update. Never selectable by AI, never a user command."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return the same fixed, read-only action string
        ProjectStateShowTool already uses for security classification.

        Reused deliberately, not duplicated: this is semantically the
        same read-only "report the project-state record" action, so it
        reuses the existing GREEN classification rule instead of
        requiring a new one.

        Args:
            request: The request being handled.

        Returns:
            The fixed string "show jarvis project state", classified
            GREEN.
        """
        return "show jarvis project state"

    def run(self, request: ToolRequest) -> ToolResult:
        """Return the current focus and phase values and last-updated
        timestamp as structured metadata, plus a short, honest
        human-readable line.

        For data minimization, only the fields a real verification
        workflow actually needs are returned - never branch, commit, or
        suite_result, since no concrete consumer requires them here
        (Phase 96 added "phase" alongside the original "focus" once a
        second real consumer, PROJECT_STATE_UPDATE_PHASE, existed - see
        this module's own docstring for why reporting both
        unconditionally introduces no new data exposure).

        Args:
            request: The request. No input is required.

        Returns:
            A successful ToolResult. metadata["focus"] is the real
            stored focus value, or "" if never recorded.
            metadata["phase"] is the real stored phase value, or "" if
            never recorded. metadata["last_updated"] is the real
            formatted timestamp, or "not recorded yet". Never fails
            outright.
        """
        record = self._project_state_store.get()
        focus = record.focus if record and record.focus else ""
        phase = record.phase if record and record.phase else ""
        last_updated = self._format_last_updated(
            record.last_updated if record else None
        )

        output = (
            f"Current focus: {focus or _NOT_RECORDED}; "
            f"current phase: {phase or _NOT_RECORDED} "
            f"(last updated: {last_updated})"
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=output,
            metadata={"focus": focus, "phase": phase, "last_updated": last_updated},
        )

    @staticmethod
    def _format_last_updated(value: datetime | None) -> str:
        """Format the record's last-updated timestamp, or an honest placeholder.

        Args:
            value: The stored last_updated timestamp, or None.

        Returns:
            A "YYYY-MM-DD HH:MM:SS UTC" string, or "not recorded yet".
        """
        if value is None:
            return _NOT_RECORDED
        return f"{value.strftime('%Y-%m-%d %H:%M:%S')} UTC"
