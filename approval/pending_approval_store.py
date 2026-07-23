"""
pending_approval_store.py

Data-access layer for durable pending-approval execution state (Phase 27,
Batch 1).

Responsibilities:
    - Persist the execution state (tool name and input, if any) a pending
      YELLOW approval would need to safely continue after a process
      restart.
    - Load every currently persisted row so ApprovalManager can attempt to
      revalidate and reload it at startup.
    - Remove a row the moment its approval is decided, expires, or is
      found invalid on reload.

Does NOT:
    - Decide whether a reloaded row is safe to treat as pending. That
      revalidation - is the tool still registered, does the action still
      classify YELLOW under a live SecurityManager, is the JSON
      well-formed, is the row stale - is entirely ApprovalManager's own
      responsibility (reload_pending()), using live code. This store only
      stores and retrieves plain data; it never inspects a ToolRegistry
      or a SecurityManager itself.
    - Execute a tool, approve, or decline anything. Loading a row here
      must never, by itself, run anything.
    - Replace or weaken approval_history. This is a *different* table
      from ApprovalHistoryEntry: approval_history is a permanent,
      read-only, non-executable audit trail (deliberately with no
      tool_name/tool_input columns - see approval_history_store.py's own
      module docstring); this table is short-lived *operational* state,
      deliberately authorized by Phase 27 planning to hold the tool name
      and input needed to resume - and it exists only for as long as the
      approval itself is genuinely pending. A row here is never copied
      into approval_history, and approval_history is never read from
      here.

This table's mere existence for a given request_id means only "this
request's execution state was persisted the last time anything wrote to
this table" - never "this request is approved" or "this request is safe
to run". Row existence must never be treated as approval.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from approval.approval_models import PendingApprovalHandoffStatus
from storage.database import session_scope
from storage.models import PendingApprovalState

#: The current schema version written to every new row. Bumped only if
#: the JSON shape of metadata_json/tool_input_json ever changes in a way
#: that would make an older row unsafe to interpret with new code -
#: ApprovalManager.reload_pending() refuses to treat a row whose
#: schema_version it does not recognise as resumable (see its own
#: docstring), rather than guessing at an unfamiliar shape.
SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PendingApprovalRecord:
    """A plain, detached view of a stored pending-approval-state row.

    The store returns these instead of live ORM objects so that callers
    never depend on an open database session. `metadata`/`tool_input` are
    already decoded from their stored JSON text; `corrupt` is set instead
    of raising when that decoding fails, so a single malformed row can
    never prevent every other valid row from loading.

    Attributes:
        id: The primary key of the stored row.
        request_id: The approval request id this row describes.
        session_id: The session the request belonged to, if any.
        action: The action string that required approval.
        reason: A human-readable explanation of why approval was needed.
        security_tier: The tier of the action, as a string (e.g. "yellow").
        metadata: The request's metadata dict, decoded from JSON. Empty
            when none was stored.
        tool_name: The tool this request would run once approved, or None
            for a request with no backing tool.
        tool_input: The tool_input dict this request would run with,
            decoded from JSON. None exactly when tool_name is None.
        schema_version: The schema version this row was written with.
        created_at: UTC timestamp of when this row was first written.
        corrupt: True if metadata_json or tool_input_json could not be
            decoded as valid JSON. When True, metadata is an empty dict
            and tool_input is None regardless of what was actually
            stored - the caller (ApprovalManager.reload_pending()) must
            treat a corrupt record as invalid and never resumable.
        handoff_status: This row's durable execution-handoff lifecycle
            state (Approval-to-Resume Handoff Interlock, Batch 1). Not
            read or acted upon by any live code in Batch 1 - present
            here only so callers (today: this batch's own tests) can
            observe it.
    """

    id: int
    request_id: str
    session_id: int | None
    action: str
    reason: str
    security_tier: str
    metadata: dict[str, str]
    tool_name: str | None
    tool_input: dict[str, object] | None
    schema_version: int
    created_at: datetime
    corrupt: bool
    handoff_status: PendingApprovalHandoffStatus


class PendingApprovalStore:
    """Reads and writes durable pending-approval execution state.

    Every write here is a full insert-or-replace keyed by request_id -
    unlike ApprovalHistoryStore's own append-then-update convention, a
    row in this table is never expected to be updated in place; it is
    either freshly written (create_request) or removed entirely (decide,
    expire, or invalidate on reload).

    Attributes:
        _session_factory: Factory used to open database sessions for each
            operation.
    """

    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        """Initialise the store with a database session factory.

        Args:
            session_factory: The factory used to create sessions, typically
                produced by storage.database.create_session_factory.
        """
        self._session_factory = session_factory

    def save(
        self,
        *,
        request_id: str,
        action: str,
        reason: str,
        security_tier: str,
        session_id: int | None = None,
        metadata: dict[str, str] | None = None,
        tool_name: str | None = None,
        tool_input: dict[str, object] | None = None,
    ) -> PendingApprovalRecord:
        """Persist (or replace) the pending state for one request_id.

        Args:
            request_id: The unique id of the approval request (matches
                ApprovalRequest.request_id).
            action: The action string that requires approval.
            reason: A human-readable explanation of why approval is needed.
            security_tier: The security tier of the action, as a string
                (for example "yellow").
            session_id: Optional session the request belongs to.
            metadata: Optional copy of the request's metadata dict.
            tool_name: The tool this request would run once approved, or
                None if this request has no backing tool.
            tool_input: The tool_input dict this request would run with.
                Must be None exactly when tool_name is None.

        Returns:
            The newly stored PendingApprovalRecord.
        """
        with session_scope(self._session_factory) as db:
            existing = (
                db.query(PendingApprovalState)
                .filter(PendingApprovalState.request_id == request_id)
                .one_or_none()
            )
            if existing is not None:
                db.delete(existing)
                db.flush()

            entry = PendingApprovalState(
                request_id=request_id,
                session_id=session_id,
                action=action,
                reason=reason,
                security_tier=security_tier,
                metadata_json=json.dumps(metadata or {}),
                tool_name=tool_name,
                tool_input_json=(
                    json.dumps(tool_input) if tool_input is not None else None
                ),
                schema_version=SCHEMA_VERSION,
                handoff_status=PendingApprovalHandoffStatus.PENDING.value,
            )
            db.add(entry)
            db.flush()  # populate id and created_at before the scope commits
            return self._to_record(entry)

    def delete(self, request_id: str) -> None:
        """Remove the persisted pending state for one request_id, if any.

        A no-op if no row exists for that request_id - callers never need
        to check existence first.

        Args:
            request_id: The id of the request whose state should be removed.
        """
        with session_scope(self._session_factory) as db:
            db.query(PendingApprovalState).filter(
                PendingApprovalState.request_id == request_id
            ).delete()

    def get(self, request_id: str) -> PendingApprovalRecord | None:
        """Return a single pending-state row by its request id.

        Args:
            request_id: The approval request id to look up.

        Returns:
            The matching PendingApprovalRecord, or None if not found.
        """
        with session_scope(self._session_factory) as db:
            entry = (
                db.query(PendingApprovalState)
                .filter(PendingApprovalState.request_id == request_id)
                .one_or_none()
            )
            if entry is None:
                return None
            return self._to_record(entry)

    def list_all(self) -> list[PendingApprovalRecord]:
        """Return every currently persisted pending-approval row.

        Used only by ApprovalManager.reload_pending() at startup. Order
        is oldest-created-first, matching this project's own general
        "oldest pending first" convention (ApprovalManager.list_pending()).

        Returns:
            A list of PendingApprovalRecord objects, oldest first.
        """
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(PendingApprovalState)
                .order_by(
                    PendingApprovalState.created_at.asc(),
                    PendingApprovalState.id.asc(),
                )
                .all()
            )
            return [self._to_record(row) for row in rows]

    @staticmethod
    def _to_record(entry: PendingApprovalState) -> PendingApprovalRecord:
        """Convert an ORM entry into a detached PendingApprovalRecord.

        A malformed metadata_json/tool_input_json never raises here -
        it is reported via the record's own `corrupt` flag instead, so
        one bad row can never prevent every other valid row from being
        listed.

        Args:
            entry: The ORM PendingApprovalState instance to convert.

        Returns:
            A detached PendingApprovalRecord with the entry's data
            decoded and copied out.
        """
        corrupt = False
        metadata: dict[str, str] = {}
        tool_input: dict[str, object] | None = None

        try:
            if entry.metadata_json is not None:
                decoded = json.loads(entry.metadata_json)
                if isinstance(decoded, dict):
                    metadata = decoded
                else:
                    corrupt = True
        except (json.JSONDecodeError, TypeError):
            corrupt = True

        try:
            if entry.tool_input_json is not None:
                decoded_input = json.loads(entry.tool_input_json)
                if isinstance(decoded_input, dict):
                    tool_input = decoded_input
                else:
                    corrupt = True
        except (json.JSONDecodeError, TypeError):
            corrupt = True

        return PendingApprovalRecord(
            id=entry.id,
            request_id=entry.request_id,
            session_id=entry.session_id,
            action=entry.action,
            reason=entry.reason,
            security_tier=entry.security_tier,
            metadata=metadata,
            tool_name=entry.tool_name,
            tool_input=tool_input,
            schema_version=entry.schema_version,
            created_at=entry.created_at,
            corrupt=corrupt,
            handoff_status=PendingApprovalHandoffStatus(entry.handoff_status),
        )

    # ----- handoff-status CAS transitions (Batch 1) --------------------------
    #
    # Every method below performs exactly one atomic, database-level
    # compare-and-set UPDATE ... WHERE request_id = ? AND handoff_status =
    # <expected> - never a read-then-write pair, never an in-memory lock,
    # never a blind update. Success requires exactly one row affected;
    # rowcount 0 means the row is missing, already in a different state,
    # or another caller already transitioned it - all reported uniformly
    # as `False`, never distinguished, since distinguishing them would
    # require exactly the read-then-write race this design avoids. No
    # method here ever modifies request_id, action, reason, security_tier,
    # tool_name, tool_input_json, metadata_json, schema_version, or
    # created_at - only handoff_status changes.
    #
    # These six methods are the *only* transitions Batch 1 permits,
    # matching the plan's own allowed transition matrix exactly:
    #   PENDING -> APPROVED_UNCONSUMED, PENDING -> DECLINED,
    #   PENDING -> EXPIRED, APPROVED_UNCONSUMED -> CLAIMED,
    #   CLAIMED -> CONSUMED, CLAIMED -> CLAIM_INTERRUPTED.
    # There is no generic transition(request_id, from_status, to_status)
    # API - every other combination (a terminal state reactivating, a
    # reversal, a skip) is structurally impossible to request through
    # this store's public surface, not merely rejected at runtime.
    #
    # No live ApprovalManager code calls any of these in Batch 1 - they
    # exist only to be exercised directly by this batch's own tests,
    # ahead of a later, separately-accepted batch wiring them into the
    # live approve()/resume() lifecycle.

    def _compare_and_set(
        self,
        request_id: str,
        *,
        expected: PendingApprovalHandoffStatus,
        new: PendingApprovalHandoffStatus,
    ) -> bool:
        """Atomically transition one row's handoff_status, iff it is
        currently `expected`.

        Args:
            request_id: The row to transition.
            expected: The handoff_status the row must currently have for
                the transition to succeed.
            new: The handoff_status to set.

        Returns:
            True if exactly one row was updated; False if no row with
            that request_id currently has handoff_status == expected
            (missing row, wrong current state, or already transitioned
            by another caller).
        """
        with session_scope(self._session_factory) as db:
            result = db.execute(
                sa_update(PendingApprovalState)
                .where(
                    PendingApprovalState.request_id == request_id,
                    PendingApprovalState.handoff_status == expected.value,
                )
                .values(handoff_status=new.value)
            )
            return result.rowcount == 1

    def mark_approved_unconsumed(self, request_id: str) -> bool:
        """Transition PENDING -> APPROVED_UNCONSUMED.

        Args:
            request_id: The row to transition.

        Returns:
            True if the transition succeeded; False otherwise (see
            _compare_and_set's own docstring for why a single bool is
            the whole story).
        """
        return self._compare_and_set(
            request_id,
            expected=PendingApprovalHandoffStatus.PENDING,
            new=PendingApprovalHandoffStatus.APPROVED_UNCONSUMED,
        )

    def claim_for_resume(self, request_id: str) -> bool:
        """Transition APPROVED_UNCONSUMED -> CLAIMED.

        This is the one operation that gives a caller exclusive
        ownership of resuming this request's execution: because the
        underlying UPDATE is atomic and rowcount-checked, at most one
        concurrent caller can ever observe True for the same
        request_id - every other concurrent or later attempt observes
        False, never a second, independent "claim."

        Args:
            request_id: The row to transition.

        Returns:
            True if this call is the one that claimed the row; False
            otherwise.
        """
        return self._compare_and_set(
            request_id,
            expected=PendingApprovalHandoffStatus.APPROVED_UNCONSUMED,
            new=PendingApprovalHandoffStatus.CLAIMED,
        )

    def mark_consumed(self, request_id: str) -> bool:
        """Transition CLAIMED -> CONSUMED (terminal).

        Ownership-transfer bookkeeping only - this never implies the
        underlying tool/workflow itself succeeded; that remains owned
        by WorkflowHistoryStore/ToolResult, independently.

        Args:
            request_id: The row to transition.

        Returns:
            True if the transition succeeded; False otherwise.
        """
        return self._compare_and_set(
            request_id,
            expected=PendingApprovalHandoffStatus.CLAIMED,
            new=PendingApprovalHandoffStatus.CONSUMED,
        )

    def mark_claim_interrupted(self, request_id: str) -> bool:
        """Transition CLAIMED -> CLAIM_INTERRUPTED (terminal).

        Args:
            request_id: The row to transition.

        Returns:
            True if the transition succeeded; False otherwise.
        """
        return self._compare_and_set(
            request_id,
            expected=PendingApprovalHandoffStatus.CLAIMED,
            new=PendingApprovalHandoffStatus.CLAIM_INTERRUPTED,
        )

    def mark_declined(self, request_id: str) -> bool:
        """Transition PENDING -> DECLINED (terminal).

        Args:
            request_id: The row to transition.

        Returns:
            True if the transition succeeded; False otherwise.
        """
        return self._compare_and_set(
            request_id,
            expected=PendingApprovalHandoffStatus.PENDING,
            new=PendingApprovalHandoffStatus.DECLINED,
        )

    def mark_expired(self, request_id: str) -> bool:
        """Transition PENDING -> EXPIRED (terminal).

        Args:
            request_id: The row to transition.

        Returns:
            True if the transition succeeded; False otherwise.
        """
        return self._compare_and_set(
            request_id,
            expected=PendingApprovalHandoffStatus.PENDING,
            new=PendingApprovalHandoffStatus.EXPIRED,
        )

    def get_handoff_status(
        self, request_id: str
    ) -> PendingApprovalHandoffStatus | None:
        """Return the current handoff_status of one row, or None.

        Args:
            request_id: The approval request id to look up.

        Returns:
            The row's current PendingApprovalHandoffStatus, or None if
            no row exists for that request_id.
        """
        with session_scope(self._session_factory) as db:
            entry = (
                db.query(PendingApprovalState)
                .filter(PendingApprovalState.request_id == request_id)
                .one_or_none()
            )
            if entry is None:
                return None
            return PendingApprovalHandoffStatus(entry.handoff_status)

    def list_by_handoff_status(
        self, status: PendingApprovalHandoffStatus
    ) -> list[PendingApprovalRecord]:
        """Return every row currently in the given handoff_status,
        oldest first.

        Intended for a later, separately-accepted batch's startup
        reconciliation pass (for example, listing every CLAIMED row to
        check against workflow history) - not called by any live code
        in Batch 1.

        Args:
            status: The handoff_status to filter by.

        Returns:
            A list of matching PendingApprovalRecord objects, oldest
            created first.
        """
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(PendingApprovalState)
                .filter(PendingApprovalState.handoff_status == status.value)
                .order_by(
                    PendingApprovalState.created_at.asc(),
                    PendingApprovalState.id.asc(),
                )
                .all()
            )
            return [self._to_record(row) for row in rows]
