"""
workflow_history_store.py

Data-access layer for durable, read-only workflow lifecycle history
(Durable Workflow Lifecycle Foundation - a prerequisite turn, not a
numbered phase).

Responsibilities:
    - Record one append-only row per workflow lifecycle transition
      (WorkflowEngine's own seven existing event names: workflow_started,
      workflow_step_started, workflow_step_completed,
      workflow_step_waiting, workflow_step_failed, workflow_completed,
      workflow_stopped).
    - Query history: most recent transitions across all workflows, the
      full transition history for one workflow, that workflow's latest
      (i.e. current) status, the ids of the most recently active
      distinct workflows (Phase 19, for the dashboard's "recent
      workflows" view), or a true, unbounded total count of distinct
      workflows (Phase 80, Batch 2, for HealthCheckTool).

Does NOT:
    - Store tool_input, resolved step input, or a serialised Plan
      anywhere. The underlying table has no such columns, so nothing
      recorded here can ever be replayed or resumed - see
      storage.models.WorkflowHistoryEntry's own docstring for why that
      boundary is deliberate.
    - Decide anything, execute anything, or approve/decline anything.
      This store only records transitions WorkflowEngine already decided
      and reports them back on request.
    - Replace the existing generic audit log (EventLogger/AuditLog).
      WorkflowEngine continues to emit its existing workflow_* audit
      events exactly as before; this store is written to additionally,
      never instead, giving a structured, workflow_id-queryable view the
      generic audit log's free-text detail field cannot provide.

This is the durable half of the Durable Workflow Lifecycle Foundation:
a workflow's lifecycle becomes permanently visible across restarts,
without making anything resumable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from storage.database import session_scope
from storage.models import WorkflowHistoryEntry

_MAX_LIMIT = 50

#: The fixed, known workflow lifecycle transition names (Phase 64,
#: Batch 1) - WorkflowEngine's own seven existing event names, exactly
#: as named in this module's own docstring above. Used by the
#: dashboard's status breakdown to report an honest count for every
#: known status, including one with zero entries, in a fixed, declared
#: order - never sorted by count.
KNOWN_WORKFLOW_STATUSES: tuple[str, ...] = (
    "workflow_started",
    "workflow_step_started",
    "workflow_step_completed",
    "workflow_step_waiting",
    "workflow_step_failed",
    "workflow_completed",
    "workflow_stopped",
)


@dataclass(frozen=True, slots=True)
class WorkflowHistoryRecord:
    """A plain, detached view of a stored workflow history entry.

    The store returns these instead of live ORM objects so that callers
    never depend on an open database session. The data is safe to read
    after the session that produced it has closed.

    There is no tool_input field and no resolved-step-input field on this
    record. That is a deliberate omission, not an oversight - see the
    module docstring and storage.models.WorkflowHistoryEntry.

    Attributes:
        id: The primary key of the stored history row.
        workflow_id: The workflow this transition belongs to.
        session_id: The session the workflow ran under, if any.
        status: The lifecycle transition name (one of WorkflowEngine's
            own seven event names).
        step_number: The 1-based step this transition concerns, or None
            for a workflow-level transition.
        step_total: The total number of steps in the plan, or None.
        tool_name: The step's tool name, or None.
        approval_request_id: The correlated approval request id, set only
            for a "workflow_step_waiting" row.
        detail: Optional short, content-free human-readable text.
        created_at: UTC timestamp of when this transition was recorded.
    """

    id: int
    workflow_id: str
    session_id: int | None
    status: str
    step_number: int | None
    step_total: int | None
    tool_name: str | None
    approval_request_id: str | None
    detail: str | None
    created_at: datetime


class WorkflowHistoryStore:
    """Reads and writes durable workflow lifecycle history.

    Every write here is a single new append-only row - existing rows are
    never updated or deleted, and nothing written here can be turned back
    into an executable action or a resumable checkpoint; the table simply
    has no columns for that.

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

    def record_transition(
        self,
        *,
        workflow_id: str,
        status: str,
        session_id: int | None = None,
        step_number: int | None = None,
        step_total: int | None = None,
        tool_name: str | None = None,
        approval_request_id: str | None = None,
        detail: str | None = None,
    ) -> WorkflowHistoryRecord:
        """Record one new workflow lifecycle transition row.

        Args:
            workflow_id: The workflow this transition belongs to.
            status: The lifecycle transition name (one of WorkflowEngine's
                own seven event names).
            session_id: Optional session the workflow ran under.
            step_number: Optional 1-based step this transition concerns.
            step_total: Optional total number of steps in the plan.
            tool_name: Optional step tool name (never its input).
            approval_request_id: Optional correlated approval request id.
            detail: Optional short, content-free human-readable text.

        Returns:
            The newly stored WorkflowHistoryRecord.
        """
        with session_scope(self._session_factory) as db:
            entry = WorkflowHistoryEntry(
                workflow_id=workflow_id,
                session_id=session_id,
                status=status,
                step_number=step_number,
                step_total=step_total,
                tool_name=tool_name,
                approval_request_id=approval_request_id,
                detail=detail,
            )
            db.add(entry)
            db.flush()  # populate id and created_at before the scope commits
            return self._to_record(entry)

    def list_recent(self, limit: int = 20) -> list[WorkflowHistoryRecord]:
        """Return the most recent transitions across all workflows, newest first.

        Args:
            limit: Maximum number of entries to return. Clamped to the
                range [1, 50].

        Returns:
            A list of WorkflowHistoryRecord objects, newest first.
        """
        safe_limit = self._clamp_limit(limit)
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(WorkflowHistoryEntry)
                .order_by(
                    WorkflowHistoryEntry.created_at.desc(),
                    WorkflowHistoryEntry.id.desc(),
                )
                .limit(safe_limit)
                .all()
            )
            return [self._to_record(row) for row in rows]

    def list_for_workflow(
        self, workflow_id: str, limit: int = 50
    ) -> list[WorkflowHistoryRecord]:
        """Return one workflow's full transition history, oldest first.

        Ordered oldest first (unlike list_recent) so the result reads as
        the chronological story of that one workflow's lifecycle.

        Args:
            workflow_id: The workflow to look up.
            limit: Maximum number of entries to return. Clamped to the
                range [1, 50].

        Returns:
            A list of matching WorkflowHistoryRecord objects, oldest
            first. An unknown workflow_id simply matches no rows.
        """
        safe_limit = self._clamp_limit(limit)
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(WorkflowHistoryEntry)
                .filter(WorkflowHistoryEntry.workflow_id == workflow_id)
                .order_by(
                    WorkflowHistoryEntry.created_at.asc(),
                    WorkflowHistoryEntry.id.asc(),
                )
                .limit(safe_limit)
                .all()
            )
            return [self._to_record(row) for row in rows]

    def latest_status_for(self, workflow_id: str) -> WorkflowHistoryRecord | None:
        """Return the most recent transition recorded for one workflow.

        A convenience read representing that workflow's "current status"
        - derived from the transition log itself, not a separately
        maintained field, so it can never drift out of sync with it.

        Args:
            workflow_id: The workflow to look up.

        Returns:
            The most recent WorkflowHistoryRecord for that workflow_id, or
            None if no row exists for it.
        """
        with session_scope(self._session_factory) as db:
            row = (
                db.query(WorkflowHistoryEntry)
                .filter(WorkflowHistoryEntry.workflow_id == workflow_id)
                .order_by(
                    WorkflowHistoryEntry.created_at.desc(),
                    WorkflowHistoryEntry.id.desc(),
                )
                .first()
            )
            if row is None:
                return None
            return self._to_record(row)

    def list_recent_workflow_ids(self, limit: int = 10) -> list[str]:
        """Return the ids of the most recently active workflows, newest first.

        Distinct workflow_ids, ordered by each workflow's own most recent
        transition - not by individual transition rows - so a workflow
        with many step transitions cannot crowd an older, distinct
        workflow out of the result window the way a naive "most recent N
        rows, deduplicated" approach would. Ties (an identical latest
        timestamp) break on that workflow's own most recent row id,
        descending, mirroring the tie-break convention every other query
        in this store already uses.

        This is a narrow, read-only addition for the dashboard's "recent
        workflows" view (Phase 19). It reinterprets no lifecycle
        semantics: the ordering key is exactly the same created_at column
        list_recent/latest_status_for already use.

        Args:
            limit: Maximum number of distinct workflow ids to return.
                Clamped to the range [1, 50].

        Returns:
            A list of distinct workflow_id strings, most recently active
            first.
        """
        safe_limit = self._clamp_limit(limit)
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(
                    WorkflowHistoryEntry.workflow_id,
                    func.max(WorkflowHistoryEntry.created_at).label(
                        "latest_created_at"
                    ),
                    func.max(WorkflowHistoryEntry.id).label("latest_id"),
                )
                .group_by(WorkflowHistoryEntry.workflow_id)
                .order_by(
                    func.max(WorkflowHistoryEntry.created_at).desc(),
                    func.max(WorkflowHistoryEntry.id).desc(),
                )
                .limit(safe_limit)
                .all()
            )
            return [row.workflow_id for row in rows]

    def count_distinct_workflows(self) -> int:
        """Return the true, unbounded total number of distinct workflows.

        A plain COUNT(DISTINCT workflow_id) - unlike
        list_recent_workflow_ids(), this is never clamped to
        _MAX_LIMIT, so it always reports the real total, mirroring
        ApprovalHistoryStore.count_by_status()'s own established
        "true, unbounded COUNT" convention (Phase 80, Batch 2). It
        counts distinct workflows, never raw transition rows - a
        workflow with many step transitions counts once, exactly like
        list_recent_workflow_ids()'s own existing distinct-workflow
        semantics.

        Returns:
            The total count of distinct workflow_id values recorded.
        """
        with session_scope(self._session_factory) as db:
            return db.query(
                func.count(func.distinct(WorkflowHistoryEntry.workflow_id))
            ).scalar()

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
    def _to_record(entry: WorkflowHistoryEntry) -> WorkflowHistoryRecord:
        """Convert an ORM entry into a detached WorkflowHistoryRecord.

        Args:
            entry: The ORM WorkflowHistoryEntry instance to convert.

        Returns:
            A detached WorkflowHistoryRecord with the entry's data copied
            out.
        """
        return WorkflowHistoryRecord(
            id=entry.id,
            workflow_id=entry.workflow_id,
            session_id=entry.session_id,
            status=entry.status,
            step_number=entry.step_number,
            step_total=entry.step_total,
            tool_name=entry.tool_name,
            approval_request_id=entry.approval_request_id,
            detail=entry.detail,
            created_at=entry.created_at,
        )
