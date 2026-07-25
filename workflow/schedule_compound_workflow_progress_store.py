"""
schedule_compound_workflow_progress_store.py

Durable, authoritative progress tracking and pure reconciliation logic
for exactly one second, still-dormant compound workflow template
(Phase 99, Batch 2 - docs/phase_99_second_compound_template_planning.md):
SCHEDULE_ENABLE -> SCHEDULE_VERIFY_ENABLED_STATE ->
SCHEDULE_SHOW_ENABLED_STATE.

A wholly separate, parallel module to
workflow/compound_workflow_progress_store.py - never a shared or
generalised progress framework. Mirrors that module's own store shape,
CAS transition contract, and status vocabulary exactly, adapted for
this template's own trusted payload (an integer schedule_id, never a
string phase value) and its own, narrower reconciliation evidence (see
reconcile_schedule_enable()'s own docstring).

Responsibilities:
    - Define the bounded, trusted vocabulary this one template's
      progress can occupy: ScheduleCompoundStepStatus,
      ScheduleCompoundOverallStatus, ScheduleCompoundVerificationOutcome.
    - Persist and retrieve ScheduleCompoundWorkflowProgress rows via
      ScheduleCompoundWorkflowProgressStore, enforcing the same small,
      explicit, monotonic transition contract with atomic,
      single-statement compare-and-set (CAS) semantics at the database
      level - never an in-memory lock, and never a read-then-write race
      window.
    - Provide reconcile_schedule_enable(), a pure, deterministic
      function that answers - honestly, and only as far as real
      evidence permits - whether a schedule-enable write appears to
      have taken effect after a restart.

Does NOT:
    - Build a generic workflow-progress framework, or rename/modify
      workflow.compound_workflow_progress_store's own table, store,
      enums, or columns - that module remains ProjectState-specific and
      completely unchanged by this batch.
    - Call SecurityManager, ApprovalManager, ToolExecutor, ScheduleStore,
      any real tool, or any AI provider. reconcile_schedule_enable() is
      a pure function of already-real values; the store only ever reads
      and writes its own narrow table.
    - Get imported by intelligence/compound_structured_output.py,
      intelligence/compound_grounding.py, intelligence/planning.py,
      core/orchestrator.py, main.py, or any other live runtime module.
      Only this module's own dedicated tests import it during Phase 99
      Batch 2 - wiring it into any live restart/execution path is a
      separately-approved, later batch's responsibility.
    - Persist unrestricted tool output, prompts, model rationale,
      assembled context, secrets, or stack traces. Only the bounded
      fields ScheduleCompoundWorkflowProgress itself declares are ever
      written.
    - Claim exactly-once execution. See reconcile_schedule_enable()'s
      own docstring for the precise, narrower claim this module
      actually supports, and its own explicit limitations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from storage.database import session_scope
from storage.models import ScheduleCompoundWorkflowProgress

#: The one, and only, trusted compound-template identity this store
#: ever accepts. Must match
#: intelligence.schedule_compound_grounding's own single entry's own
#: template_id exactly - duplicated here as an independent literal,
#: deliberately, rather than imported, mirroring
#: workflow.compound_workflow_progress_store.ALLOWED_TEMPLATE_ID's own
#: established convention (this module must never depend on
#: intelligence/) - cross-module consistency is proven by a dedicated
#: test, not by a shared import.
ALLOWED_SCHEDULE_TEMPLATE_ID = "schedule_enable_then_show_enabled_state"


class ScheduleCompoundStepStatus(Enum):
    """The bounded status vocabulary for one trusted step of this one
    template. Exactly these four members exist. A wholly separate enum
    from workflow.compound_workflow_progress_store.CompoundStepStatus -
    never shared, never imported cross-module."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ScheduleCompoundOverallStatus(Enum):
    """The bounded status vocabulary for the whole compound workflow.
    Exactly these six members exist - mirrors CompoundOverallStatus's
    own vocabulary exactly, as a wholly separate enum.

    NOT_EXECUTED: the one honest, non-execution terminal state for a
    workflow whose Step 1 approval was declined, or whose approval
    window expired, strictly before Step 1 was ever durably attempted.
    Deliberately separate from FAILED, which always means a real
    execution attempt genuinely did not succeed.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    NEEDS_RECONCILIATION = "needs_reconciliation"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_EXECUTED = "not_executed"


class ScheduleCompoundVerificationOutcome(Enum):
    """Mirrors CompoundVerificationOutcome's own bounded vocabulary for
    the subset this template's internal verification step can produce -
    never a raw metadata string, and never extended or modified
    independently."""

    VERIFIED = "verified"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class ScheduleCompoundWorkflowProgressError(Exception):
    """Raised when a requested transition is illegal, or when a
    compare-and-set precondition does not hold (an already-applied
    concurrent transition, a terminal state, or an unknown workflow_id).

    Attributes:
        reason: A short, bounded, non-sensitive description of why the
            transition was refused.
    """

    def __init__(self, reason: str) -> None:
        """Initialise the error with its bounded reason.

        Args:
            reason: A short, bounded, non-sensitive failure description.
        """
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ScheduleCompoundWorkflowProgressRecord:
    """A plain, detached view of one stored schedule-compound-workflow-
    progress row. Mirrors CompoundWorkflowProgressRecord's own
    "detached view" convention.

    Attributes:
        id: The primary key of the stored row.
        workflow_id: The workflow this row describes.
        template_id: The trusted, static template identity.
        request_id: The linked approval/paused-workflow id, if any.
        schedule_id: The exact, already-approved schedule id.
        pre_execution_enabled: The real enabled value observed
            immediately before the write step was attempted, or None.
        step_1_status: The schedule-enable write step's own status.
        step_2_status: The internal enabled-state-verification step's
            own status.
        step_2_verification_outcome: The verification outcome, or None
            before step 2 completes.
        step_3_status: The SCHEDULE_SHOW_ENABLED_STATE read step's own
            status.
        overall_status: The whole workflow's own status.
        created_at: When this row was first written.
        updated_at: When this row was last written.
    """

    id: int
    workflow_id: str
    template_id: str
    request_id: str | None
    schedule_id: int
    pre_execution_enabled: bool | None
    step_1_status: ScheduleCompoundStepStatus
    step_2_status: ScheduleCompoundStepStatus
    step_2_verification_outcome: ScheduleCompoundVerificationOutcome | None
    step_3_status: ScheduleCompoundStepStatus
    overall_status: ScheduleCompoundOverallStatus
    created_at: datetime
    updated_at: datetime


def _to_record(
    row: ScheduleCompoundWorkflowProgress,
) -> ScheduleCompoundWorkflowProgressRecord:
    """Convert a live ORM row into a detached
    ScheduleCompoundWorkflowProgressRecord.

    Args:
        row: The ORM row to snapshot, while still attached to an open
            session.

    Returns:
        A plain, immutable record safe to use after the session closes.
    """
    return ScheduleCompoundWorkflowProgressRecord(
        id=row.id,
        workflow_id=row.workflow_id,
        template_id=row.template_id,
        request_id=row.request_id,
        schedule_id=row.schedule_id,
        pre_execution_enabled=row.pre_execution_enabled,
        step_1_status=ScheduleCompoundStepStatus(row.step_1_status),
        step_2_status=ScheduleCompoundStepStatus(row.step_2_status),
        step_2_verification_outcome=(
            ScheduleCompoundVerificationOutcome(row.step_2_verification_outcome)
            if row.step_2_verification_outcome is not None
            else None
        ),
        step_3_status=ScheduleCompoundStepStatus(row.step_3_status),
        overall_status=ScheduleCompoundOverallStatus(row.overall_status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ScheduleCompoundWorkflowProgressStore:
    """Reads and writes durable, authoritative progress state for
    exactly one compound workflow template - the schedule-enable-then-
    show template. A wholly separate store from
    CompoundWorkflowProgressStore; never shares a table, session usage
    pattern, or transition method with it beyond structural similarity.

    Every transition method uses a single, atomic SQL UPDATE ... WHERE
    statement checking the row's own expected prior state - never a
    separate read-then-write pair, and never an in-memory lock - so two
    concurrent callers attempting to advance the same row from the same
    expected state can never both succeed.

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

    def create(
        self,
        *,
        workflow_id: str,
        template_id: str,
        request_id: str | None,
        schedule_id: int,
    ) -> ScheduleCompoundWorkflowProgressRecord:
        """Create a new progress row in its initial, all-pending state.

        Args:
            workflow_id: The unique workflow id this row describes.
            template_id: The trusted template identity - must equal
                ALLOWED_SCHEDULE_TEMPLATE_ID exactly.
            request_id: The linked approval/paused-workflow id, if any.
            schedule_id: The exact, already-approved schedule id -
                immutable once set.

        Returns:
            The newly created ScheduleCompoundWorkflowProgressRecord.

        Raises:
            ScheduleCompoundWorkflowProgressError: If template_id is
                not ALLOWED_SCHEDULE_TEMPLATE_ID.
        """
        if template_id != ALLOWED_SCHEDULE_TEMPLATE_ID:
            raise ScheduleCompoundWorkflowProgressError(
                f"Unsupported compound template id: {template_id!r}. "
                f"Only {ALLOWED_SCHEDULE_TEMPLATE_ID!r} is supported."
            )

        with session_scope(self._session_factory) as db:
            entry = ScheduleCompoundWorkflowProgress(
                workflow_id=workflow_id,
                template_id=template_id,
                request_id=request_id,
                schedule_id=schedule_id,
                pre_execution_enabled=None,
                step_1_status=ScheduleCompoundStepStatus.PENDING.value,
                step_2_status=ScheduleCompoundStepStatus.PENDING.value,
                step_2_verification_outcome=None,
                step_3_status=ScheduleCompoundStepStatus.PENDING.value,
                overall_status=ScheduleCompoundOverallStatus.PENDING.value,
            )
            db.add(entry)
            db.flush()
            return _to_record(entry)

    def get(
        self, workflow_id: str
    ) -> ScheduleCompoundWorkflowProgressRecord | None:
        """Return a single progress row by its workflow id.

        Args:
            workflow_id: The workflow id to look up.

        Returns:
            The matching ScheduleCompoundWorkflowProgressRecord, or None.
        """
        with session_scope(self._session_factory) as db:
            row = (
                db.query(ScheduleCompoundWorkflowProgress)
                .filter(ScheduleCompoundWorkflowProgress.workflow_id == workflow_id)
                .one_or_none()
            )
            return _to_record(row) if row is not None else None

    def list_all(self) -> list[ScheduleCompoundWorkflowProgressRecord]:
        """Return every currently persisted progress row, oldest first.

        Returns:
            A list of ScheduleCompoundWorkflowProgressRecord objects.
        """
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(ScheduleCompoundWorkflowProgress)
                .order_by(
                    ScheduleCompoundWorkflowProgress.created_at.asc(),
                    ScheduleCompoundWorkflowProgress.id.asc(),
                )
                .all()
            )
            return [_to_record(row) for row in rows]

    def _compare_and_set(
        self,
        workflow_id: str,
        *,
        expected: dict[str, str | bool | None],
        updates: dict[str, object],
    ) -> ScheduleCompoundWorkflowProgressRecord:
        """Apply `updates` in one atomic statement, only if every
        column named in `expected` currently holds its given value.

        Args:
            workflow_id: The workflow id to update.
            expected: Column name -> required current value.
            updates: Column name -> new value to write.

        Returns:
            The record after the update.

        Raises:
            ScheduleCompoundWorkflowProgressError: If no row exists for
                workflow_id, or the row's current state does not match
                every entry in `expected`.
        """
        with session_scope(self._session_factory) as db:
            stmt = sa_update(ScheduleCompoundWorkflowProgress).where(
                ScheduleCompoundWorkflowProgress.workflow_id == workflow_id
            )
            for column, expected_value in expected.items():
                stmt = stmt.where(
                    getattr(ScheduleCompoundWorkflowProgress, column)
                    == expected_value
                )
            stmt = stmt.values(**updates)

            result = db.execute(stmt)
            if result.rowcount == 0:
                exists = (
                    db.query(ScheduleCompoundWorkflowProgress.id)
                    .filter(
                        ScheduleCompoundWorkflowProgress.workflow_id == workflow_id
                    )
                    .first()
                    is not None
                )
                if not exists:
                    raise ScheduleCompoundWorkflowProgressError(
                        f"No schedule compound workflow progress row for "
                        f"workflow_id={workflow_id!r}."
                    )
                raise ScheduleCompoundWorkflowProgressError(
                    "Transition rejected: the row is not in the expected "
                    "state (an illegal transition, or a concurrent "
                    "transition already applied)."
                )

            db.flush()
            row = (
                db.query(ScheduleCompoundWorkflowProgress)
                .filter(ScheduleCompoundWorkflowProgress.workflow_id == workflow_id)
                .one()
            )
            return _to_record(row)

    def record_pre_execution_observation(
        self, workflow_id: str, *, enabled: bool
    ) -> ScheduleCompoundWorkflowProgressRecord:
        """Durably record the real, pre-execution enabled observation
        and begin step 1 (legal only from the initial, all-pending
        state).

        Args:
            workflow_id: The workflow id to update.
            enabled: The real ScheduleEntry.enabled value observed
                immediately before attempting the write.

        Returns:
            The record after the transition.

        Raises:
            ScheduleCompoundWorkflowProgressError: If step_1_status is
                not currently PENDING.
        """
        return self._compare_and_set(
            workflow_id,
            expected={
                "step_1_status": ScheduleCompoundStepStatus.PENDING.value,
                "overall_status": ScheduleCompoundOverallStatus.PENDING.value,
            },
            updates={
                "pre_execution_enabled": enabled,
                "step_1_status": ScheduleCompoundStepStatus.IN_PROGRESS.value,
                "overall_status": ScheduleCompoundOverallStatus.IN_PROGRESS.value,
            },
        )

    def mark_step_1_completed(
        self, workflow_id: str
    ) -> ScheduleCompoundWorkflowProgressRecord:
        """Mark the schedule-enable write step completed (legal only
        from step_1_status=IN_PROGRESS).

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition.

        Raises:
            ScheduleCompoundWorkflowProgressError: If step_1_status is
                not currently IN_PROGRESS.
        """
        return self._compare_and_set(
            workflow_id,
            expected={"step_1_status": ScheduleCompoundStepStatus.IN_PROGRESS.value},
            updates={"step_1_status": ScheduleCompoundStepStatus.COMPLETED.value},
        )

    def mark_step_1_failed(
        self, workflow_id: str
    ) -> ScheduleCompoundWorkflowProgressRecord:
        """Mark the schedule-enable write step failed - and the whole
        workflow failed - reached by an ordinary write-tool failure
        (legal only from step_1_status=IN_PROGRESS; never from PENDING,
        which is reserved for mark_not_executed_before_start()'s own
        decline/expiry path).

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition.

        Raises:
            ScheduleCompoundWorkflowProgressError: If step_1_status is
                not currently IN_PROGRESS.
        """
        return self._compare_and_set(
            workflow_id,
            expected={"step_1_status": ScheduleCompoundStepStatus.IN_PROGRESS.value},
            updates={
                "step_1_status": ScheduleCompoundStepStatus.FAILED.value,
                "overall_status": ScheduleCompoundOverallStatus.FAILED.value,
            },
        )

    def mark_not_executed_before_start(
        self, workflow_id: str
    ) -> ScheduleCompoundWorkflowProgressRecord:
        """Terminalize a pristine, never-attempted row as honestly
        NOT_EXECUTED: the dedicated non-execution path for a decline or
        an approval-window expiry that occurred strictly before Step 1
        was ever durably attempted.

        Idempotent: calling this a second time on a row already
        NOT_EXECUTED is a safe no-op, returning the record unchanged.

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition, or the already-
            NOT_EXECUTED record unchanged if already terminalized.

        Raises:
            ScheduleCompoundWorkflowProgressError: If no row exists for
                workflow_id, or execution has already genuinely begun
                (any step is not PENDING, or a pre-execution observation
                was already recorded) - this never overwrites real
                progress.
        """
        existing = self.get(workflow_id)
        if existing is None:
            raise ScheduleCompoundWorkflowProgressError(
                f"No schedule compound workflow progress row for "
                f"workflow_id={workflow_id!r}."
            )
        if existing.overall_status is ScheduleCompoundOverallStatus.NOT_EXECUTED:
            return existing

        return self._compare_and_set(
            workflow_id,
            expected={
                "step_1_status": ScheduleCompoundStepStatus.PENDING.value,
                "step_2_status": ScheduleCompoundStepStatus.PENDING.value,
                "step_3_status": ScheduleCompoundStepStatus.PENDING.value,
                "overall_status": ScheduleCompoundOverallStatus.PENDING.value,
                "pre_execution_enabled": None,
            },
            updates={"overall_status": ScheduleCompoundOverallStatus.NOT_EXECUTED.value},
        )

    def start_step_2(
        self, workflow_id: str
    ) -> ScheduleCompoundWorkflowProgressRecord:
        """Begin the internal enabled-state-verification step (legal
        only once step 1 has completed).

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition.

        Raises:
            ScheduleCompoundWorkflowProgressError: If step_1_status is
                not COMPLETED, or step_2_status is not PENDING.
        """
        return self._compare_and_set(
            workflow_id,
            expected={
                "step_1_status": ScheduleCompoundStepStatus.COMPLETED.value,
                "step_2_status": ScheduleCompoundStepStatus.PENDING.value,
            },
            updates={"step_2_status": ScheduleCompoundStepStatus.IN_PROGRESS.value},
        )

    def mark_step_2_completed(
        self,
        workflow_id: str,
        *,
        verification_outcome: ScheduleCompoundVerificationOutcome,
    ) -> ScheduleCompoundWorkflowProgressRecord:
        """Mark the internal enabled-state-verification step completed
        with its real, bounded outcome (legal only from
        step_2_status=IN_PROGRESS).

        When verification_outcome is not VERIFIED, the whole workflow's
        overall_status is atomically set to FAILED in the same
        transition - step 3 can never legally start afterward.

        Args:
            workflow_id: The workflow id to update.
            verification_outcome: The real, already-computed outcome -
                never a raw metadata string.

        Returns:
            The record after the transition.

        Raises:
            ScheduleCompoundWorkflowProgressError: If step_2_status is
                not currently IN_PROGRESS.
        """
        updates: dict[str, object] = {
            "step_2_status": ScheduleCompoundStepStatus.COMPLETED.value,
            "step_2_verification_outcome": verification_outcome.value,
        }
        if verification_outcome is not ScheduleCompoundVerificationOutcome.VERIFIED:
            updates["overall_status"] = ScheduleCompoundOverallStatus.FAILED.value

        return self._compare_and_set(
            workflow_id,
            expected={"step_2_status": ScheduleCompoundStepStatus.IN_PROGRESS.value},
            updates=updates,
        )

    def start_step_3(
        self, workflow_id: str
    ) -> ScheduleCompoundWorkflowProgressRecord:
        """Begin the SCHEDULE_SHOW_ENABLED_STATE read step (legal only
        once step 2 has completed with outcome VERIFIED).

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition.

        Raises:
            ScheduleCompoundWorkflowProgressError: If step_2_status is
                not COMPLETED, step_2_verification_outcome is not
                VERIFIED, or step_3_status is not PENDING.
        """
        return self._compare_and_set(
            workflow_id,
            expected={
                "step_2_status": ScheduleCompoundStepStatus.COMPLETED.value,
                "step_2_verification_outcome": (
                    ScheduleCompoundVerificationOutcome.VERIFIED.value
                ),
                "step_3_status": ScheduleCompoundStepStatus.PENDING.value,
            },
            updates={"step_3_status": ScheduleCompoundStepStatus.IN_PROGRESS.value},
        )

    def mark_step_3_completed(
        self, workflow_id: str
    ) -> ScheduleCompoundWorkflowProgressRecord:
        """Mark the SCHEDULE_SHOW_ENABLED_STATE step completed and the
        whole workflow completed (legal only from
        step_3_status=IN_PROGRESS).

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition.

        Raises:
            ScheduleCompoundWorkflowProgressError: If step_3_status is
                not currently IN_PROGRESS.
        """
        return self._compare_and_set(
            workflow_id,
            expected={"step_3_status": ScheduleCompoundStepStatus.IN_PROGRESS.value},
            updates={
                "step_3_status": ScheduleCompoundStepStatus.COMPLETED.value,
                "overall_status": ScheduleCompoundOverallStatus.COMPLETED.value,
            },
        )

    def mark_step_3_failed(
        self, workflow_id: str
    ) -> ScheduleCompoundWorkflowProgressRecord:
        """Mark the SCHEDULE_SHOW_ENABLED_STATE step failed - genuine
        partial completion: the enable and its verification already
        succeeded (legal only from step_3_status=IN_PROGRESS).

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition.

        Raises:
            ScheduleCompoundWorkflowProgressError: If step_3_status is
                not currently IN_PROGRESS.
        """
        return self._compare_and_set(
            workflow_id,
            expected={"step_3_status": ScheduleCompoundStepStatus.IN_PROGRESS.value},
            updates={
                "step_3_status": ScheduleCompoundStepStatus.FAILED.value,
                "overall_status": ScheduleCompoundOverallStatus.FAILED.value,
            },
        )

    def mark_needs_reconciliation(
        self, workflow_id: str
    ) -> ScheduleCompoundWorkflowProgressRecord:
        """Flag a row as needing reconciliation - for operator
        visibility only; never blocks the safe, automatic
        reconciliation logic this module also provides. Illegal once
        the workflow has already reached a terminal state.

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition.

        Raises:
            ScheduleCompoundWorkflowProgressError: If overall_status is
                already COMPLETED or FAILED.
        """
        record = self.get(workflow_id)
        if record is None:
            raise ScheduleCompoundWorkflowProgressError(
                f"No schedule compound workflow progress row for "
                f"workflow_id={workflow_id!r}."
            )
        if record.overall_status in (
            ScheduleCompoundOverallStatus.COMPLETED,
            ScheduleCompoundOverallStatus.FAILED,
        ):
            raise ScheduleCompoundWorkflowProgressError(
                "Transition rejected: a terminal workflow cannot be marked "
                "as needing reconciliation."
            )
        return self._compare_and_set(
            workflow_id,
            expected={"overall_status": record.overall_status.value},
            updates={
                "overall_status": ScheduleCompoundOverallStatus.NEEDS_RECONCILIATION.value
            },
        )


