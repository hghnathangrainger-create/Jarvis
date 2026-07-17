"""
project_state_update_tool.py

A guarded tool that updates one field of Jarvis's manually-maintained
project-state record (Phase 89, Batch 1): branch, phase, commit, suite
result (grammar field "suite"), or focus.

ProjectStateUpdateTool is a YELLOW tool. It changes a stored record, so
its action is classified YELLOW and it runs only after explicit
approval through the normal Tool Executor and Approval Manager path.
It never inspects git, a subprocess, or the filesystem to determine a
value itself - every value comes only from what Nathan explicitly
typed in the command.

Supported input (via input_data):
    field: one of "branch", "phase", "commit", "suite", "focus" (required).
    value: the new value, preserved verbatim including internal "=" or
        ":" characters (required, non-empty).

Safety note:
    This tool does not enforce approval itself. Approval is enforced by
    the Tool Executor, which classifies this tool's action ("update
    jarvis project state") as YELLOW and withholds it until an approved
    decision is supplied. A declined action never reaches run(), so
    nothing is changed.
"""

from __future__ import annotations

from project_state.project_state_store import ProjectStateStore
from tools.base_tool import BaseTool, ToolRequest, ToolResult

#: Maps each accepted user-facing grammar field name to the store's own
#: model attribute name - "suite" is the one place these differ (the
#: model/store call it suite_result, matching JarvisBrainStatusTool's/
#: PromptContext's own naming for the same real-world concept).
KNOWN_PROJECT_STATE_FIELDS: dict[str, str] = {
    "branch": "branch",
    "phase": "phase",
    "commit": "commit",
    "suite": "suite_result",
    "focus": "focus",
}


class ProjectStateUpdateTool(BaseTool):
    """Updates one field of the project-state record. Sensitive (YELLOW)."""

    def __init__(self, project_state_store: ProjectStateStore) -> None:
        """Initialise the tool with an already-constructed store.

        Args:
            project_state_store: The already-constructed
                ProjectStateStore used to apply the change.
        """
        self._project_state_store = project_state_store

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "project_state_update".
        """
        return "project_state_update"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Updates one field (branch, phase, commit, suite, focus) of "
            "Jarvis's manually-maintained project-state record. "
            "Sensitive: requires approval."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return a fixed action string for security classification.

        Args:
            request: The request being handled.

        Returns:
            The fixed string "update jarvis project state", classified
            YELLOW regardless of which field or value was given.
        """
        return "update jarvis project state"

    def run(self, request: ToolRequest) -> ToolResult:
        """Apply the requested update to the project-state record.

        Args:
            request: The request. Recognised input keys:
                field: one of "branch", "phase", "commit", "suite",
                    "focus" (required).
                value: the new value (required, non-empty).

        Returns:
            A successful ToolResult confirming the change, or a failed
            result if the field is missing/unknown or the value is
            missing/empty.
        """
        field = request.input_data.get("field")
        if not isinstance(field, str) or not field.strip():
            return self.fail(
                "Updating the project state requires a 'field' - one of: "
                + ", ".join(KNOWN_PROJECT_STATE_FIELDS)
            )

        normalized_field = field.strip().casefold()
        if normalized_field not in KNOWN_PROJECT_STATE_FIELDS:
            return self.fail(
                f"Unknown project-state field: {field!r}. Accepted fields: "
                + ", ".join(KNOWN_PROJECT_STATE_FIELDS)
            )

        value = request.input_data.get("value")
        if not isinstance(value, str) or not value.strip():
            return self.fail(
                f"Updating the '{normalized_field}' field requires a "
                "non-empty 'value'."
            )

        model_field = KNOWN_PROJECT_STATE_FIELDS[normalized_field]
        self._project_state_store.update(model_field, value)

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Updated project state field '{normalized_field}' to: "
                f"{value}\n"
                "(Manually recorded by you - not auto-detected from git, "
                "a subprocess, or the filesystem.)"
            ),
            metadata={
                "operation": "update_project_state",
                "field": normalized_field,
            },
        )
