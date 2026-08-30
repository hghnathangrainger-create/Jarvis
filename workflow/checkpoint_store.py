"""
checkpoint_store.py

SQLite-backed checkpoint persistence for DAG workflow execution.

Responsibilities:
    - Save workflow step progress after each step completes, fails, or
      is skipped, so a crashed workflow can resume from the last
      successful step.
    - Track which steps are complete, pending, running, failed, or
      skipped for a given workflow_id.
    - Provide a clean interface for the DAG engine to query and update
      step status durably.

Does NOT:
    - Execute anything or call ToolExecutor.
    - Make policy decisions about retry, rollback, or compensation.
    - Replace the existing WorkflowHistoryStore (append-only lifecycle
      events). This store is the read/write counterpart: it holds the
      mutable execution state needed for crash recovery.

Design:
    Uses SQLAlchemy with the same session_factory pattern the rest of
    the codebase already uses (EpisodicMemoryStore, WorkflowHistoryStore,
    etc.).  Each workflow gets one row per step, updated in-place as
    the step progresses.  The table is keyed on (workflow_id, step_id)
    so a single workflow can have N steps tracked independently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from storage.database import session_scope


# ---------------------------------------------------------------------------
# ORM model — imported from storage.models so Base.metadata.create_all
# picks it up automatically.
# ---------------------------------------------------------------------------

from storage.models import WorkflowCheckpointEntry as WorkflowCheckpointRow


# ---------------------------------------------------------------------------
# Public dataclass (detached view, same convention as MemoryRecord, etc.)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StepCheckpoint:
    """A plain, detached view of one step's persisted checkpoint."""

    workflow_id: str
    step_id: str
    step_number: int
    status: str
    tool_result_json: str | None
    error: str | None
    retries_used: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class WorkflowCheckpointStore:
    """Read/write store for DAG workflow step checkpoints.

    Attributes:
        _session_factory: Factory used to open database sessions.
    """

    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        """Initialise with a database session factory.

        Args:
            session_factory: Typically produced by
                storage.database.create_session_factory.
        """
        self._session_factory = session_factory

    # -- write ---------------------------------------------------------------

    def save_step(
        self,
        *,
        workflow_id: str,
        step_id: str,
        step_number: int,
        status: str,
        tool_result_json: str | None = None,
        error: str | None = None,
        retries_used: int = 0,
    ) -> StepCheckpoint:
        """Save or update the checkpoint for one step within a workflow.

        If a row for (workflow_id, step_id) already exists it is updated
        in-place; otherwise a new row is inserted.  This is an upsert.

        Args:
            workflow_id: The workflow's correlation id.
            step_id: The step's stable identifier.
            step_number: The 1-based step number.
            status: One of "pending", "running", "completed", "failed",
                "skipped", "waiting".
            tool_result_json: Optional serialised ToolResult JSON.
            error: Optional error message if the step failed.
            retries_used: How many retries have been consumed.

        Returns:
            The saved StepCheckpoint.
        """
        now = datetime.now(timezone.utc)
        with session_scope(self._session_factory) as db:
            existing = (
                db.query(WorkflowCheckpointRow)
                .filter_by(workflow_id=workflow_id, step_id=step_id)
                .first()
            )
            if existing is not None:
                existing.status = status
                existing.tool_result_json = tool_result_json
                existing.error = error
                existing.retries_used = retries_used
                existing.updated_at = now
                row = existing
            else:
                row = WorkflowCheckpointRow(
                    workflow_id=workflow_id,
                    step_id=step_id,
                    step_number=step_number,
                    status=status,
                    tool_result_json=tool_result_json,
                    error=error,
                    retries_used=retries_used,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
                db.flush()
            return self._to_checkpoint(row)

    # -- read ----------------------------------------------------------------

    def list_for_workflow(self, workflow_id: str) -> list[StepCheckpoint]:
        """Return all step checkpoints for a workflow, ordered by step_number.

        Args:
            workflow_id: The workflow to look up.

        Returns:
            A list of StepCheckpoint objects, ordered by step number.
        """
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(WorkflowCheckpointRow)
                .filter_by(workflow_id=workflow_id)
                .order_by(WorkflowCheckpointRow.step_number.asc())
                .all()
            )
            return [self._to_checkpoint(r) for r in rows]

    def get_step(
        self, workflow_id: str, step_id: str
    ) -> StepCheckpoint | None:
        """Return the checkpoint for one specific step, or None.

        Args:
            workflow_id: The workflow's correlation id.
            step_id: The step's stable identifier.

        Returns:
            The StepCheckpoint, or None if no row exists.
        """
        with session_scope(self._session_factory) as db:
            row = (
                db.query(WorkflowCheckpointRow)
                .filter_by(workflow_id=workflow_id, step_id=step_id)
                .first()
            )
            return self._to_checkpoint(row) if row is not None else None

    def get_latest_workflow_ids(self, limit: int = 50) -> list[str]:
        """Return workflow_ids that have at least one checkpoint row.

        Args:
            limit: Maximum number of distinct workflow ids.

        Returns:
            A list of workflow_id strings, most-recently-updated first.
        """
        from sqlalchemy import func

        with session_scope(self._session_factory) as db:
            rows = (
                db.query(
                    WorkflowCheckpointRow.workflow_id,
                    func.max(WorkflowCheckpointRow.updated_at).label("latest"),
                )
                .group_by(WorkflowCheckpointRow.workflow_id)
                .order_by(func.max(WorkflowCheckpointRow.updated_at).desc())
                .limit(limit)
                .all()
            )
            return [r.workflow_id for r in rows]

    # -- delete --------------------------------------------------------------

    def delete_workflow(self, workflow_id: str) -> int:
        """Remove all checkpoint rows for a workflow.

        Args:
            workflow_id: The workflow whose checkpoints to remove.

        Returns:
            The number of rows deleted.
        """
        with session_scope(self._session_factory) as db:
            count = (
                db.query(WorkflowCheckpointRow)
                .filter_by(workflow_id=workflow_id)
                .delete()
            )
            return count

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _to_checkpoint(row: WorkflowCheckpointRow) -> StepCheckpoint:
        """Convert an ORM row into a detached StepCheckpoint."""
        return StepCheckpoint(
            workflow_id=row.workflow_id,
            step_id=row.step_id,
            step_number=row.step_number,
            status=row.status,
            tool_result_json=row.tool_result_json,
            error=row.error,
            retries_used=row.retries_used,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
