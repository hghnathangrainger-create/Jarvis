"""
project_state_store.py

Data-access layer for the single, durable, manually-maintained record
of Jarvis's project context (Phase 89, Batch 1).

Responsibilities:
    - Read the record's current fields (all None if never written).
    - Update exactly one field at a time, creating the single
      underlying row on first write, and refreshing last_updated on
      every write.

Does NOT:
    - Inspect git, a subprocess, the filesystem, or any live process
      state to populate any field - every value comes only from an
      explicit update() call, itself only ever triggered by Nathan's
      own "update jarvis project state: <field>=<value>" command
      (see tools/builtin/project_state_update_tool.py).
    - Provide a generic key/value settings API. This store has exactly
      the five known fields (branch, phase, commit, suite_result,
      focus) plus last_updated - not a framework for arbitrary future
      fields.
    - Create a second row. There is exactly one project-state row,
      ever; update() updates it in place, creating it only on the very
      first call - mirroring ScheduledInboxNoticeStore's own
      established "query-first, insert-if-absent, else mutate" pattern.
    - Return a live ORM object from any public method. Every method
      returns a plain, detached ProjectStateRecord snapshot instead,
      mirroring MemoryRecord's own established "detached view" pattern
      - callers never depend on an open database session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from storage.database import session_scope
from storage.models import ProjectState

#: The only model attribute names update() accepts. "suite" vs.
#: "suite_result" grammar-to-column name mapping is owned by
#: ProjectStateUpdateTool, not this store - this store only ever knows
#: about its own real column names.
UPDATABLE_FIELDS: frozenset[str] = frozenset(
    {"branch", "phase", "commit", "suite_result", "focus"}
)


@dataclass(frozen=True, slots=True)
class ProjectStateRecord:
    """A plain, detached view of the current project-state record.

    The store returns this instead of the live ORM object so callers
    never depend on an open database session - mirrors MemoryRecord's
    own established "detached view" pattern (memory/episodic_memory.py).

    Attributes:
        branch: The current git branch name, as manually recorded, or
            None if never recorded.
        phase: The latest closed phase, as manually recorded, or None.
        commit: The latest closed commit hash, as manually recorded,
            or None.
        suite_result: The latest full test-suite result, as manually
            recorded, or None.
        focus: The current focus/next goal, as manually recorded, or
            None.
        last_updated: When this record was last written (UTC), or None
            if never written - meaning only "when this stored record
            was last updated," never a live git/test-run timestamp.
    """

    branch: str | None
    phase: str | None
    commit: str | None
    suite_result: str | None
    focus: str | None
    last_updated: datetime | None


def _to_record(row: ProjectState) -> ProjectStateRecord:
    """Build a detached ProjectStateRecord snapshot from a live row.

    Args:
        row: The ORM row to snapshot, while still attached to an open
            session.

    Returns:
        A plain, immutable ProjectStateRecord safe to use after the
        session closes.
    """
    return ProjectStateRecord(
        branch=row.branch,
        phase=row.phase,
        commit=row.commit,
        suite_result=row.suite_result,
        focus=row.focus,
        last_updated=row.last_updated,
    )


class ProjectStateStore:
    """Reads and updates the single, durable project-state record.

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

    def get(self) -> ProjectStateRecord | None:
        """Return the current project-state record, or None.

        Returns:
            A ProjectStateRecord snapshot of the single row, or None if
            no row exists yet (update() has never been called).
        """
        with session_scope(self._session_factory) as db:
            row = db.query(ProjectState).first()
            return _to_record(row) if row is not None else None

    def update(self, field: str, value: str) -> ProjectStateRecord:
        """Set one field of the project-state record to a new value.

        Creates the single underlying row on the first call; every
        subsequent call updates that same row in place - never a
        second row. Always refreshes last_updated to the current time,
        since this timestamp means only "when this stored record was
        last updated," never a live git/test-run timestamp.

        Args:
            field: The model attribute name to set - must be one of
                UPDATABLE_FIELDS. ProjectStateUpdateTool already
                validates the user-facing grammar field name (and maps
                "suite" to "suite_result") before ever calling this
                method; this check is a defensive second layer, not
                the primary validation.
            value: The new value to store, preserved verbatim.

        Returns:
            A ProjectStateRecord snapshot of the row after the update.

        Raises:
            ValueError: If field is not a member of UPDATABLE_FIELDS.
        """
        if field not in UPDATABLE_FIELDS:
            raise ValueError(f"Unknown project-state field: {field!r}")

        with session_scope(self._session_factory) as db:
            row = db.query(ProjectState).first()
            if row is None:
                row = ProjectState()
                db.add(row)
            setattr(row, field, value)
            row.last_updated = datetime.now(timezone.utc)
            return _to_record(row)
