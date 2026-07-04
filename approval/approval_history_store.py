"""
approval_history_store.py

Data-access layer for durable, read-only approval history (Phase 6, Batch 1).

Responsibilities:
    - Record a newly created approval request as a pending history row.
    - Update a history row with its final outcome once a decision is made.
    - Query history: most recent, most recent N, filtered by status, or a
      single entry by request id.

Does NOT:
    - Store a tool_name or tool_input anywhere. The underlying table has no
      such columns, and no method here accepts or returns one. History rows
      describe what was asked and how it was decided; they are never enough,
      by themselves, to re-run or replay the original action.
    - Decide anything. This store never approves, declines, creates, or
      executes an action - it only records outcomes that ApprovalManager
      already decided, and reports them back on request.
    - Rehydrate ApprovalManager's in-memory pending requests. There is no
      "list pending for resumption" method here, on purpose: a restart clears
      pending approvals exactly as it always has, and only the historical
      record of past requests and decisions survives in this table.

This is the durable half of Phase 6 Batch 1: approval decisions become
permanently visible across restarts, without making anything resumable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from storage.database import session_scope
from storage.models import ApprovalHistoryEntry

_MAX_LIMIT = 50


@dataclass(frozen=True, slots=True)
class ApprovalHistoryRecord:
    """A plain, detached view of a stored approval history entry.

    The store returns these instead of live ORM objects so that callers never
    depend on an open database session. The data is safe to read after the
    session that produced it has closed.

    There is no tool_name field and no tool_input field on this record. That
    is a deliberate omission, not an oversight - see the module docstring.

    Attributes:
        id: The primary key of the stored history row.
        request_id: The approval request id this entry describes.
        session_id: The session the request belonged to, if any.
        action: The action string that required approval.
        reason: A human-readable explanation of why approval was needed.
        security_tier: The tier of the action, as a string (e.g. "yellow").
        status: The lifecycle state - "pending", "approved", or "declined".
        created_at: UTC timestamp of when the request was created.
        decided_at: UTC timestamp of when the request was decided, or None
            while still pending.
        decided_by: Who decided it, or None while still pending.
        decision_reason: An optional explanation supplied with the decision.
    """

    id: int
    request_id: str
    session_id: int | None
    action: str
    reason: str
    security_tier: str
    status: str
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    decision_reason: str | None


class ApprovalHistoryStore:
    """Reads and writes durable approval history using the storage layer.

    Every write here is append-then-update: a request is recorded once as
    "pending", and later, at most once, that same row is updated with its
    final outcome. Nothing is ever deleted, and nothing written here can be
    turned back into an executable action - the table simply has no columns
    for that.

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

    def record_request(
        self,
        *,
        request_id: str,
        action: str,
        reason: str,
        security_tier: str,
        session_id: int | None = None,
    ) -> ApprovalHistoryRecord:
        """Record a newly created approval request as a pending history row.

        Args:
            request_id: The unique id of the approval request (matches
                ApprovalRequest.request_id).
            action: The action string that requires approval.
            reason: A human-readable explanation of why approval is needed.
            security_tier: The security tier of the action, as a string
                (for example "yellow").
            session_id: Optional session the request belongs to.

        Returns:
            The newly stored ApprovalHistoryRecord, with status "pending".
        """
        with session_scope(self._session_factory) as db:
            entry = ApprovalHistoryEntry(
                request_id=request_id,
                session_id=session_id,
                action=action,
                reason=reason,
                security_tier=security_tier,
                status="pending",
            )
            db.add(entry)
            db.flush()  # populate id and created_at before the scope commits
            return self._to_record(entry)

    def record_decision(
        self,
        *,
        request_id: str,
        approved: bool,
        decided_by: str,
        decided_at: datetime,
        reason: str | None = None,
    ) -> ApprovalHistoryRecord | None:
        """Update a history row with its final decision.

        Args:
            request_id: The id of the request that was decided.
            approved: True if the request was approved, False if declined.
            decided_by: Who made the decision (for example, "user").
            decided_at: UTC timestamp of when the decision was made.
            reason: Optional explanation supplied with the decision.

        Returns:
            The updated ApprovalHistoryRecord, or None if no history row
            exists for that request_id (for example, a request created before
            history recording existed).
        """
        with session_scope(self._session_factory) as db:
            entry = (
                db.query(ApprovalHistoryEntry)
                .filter(ApprovalHistoryEntry.request_id == request_id)
                .one_or_none()
            )
            if entry is None:
                return None
            entry.status = "approved" if approved else "declined"
            entry.decided_by = decided_by
            entry.decided_at = decided_at
            entry.decision_reason = reason
            db.flush()
            return self._to_record(entry)

    def list_recent(self, limit: int = 20) -> list[ApprovalHistoryRecord]:
        """Return the most recent history entries, newest first, any status.

        Args:
            limit: Maximum number of entries to return. Clamped to the range
                [1, 50].

        Returns:
            A list of ApprovalHistoryRecord objects, newest first.
        """
        safe_limit = self._clamp_limit(limit)
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(ApprovalHistoryEntry)
                .order_by(
                    ApprovalHistoryEntry.created_at.desc(),
                    ApprovalHistoryEntry.id.desc(),
                )
                .limit(safe_limit)
                .all()
            )
            return [self._to_record(row) for row in rows]

    def list_by_status(
        self, status: str, limit: int = 20
    ) -> list[ApprovalHistoryRecord]:
        """Return history entries with the given status, newest first.

        Args:
            status: One of "pending", "approved", "declined".
            limit: Maximum number of entries to return. Clamped to the range
                [1, 50].

        Returns:
            A list of matching ApprovalHistoryRecord objects, newest first. An
            unrecognised status simply matches no rows.
        """
        safe_limit = self._clamp_limit(limit)
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(ApprovalHistoryEntry)
                .filter(ApprovalHistoryEntry.status == status)
                .order_by(
                    ApprovalHistoryEntry.created_at.desc(),
                    ApprovalHistoryEntry.id.desc(),
                )
                .limit(safe_limit)
                .all()
            )
            return [self._to_record(row) for row in rows]

    def get(self, request_id: str) -> ApprovalHistoryRecord | None:
        """Return a single history entry by its request id.

        Args:
            request_id: The approval request id to look up.

        Returns:
            The matching ApprovalHistoryRecord, or None if not found.
        """
        with session_scope(self._session_factory) as db:
            entry = (
                db.query(ApprovalHistoryEntry)
                .filter(ApprovalHistoryEntry.request_id == request_id)
                .one_or_none()
            )
            if entry is None:
                return None
            return self._to_record(entry)

    @staticmethod
    def _clamp_limit(value: int) -> int:
        """Clamp a requested limit into a safe range.

        Args:
            value: The requested limit.

        Returns:
            An integer between 1 and _MAX_LIMIT, inclusive.
        """
        if value < 1:
            return 1
        if value > _MAX_LIMIT:
            return _MAX_LIMIT
        return value

    @staticmethod
    def _to_record(entry: ApprovalHistoryEntry) -> ApprovalHistoryRecord:
        """Convert an ORM entry into a detached ApprovalHistoryRecord.

        Args:
            entry: The ORM ApprovalHistoryEntry instance to convert.

        Returns:
            A detached ApprovalHistoryRecord with the entry's data copied out.
        """
        return ApprovalHistoryRecord(
            id=entry.id,
            request_id=entry.request_id,
            session_id=entry.session_id,
            action=entry.action,
            reason=entry.reason,
            security_tier=entry.security_tier,
            status=entry.status,
            created_at=entry.created_at,
            decided_at=entry.decided_at,
            decided_by=entry.decided_by,
            decision_reason=entry.decision_reason,
        )