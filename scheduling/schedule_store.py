"""
schedule_store.py

Data-access layer for durable, Nathan-configured web-search-summary
schedules (Phase 21, Batch 1).

Responsibilities:
    - Create a new schedule, validating its query and time_of_day.
    - List schedules, get a single schedule by id.
    - Enable/disable a schedule (the only supported mutations).
    - Count schedules.

Does NOT:
    - Determine whether a schedule is currently due, or claim/run one -
      that logic (claim_due and the atomic guard it requires) is added
      in a later batch, once it can be verified against real SQLite
      concurrency. Batch 1 never writes to last_run_at at all.
    - Perform a web search, call AI, or write an Inbox entry.
    - Provide any update/delete/rename/reschedule method. Disabling is
      the only way to stop a schedule from running - there is no
      "delete" or "edit the query" operation, keeping the write surface
      exactly as narrow as Batch 1 needs.
    - Store or interpret anything beyond the literal query text and a
      fixed HH:MM time - no command string, no action type, no
      recurrence expression.

ScheduleEntry is the first mutable (non-append-only) durable table in
this project. This store's public API is kept deliberately narrow in
compensation - every method here is independently reviewable, and none
of them is generic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from storage.database import session_scope
from storage.models import ScheduleEntry

_MAX_LIMIT = 50

#: Strict 24-hour "HH:MM" format - seconds are never accepted, and no
#: other format (12-hour, natural language, cron expression) is parsed.
_TIME_OF_DAY_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ScheduleValidationError(ValueError):
    """Raised when a schedule's query or time_of_day is invalid.

    A distinct exception type (rather than a bare ValueError) so callers
    - in particular the schedule-creation tool - can translate it into an
    honest, specific tool-result failure without guessing at the cause
    of a generic ValueError.
    """


@dataclass(frozen=True, slots=True)
class ScheduleRecord:
    """A plain, detached view of a stored schedule.

    The store returns these instead of live ORM objects so that callers
    never depend on an open database session. The data is safe to read
    after the session that produced it has closed.

    Attributes:
        id: The primary key of the stored schedule.
        name: An optional, user-supplied label; display-only.
        query: The literal search query this schedule runs.
        time_of_day: The scheduled time, as "HH:MM" in host local time.
        enabled: Whether the schedule is currently active.
        last_run_at: UTC timestamp of the most recent claimed run, or
            None if it has never run. Always None for a schedule created
            in Batch 1, since no claim mechanism exists yet.
        created_at: UTC timestamp of when the schedule was created.
    """

    id: int
    name: str | None
    query: str
    time_of_day: str
    enabled: bool
    last_run_at: datetime | None
    created_at: datetime


class ScheduleStore:
    """Reads, creates, and enables/disables durable web-search schedules.

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

    def create(
        self, *, query: str, time_of_day: str, name: str | None = None
    ) -> ScheduleRecord:
        """Create and persist one new schedule.

        Args:
            query: The literal search query to run. Stripped of
                surrounding whitespace; never otherwise normalised, so
                its meaning is never silently changed.
            time_of_day: The scheduled time, as a strict 24-hour "HH:MM"
                string.
            name: An optional display label. Stripped; empty becomes
                None.

        Returns:
            The newly stored ScheduleRecord.

        Raises:
            ScheduleValidationError: If query is empty/whitespace-only,
                or time_of_day does not match the required "HH:MM"
                24-hour format.
        """
        clean_query = query.strip()
        if not clean_query:
            raise ScheduleValidationError("A schedule's query must not be empty.")

        clean_time = time_of_day.strip()
        if not _TIME_OF_DAY_PATTERN.match(clean_time):
            raise ScheduleValidationError(
                f"time_of_day must be a 24-hour 'HH:MM' value, got {time_of_day!r}."
            )

        clean_name = name.strip() if name else None
        clean_name = clean_name if clean_name else None

        with session_scope(self._session_factory) as db:
            entry = ScheduleEntry(
                name=clean_name,
                query=clean_query,
                time_of_day=clean_time,
                enabled=True,
            )
            db.add(entry)
            db.flush()  # populate id and created_at before the scope commits
            return self._to_record(entry)

    def list_all(self, limit: int = 50) -> list[ScheduleRecord]:
        """Return schedules ordered by id, ascending.

        A stable configuration listing, not a "most recent history"
        view - deliberately ordered oldest-created-first (by id), unlike
        every other store's newest-first convention, since schedules are
        a small, user-managed list rather than a growing history log.

        Args:
            limit: Maximum number of schedules to return. Clamped to the
                range [1, 50].

        Returns:
            A list of ScheduleRecord objects, ordered by id ascending.
        """
        safe_limit = self._clamp_limit(limit)
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(ScheduleEntry)
                .order_by(ScheduleEntry.id.asc())
                .limit(safe_limit)
                .all()
            )
            return [self._to_record(row) for row in rows]

    def get(self, schedule_id: int) -> ScheduleRecord | None:
        """Return a single schedule by its id, or None if it does not exist.

        Args:
            schedule_id: The primary key of the schedule to fetch.

        Returns:
            The matching ScheduleRecord, or None when no schedule has
            that id.
        """
        with session_scope(self._session_factory) as db:
            entry = db.get(ScheduleEntry, schedule_id)
            if entry is None:
                return None
            return self._to_record(entry)

    def enable(self, schedule_id: int) -> ScheduleRecord | None:
        """Set a schedule's enabled flag to True.

        Args:
            schedule_id: The id of the schedule to enable.

        Returns:
            The updated ScheduleRecord, or None if no schedule has that id.
        """
        with session_scope(self._session_factory) as db:
            entry = db.get(ScheduleEntry, schedule_id)
            if entry is None:
                return None
            entry.enabled = True
            db.flush()
            return self._to_record(entry)

    def disable(self, schedule_id: int) -> ScheduleRecord | None:
        """Set a schedule's enabled flag to False.

        This is the only way to stop a schedule from running - there is
        no delete method.

        Args:
            schedule_id: The id of the schedule to disable.

        Returns:
            The updated ScheduleRecord, or None if no schedule has that id.
        """
        with session_scope(self._session_factory) as db:
            entry = db.get(ScheduleEntry, schedule_id)
            if entry is None:
                return None
            entry.enabled = False
            db.flush()
            return self._to_record(entry)

    def count(self) -> int:
        """Return the total number of stored schedules.

        Returns:
            The total count of schedules, enabled or disabled.
        """
        with session_scope(self._session_factory) as db:
            return db.query(ScheduleEntry).count()

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
    def _to_record(entry: ScheduleEntry) -> ScheduleRecord:
        """Convert an ORM entry into a detached ScheduleRecord.

        Args:
            entry: The ORM ScheduleEntry instance to convert.

        Returns:
            A detached ScheduleRecord with the entry's data copied out.
        """
        return ScheduleRecord(
            id=entry.id,
            name=entry.name,
            query=entry.query,
            time_of_day=entry.time_of_day,
            enabled=entry.enabled,
            last_run_at=entry.last_run_at,
            created_at=entry.created_at,
        )
