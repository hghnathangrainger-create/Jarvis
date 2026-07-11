"""
scheduled_inbox_notice_store.py

Data-access layer for the single, durable last-seen marker tracking
which scheduled Inbox entries the CLI has already reported to Nathan
(Phase 22, Batch 1).

Responsibilities:
    - Read the marker's current value (None if no notice has ever been
      shown).
    - Update the marker to a new highest-reported InboxEntry.id,
      creating the single underlying row on first write.

Does NOT:
    - Read, write, or know anything about InboxEntry or ScheduleEntry -
      this store's only concern is the marker integer itself. Counting
      Inbox entries against this marker is InboxStore.count_since()'s
      own responsibility (see inbox/inbox_store.py).
    - Provide a generic key/value settings API. This store has exactly
      two methods, both scoped to the one marker it owns - not a
      framework for arbitrary future settings.
    - Create a second row. There is exactly one marker row, ever;
      set_last_seen_entry_id() updates it in place, creating it only on
      the very first call.
    - Implement any read/unread, dismiss, or per-entry notification
      concept. This is a single integer, not a notification record.
"""

from __future__ import annotations

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from storage.database import session_scope
from storage.models import ScheduledInboxNoticeState


class ScheduledInboxNoticeStore:
    """Reads and updates the single, durable scheduled-Inbox-notice marker.

    Attributes:
        _session_factory: Factory used to open database sessions for
            each operation.
    """

    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        """Initialise the store with a database session factory.

        Args:
            session_factory: The factory used to create sessions,
                typically produced by storage.database.create_session_factory.
        """
        self._session_factory = session_factory

    def get_last_seen_entry_id(self) -> int | None:
        """Return the highest InboxEntry.id already reported, or None.

        Returns:
            The marker's current value, or None if no marker row exists
            yet (no notice has ever been shown).
        """
        with session_scope(self._session_factory) as db:
            row = db.query(ScheduledInboxNoticeState).first()
            return row.last_seen_entry_id if row is not None else None

    def set_last_seen_entry_id(self, entry_id: int) -> None:
        """Advance the marker to a new highest-reported InboxEntry.id.

        Creates the single underlying row on the first call; every
        subsequent call updates that same row in place - never a second
        row.

        Args:
            entry_id: The InboxEntry.id to record as the new marker
                value.
        """
        with session_scope(self._session_factory) as db:
            row = db.query(ScheduledInboxNoticeState).first()
            if row is None:
                db.add(ScheduledInboxNoticeState(last_seen_entry_id=entry_id))
            else:
                row.last_seen_entry_id = entry_id
