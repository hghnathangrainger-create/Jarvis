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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from approval.approval_models import (
    ApprovalDecision,
    ApprovalError,
    ApprovalRequest,
    ApprovalStatus,
)
from approval.pending_approval_store import SCHEMA_VERSION, PendingApprovalRecord
from config.constants import EventOutcome, SecurityTier
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.registry import ToolRegistry


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


class _PendingApprovalStateStore(Protocol):
    """The minimal pending-approval-state interface ApprovalManager depends on.

    Matches the write/read-side methods of
    approval.pending_approval_store.PendingApprovalStore. Declaring it as a
    Protocol keeps the manager decoupled from the concrete store (Phase 27,
    Batch 1), mirroring _ApprovalHistoryRecorder immediately above.

    Unlike _ApprovalHistoryRecorder, this interface's whole purpose is to
    let a pending request's execution state (tool_name/tool_input) survive
    a restart - that is explicitly authorized for *this* table only (see
    pending_approval_store.py's own module docstring), never for
    approval_history, which remains completely untouched by this feature.
    """

    def save(
        self,
        *,
        request_id: str,
        action: str,
        reason: str,
        security_tier: str,
        session_id: int | None = ...,
        metadata: dict[str, str] | None = ...,
        tool_name: str | None = ...,
        tool_input: dict[str, object] | None = ...,
    ) -> object:
        """Persist (or replace) the pending state for one request_id."""
        ...

    def delete(self, request_id: str) -> None:
        """Remove the persisted pending state for one request_id, if any."""
        ...

    def list_all(self) -> list[PendingApprovalRecord]:
        """Return every currently persisted pending-approval row."""
        ...


@dataclass(frozen=True, slots=True)
class PendingToolState:
    """The tool name and input needed to run a pending approval once it is
    approved, for a request that has a backing tool at all (Phase 27,
    Batch 1).

    This is plain data only. It never lets anything execute by itself - a
    caller (JarvisOrchestrator.execute_approved for a live request, or a
    caller resuming a reloaded one) must still pass tool_name/tool_input
    through the unmodified ToolExecutor.execute() gate, exactly as the
    live approval flow already does via JarvisResponse.tool_name/
    tool_input.

    Attributes:
        tool_name: The registered tool this request would run.
        tool_input: The plain input dict this request would run with.
    """

    tool_name: str
    tool_input: dict[str, object]


