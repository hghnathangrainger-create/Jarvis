"""
workflow_history_tool.py

A safe, read-only tool that shows durable workflow lifecycle history
(Durable Workflow Lifecycle Foundation - a prerequisite turn, not a
numbered phase; extended Phase 73, Batch 2 with a real,
recent-activity-scoped status breakdown in the "history"/"recent"
list headers).

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

from collections import Counter

from tools.base_tool import BaseTool, ToolRequest, ToolResult
from workflow.workflow_history_store import (
    KNOWN_WORKFLOW_STATUSES,
    WorkflowHistoryRecord,
    WorkflowHistoryStore,
)

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
            header = self._list_header("Recent workflows", records, _RECENT_LIMIT)
            return self.ok(self._format_many(records, header))

        if operation == "history":
            records = self._history.list_recent(limit=_DEFAULT_LIMIT)
            header = self._list_header("Workflow history", records, _DEFAULT_LIMIT)
            return self.ok(self._format_many(records, header))

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

    def _list_header(
        self, base_header: str, records: list[WorkflowHistoryRecord], workflow_id_limit: int
    ) -> str:
        """Build a list operation's header, including a real,
        recent-activity-scoped status breakdown when there is at least
        one result (Phase 73, Batch 2).

        Only "history"/"recent" (the list operations) ever call this -
        the single-workflow "get" detail view is completely unaffected.
        When `records` is empty, the plain `base_header` is returned
        unchanged, so `_format_many()`'s own existing empty-state
        message ("{header}: none found.") is preserved exactly as it
        was before this batch - an empty result means every status's
        real count is honestly zero anyway, so no breakdown is needed
        to say so.

        Args:
            base_header: The plain header text ("Workflow history" or
                "Recent workflows").
            records: The already-fetched transition records this list
                operation is about to render - only used here to decide
                whether any results exist at all.
            workflow_id_limit: The maximum number of most-recently-active
                distinct workflows to consider for the breakdown - passed
                straight through to list_recent_workflow_ids().

        Returns:
            The plain header, or the header with a parenthetical,
            recent-activity-scoped breakdown appended.
        """
        if not records:
            return base_header
        breakdown = self._workflow_status_breakdown_text(workflow_id_limit)
        return f"{base_header} (recent activity: {breakdown})"

    def _workflow_status_breakdown_text(self, limit: int) -> str:
        """Return a real, honest, recent-activity-scoped status
        breakdown as a single comma-separated text fragment (Phase 73,
        Batch 2).

        Tallies only the most recently active *distinct* workflows'
        current status - never raw transition rows, which would
        double-count a busy workflow with many transitions. Uses only
        already-existing WorkflowHistoryStore methods:
        list_recent_workflow_ids() to identify distinct workflow ids,
        then latest_status_for() once per id to find each one's current
        status - the exact same methodology
        dashboard/read_model.py's own get_workflow_status_breakdown()
        already established and proved (Phase 64, Batch 1).

        Never presented, or claimed, as an all-time total: no all-time
        per-status aggregation exists for workflows, since a workflow's
        "status" is its own latest transition, not a fixed column.
        Every status in KNOWN_WORKFLOW_STATUSES is included, even one
        matched by none of the considered workflows - an honest zero is
        reported, never omitted. Statuses are rendered in
        KNOWN_WORKFLOW_STATUSES's own fixed, declared order - never
        sorted by count.

        Args:
            limit: Maximum number of most-recently-active distinct
                workflows to consider, passed straight through to
                list_recent_workflow_ids().

        Returns:
            A single text fragment like "workflow_started: 1,
            workflow_completed: 2, ...", one entry per known status, in
            KNOWN_WORKFLOW_STATUSES's own fixed order.
        """
        workflow_ids = self._history.list_recent_workflow_ids(limit=limit)
        latest_statuses = []
        for workflow_id in workflow_ids:
            latest = self._history.latest_status_for(workflow_id)
            if latest is not None:
                latest_statuses.append(latest.status)
        tally = Counter(latest_statuses)
        return ", ".join(
            f"{status}: {tally.get(status, 0)}" for status in KNOWN_WORKFLOW_STATUSES
        )

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