class ScheduleReconciliationConfidence(Enum):
    """The bounded, honest vocabulary reconcile_schedule_enable() may
    report. Deliberately never a bare boolean, and deliberately never
    an "executed exactly once" claim.

    Attributes:
        POSTCONDITION_NOT_SATISFIED: The durable enabled value is not
            True - the enable has definitely not taken effect (whether
            never attempted, or superseded by an independent disable).
        POSTCONDITION_SATISFIED_STATE_CHANGED: The durable enabled value
            is True, AND the pre-execution observation was False - a
            real change occurred; the enable appears to have taken
            effect.
        POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED: The durable
            enabled value is already True, and the pre-execution
            observation was also True (or was never recorded) - nothing
            distinguishes "the tool executed and trivially re-enabled an
            already-enabled schedule" from "the tool never executed at
            all, and the schedule was already enabled beforehand."
            Unlike reconcile_phase_update()'s own equivalent ambiguous
            case, ScheduleEntry has no updated_at/version column to
            consult as a further tie-breaker (see
            ScheduleCompoundWorkflowProgress's own docstring) - so this
            case is reported honestly as unconfirmed, with no further
            evidence ever available to narrow it further.
    """

    POSTCONDITION_NOT_SATISFIED = "postcondition_not_satisfied"
    POSTCONDITION_SATISFIED_STATE_CHANGED = "postcondition_satisfied_state_changed"
    POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED = (
        "postcondition_satisfied_execution_unconfirmed"
    )


