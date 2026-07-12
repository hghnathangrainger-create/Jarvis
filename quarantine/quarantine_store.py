"""
quarantine_store.py

Data-access layer for durable quarantine metadata (Phase 37, Batch 1).

Responsibilities:
    - Record one new QuarantineRecord when a file is successfully
      quarantined (write-once; there is no update method).
    - Retrieve a single record by its quarantine_path, for a future
      restore command (or Batch 2's own display extension) to look up
      a quarantined file's original location.

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
