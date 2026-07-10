"""
workflow_history_tool.py

A safe, read-only tool that shows durable workflow lifecycle history
(Durable Workflow Lifecycle Foundation - a prerequisite turn, not a
numbered phase).

WorkflowHistoryTool is a GREEN tool. It only reads from a
WorkflowHistoryStore and never starts, resumes, pauses, or executes
anything. It has no operation and no input field that names a tool or
carries tool input for a past workflow, so nothing this tool shows can
ever be replayed or resumed - see workflow_history_store.py for why that
boundary is deliberate.

Supported operations (via the 'operation' input):
    - "history": the most recent transitions across all workflows
      (default).
    - "recent":  the last 10 transitions across all workflows.
    - "get":     one workflow's full transition history, oldest first, by
      'workflow_id'.
"""

from __future__ import annotations

from tools.base_tool import BaseTool, ToolRequest, ToolResult
from workflow.workflow_history_store import WorkflowHistoryRecord, WorkflowHistoryStore

_DEFAULT_LIMIT = 20
_RECENT_LIMIT = 10


class WorkflowHistoryTool(BaseTool):
    """Shows durable, read-only workflow lifecycle history.

    Attributes:
        _history: The WorkflowHistoryStore used for read-only access.
    """

    def __init__(self, history_store: WorkflowHistoryStore) -> None:
        """Initialise the tool with a WorkflowHistoryStore.

        Args:
            history_store: The store providing read access to workflow
                lifecycle history.
        """
        self._history = history_store

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "workflow_history".
        """
        return "workflow_history"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Shows durable workflow lifecycle history (started, step "
            "transitions, waiting, completed, stopped). Read-only and safe."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return an honest action string for security classification.

        Every operation this tool supports is a read. The Security Manager
        classifies both action strings below GREEN via its existing,
        unchanged "show" rule - no new Security Manager rule was needed
        or added for this tool.

        Args:
            request: The request being handled.

        Returns:
            An action string describing the operation.
        """
        operation = str(
            request.input_data.get("operation", "history")
        ).strip().lower()
        if operation == "recent":
            return "show recent workflows"
        if operation == "get":
            return "show workflow details"
        return "show workflow history"

    def run(self, request: ToolRequest) -> ToolResult:
        """Show workflow history according to the requested operation.

        Args:
            request: The request. Recognised input keys:
                operation: "history" (default) or "recent" or "get".
                workflow_id: the workflow id, required when operation is
                    "get".

        Returns:
            A ToolResult containing the formatted history, or a failed
            result if "get" is requested without a workflow_id, finds
            nothing, or the operation is unrecognised.
        """
        operation = str(
            request.input_data.get("operation", "history")
        ).strip().lower()

        if operation == "get":
            return self._run_get(request)

        if operation == "recent":
            records = self._history.list_recent(limit=_RECENT_LIMIT)
            return self.ok(self._format_many(records, "Recent workflows"))

        if operation == "history":
            records = self._history.list_recent(limit=_DEFAULT_LIMIT)
            return self.ok(self._format_many(records, "Workflow history"))

        return self.fail(
            f"Unknown operation '{operation}'. Use 'history', 'recent', or 'get'."
        )

    def _run_get(self, request: ToolRequest) -> ToolResult:
        """Handle the "get" operation: show one workflow's full history.

        Args:
            request: The request carrying the 'workflow_id' to look up.

        Returns:
            A ToolResult with the formatted transitions, or a failure when
            workflow_id is missing or nothing is found for it.
        """
        workflow_id = request.input_data.get("workflow_id")
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            return self.fail(
                "Showing a single workflow's history requires a 'workflow_id'."
            )
        records = self._history.list_for_workflow(workflow_id.strip())
        if not records:
            return self.fail(
                f"No workflow history found for id '{workflow_id.strip()}'."
            )
        return self.ok(self._format_workflow(workflow_id.strip(), records))

    @staticmethod
    def _format_many(
        records: list[WorkflowHistoryRecord], header: str
    ) -> str:
        """Format a list of history records into readable text.

        Args:
            records: The history records to format.
            header: A header line describing the result set.

        Returns:
            A formatted, multi-line string. Reports when there are no
            results.
        """
        if not records:
            return f"{header}: none found."
        lines = [f"{header}:"]
        for record in records:
            lines.append(WorkflowHistoryTool._format_entry(record))
        return "\n".join(lines)

    @staticmethod
    def _format_entry(record: WorkflowHistoryRecord) -> str:
        """Format a single history record as a compact, complete two-line block.

        Args:
            record: The history record to format.

        Returns:
            A two-line string: a summary line and a detail line.
        """
        summary = f"  [{record.workflow_id}] {record.status}"
        if record.step_number is not None:
            summary += f" (step {record.step_number}/{record.step_total})"

        detail_parts = [f"at: {record.created_at.isoformat(timespec='seconds')}"]
        if record.tool_name is not None:
            detail_parts.append(f"tool: {record.tool_name}")
        if record.approval_request_id is not None:
            detail_parts.append(f"approval: {record.approval_request_id}")
        if record.detail:
            detail_parts.append(f"detail: {record.detail}")

        detail = "      " + " | ".join(detail_parts)
        return f"{summary}\n{detail}"

    @staticmethod
    def _format_workflow(
        workflow_id: str, records: list[WorkflowHistoryRecord]
    ) -> str:
        """Format one workflow's full transition history as a detailed block.

        Args:
            workflow_id: The workflow id being shown.
            records: That workflow's transitions, oldest first.

        Returns:
            A multi-line, detailed description of the workflow's history.
        """
        lines = [f"Workflow {workflow_id}"]
        for record in records:
            lines.append(f"  {WorkflowHistoryTool._format_entry(record)}")
        return "\n".join(lines)
