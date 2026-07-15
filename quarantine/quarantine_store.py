"""
quarantine_store.py

Data-access layer for durable quarantine metadata (Phase 37, Batch 1).

Responsibilities:
    - Record one new QuarantineRecord when a file is successfully
      quarantined (write-once; there is no update method).
    - Retrieve a single record by its quarantine_path, so a restore
      command (Phase 38) or the quarantine-listing display (Phase 37,
      Batch 2) can look up a quarantined file's original location.
    - List recorded quarantine metadata, newest first, for dashboard
      display (Phase 39) - a read-only listing over the same durable
      records, never the live filesystem.
    - Report the total number of recorded quarantine entries (Phase 66,
      Batch 1) - a true, unbounded count, never clamped the way
      list_recent()'s own listing is.

Does NOT:
    - Provide any update, delete, restore, or cleanup method. This is a
      deliberate, structural guarantee of write-once semantics: since
      no such method exists on this class, nothing - not a future
      restore command, not a dashboard, not this store's own caller -
      can mutate or remove an existing row through this store, even by
      mistake.
    - Decide when to record a row, or what to do if recording fails -
      that is FileDeleteTool's own responsibility (Phase 37, Batch 1).
      This store simply persists what it is given, or raises if the
      database itself rejects the write (for example, a duplicate
      quarantine_path, which the unique column constraint refuses).
    - Assume every quarantined file has a record. Files quarantined
      before this table existed (Phase 35/36) have none;
      get_by_quarantine_path() returning None for such a file is the
      expected, ordinary case, not a failure.
    - Import ai, workflow, scheduler, dashboard/ui, inbox, or any
      permanent-delete API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from storage.database import session_scope
from storage.models import QuarantineRecord

#: Maximum number of records list_recent() will ever return in one
#: call, matching InboxStore/ScheduleStore's own established convention
#: for a bounded, dashboard-sized listing.
_MAX_LIMIT = 50


@dataclass(frozen=True, slots=True)
class QuarantineRecordView:
    """A plain, detached view of a stored quarantine record.

    The store returns these instead of live ORM objects so that callers
    never depend on an open database session.

    Attributes:
        id: The primary key of the stored record.
        original_path: The absolute, resolved path the file was
            quarantined from.
        quarantine_path: The absolute, resolved path the file was moved
            to inside the quarantine directory.
        quarantined_at: UTC timestamp of when the file was quarantined.
        session_id: The session the quarantine happened under, if any.
    """

    id: int
    original_path: str
    quarantine_path: str
    quarantined_at: datetime
    session_id: int | None


class QuarantineStore:
    """Records and retrieves durable quarantine metadata.

    Every write here is a single new row - existing rows are never
    updated or deleted. There is no restore, cleanup, or delete method
    on this class.

    Attributes:
        _session_factory: Factory used to open database sessions for
            each operation.
    """

    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        """Initialise the store with a database session factory.

        Args:
            session_factory: The factory used to create sessions,
                typically produced by
                storage.database.create_session_factory.
        """
        self._session_factory = session_factory

    def record_quarantine(
        self,
        *,
        original_path: str,
        quarantine_path: str,
        session_id: int | None = None,
    ) -> QuarantineRecordView:
        """Persist one new quarantine record.

        Args:
            original_path: The absolute, resolved path the file was
                quarantined from.
            quarantine_path: The absolute, resolved path the file was
                moved to inside the quarantine directory. Must not
                already have a record - the underlying column is
                unique, so a duplicate raises rather than silently
                overwriting or duplicating a row.
            session_id: Optional session the quarantine happened under.

        Returns:
            A detached QuarantineRecordView describing the stored
            record.

        Raises:
            sqlalchemy.exc.IntegrityError: If a record for
                quarantine_path already exists.
        """
        with session_scope(self._session_factory) as db:
            record = QuarantineRecord(
                original_path=original_path,
                quarantine_path=quarantine_path,
                session_id=session_id,
            )
            db.add(record)
            db.flush()  # populate id and quarantined_at before the scope commits
            return self._to_view(record)

    def get_by_quarantine_path(
        self, quarantine_path: str
    ) -> QuarantineRecordView | None:
        """Return the record for a given quarantine path, if any.

        Args:
            quarantine_path: The absolute, resolved quarantine path to
                look up.

        Returns:
            The matching QuarantineRecordView, or None if no record
            exists for that path - the ordinary, expected case for a
            file quarantined before this table existed.
        """
        with session_scope(self._session_factory) as db:
            record = (
                db.query(QuarantineRecord)
                .filter(QuarantineRecord.quarantine_path == quarantine_path)
                .one_or_none()
            )
            if record is None:
                return None
            return self._to_view(record)

    def count(self) -> int:
        """Return the total number of recorded quarantine entries.

        A plain, unbounded COUNT - unlike list_recent(), this is never
        clamped to _MAX_LIMIT, so it always reports the real, true total
        (Phase 66, Batch 1).

        Returns:
            The total count of recorded quarantine entries.
        """
        with session_scope(self._session_factory) as db:
            return db.query(QuarantineRecord).count()

    def list_recent(self, limit: int = 50) -> list[QuarantineRecordView]:
        """Return recorded quarantine metadata, newest first.

        A read-only listing intended for dashboard display (Phase 39).
        This reads only the durable database records already written by
        record_quarantine() - it never inspects the filesystem or
        .jarvis_trash/'s actual contents. A row here does not guarantee
        the underlying file still exists in quarantine (for example, it
        may have already been restored - Phase 38 never deletes or
        updates a QuarantineRecord on restore); reconciling database
        records against the live filesystem, if ever needed, is a
        distinct, separately-reviewed future decision.

        Args:
            limit: Maximum number of records to return. Clamped to the
                range [1, 50].

        Returns:
            A list of QuarantineRecordView objects, newest first (by
            quarantined_at, then id, both descending) - mirroring
            InboxStore.list_recent()'s own append-only-history ordering
            convention exactly, since quarantine records are likewise
            write-once and never updated.
        """
        safe_limit = self._clamp_limit(limit)
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(QuarantineRecord)
                .order_by(
                    QuarantineRecord.quarantined_at.desc(),
                    QuarantineRecord.id.desc(),
                )
                .limit(safe_limit)
                .all()
            )
            return [self._to_view(row) for row in rows]

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
    def _to_view(record: QuarantineRecord) -> QuarantineRecordView:
        """Convert an ORM record into a detached QuarantineRecordView.

        Args:
            record: The ORM QuarantineRecord instance to convert.

        Returns:
            A detached QuarantineRecordView with the record's data
            copied out.
        """
        return QuarantineRecordView(
            id=record.id,
            original_path=record.original_path,
            quarantine_path=record.quarantine_path,
            quarantined_at=record.quarantined_at,
            session_id=record.session_id,
        )
