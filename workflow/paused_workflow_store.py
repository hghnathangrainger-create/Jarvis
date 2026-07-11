"""
paused_workflow_store.py

Data-access layer for durable paused-workflow operational state (Phase
27, Batch 2).

Responsibilities:
    - Persist the resumption state a paused workflow would need to
      safely continue after a process restart: its plan, which steps
      already completed, which step is waiting, and that step's resolved
      input.
    - Load every currently persisted row so WorkflowEngine can attempt to
      revalidate and reload it at startup.
    - Remove a row the moment its workflow resumes (successfully or not)
      or is found invalid on reload.

Does NOT:
    - Decide whether a reloaded row is safe to treat as paused. That
      revalidation - can the plan be reconstructed, is the waiting
      step's tool still registered, does its action still classify
      YELLOW, is its linked approval still genuinely pending - is
      entirely WorkflowEngine's own responsibility (reload_paused()),
      using live code and the already-reloaded ApprovalManager. This
      store only stores and retrieves plain data; it never inspects a
      ToolRegistry, a SecurityManager, or an ApprovalManager itself.
    - Execute a tool, resume a workflow, or approve/decline anything.
      Loading a row here must never, by itself, run or advance anything.
    - Replace or weaken workflow_history. This is a *different* table
      from WorkflowHistoryEntry: workflow_history is a permanent,
      read-only, non-executable lifecycle log (deliberately with no
      serialised-Plan or tool-input columns - see
      workflow_history_store.py's own module docstring); this table is
      short-lived *operational* state, deliberately authorized by Phase
      27 planning to hold the plan and resolved input needed to resume -
      and it exists only for as long as the workflow itself is genuinely
      paused. A row here is never copied into workflow_history, and
      workflow_history is never read from here.

This table's mere existence for a given workflow_id means only "this
workflow's resumption state was persisted the last time anything wrote to
this table" - never "this workflow's pause is approved" or "this workflow
is safe to resume". Row existence must never be treated as approval.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from storage.database import session_scope
from storage.models import PausedWorkflowState

#: The current schema version written to every new row. Bumped only if
#: the JSON shape of plan_steps_json/completed_outcomes_json/
#: resolved_tool_input_json ever changes in a way that would make an
#: older row unsafe to interpret with new code -
#: WorkflowEngine.reload_paused() refuses to treat a row whose
#: schema_version it does not recognise as resumable, rather than
#: guessing at an unfamiliar shape.
SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PausedWorkflowRecord:
    """A plain, detached view of a stored paused-workflow-state row.

    The store returns these instead of live ORM objects so that callers
    never depend on an open database session, and deliberately does NOT
    reconstruct real Plan/PlanStep/WorkflowStepOutcome objects itself -
    that reconstruction, and the validation it requires, belongs to
    WorkflowEngine.reload_paused() alone. `plan_steps`/
    `completed_outcomes`/`resolved_tool_input` are plain decoded
    dict/list structures; `corrupt` is set instead of raising when JSON
    decoding fails, so a single malformed row can never prevent every
    other valid row from loading.

    Attributes:
        id: The primary key of the stored row.
        workflow_id: The workflow this row describes.
        session_id: The session the workflow ran under, if any.
        request_id: The id of the linked pending approval this workflow
            is paused on.
        user_request: The original Plan.user_request text, or None if it
            could not be read (see `corrupt`).
        plan_steps: A list of plain step dicts, decoded from JSON, or
            None if decoding failed.
        completed_outcomes: A list of plain completed-outcome dicts,
            decoded from JSON, or None if decoding failed.
        waiting_step_index: The plan.steps index this workflow is
            paused on.
        resolved_tool_input: The plain input dict the waiting step would
            run with, decoded from JSON, or None if decoding failed.
        schema_version: The schema version this row was written with.
        created_at: UTC timestamp of when this row was first written.
        corrupt: True if plan_steps_json, completed_outcomes_json, or
            resolved_tool_input_json could not be decoded as valid JSON.
            When True, plan_steps/completed_outcomes/resolved_tool_input
            are all None regardless of what was actually stored - the
            caller (WorkflowEngine.reload_paused()) must treat a corrupt
            record as invalid and never resumable.
    """

    id: int
    workflow_id: str
    session_id: int | None
    request_id: str
    user_request: str | None
    plan_steps: list[dict[str, object]] | None
    completed_outcomes: list[dict[str, object]] | None
    waiting_step_index: int
    resolved_tool_input: dict[str, object] | None
    schema_version: int
    created_at: datetime
    corrupt: bool


class PausedWorkflowStore:
    """Reads and writes durable paused-workflow operational state.

    Every write here is a full insert-or-replace keyed by workflow_id -
    exactly like PendingApprovalStore's own convention, and unlike
    WorkflowHistoryStore's own append-only convention - a row in this
    table is never expected to be updated in place; it is either freshly
    written (when a workflow pauses) or removed entirely (when it
    resumes, or is invalidated on reload).

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
        workflow_id: str,
        session_id: int | None,
        request_id: str,
        user_request: str,
        plan_steps: list[dict[str, object]],
        completed_outcomes: list[dict[str, object]],
        waiting_step_index: int,
        resolved_tool_input: dict[str, object],
    ) -> PausedWorkflowRecord:
        """Persist (or replace) the paused state for one workflow_id.

        Args:
            workflow_id: The unique id of the paused workflow.
            session_id: Optional session the workflow ran under.
            request_id: The id of the linked pending approval.
            user_request: The original Plan.user_request text.
            plan_steps: A plain list of step dicts (already JSON-safe).
            completed_outcomes: A plain list of completed-outcome dicts
                (already JSON-safe).
            waiting_step_index: The plan.steps index this workflow is
                paused on.
            resolved_tool_input: The plain input dict the waiting step
                would run with.

        Returns:
            The newly stored PausedWorkflowRecord.
        """
        with session_scope(self._session_factory) as db:
            existing = (
                db.query(PausedWorkflowState)
                .filter(PausedWorkflowState.workflow_id == workflow_id)
                .one_or_none()
            )
            if existing is not None:
                db.delete(existing)
                db.flush()

            entry = PausedWorkflowState(
                workflow_id=workflow_id,
                session_id=session_id,
                request_id=request_id,
                user_request=user_request,
                plan_steps_json=json.dumps(plan_steps),
                completed_outcomes_json=json.dumps(completed_outcomes),
                waiting_step_index=waiting_step_index,
                resolved_tool_input_json=json.dumps(resolved_tool_input),
                schema_version=SCHEMA_VERSION,
            )
            db.add(entry)
            db.flush()  # populate id and created_at before the scope commits
            return self._to_record(entry)

    def delete(self, workflow_id: str) -> None:
        """Remove the persisted paused state for one workflow_id, if any.

        A no-op if no row exists for that workflow_id - callers never
        need to check existence first.

        Args:
            workflow_id: The id of the workflow whose state should be
                removed.
        """
        with session_scope(self._session_factory) as db:
            db.query(PausedWorkflowState).filter(
                PausedWorkflowState.workflow_id == workflow_id
            ).delete()

    def get(self, workflow_id: str) -> PausedWorkflowRecord | None:
        """Return a single paused-workflow-state row by its workflow id.

        Args:
            workflow_id: The workflow id to look up.

        Returns:
            The matching PausedWorkflowRecord, or None if not found.
        """
        with session_scope(self._session_factory) as db:
            entry = (
                db.query(PausedWorkflowState)
                .filter(PausedWorkflowState.workflow_id == workflow_id)
                .one_or_none()
            )
            if entry is None:
                return None
            return self._to_record(entry)

    def list_all(self) -> list[PausedWorkflowRecord]:
        """Return every currently persisted paused-workflow row.

        Used only by WorkflowEngine.reload_paused() at startup. Order is
        oldest-created-first, matching PendingApprovalStore's own
        convention.

        Returns:
            A list of PausedWorkflowRecord objects, oldest first.
        """
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(PausedWorkflowState)
                .order_by(
                    PausedWorkflowState.created_at.asc(),
                    PausedWorkflowState.id.asc(),
                )
                .all()
            )
            return [self._to_record(row) for row in rows]

    @staticmethod
    def _to_record(entry: PausedWorkflowState) -> PausedWorkflowRecord:
        """Convert an ORM entry into a detached PausedWorkflowRecord.

        A malformed plan_steps_json/completed_outcomes_json/
        resolved_tool_input_json never raises here - it is reported via
        the record's own `corrupt` flag instead, so one bad row can
        never prevent every other valid row from being listed.

        Args:
            entry: The ORM PausedWorkflowState instance to convert.

        Returns:
            A detached PausedWorkflowRecord with the entry's data
            decoded and copied out.
        """
        corrupt = False
        plan_steps: list[dict[str, object]] | None = None
        completed_outcomes: list[dict[str, object]] | None = None
        resolved_tool_input: dict[str, object] | None = None

        try:
            decoded_steps = json.loads(entry.plan_steps_json)
            if isinstance(decoded_steps, list):
                plan_steps = decoded_steps
            else:
                corrupt = True
        except (json.JSONDecodeError, TypeError):
            corrupt = True

        try:
            decoded_outcomes = json.loads(entry.completed_outcomes_json)
            if isinstance(decoded_outcomes, list):
                completed_outcomes = decoded_outcomes
            else:
                corrupt = True
        except (json.JSONDecodeError, TypeError):
            corrupt = True

        try:
            decoded_input = json.loads(entry.resolved_tool_input_json)
            if isinstance(decoded_input, dict):
                resolved_tool_input = decoded_input
            else:
                corrupt = True
        except (json.JSONDecodeError, TypeError):
            corrupt = True

        return PausedWorkflowRecord(
            id=entry.id,
            workflow_id=entry.workflow_id,
            session_id=entry.session_id,
            request_id=entry.request_id,
            user_request=entry.user_request,
            plan_steps=plan_steps,
            completed_outcomes=completed_outcomes,
            waiting_step_index=entry.waiting_step_index,
            resolved_tool_input=resolved_tool_input,
            schema_version=entry.schema_version,
            created_at=entry.created_at,
            corrupt=corrupt,
        )