@dataclass(frozen=True, slots=True)
class ApprovalReloadReport:
    """A small, honest summary of what reload_pending() did (Phase 27,
    Batch 1).

    Attributes:
        resumed: Number of persisted rows that passed revalidation and are
            now genuinely pending again, exactly as if the process had
            never restarted.
        invalidated: Number of persisted rows that failed revalidation and
            were removed, with a terminal entry recorded in approval
            history explaining why - never approved, declined, or
            executed.
    """

    resumed: int
    invalidated: int


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
        _pending_store: Optional durable pending-approval-state store
            (Phase 27, Batch 1). When provided, the execution state
            (tool_name/tool_input) needed to run a pending request once
            approved is additionally persisted there, so it can survive a
            restart. __init__ never reads from this store either - exactly
            like history_store, a freshly constructed manager always
            starts with empty _pending/_tool_state; a caller must
            explicitly call reload_pending() to repopulate them from what
            was persisted, after independently revalidating every row.
        _tool_state: Mapping of request_id to the PendingToolState needed
            to run that request's tool once approved. Populated by
            create_request() (when a tool_name is supplied) and by
            reload_pending() (for a row that passes revalidation).
            Deliberately never cleared on decide/expire, mirroring
            _decisions's own unbounded-for-the-session lifetime, so a
            caller can still retrieve it immediately after approving a
            request.
    """

    def __init__(
        self,
        *,
        audit_logger: _ApprovalAuditLogger | None = None,
        history_store: _ApprovalHistoryRecorder | None = None,
        timeout_seconds: int | None = None,
        clock: Callable[[], datetime] | None = None,
        pending_store: _PendingApprovalStateStore | None = None,
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
            pending_store: Optional durable pending-approval-state store
                (such as a PendingApprovalStore) used to persist the
                execution state of every pending request (Phase 27, Batch
                1). When omitted, the manager behaves exactly as it did
                before this feature existed - purely in memory, and a
                restart always loses every pending request, exactly as
                today. This parameter only ever causes writes during
                __init__/create_request()/decide/expire; reload_pending()
                must be called explicitly to read anything back.

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
        self._pending_store = pending_store
        self._tool_state: dict[str, PendingToolState] = {}

    def create_request(
        self,
        action: str,
        reason: str,
        security_tier: SecurityTier,
        *,
        session_id: int | None = None,
        metadata: dict[str, str] | None = None,
        tool_name: str | None = None,
        tool_input: dict[str, object] | None = None,
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
            tool_name: Optional registered tool this request would run once
                approved (Phase 27, Batch 1). Omitted for a request with no
                backing tool at all (a plan-only confirmation) - such a
                request has never been resumable across a restart, and
                still is not.
            tool_input: Optional plain input dict this request would run
                the tool with once approved. Only meaningful together with
                tool_name.

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
        if tool_name is not None:
            self._tool_state[request.request_id] = PendingToolState(
                tool_name=tool_name, tool_input=dict(tool_input or {})
            )
        self._record_history_request(request)
        self._record_pending_state(request, tool_name=tool_name, tool_input=tool_input)
        return request

    def get_pending_tool_state(self, request_id: str) -> PendingToolState | None:
        """Return the tool name/input needed to run a request once approved.

        Returns None for a request with no backing tool at all (a
        plan-only confirmation with nothing to execute) or for an unknown
        request_id. This never executes anything itself - a caller (such
        as JarvisOrchestrator, or a test resuming a reloaded approval)
        must still pass the returned tool_name/tool_input through the
        unmodified ToolExecutor.execute() gate, exactly as the live
        approval flow already does via JarvisResponse.tool_name/
        tool_input. Available for the life of this manager instance once
        recorded - it is never cleared on decide/expire (see _tool_state's
        own docstring above), so a caller can still retrieve it
        immediately after approving a request.

        Args:
            request_id: The identifier of the request to look up.

        Returns:
            The PendingToolState, or None.
        """
        return self._tool_state.get(request_id)

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
        self._remove_pending_state(request_id)
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
        outcome = (
            EventOutcome.SUCCESS if decision.is_approved else EventOutcome.BLOCKED
        )
        self._emit_audit_event(
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
        self._remove_pending_state(request.request_id)

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
        self._emit_audit_event(
            outcome=EventOutcome.TIMEOUT,
            detail=self._build_timeout_detail(request),
            security_tier=request.security_tier,
            session_id=request.session_id,
        )

    def _emit_audit_event(
        self,
        *,
        outcome: EventOutcome,
        detail: str,
        security_tier: SecurityTier,
        session_id: int | None,
    ) -> None:
        """Emit one approval_decision audit event, isolating a failing
        logger so it can never alter an already-authoritative approval
        outcome (Phase 15 Batch 4B closure).

        Empirically proven defect this closes: _audit()/_audit_timeout()
        previously called self._audit_logger.emit(...) directly, with no
        isolation, from a point *after* the authoritative in-memory state
        change had already happened (approve()/decline() had already
        removed the request from _pending and recorded the decision in
        _decisions; _sweep_expired() had already popped the expired
        request from _pending). A raising logger therefore propagated out
        of approve()/decline()/get_pending()/list_pending()/has_pending()
        - even for has_pending() checking a request_id entirely unrelated
        to the one that happened to expire - silently orphaning an
        already-decided or already-expired request: the caller (and, for a
        Phase 15 workflow, WorkflowEngine.resume()) never received the
        decision, the durable ApprovalHistoryStore write for it was never
        reached, and a paused workflow could be left permanently stuck.

        When no audit logger is configured, this remains a no-op exactly
        as before. Nothing here changes event names, EventOutcome mapping,
        detail content, security tier, session_id, timeout durations, or
        approval semantics - only the emit() call itself is now isolated.

        Args:
            outcome: The EventOutcome to record.
            detail: The already-built detail string.
            security_tier: The tier to record.
            session_id: Optional session identifier.
        """
        if self._audit_logger is None:
            return
        try:
            self._audit_logger.emit(
                source=_SOURCE,
                action_type=_ACTION_TYPE,
                outcome=outcome,
                detail=detail,
                security_tier=security_tier,
                session_id=session_id,
            )
        except Exception:
            # Observability-only: a failing audit logger must never break
            # the authoritative approval outcome already decided.
            pass

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

    # ----- durable pending-approval state (Phase 27, Batch 1) ---------------

    def _record_pending_state(
        self,
        request: ApprovalRequest,
        *,
        tool_name: str | None,
        tool_input: dict[str, object] | None,
    ) -> None:
        """Durably persist this request's pending execution state, if a
        pending_store is configured.

        When no pending_store is configured, this is a no-op and the
        manager behaves purely in memory, exactly as before this feature
        existed. Unlike _emit_audit_event, this is deliberately not
        isolated in a try/except: a failing durable write here is treated
        the same way _record_history_request already treats a failing
        history_store - a real problem worth surfacing, not a purely
        observational one.

        Args:
            request: The request that was just created and is now pending.
            tool_name: The tool this request would run once approved, or
                None.
            tool_input: The input the tool would run with, or None.
        """
        if self._pending_store is None:
            return

        self._pending_store.save(
            request_id=request.request_id,
            action=request.action,
            reason=request.reason,
            security_tier=request.security_tier.value,
            session_id=request.session_id,
            metadata=dict(request.metadata),
            tool_name=tool_name,
            tool_input=dict(tool_input) if tool_input is not None else None,
        )

    def _remove_pending_state(self, request_id: str) -> None:
        """Remove this request's durable pending-execution-state row, if a
        pending_store is configured.

        Only the durable row is removed here - self._tool_state (in
        memory) is deliberately retained for the life of this manager
        instance; see its own docstring on the class for why.

        Args:
            request_id: The identifier of the request that was just
                decided or expired.
        """
        if self._pending_store is None:
            return
        self._pending_store.delete(request_id)

    def reload_pending(
        self,
        *,
        registry: ToolRegistry,
        security_manager: SecurityManager | None = None,
    ) -> ApprovalReloadReport:
        """Reload every persisted pending approval, revalidating each
        against live code before treating it as genuinely pending again
        (Phase 27, Batch 1).

        This is never called from __init__ - a freshly constructed
        ApprovalManager always starts with empty _pending/_decisions/
        _tool_state, exactly as before this feature existed. A caller
        (the composition root, main.py) calls this explicitly, once,
        after every tool has been registered on `registry`.

        A persisted row is only ever treated as resumable if ALL of the
        following hold:
            - its metadata_json/tool_input_json decoded without error
              (PendingApprovalRecord.corrupt is False);
            - its schema_version is one this code recognises;
            - its action string is non-empty;
            - tool_name is either None (a plan-only confirmation - never
              resumable, but not itself invalid on that basis alone) or
              names a tool that is still registered in `registry`;
            - classifying the tool's own fixed action_for() output (or,
              when tool_name is None, the stored action text directly -
              mirroring ToolExecutor.execute()'s own rule that only a
              tool's fixed action string is ever classified) still
              returns SecurityTier.YELLOW right now, not merely at
              creation time;
            - it is not older than this manager's own configured
              timeout_seconds (if any), evaluated exactly as
              _sweep_expired() already evaluates a live pending request.

        A row that fails any check is never executed, never approved, and
        never silently dropped: it is removed from the durable pending-
        state table, and a terminal entry is recorded in approval history
        (via the existing record_timeout() shape) explaining that it
        could not be resumed - so it remains just as durably visible as
        any other outcome. Nothing here ever auto-approves, auto-
        declines, or auto-executes anything; a row that passes every
        check is only ever added back to self._pending (and, if it has a
        tool, self._tool_state) - a caller must still explicitly approve
        or decline it, exactly as for a live request.

        Args:
            registry: The live ToolRegistry to check every stored
                tool_name against. Should already have every tool
                registered.
            security_manager: The live SecurityManager to reclassify
                every stored action against. Defaults to a new
                SecurityManager() if omitted (it is stateless, so this is
                equivalent to sharing the application's own instance).

        Returns:
            An ApprovalReloadReport summarising how many rows were
            resumed versus invalidated.
        """
        if self._pending_store is None:
            return ApprovalReloadReport(resumed=0, invalidated=0)

        security = security_manager or SecurityManager()
        now = self._clock()
        resumed = 0
        invalidated = 0

        for record in self._pending_store.list_all():
            rejection = self._reload_rejection_reason(
                record, registry=registry, security=security, now=now
            )
            if rejection is not None:
                self._invalidate_reloaded_row(record, reason=rejection, now=now)
                invalidated += 1
                continue

            created_at = record.created_at
            if created_at.tzinfo is None:
                # See the matching normalisation in
                # _reload_rejection_reason - SQLite does not durably
                # round-trip timezone info, and this project's own
                # established convention treats a naive value as
                # UTC-in-substance.
                created_at = created_at.replace(tzinfo=timezone.utc)

            request = ApprovalRequest(
                action=record.action,
                reason=record.reason,
                security_tier=SecurityTier.YELLOW,
                session_id=record.session_id,
                metadata=dict(record.metadata),
                request_id=record.request_id,
                created_at=created_at,
            )
            self._pending[request.request_id] = request
            if record.tool_name is not None:
                self._tool_state[request.request_id] = PendingToolState(
                    tool_name=record.tool_name,
                    tool_input=dict(record.tool_input or {}),
                )
            resumed += 1

        return ApprovalReloadReport(resumed=resumed, invalidated=invalidated)

    def _reload_rejection_reason(
        self,
        record: PendingApprovalRecord,
        *,
        registry: ToolRegistry,
        security: SecurityManager,
        now: datetime,
    ) -> str | None:
        """Return why `record` must fail closed on reload, or None if it
        may be safely treated as pending again.

        Args:
            record: The persisted row being considered for reload.
            registry: The live ToolRegistry to resolve record.tool_name
                against.
            security: The live SecurityManager to reclassify against.
            now: The current moment, from this manager's own clock.

        Returns:
            A short, human-readable rejection reason, or None if the row
            passes every check.
        """
        if record.corrupt:
            return "Persisted state could not be parsed."
        if record.schema_version != SCHEMA_VERSION:
            return (
                "Persisted state uses an unsupported schema version "
                f"({record.schema_version})."
            )
        if not record.action.strip():
            return "Persisted state has no action to reclassify."

        if record.tool_name is not None:
            tool = registry.get_tool(record.tool_name)
            if tool is None:
                return f"Tool '{record.tool_name}' is no longer registered."
            classify_text = tool.action_for(
                ToolRequest(
                    tool_name=record.tool_name,
                    input_data=dict(record.tool_input or {}),
                )
            )
        else:
            classify_text = record.action

        try:
            decision = security.classify_action(classify_text)
        except ValueError:
            return "Persisted action text is empty and cannot be reclassified."
        if decision.tier is not SecurityTier.YELLOW:
            return (
                "Action no longer classifies as YELLOW "
                f"(now {decision.tier.value})."
            )

        if self._timeout_seconds is not None:
            # SQLite does not durably round-trip timezone info even for a
            # DateTime(timezone=True) column - a value read back may come
            # back naive. This project's own established convention
            # (see scheduling/schedule_store.py's own docstring) is that a
            # naive value read back is always UTC-in-substance, since
            # every created_at column is written via _utc_now(). Without
            # this normalisation, comparing against self._clock()'s own
            # timezone-aware "now" would raise TypeError.
            created_at = record.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age = (now - created_at).total_seconds()
            if age >= self._timeout_seconds:
                return "Persisted approval is older than the configured timeout."

        return None

    def _invalidate_reloaded_row(
        self, record: PendingApprovalRecord, *, reason: str, now: datetime
    ) -> None:
        """Remove a persisted row that failed reload revalidation, and
        record an honest terminal entry in approval history so the
        outcome remains durably visible - never approved, declined, or
        executed.

        Args:
            record: The persisted row that failed revalidation.
            reason: The human-readable rejection reason.
            now: The current moment, from this manager's own clock.
        """
        self._finalize_pending_as_unresumable(
            request_id=record.request_id,
            action=record.action,
            session_id=record.session_id,
            reason=reason,
            now=now,
        )

    def invalidate_pending(self, request_id: str, *, reason: str) -> bool:
        """Forcibly invalidate a still-pending request as unresumable, for
        a reason external to this manager's own reload revalidation
        (Phase 27, Batch 2).

        Used specifically when a paused workflow's own persisted state
        could not be safely reloaded (corrupt, unsupported schema
        version, an unregistered tool, a no-longer-YELLOW action, or an
        out-of-range step index) - its linked pending approval, even if
        it would otherwise still look individually valid, can never
        actually be resumed once its workflow is gone, so it must not be
        left sitting as if it still meant something. Never approves,
        declines, or executes anything.

        This is a no-op (returns False) if request_id is not currently
        pending - a caller (WorkflowEngine.reload_paused()) may call this
        even when it is not certain the approval is still pending,
        without needing to check first.

        Args:
            request_id: The identifier of the pending request to
                invalidate.
            reason: A human-readable explanation, recorded in approval
                history exactly like any other reload-invalidation.

        Returns:
            True if a pending request was found and invalidated; False
            if there was nothing pending to invalidate.
        """
        request = self._pending.pop(request_id, None)
        if request is None:
            return False
        self._finalize_pending_as_unresumable(
            request_id=request_id,
            action=request.action,
            session_id=request.session_id,
            reason=reason,
            now=self._clock(),
        )
        return True

    def _finalize_pending_as_unresumable(
        self,
        *,
        request_id: str,
        action: str,
        session_id: int | None,
        reason: str,
        now: datetime,
    ) -> None:
        """Shared terminal-invalidation logic: remove durable state, audit,
        and record an honest approval-history entry.

        Used both when a reload_pending() row fails its own revalidation
        (_invalidate_reloaded_row, the request was never added back to
        _pending) and when an already-pending request is invalidated
        externally (invalidate_pending, e.g. orphaned by a paused
        workflow that could not itself be reloaded).

        Args:
            request_id: The identifier of the request being invalidated.
            action: The action string, for the audit detail.
            session_id: Optional session identifier.
            reason: The human-readable rejection reason.
            now: The current moment, from this manager's own clock.
        """
        if self._pending_store is not None:
            self._pending_store.delete(request_id)
        self._emit_audit_event(
            outcome=EventOutcome.TIMEOUT,
            detail=(
                f"request_id={request_id} action={action} "
                f"status=invalidated_on_reload reason={reason}"
            ),
            security_tier=SecurityTier.YELLOW,
            session_id=session_id,
        )
        if self._history is not None:
            self._history.record_timeout(
                request_id=request_id,
                timed_out_at=now,
                reason=f"Could not be resumed after restart: {reason}",
            )