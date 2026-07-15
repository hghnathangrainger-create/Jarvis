"""
inbox_store.py

Data-access layer for the durable, append-only Jarvis inbox (Phase 20,
Batch 1; extended Phase 22, Batch 1 with a narrow, read-only count-since
query; extended Phase 65, Batch 1 with KNOWN_INBOX_SOURCE_TYPES, the
fixed vocabulary the dashboard's source-type breakdown reads via
count_since()).

Responsibilities:
    - Append one new inbox entry (write-once; there is no update method).
    - Query the inbox: most recent entries, a total count, a single
      entry by id, or a source-type-scoped count/latest-id lookup since
      a given id (Phase 22).

Does NOT:
    - Decide which command should write an entry, or when - see
      core/orchestrator.py's producer wiring (Phase 20, Batch 2) for
      that. This store has no opinion about producers at all.
    - Provide any update, delete, or read/unread-mutation method. This is
      a deliberate, structural guarantee of append-only semantics: since
      no such method exists on this class, nothing - not the dashboard,
      not a future caller - can mutate an existing row through this
      store, even by mistake.
    - Store a status or error column - every row is, by construction, a
      successful entry, since the one approved producer only ever calls
      append() after a real summary has already been produced.
    - Implement a generic notification/event framework. This store's API
      is exactly as wide as the approved single producer and single
      dashboard consumer need, no wider. count_since() (Phase 22) is a
      pure, read-only count/lookup - it never returns entry bodies or
      queries, and it requires an explicit source_type so no caller can
      accidentally count every producer's entries together.

This is the durable half of Phase 20: an AI-generated output that would
otherwise vanish with CLI scrollback survives a restart, without becoming
executable, editable, or trusted context.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from storage.database import session_scope
from storage.models import InboxEntry

_MAX_LIMIT = 50

#: The fixed, known inbox source types (Phase 65, Batch 1) - every
#: producer that has ever called append(): the interactive web-search
#: summary (Phase 20), the scheduler's own web-search summary (Phase 21),
#: and the webpage summary (Phase 61). Used by the dashboard's source-type
#: breakdown to report an honest count for every known type, including one
#: with zero entries, in a fixed, declared order - never sorted by count.
KNOWN_INBOX_SOURCE_TYPES: tuple[str, ...] = (
    "web_search_summary",
    "scheduled_web_search_summary",
    "webpage_summary",
)


@dataclass(frozen=True, slots=True)
class InboxRecord:
    """A plain, detached view of a stored inbox entry.

    The store returns these instead of live ORM objects so that callers
    never depend on an open database session. The data is safe to read
    after the session that produced it has closed.

    There is no status field and no error field on this record - every
    entry is, by construction, a successful, already-produced output (see
    storage.models.InboxEntry's own docstring for why).

    Attributes:
        id: The primary key of the stored entry.
        session_id: The session the entry was produced under, if any.
        source_type: The producer that created this entry (for example,
            "web_search_summary").
        source_query: The literal query this entry is about, stored
            verbatim.
        body: The exact final text Nathan was shown, disclosure label
            included, stored verbatim.
        included_count: The number of search results the summary was
            based on, if known.
        created_at: UTC timestamp of when this entry was saved.
    """

    id: int
    session_id: int | None
    source_type: str
    source_query: str
    body: str
    included_count: int | None
    created_at: datetime


class InboxStore:
    """Reads and appends durable inbox entries using the storage layer.

    Every write here is a single new append-only row - existing rows are
    never updated or deleted. There is no method on this class capable of
    mutating an existing entry.

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

    def append(
        self,
        *,
        source_type: str,
        source_query: str,
        body: str,
        included_count: int | None = None,
        session_id: int | None = None,
    ) -> InboxRecord:
        """Persist one new inbox entry.

        Args:
            source_type: The producer that created this entry (for
                example, "web_search_summary").
            source_query: The literal query this entry is about, stored
                verbatim.
            body: The exact final text Nathan was shown, disclosure label
                included, stored verbatim.
            included_count: The number of search results the summary was
                based on, if known.
            session_id: Optional session the entry was produced under.

        Returns:
            A detached InboxRecord describing the stored entry.
        """
        with session_scope(self._session_factory) as db:
            entry = InboxEntry(
                session_id=session_id,
                source_type=source_type,
                source_query=source_query,
                body=body,
                included_count=included_count,
            )
            db.add(entry)
            db.flush()  # populate id and created_at before the scope commits
            return self._to_record(entry)

    def list_recent(self, limit: int = 20) -> list[InboxRecord]:
        """Return the most recent inbox entries, newest first.

        Args:
            limit: Maximum number of entries to return. Clamped to the
                range [1, 50].

        Returns:
            A list of InboxRecord objects, newest first.
        """
        safe_limit = self._clamp_limit(limit)
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(InboxEntry)
                .order_by(InboxEntry.created_at.desc(), InboxEntry.id.desc())
                .limit(safe_limit)
                .all()
            )
            return [self._to_record(row) for row in rows]

    def count(self) -> int:
        """Return the total number of stored inbox entries.

        Returns:
            The total count of inbox entries.
        """
        with session_scope(self._session_factory) as db:
            return db.query(InboxEntry).count()

    def count_since(
        self, *, source_type: str, after_id: int | None
    ) -> tuple[int, int | None, datetime | None]:
        """Count entries of one source_type newer than a given id.

        A pure, read-only lookup for the Phase 22 startup notice: never
        returns an entry's body or query, and requires an explicit
        source_type so a caller can never accidentally count every
        producer's entries together.

        Args:
            source_type: The exact producer value to count (for example,
                "scheduled_web_search_summary"). Interactive entries
                (for example, "web_search_summary") are excluded unless
                this argument names them explicitly.
            after_id: Only count entries with id strictly greater than
                this value. When None, every entry of source_type is
                counted.

        Returns:
            A tuple of (count, latest_id, latest_created_at) - the
            number of matching entries, the highest id among them, and
            that entry's created_at. latest_id/latest_created_at are
            both None when count is 0.
        """
        with session_scope(self._session_factory) as db:
            query = db.query(InboxEntry).filter(
                InboxEntry.source_type == source_type
            )
            if after_id is not None:
                query = query.filter(InboxEntry.id > after_id)

            count = query.count()
            if count == 0:
                return 0, None, None

            latest = query.order_by(InboxEntry.id.desc()).first()
            assert latest is not None  # guaranteed by count > 0 above
            return count, latest.id, latest.created_at

    def get(self, entry_id: int) -> InboxRecord | None:
        """Return a single inbox entry by its id, or None if it does not exist.

        Args:
            entry_id: The primary key of the entry to fetch.

        Returns:
            The matching InboxRecord, or None when no entry has that id.
        """
        with session_scope(self._session_factory) as db:
            entry = db.get(InboxEntry, entry_id)
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
    def _to_record(entry: InboxEntry) -> InboxRecord:
        """Convert an ORM entry into a detached InboxRecord.

        Args:
            entry: The ORM InboxEntry instance to convert.

        Returns:
            A detached InboxRecord with the entry's data copied out.
        """
        return InboxRecord(
            id=entry.id,
            session_id=entry.session_id,
            source_type=entry.source_type,
            source_query=entry.source_query,
            body=entry.body,
            included_count=entry.included_count,
            created_at=entry.created_at,
        )