@dataclass(frozen=True, slots=True)
class ScheduleEnableReconciliation:
    """The result of one reconcile_schedule_enable() call.

    Attributes:
        confidence: The single, bounded ScheduleReconciliationConfidence
            value.
        detail: A short, honest, human-readable explanation - never a
            raw exception, raw tool output, or fabricated claim.
    """

    confidence: ScheduleReconciliationConfidence
    detail: str


def reconcile_schedule_enable(
    *,
    pre_execution_enabled: bool | None,
    current_enabled: bool | None,
) -> ScheduleEnableReconciliation:
    """Determine, honestly and only as far as real evidence permits,
    whether a schedule-enable write appears to have taken effect after
    a restart.

    This is a pure function - it never calls ScheduleStore, ToolExecutor,
    ApprovalManager, or any tool itself; the caller (a later, separately-
    approved batch) is responsible for supplying already-observed, real
    values. It never claims "executed exactly once" merely because the
    final durable value is True - see ScheduleReconciliationConfidence's
    own docstring for the precise, narrower distinctions this function
    draws instead, and its own explicit note about the one further
    tie-breaker (a changed last_updated timestamp) that
    reconcile_phase_update() has available and this function does not,
    since ScheduleEntry carries no such column.

    Args:
        pre_execution_enabled: The real ScheduleEntry.enabled value
            observed immediately before the write was attempted, or
            None if never recorded.
        current_enabled: The real, current ScheduleEntry.enabled value,
            observed now (at reconciliation time), or None if no
            schedule with that id exists at all.

    Returns:
        A ScheduleEnableReconciliation with the single, honest, bounded
        confidence level and a human-readable detail.
    """
    if current_enabled is not True:
        detail = (
            "the durable schedule is not enabled - the enable has "
            "definitely not taken effect (whether never attempted, "
            "superseded by an independent disable, or the schedule no "
            "longer exists)"
        )
        return ScheduleEnableReconciliation(
            ScheduleReconciliationConfidence.POSTCONDITION_NOT_SATISFIED, detail
        )

    # current_enabled is True from here on.
    if pre_execution_enabled is False:
        return ScheduleEnableReconciliation(
            ScheduleReconciliationConfidence.POSTCONDITION_SATISFIED_STATE_CHANGED,
            "the durable schedule changed from disabled to enabled; the "
            "enable appears to have taken effect",
        )

    return ScheduleEnableReconciliation(
        ScheduleReconciliationConfidence.POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED,
        "the durable schedule is enabled, but either no pre-execution "
        "observation was recorded or it was already enabled beforehand, "
        "and no further evidence (no comparable timestamp column exists "
        "on this table) can confirm whether the enable tool executed",
    )
