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
    - Optionally expire a pending YELLOW request once it has been unanswered
      for timeout_seconds, recording ApprovalStatus.EXPIRED rather than a
      decision (Phase 6, Batch 3).

Does NOT:
    - Use the database directly (persistence goes through the audit logger).
    - Connect to the CLI or the Core.
    - Call the Claude API or any AI provider.
    - Ask the user anything or run any action.
    - Allow a RED action to enter the timeout lifecycle - ApprovalRequest
      rejects any non-YELLOW tier at construction, so only YELLOW requests
      are ever pending, and only YELLOW requests can ever expire.

The manager owns the lifecycle of an approval: a request starts pending, and
exactly one outcome - approved, declined, or expired - moves it to completed.
Because a decided or expired request is no longer pending, it cannot be
decided a second time. An audit logger may be supplied to record each
decision or timeout permanently; when it is omitted, the manager works purely
in memory, exactly as before. Timeout enforcement itself is optional and off
by default: without a timeout_seconds value, no request ever expires, and the
manager's behaviour is unchanged from before this feature existed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from approval.approval_models import (
    ApprovalDecision,
    ApprovalError,
    ApprovalRequest,
    ApprovalStatus,
)
from config.constants import EventOutcome, SecurityTier


def _default_clock() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Used as the default clock for ApprovalManager so that YELLOW approval
    timeouts are measured against real wall-clock time unless a test injects
    its own clock to simulate elapsed time deterministically.

    Returns:
        The current moment in UTC, as a timezone-aware datetime.
    """
    return datetime.now(timezone.utc)


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

    def record_timeout(
        self,
        *,
        request_id: str,
        timed_out_at: datetime,
        reason: str | None = ...,
    ) -> object:
        """Record that a previously recorded request's approval window expired.

        Deliberately separate from record_decision: a timeout is not a
        decision (nobody approved or declined anything), so it must never be
        written through record_decision's approved/declined shape.
        """
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
        _timeout_seconds: Optional number of seconds a pending YELLOW request
            may remain unanswered before it expires. None (the default)
            disables timeout enforcement entirely, exactly as before this
            feature existed. Only YELLOW requests can ever be pending in the
            first place - ApprovalRequest rejects any other tier - so RED can
            never enter this timeout lifecycle.
        _clock: Callable returning the current UTC time, used to measure a
            pending request's age against _timeout_seconds. Defaults to the
            real wall clock; tests may inject a fake clock to simulate
            elapsed time deterministically.
    """

    def __init__(
        self,
        *,
        audit_logger: _ApprovalAuditLogger | None = None,
        history_store: _ApprovalHistoryRecorder | None = None,
        timeout_seconds: int | None = None,
        clock: Callable[[], datetime] | None = None,
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
            timeout_seconds: Optional number of seconds a pending YELLOW
                request may remain unanswered before it expires. When
                omitted or None, timeout enforcement is disabled and the
                manager behaves exactly as it did before this feature
                existed. When provided, must be a positive number of
                seconds.
            clock: Optional callable returning the current UTC time, used to
                evaluate timeouts. Defaults to the real wall clock. Intended
                for tests that need to simulate elapsed time exactly.

        Raises:
            ApprovalError: If timeout_seconds is provided but is not a
                positive number of seconds.
        """
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ApprovalError(
                "timeout_seconds must be a positive number of seconds, or "
                "None to disable YELLOW approval timeouts entirely. "
                f"Received: {timeout_seconds}."
            )

        self._pending: dict[str, ApprovalRequest] = {}
        self._decisions: dict[str, ApprovalDecision] = {}
        self._audit_logger = audit_logger
        self._history = history_store
        self._timeout_seconds = timeout_seconds
        self._clock = clock or _default_clock

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
            created_at=self._clock(),
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
        self._sweep_expired()
        request = self._pending.get(request_id)
        if request is None:
            raise ApprovalError(
                f"No pending approval request with id '{request_id}'. It may "
                "not exist, it may already have been approved or declined, "
                "or its approval window may have expired."
            )
        return request

    def list_pending(self) -> list[ApprovalRequest]:
        """Return all currently pending requests, oldest first.

        Returns:
            A list of pending ApprovalRequest objects ordered by creation time.
            A request whose approval window has expired is never included.
        """
        self._sweep_expired()
        return sorted(self._pending.values(), key=lambda r: r.created_at)

    def has_pending(self, request_id: str) -> bool:
        """Report whether a request with the given id is still pending.

        Args:
            request_id: The identifier to check.

        Returns:
            True if the request is pending, False otherwise. A request whose
            approval window has expired is reported as not pending.
        """
        self._sweep_expired()
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

    def _sweep_expired(self) -> None:
        """Move any pending YELLOW requests whose approval window has elapsed.

        A request expires once its age (now - created_at) is greater than or
        equal to timeout_seconds - not strictly greater than. For the default
        60-second timeout, a request that is 59.999 seconds old is still
        pending; one that is exactly 60.000 seconds old has expired.

        Only YELLOW requests can ever be pending in the first place -
        ApprovalRequest rejects any other tier at construction - so this sweep
        can never affect a RED action. There is no timeout path for RED to
        enter, structurally, not by convention.

        Expiry never creates an ApprovalDecision: nobody approved or declined
        anything, the window simply passed. Instead, an EventOutcome.TIMEOUT
        audit event is emitted and ApprovalStatus.EXPIRED is recorded in
        durable history via record_timeout - never via record_decision, so a
        timeout can never be mistaken for a decline. Once removed here, the
        request is gone from _pending for good: it can never again be
        approved or declined, and it is never rehydrated on restart, exactly
        like every other pending request.

        This is a no-op when no timeout is configured (timeout_seconds is
        None) or when there is nothing pending to check.
        """
        if self._timeout_seconds is None or not self._pending:
            return

        now = self._clock()
        expired_ids = [
            request_id
            for request_id, request in self._pending.items()
            if (now - request.created_at).total_seconds() >= self._timeout_seconds
        ]
        for request_id in expired_ids:
            request = self._pending.pop(request_id)
            self._expire(request, expired_at=now)

    def _expire(self, request: ApprovalRequest, *, expired_at: datetime) -> None:
        """Finalise one request as timed out: audit, then durable history.

        Args:
            request: The pending request whose approval window elapsed. It
                has already been removed from _pending by the caller.
            expired_at: The moment the expiry was detected, from the manager's
                clock.
        """
        self._audit_timeout(request, expired_at=expired_at)
        self._record_history_timeout(request, expired_at=expired_at)

    def _audit_timeout(
        self, request: ApprovalRequest, *, expired_at: datetime
    ) -> None:
        """Record a timeout in the audit log, if a logger was supplied.

        When no audit logger is configured, this is a no-op, matching how
        approve/decline behave without one. When a logger is present, one
        EventOutcome.TIMEOUT event is emitted - distinct from the SUCCESS
        (approved) and BLOCKED (declined) outcomes used elsewhere in this
        class, so a timeout is never confused with either in the audit log.

        Args:
            request: The request that expired.
            expired_at: The moment the expiry was detected.
        """
        if self._audit_logger is None:
            return

        self._audit_logger.emit(
            source=_SOURCE,
            action_type=_ACTION_TYPE,
            outcome=EventOutcome.TIMEOUT,
            detail=self._build_timeout_detail(request),
            security_tier=request.security_tier,
            session_id=request.session_id,
        )

    def _build_timeout_detail(self, request: ApprovalRequest) -> str:
        """Build the human-readable detail string for a timeout event.

        Args:
            request: The request that expired.

        Returns:
            A detail string containing the request_id, action, the resulting
            ApprovalStatus, and the configured timeout duration.
        """
        return (
            f"request_id={request.request_id} action={request.action} "
            f"status={ApprovalStatus.EXPIRED.value} "
            f"timeout_seconds={self._timeout_seconds}"
        )

    def _record_history_timeout(
        self, request: ApprovalRequest, *, expired_at: datetime
    ) -> None:
        """Record a timeout in durable history, if configured.

        When no history_store is configured, this is a no-op, matching how
        approve/decline behave without one. This always calls
        record_timeout, never record_decision - the two are kept structurally
        separate so a timeout can never be persisted as a decline.

        Args:
            request: The request that expired.
            expired_at: The moment the expiry was detected.
        """
        if self._history is None:
            return

        self._history.record_timeout(
            request_id=request.request_id,
            timed_out_at=expired_at,
            reason=(
                f"No response within {self._timeout_seconds} seconds."
            ),
        )