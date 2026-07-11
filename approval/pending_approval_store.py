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

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

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
        )
