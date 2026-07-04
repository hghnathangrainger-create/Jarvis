"""
approval_history_tool.py

A safe, read-only tool that shows durable approval history (Phase 6, Batch 1).

ApprovalHistoryTool is a GREEN tool. It only reads from an ApprovalHistoryStore
and never approves, declines, creates, or executes anything. It has no
operation, no input field, and no code path that accepts a tool name or tool
input for a past request, so nothing this tool shows can ever be replayed -
see approval_history_store.py for why that boundary is deliberate.

Supported operations (via the 'operation' input):
    - "history":  the most recent history entries, any status (default).
    - "recent":   the last 10 entries, any status.
    - "approved": entries with status "approved".
    - "declined": entries with status "declined".
    - "get":      a single entry by 'request_id'.
"""

from __future__ import annotations

from approval.approval_history_store import (
    ApprovalHistoryRecord,
    ApprovalHistoryStore,
)
from tools.base_tool import BaseTool, ToolRequest, ToolResult

_DEFAULT_LIMIT = 20
_RECENT_LIMIT = 10


class ApprovalHistoryTool(BaseTool):
    """Shows durable, read-only approval history using the history store.

    Attributes:
        _history: The ApprovalHistoryStore used for read-only access.
    """

    def __init__(self, history_store: ApprovalHistoryStore) -> None:
        """Initialise the tool with an ApprovalHistoryStore.

        Args:
            history_store: The store providing read access to approval
                history.
        """
        self._history = history_store

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "approval_history".
        """
        return "approval_history"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Shows durable approval history (pending, approved, declined). "
            "Read-only and safe."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return an honest action string for security classification.

        Every operation this tool supports is a read. The Security Manager
        classifies all five action strings below GREEN via its existing,
        unchanged "show" rule - no new Security Manager rule was needed or
        added for this tool.

        Args:
            request: The request being handled.

        Returns:
            An action string describing the operation.
        """
        operation = str(
            request.input_data.get("operation", "history")
        ).strip().lower()
        if operation == "recent":
            return "show recent approvals"
        if operation == "approved":
            return "show approved actions"
        if operation == "declined":
            return "show declined actions"
        if operation == "get":
            return "show approval details"
        return "show approval history"

    def run(self, request: ToolRequest) -> ToolResult:
        """Show approval history according to the requested operation.

        Args:
            request: The request. Recognised input keys:
                operation: "history" (default), "recent", "approved",
                    "declined", or "get".
                request_id: the approval request id, required when operation
                    is "get".

        Returns:
            A ToolResult containing the formatted history, or a failed result
            if "get" is requested without a request_id, or finds nothing, or
            the operation is unrecognised.
        """
        operation = str(
            request.input_data.get("operation", "history")
        ).strip().lower()

        if operation == "get":
            return self._run_get(request)

        if operation == "recent":
            records = self._history.list_recent(limit=_RECENT_LIMIT)
            return self.ok(self._format_many(records, "Recent approvals"))

        if operation == "approved":
            records = self._history.list_by_status(
                "approved", limit=_DEFAULT_LIMIT
            )
            return self.ok(self._format_many(records, "Approved actions"))

        if operation == "declined":
            records = self._history.list_by_status(
                "declined", limit=_DEFAULT_LIMIT
            )
            return self.ok(self._format_many(records, "Declined actions"))

        if operation == "history":
            records = self._history.list_recent(limit=_DEFAULT_LIMIT)
            return self.ok(self._format_many(records, "Approval history"))

        return self.fail(
            f"Unknown operation '{operation}'. Use 'history', 'recent', "
            "'approved', 'declined', or 'get'."
        )

    def _run_get(self, request: ToolRequest) -> ToolResult:
        """Handle the "get" operation: show a single history entry.

        Args:
            request: The request carrying the 'request_id' to look up.

        Returns:
            A ToolResult with the formatted entry, or a failure when
            request_id is missing or not found.
        """
        request_id = request.input_data.get("request_id")
        if not isinstance(request_id, str) or not request_id.strip():
            return self.fail(
                "Showing a single approval requires a 'request_id'."
            )
        record = self._history.get(request_id.strip())
        if record is None:
            return self.fail(
                f"No approval history found for id '{request_id.strip()}'."
            )
        return self.ok(self._format_one(record))

    @staticmethod
    def _format_many(
        records: list[ApprovalHistoryRecord], header: str
    ) -> str:
        """Format a list of history records into readable text.

        Args:
            records: The history records to format.
            header: A header line describing the result set.

        Returns:
            A formatted, multi-line string. Reports when there are no results.
        """
        if not records:
            return f"{header}: none found."
        lines = [f"{header}:"]
        for record in records:
            lines.append(ApprovalHistoryTool._format_entry(record))
        return "\n".join(lines)

    @staticmethod
    def _format_entry(record: ApprovalHistoryRecord) -> str:
        """Format a single history record as a compact, complete two-line block.

        The first line names the record and what happened - id, status, and
        action, matching the format used since Batch 1. The second line
        carries the remaining required detail: security tier and created
        time always appear; decided time, decided by, and decision reason
        are appended only when the record actually has them.

        A pending record therefore shows only tier and created time - the
        decision fields are omitted entirely rather than shown as blank or
        "N/A", so the output never implies a decision has been made when it
        has not.

        Args:
            record: The history record to format.

        Returns:
            A two-line string: a summary line and a detail line.
        """
        status = record.status.upper()
        summary = f"  [{record.request_id}] {status} - {record.action}"

        detail_parts = [
            f"tier: {record.security_tier}",
            f"created: {record.created_at.isoformat(timespec='seconds')}",
        ]
        if record.decided_at is not None:
            decided_part = (
                f"decided: {record.decided_at.isoformat(timespec='seconds')}"
            )
            if record.decided_by is not None:
                decided_part += f" by {record.decided_by}"
            detail_parts.append(decided_part)
        if record.decision_reason:
            detail_parts.append(f"reason: {record.decision_reason}")

        detail = "      " + " | ".join(detail_parts)
        return f"{summary}\n{detail}"

    @staticmethod
    def _format_one(record: ApprovalHistoryRecord) -> str:
        """Format a single history record as a detailed block.

        Args:
            record: The history record to format.

        Returns:
            A multi-line, detailed description of the record.
        """
        lines = [
            f"Approval {record.request_id}",
            f"  status: {record.status}",
            f"  action: {record.action}",
            f"  reason: {record.reason}",
            f"  tier: {record.security_tier}",
            f"  created_at: {record.created_at.isoformat(timespec='seconds')}",
        ]
        if record.decided_at is not None:
            lines.append(
                "  decided_at: "
                f"{record.decided_at.isoformat(timespec='seconds')}"
            )
        if record.decided_by is not None:
            lines.append(f"  decided_by: {record.decided_by}")
        if record.decision_reason:
            lines.append(f"  decision_reason: {record.decision_reason}")
        return "\n".join(lines)