"""
approval_manager.py

In-memory management of approval requests and decisions (Phase 2).

Responsibilities:
    - Create and hold pending approval requests.
    - Look up and list pending requests.
    - Approve or decline a pending request, producing a decision.
    - Move a request from pending to completed once it is decided.
    - Store and retrieve completed decisions.
    - Optionally record every approve/decline decision in the audit log.

Does NOT:
    - Use the database directly (persistence goes through the audit logger).
    - Connect to the CLI or the Core.
    - Call the Claude API or any AI provider.
    - Ask the user anything or run any action.

The manager owns the lifecycle of an approval: a request starts pending, and
exactly one decision moves it to completed. Because a decided request is no
longer pending, it cannot be decided a second time. An audit logger may be
supplied to record each decision permanently; when it is omitted, the manager
works purely in memory, exactly as before.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from approval.approval_models import (
    ApprovalDecision,
    ApprovalError,
    ApprovalRequest,
)
from config.constants import EventOutcome, SecurityTier


class _ApprovalAuditLogger(Protocol):
    """The minimal logging interface the ApprovalManager depends on.

    This matches the emit method of observability.logger.EventLogger. Declaring
    it as a Protocol keeps the manager decoupled from the concrete logger, so it
    can be tested with a simple stand-in and works with the real EventLogger
    without importing it directly.
    """

    def emit(
        self,
        *,
        source: str,
        action_type: str,
        outcome: EventOutcome,
        detail: str | None = ...,
        duration_ms: int | None = ...,
        security_tier: SecurityTier | None = ...,
        session_id: int | None = ...,
    ) -> str:
        """Emit a structured event. See EventLogger.emit for details."""
        ...


class _ApprovalHistoryRecorder(Protocol):
    """The minimal history-recording interface the ApprovalManager depends on.

    This matches the write-side methods of
    approval.approval_history_store.ApprovalHistoryStore. Declaring it as a
    Protocol keeps the manager decoupled from the concrete store, so it can be
    tested with a simple stand-in (Phase 6, Batch 1).

    Deliberately absent from this interface: anything that stores or returns a
    tool name or tool input, and anything that lists "pending" requests for
    later resumption. ApprovalManager's in-memory pending state is always
    rebuilt from nothing on startup; only the historical record of requests
    and their decisions is written here, never read back into _pending.
    """

    def record_request(
        self,
        *,
        request_id: str,
        action: str,
        reason: str,
        security_tier: str,
        session_id: int | None = ...,
    ) -> object:
        """Record a newly created request as a pending history row."""
        ...

    def record_decision(
        self,
        *,
        request_id: str,
        approved: bool,
        decided_by: str,
        decided_at: datetime,
        reason: str | None = ...,
    ) -> object:
        """Record the final decision for a previously recorded request."""
        ...


_SOURCE = "approval_manager"
_ACTION_TYPE = "approval_decision"


class ApprovalManager:
    """Manages pending approval requests and completed decisions in memory.

    A single manager instance holds all currently pending requests and every
    decision made so far. Requests are keyed by their request_id.

    Attributes:
        _pending: Mapping of request_id to a pending ApprovalRequest. This is
            always empty when a manager is first constructed - see
            history_store below for why that never changes.
        _decisions: Mapping of request_id to a completed ApprovalDecision.
        _audit_logger: Optional logger used to record each decision. When None,
            the manager works purely in memory.
        _history: Optional durable history recorder. When provided, every
            created request and every decision is also written there, so it
            can be reviewed later - including after a restart. Crucially,
            __init__ never reads from this store: a freshly constructed
            manager always starts with empty _pending and _decisions, exactly
            as it did before history recording existed. Making a past pending
            request resumable after a restart is an explicit, separate
            decision for a later phase, not something this store enables.
    """

    def __init__(
        self,
        *,
        audit_logger: _ApprovalAuditLogger | None = None,
        history_store: _ApprovalHistoryRecorder | None = None,
    ) -> None:
        """Initialise an empty approval manager.

        Args:
            audit_logger: Optional logger (such as an EventLogger) used to
                record every approve/decline decision in the audit log. When
                omitted, the manager works purely in memory as before.
            history_store: Optional durable history recorder (such as an
                ApprovalHistoryStore) used to persist every created request
                and every decision so they remain visible after a restart.
                When omitted, the manager works purely in memory as before.
                This parameter only ever causes writes; it is never read from
                during construction, so pending requests never survive a
                restart even when a history_store is supplied.
        """
        self._pending: dict[str, ApprovalRequest] = {}
        self._decisions: dict[str, ApprovalDecision] = {}
        self._audit_logger = audit_logger
        self._history = history_store

    def create_request(
        self,
        action: str,
        reason: str,
        security_tier: SecurityTier,
        *,
        session_id: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> ApprovalRequest:
        """Create a pending approval request and store it.

        Validation of the action, reason, and security tier is performed by
        ApprovalRequest itself, so a GREEN or RED tier, or an empty action or
        reason, raises ApprovalError before the request is stored.

        Args:
            action: The action string that requires approval.
            reason: A human-readable explanation of why approval is needed.
            security_tier: The security tier of the action. Must be YELLOW.
            session_id: Optional session the request belongs to.
            metadata: Optional extra string details about the request.

        Returns:
            The newly created, pending ApprovalRequest.

        Raises:
            ApprovalError: If the request is invalid (see ApprovalRequest).
        """
        request = ApprovalRequest(
            action=action,
            reason=reason,
            security_tier=security_tier,
            session_id=session_id,
            metadata=dict(metadata) if metadata is not None else {},
        )
        self._pending[request.request_id] = request
        self._record_history_request(request)
        return request

    def get_pending(self, request_id: str) -> ApprovalRequest:
        """Return the pending request with the given id.

        Args:
            request_id: The identifier of the pending request.

        Returns:
            The pending ApprovalRequest.

        Raises:
            ApprovalError: If no pending request has that id.
        """
        request = self._pending.get(request_id)
        if request is None:
            raise ApprovalError(
                f"No pending approval request with id '{request_id}'. It may not "
                "exist, or it may already have been approved or declined."
            )
        return request

    def list_pending(self) -> list[ApprovalRequest]:
        """Return all currently pending requests, oldest first.

        Returns:
            A list of pending ApprovalRequest objects ordered by creation time.
        """
        return sorted(self._pending.values(), key=lambda r: r.created_at)

    def has_pending(self, request_id: str) -> bool:
        """Report whether a request with the given id is still pending.

        Args:
            request_id: The identifier to check.

        Returns:
            True if the request is pending, False otherwise.
        """
        return request_id in self._pending

    def approve(
        self,
        request_id: str,
        *,
        decided_by: str = "user",
        reason: str | None = None,
    ) -> ApprovalDecision:
        """Approve a pending request and record the decision.

        Args:
            request_id: The identifier of the pending request to approve.
            decided_by: Who made the decision. Defaults to "user".
            reason: Optional explanation for the approval.

        Returns:
            The recorded ApprovalDecision (approved).

        Raises:
            ApprovalError: If the request is not pending (unknown id, or it was
                already decided).
        """
        return self._decide(
            request_id, approved=True, decided_by=decided_by, reason=reason
        )

    def decline(
        self,
        request_id: str,
        *,
        decided_by: str = "user",
        reason: str | None = None,
    ) -> ApprovalDecision:
        """Decline a pending request and record the decision.

        Args:
            request_id: The identifier of the pending request to decline.
            decided_by: Who made the decision. Defaults to "user".
            reason: Optional explanation for the decline.

        Returns:
            The recorded ApprovalDecision (declined).

        Raises:
            ApprovalError: If the request is not pending (unknown id, or it was
                already decided).
        """
        return self._decide(
            request_id, approved=False, decided_by=decided_by, reason=reason
        )

    def get_decision(self, request_id: str) -> ApprovalDecision:
        """Return the completed decision for the given request id.

        Args:
            request_id: The identifier of the decided request.

        Returns:
            The recorded ApprovalDecision.

        Raises:
            ApprovalError: If no decision has been recorded for that id.
        """
        decision = self._decisions.get(request_id)
        if decision is None:
            raise ApprovalError(
                f"No decision recorded for request id '{request_id}'. It may not "
                "exist, or it may still be pending."
            )
        return decision

    def list_decisions(self) -> list[ApprovalDecision]:
        """Return all completed decisions, oldest first.

        Returns:
            A list of ApprovalDecision objects ordered by decision time.
        """
        return sorted(self._decisions.values(), key=lambda d: d.decided_at)

    def _decide(
        self,
        request_id: str,
        *,
        approved: bool,
        decided_by: str,
        reason: str | None,
    ) -> ApprovalDecision:
        """Resolve a pending request into a decision.

        The request is looked up (raising if not pending), a decision is
        created from it, the request is removed from pending, and the decision
        is stored. Removing it from pending is what prevents a second decision.

        Args:
            request_id: The identifier of the pending request.
            approved: True to approve, False to decline.
            decided_by: Who made the decision.
            reason: Optional explanation for the decision.

        Returns:
            The recorded ApprovalDecision.

        Raises:
            ApprovalError: If the request is not pending.
        """
        request = self.get_pending(request_id)
        decision = request.decide(
            approved=approved, decided_by=decided_by, reason=reason
        )
        del self._pending[request_id]
        self._decisions[request_id] = decision

        self._audit(request, decision)
        self._record_history_decision(decision)
        return decision

    def _audit(
        self, request: ApprovalRequest, decision: ApprovalDecision
    ) -> None:
        """Record a decision in the audit log, if a logger was supplied.

        When no audit logger is configured, this is a no-op and the manager
        behaves purely in memory. When a logger is present, one event is
        emitted describing the decision.

        The event outcome is SUCCESS for an approval (the action was allowed)
        and BLOCKED for a decline (the action was prevented). The detail
        captures the request_id, the action, the outcome, who decided, and the
        reason when one was supplied.

        Args:
            request: The request that was decided.
            decision: The recorded decision.
        """
        if self._audit_logger is None:
            return

        outcome = (
            EventOutcome.SUCCESS if decision.is_approved else EventOutcome.BLOCKED
        )
        self._audit_logger.emit(
            source=_SOURCE,
            action_type=_ACTION_TYPE,
            outcome=outcome,
            detail=self._build_detail(request, decision),
            security_tier=request.security_tier,
            session_id=request.session_id,
        )

    @staticmethod
    def _build_detail(
        request: ApprovalRequest, decision: ApprovalDecision
    ) -> str:
        """Build the human-readable detail string for an approval event.

        Args:
            request: The request that was decided.
            decision: The recorded decision.

        Returns:
            A detail string containing the request_id, action, outcome,
            decider, and reason (when supplied).
        """
        verdict = "approved" if decision.is_approved else "declined"
        parts = [
            f"request_id={request.request_id}",
            f"action={request.action}",
            f"outcome={verdict}",
            f"decided_by={decision.decided_by}",
        ]
        if decision.reason:
            parts.append(f"reason={decision.reason}")
        return " ".join(parts)

    def _record_history_request(self, request: ApprovalRequest) -> None:
        """Record a newly created request in durable history, if configured.

        When no history_store is configured, this is a no-op and the manager
        behaves purely in memory, exactly as before. No tool name or tool
        input is ever passed here - ApprovalRequest does not carry either, so
        there is nothing to persist beyond what the request itself is: an
        action, a reason, and a tier.

        Args:
            request: The request that was just created and is now pending.
        """
        if self._history is None:
            return

        self._history.record_request(
            request_id=request.request_id,
            action=request.action,
            reason=request.reason,
            security_tier=request.security_tier.value,
            session_id=request.session_id,
        )

    def _record_history_decision(self, decision: ApprovalDecision) -> None:
        """Record a decision in durable history, if configured.

        When no history_store is configured, this is a no-op and the manager
        behaves purely in memory, exactly as before. This only ever updates
        the outcome of a row already written by _record_history_request; it
        never creates a new pending row and never causes anything to execute.

        Args:
            decision: The decision that was just recorded.
        """
        if self._history is None:
            return

        self._history.record_decision(
            request_id=decision.request_id,
            approved=decision.approved,
            decided_by=decision.decided_by,
            decided_at=decision.decided_at,
            reason=decision.reason,
        )