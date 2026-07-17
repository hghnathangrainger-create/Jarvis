"""
project_state_show_tool.py

A safe, read-only tool that reports Jarvis's manually-maintained
project-state record (Phase 89, Batch 1): the current branch, latest
closed phase, latest closed commit, latest full test-suite result, and
current focus/next goal - each exactly as Nathan last recorded it via
"update jarvis project state: <field>=<value>", or an honest "not
recorded yet" if never set.

ProjectStateShowTool is a GREEN tool: it only ever reads
ProjectStateStore.get(), never writes anything, never calls git, a
subprocess, or any AI provider, and never fabricates a value for a
field that has not yet been recorded.
"""

from __future__ import annotations

from datetime import datetime

from project_state.project_state_store import ProjectStateStore
from tools.base_tool import BaseTool, ToolRequest, ToolResult

#: Shown for any field, or the last-updated timestamp, that has never
#: been recorded - never a fabricated or guessed value.
_NOT_RECORDED = "not recorded yet"

#: Shown once, right under the header, so every reader sees the same
#: honesty disclosure regardless of which fields happen to be set.
_MANUAL_DISCLOSURE = (
    "Manually maintained by you - never auto-detected from git, a "
    "subprocess, or the filesystem."
)


class ProjectStateShowTool(BaseTool):
    """Reports Jarvis's manually-maintained project-state record.

    Read-only and safe; every value is exactly what Nathan last
    recorded, or an honest "not recorded yet" - nothing here is
    inferred, estimated, or auto-detected.
    """

    def __init__(self, project_state_store: ProjectStateStore) -> None:
        """Initialise the tool with an already-constructed store.

        Args:
            project_state_store: The already-constructed
                ProjectStateStore. Only get() is ever called.
        """
        self._project_state_store = project_state_store

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "project_state_show".
        """
        return "project_state_show"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Reports Jarvis's manually-maintained project-state record "
            "(branch, phase, commit, suite result, focus). Read-only "
            "and safe."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return a fixed, read-only action string for security classification.

        Args:
            request: The request being handled.

        Returns:
            The fixed string "show jarvis project state", classified GREEN.
        """
        return "show jarvis project state"

    def run(self, request: ToolRequest) -> ToolResult:
        """Return the current project-state record, honestly.

        Args:
            request: The request. No input is required.

        Returns:
            A successful ToolResult listing every field's real, stored
            value (or "not recorded yet"), clearly labelled as manually
            maintained. Never fails outright.
        """
        record = self._project_state_store.get()
        branch = record.branch if record else None
        phase = record.phase if record else None
        commit = record.commit if record else None
        suite_result = record.suite_result if record else None
        focus = record.focus if record else None
        last_updated = record.last_updated if record else None

        lines = [
            "Jarvis Project State:",
            _MANUAL_DISCLOSURE,
            "",
            f"  Branch: {self._field(branch)}",
            f"  Phase: {self._field(phase)}",
            f"  Commit: {self._field(commit)}",
            f"  Suite result: {self._field(suite_result)}",
            f"  Focus: {self._field(focus)}",
            f"  Last updated: {self._format_last_updated(last_updated)}",
        ]
        return self.ok("\n".join(lines))

    @staticmethod
    def _field(value: str | None) -> str:
        """Format one field's stored value, or an honest placeholder.

        Args:
            value: The field's stored value, or None if never recorded.

        Returns:
            value if set, otherwise the fixed "not recorded yet" string.
        """
        return value if value else _NOT_RECORDED

    @staticmethod
    def _format_last_updated(value: datetime | None) -> str:
        """Format the record's last-updated timestamp, or an honest placeholder.

        Args:
            value: The stored last_updated timestamp, or None if the
                record has never been written to.

        Returns:
            A "YYYY-MM-DD HH:MM:SS UTC" string, or "not recorded yet".
        """
        if value is None:
            return _NOT_RECORDED
        return f"{value.strftime('%Y-%m-%d %H:%M:%S')} UTC"
