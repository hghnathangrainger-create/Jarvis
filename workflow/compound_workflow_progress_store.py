"""
compound_workflow_progress_store.py

Durable, authoritative progress tracking and pure reconciliation logic
for exactly one future, not-yet-live compound workflow template (Phase
98, Batch 1 - docs/phase_98_implementation_plan.md):
PROJECT_STATE_UPDATE_PHASE -> internal phase verification ->
PROJECT_STATE_SHOW.

Responsibilities:
    - Define the bounded, trusted vocabulary this one template's
      progress can occupy: CompoundStepStatus, CompoundOverallStatus,
      CompoundVerificationOutcome.
    - Persist and retrieve CompoundWorkflowProgress rows via
      CompoundWorkflowProgressStore, enforcing a small, explicit,
      monotonic transition contract with atomic, single-statement
      compare-and-set (CAS) semantics at the database level - never an
      in-memory lock, and never a read-then-write race window.
    - Provide reconcile_phase_update(), a pure, deterministic function
      that answers - honestly, and only as far as real evidence
      permits - whether a phase-update write appears to have taken
      effect after a restart, without ever claiming "executed exactly
      once" merely because the final durable value matches the
      approved one.

Does NOT:
    - Build a generic workflow-progress framework. Every status value,
      column, and transition here is specific to this one template's
      own three trusted steps - a second template is not supported by
      this module and would require a fresh, separate review.
    - Call SecurityManager, ApprovalManager, ToolExecutor, any real
      tool, or any AI provider. reconcile_phase_update() is a pure
      function of already-real values; the store only ever reads and
      writes its own narrow table.
    - Get imported by intelligence/compound_structured_output.py,
      intelligence/compound_grounding.py, intelligence/planning.py,
      core/orchestrator.py, main.py, or any other live runtime module.
      Only this module's own dedicated tests import it during Phase 98
      Batch 1 - wiring it into any live restart/execution path is a
      separately-approved, later batch's responsibility.
    - Persist unrestricted tool output, prompts, model rationale,
      assembled context, secrets, or stack traces. Only the bounded
      fields CompoundWorkflowProgress itself declares are ever written
      - see storage/models.py's own docstring for the exact list.
    - Claim exactly-once execution. See reconcile_phase_update()'s own
      docstring for the precise, narrower claim this module actually
      supports, and its own explicit limitations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from storage.database import session_scope
from storage.models import CompoundWorkflowProgress

#: The one, and only, trusted compound-template identity this store
#: ever accepts. Must match
#: intelligence.compound_grounding._ALLOWED_COMPOUND_TEMPLATES's own
#: single entry's own template_id exactly - duplicated here as an
#: independent literal, deliberately, rather than imported, since this
#: module must never depend on intelligence/ (see this module's own
#: "Does NOT" list) - cross-module consistency is proven by a dedicated
#: test, not by a shared import.
ALLOWED_TEMPLATE_ID = "project_state_update_phase_then_show"


class CompoundStepStatus(Enum):
    """The bounded status vocabulary for one trusted step of this one
    template. Exactly these four members exist."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class CompoundOverallStatus(Enum):
    """The bounded status vocabulary for the whole compound workflow.
    Exactly these five members exist."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    NEEDS_RECONCILIATION = "needs_reconciliation"
    COMPLETED = "completed"
    FAILED = "failed"


class CompoundVerificationOutcome(Enum):
    """Mirrors intelligence.verification.VerificationOutcome's own
    bounded vocabulary for the subset this template's internal
    verification step can produce - never a raw metadata string, and
    never extended or modified independently of that module's own
    taxonomy."""

    VERIFIED = "verified"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class CompoundWorkflowProgressError(Exception):
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
class CompoundWorkflowProgressRecord:
    """A plain, detached view of one stored compound-workflow-progress
    row. Mirrors PausedWorkflowRecord's own "detached view" convention.

    Attributes:
        id: The primary key of the stored row.
        workflow_id: The workflow this row describes.
        template_id: The trusted, static template identity.
        request_id: The linked approval/paused-workflow id, if any.
        approved_phase_value: The exact, already-approved phase value.
        pre_execution_phase_value: The real phase value observed
            immediately before the write step was attempted, or None.
        pre_execution_last_updated: The real last_updated timestamp
            observed at the same moment, or None.
        step_1_status: The phase-update write step's own status.
        step_2_status: The internal phase-verification step's own status.
        step_2_verification_outcome: The verification outcome, or None
            before step 2 completes.
        step_3_status: The ProjectState-show read step's own status.
        overall_status: The whole workflow's own status.
        created_at: When this row was first written.
        updated_at: When this row was last written.
    """

    id: int
    workflow_id: str
    template_id: str
    request_id: str | None
    approved_phase_value: str
    pre_execution_phase_value: str | None
    pre_execution_last_updated: datetime | None
    step_1_status: CompoundStepStatus
    step_2_status: CompoundStepStatus
    step_2_verification_outcome: CompoundVerificationOutcome | None
    step_3_status: CompoundStepStatus
    overall_status: CompoundOverallStatus
    created_at: datetime
    updated_at: datetime


def _to_record(row: CompoundWorkflowProgress) -> CompoundWorkflowProgressRecord:
    """Convert a live ORM row into a detached CompoundWorkflowProgressRecord.

    Args:
        row: The ORM row to snapshot, while still attached to an open
            session.

    Returns:
        A plain, immutable record safe to use after the session closes.
    """
    return CompoundWorkflowProgressRecord(
        id=row.id,
        workflow_id=row.workflow_id,
        template_id=row.template_id,
        request_id=row.request_id,
        approved_phase_value=row.approved_phase_value,
        pre_execution_phase_value=row.pre_execution_phase_value,
        pre_execution_last_updated=row.pre_execution_last_updated,
        step_1_status=CompoundStepStatus(row.step_1_status),
        step_2_status=CompoundStepStatus(row.step_2_status),
        step_2_verification_outcome=(
            CompoundVerificationOutcome(row.step_2_verification_outcome)
            if row.step_2_verification_outcome is not None
            else None
        ),
        step_3_status=CompoundStepStatus(row.step_3_status),
        overall_status=CompoundOverallStatus(row.overall_status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class CompoundWorkflowProgressStore:
    """Reads and writes durable, authoritative progress state for
    exactly one compound workflow template.

    Every transition method uses a single, atomic SQL UPDATE ... WHERE
    statement checking the row's own expected prior state - never a
    separate read-then-write pair, and never an in-memory lock - so
    two concurrent callers attempting to advance the same row from the
    same expected state can never both succeed: the second caller's
    UPDATE always affects zero rows once the first has committed, and
    is reported as a rejected transition, never silently ignored or
    silently duplicated.

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
        approved_phase_value: str,
    ) -> CompoundWorkflowProgressRecord:
        """Create a new progress row in its initial, all-pending state.

        Args:
            workflow_id: The unique workflow id this row describes.
            template_id: The trusted template identity - must equal
                ALLOWED_TEMPLATE_ID exactly.
            request_id: The linked approval/paused-workflow id, if any.
            approved_phase_value: The exact, already-approved phase
                value - immutable once set.

        Returns:
            The newly created CompoundWorkflowProgressRecord.

        Raises:
            CompoundWorkflowProgressError: If template_id is not
                ALLOWED_TEMPLATE_ID.
        """
        if template_id != ALLOWED_TEMPLATE_ID:
            raise CompoundWorkflowProgressError(
                f"Unsupported compound template id: {template_id!r}. "
                f"Only {ALLOWED_TEMPLATE_ID!r} is supported."
            )

        with session_scope(self._session_factory) as db:
            entry = CompoundWorkflowProgress(
                workflow_id=workflow_id,
                template_id=template_id,
                request_id=request_id,
                approved_phase_value=approved_phase_value,
                pre_execution_phase_value=None,
                pre_execution_last_updated=None,
                step_1_status=CompoundStepStatus.PENDING.value,
                step_2_status=CompoundStepStatus.PENDING.value,
                step_2_verification_outcome=None,
                step_3_status=CompoundStepStatus.PENDING.value,
                overall_status=CompoundOverallStatus.PENDING.value,
            )
            db.add(entry)
            db.flush()
            return _to_record(entry)

    def get(self, workflow_id: str) -> CompoundWorkflowProgressRecord | None:
        """Return a single progress row by its workflow id.

        Args:
            workflow_id: The workflow id to look up.

        Returns:
            The matching CompoundWorkflowProgressRecord, or None.
        """
        with session_scope(self._session_factory) as db:
            row = (
                db.query(CompoundWorkflowProgress)
                .filter(CompoundWorkflowProgress.workflow_id == workflow_id)
                .one_or_none()
            )
            return _to_record(row) if row is not None else None

    def list_all(self) -> list[CompoundWorkflowProgressRecord]:
        """Return every currently persisted progress row, oldest first.

        Returns:
            A list of CompoundWorkflowProgressRecord objects.
        """
        with session_scope(self._session_factory) as db:
            rows = (
                db.query(CompoundWorkflowProgress)
                .order_by(
                    CompoundWorkflowProgress.created_at.asc(),
                    CompoundWorkflowProgress.id.asc(),
                )
                .all()
            )
            return [_to_record(row) for row in rows]

    def _compare_and_set(
        self,
        workflow_id: str,
        *,
        expected: dict[str, str | None],
        updates: dict[str, object],
    ) -> CompoundWorkflowProgressRecord:
        """Apply `updates` in one atomic statement, only if every
        column named in `expected` currently holds its given value.

        Args:
            workflow_id: The workflow id to update.
            expected: Column name -> required current value (a plain
                string, matching the enum's own .value, or None).
            updates: Column name -> new value to write.

        Returns:
            The record after the update.

        Raises:
            CompoundWorkflowProgressError: If no row exists for
                workflow_id, or the row's current state does not match
                every entry in `expected` (a rejected transition,
                whether due to an illegal request or a concurrent
                advancement that already happened).
        """
        with session_scope(self._session_factory) as db:
            stmt = sa_update(CompoundWorkflowProgress).where(
                CompoundWorkflowProgress.workflow_id == workflow_id
            )
            for column, expected_value in expected.items():
                stmt = stmt.where(
                    getattr(CompoundWorkflowProgress, column) == expected_value
                )
            stmt = stmt.values(**updates)

            result = db.execute(stmt)
            if result.rowcount == 0:
                exists = (
                    db.query(CompoundWorkflowProgress.id)
                    .filter(CompoundWorkflowProgress.workflow_id == workflow_id)
                    .first()
                    is not None
                )
                if not exists:
                    raise CompoundWorkflowProgressError(
                        f"No compound workflow progress row for "
                        f"workflow_id={workflow_id!r}."
                    )
                raise CompoundWorkflowProgressError(
                    "Transition rejected: the row is not in the expected "
                    "state (an illegal transition, or a concurrent "
                    "transition already applied)."
                )

            db.flush()
            row = (
                db.query(CompoundWorkflowProgress)
                .filter(CompoundWorkflowProgress.workflow_id == workflow_id)
                .one()
            )
            return _to_record(row)

    def record_pre_execution_observation(
        self, workflow_id: str, *, phase_value: str, last_updated: datetime | None
    ) -> CompoundWorkflowProgressRecord:
        """Durably record the real, pre-execution phase observation and
        begin step 1 (legal only from the initial, all-pending state).

        Args:
            workflow_id: The workflow id to update.
            phase_value: The real ProjectState.phase value observed
                immediately before attempting the write.
            last_updated: The real ProjectState.last_updated value
                observed at the same moment, or None if never recorded.

        Returns:
            The record after the transition.

        Raises:
            CompoundWorkflowProgressError: If step_1_status is not
                currently PENDING.
        """
        return self._compare_and_set(
            workflow_id,
            expected={
                "step_1_status": CompoundStepStatus.PENDING.value,
                "overall_status": CompoundOverallStatus.PENDING.value,
            },
            updates={
                "pre_execution_phase_value": phase_value,
                "pre_execution_last_updated": last_updated,
                "step_1_status": CompoundStepStatus.IN_PROGRESS.value,
                "overall_status": CompoundOverallStatus.IN_PROGRESS.value,
            },
        )

    def mark_step_1_completed(
        self, workflow_id: str
    ) -> CompoundWorkflowProgressRecord:
        """Mark the phase-update write step completed (legal only from
        step_1_status=IN_PROGRESS).

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition.

        Raises:
            CompoundWorkflowProgressError: If step_1_status is not
                currently IN_PROGRESS.
        """
        return self._compare_and_set(
            workflow_id,
            expected={"step_1_status": CompoundStepStatus.IN_PROGRESS.value},
            updates={"step_1_status": CompoundStepStatus.COMPLETED.value},
        )

    def mark_step_1_failed(self, workflow_id: str) -> CompoundWorkflowProgressRecord:
        """Mark the phase-update write step failed - and the whole
        workflow failed - reached either by an ordinary write-tool
        failure or by a user decline (both mean "the write never
        happened and never will for this request"; Phase 98, Batch 2 -
        docs/phase_98_live_compound_reentry_plan.md, Foundation D -
        the one new primitive the amended plan identified as missing:
        Batch 1 defined mark_step_3_failed() for the read-only final
        step but never a write-step-failure counterpart).

        Legal only from step_1_status=IN_PROGRESS (the same precondition
        mark_step_1_completed() already requires) - never from PENDING
        (nothing was ever attempted) and never a second time once
        already FAILED or once step 1 has already been marked
        COMPLETED. Mirrors mark_step_3_failed()'s own exact shape:
        atomically sets both step_1_status and overall_status in one
        CAS statement, so Step 2 can never legally begin afterward
        (start_step_2()'s own precondition requires step_1_status
        COMPLETED).

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition.

        Raises:
            CompoundWorkflowProgressError: If step_1_status is not
                currently IN_PROGRESS.
        """
        return self._compare_and_set(
            workflow_id,
            expected={"step_1_status": CompoundStepStatus.IN_PROGRESS.value},
            updates={
                "step_1_status": CompoundStepStatus.FAILED.value,
                "overall_status": CompoundOverallStatus.FAILED.value,
            },
        )

    def start_step_2(self, workflow_id: str) -> CompoundWorkflowProgressRecord:
        """Begin the internal phase-verification step (legal only once
        step 1 has completed).

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition.

        Raises:
            CompoundWorkflowProgressError: If step_1_status is not
                COMPLETED, or step_2_status is not PENDING.
        """
        return self._compare_and_set(
            workflow_id,
            expected={
                "step_1_status": CompoundStepStatus.COMPLETED.value,
                "step_2_status": CompoundStepStatus.PENDING.value,
            },
            updates={"step_2_status": CompoundStepStatus.IN_PROGRESS.value},
        )

    def mark_step_2_completed(
        self, workflow_id: str, *, verification_outcome: CompoundVerificationOutcome
    ) -> CompoundWorkflowProgressRecord:
        """Mark the internal phase-verification step completed with its
        real, bounded outcome (legal only from step_2_status=IN_PROGRESS).

        When verification_outcome is not VERIFIED, the whole workflow's
        overall_status is atomically set to FAILED in the same
        transition - step 3 (PROJECT_STATE_SHOW) can never legally
        start afterward (start_step_3's own expected-state check
        requires step_2_verification_outcome=VERIFIED).

        Args:
            workflow_id: The workflow id to update.
            verification_outcome: The real, already-computed outcome -
                never a raw metadata string.

        Returns:
            The record after the transition.

        Raises:
            CompoundWorkflowProgressError: If step_2_status is not
                currently IN_PROGRESS.
        """
        updates: dict[str, object] = {
            "step_2_status": CompoundStepStatus.COMPLETED.value,
            "step_2_verification_outcome": verification_outcome.value,
        }
        if verification_outcome is not CompoundVerificationOutcome.VERIFIED:
            updates["overall_status"] = CompoundOverallStatus.FAILED.value

        return self._compare_and_set(
            workflow_id,
            expected={"step_2_status": CompoundStepStatus.IN_PROGRESS.value},
            updates=updates,
        )

    def start_step_3(self, workflow_id: str) -> CompoundWorkflowProgressRecord:
        """Begin the ProjectState-show read step (legal only once step 2
        has completed with outcome VERIFIED).

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition.

        Raises:
            CompoundWorkflowProgressError: If step_2_status is not
                COMPLETED, step_2_verification_outcome is not VERIFIED,
                or step_3_status is not PENDING.
        """
        return self._compare_and_set(
            workflow_id,
            expected={
                "step_2_status": CompoundStepStatus.COMPLETED.value,
                "step_2_verification_outcome": (
                    CompoundVerificationOutcome.VERIFIED.value
                ),
                "step_3_status": CompoundStepStatus.PENDING.value,
            },
            updates={"step_3_status": CompoundStepStatus.IN_PROGRESS.value},
        )

    def mark_step_3_completed(
        self, workflow_id: str
    ) -> CompoundWorkflowProgressRecord:
        """Mark the ProjectState-show step completed and the whole
        workflow completed (legal only from step_3_status=IN_PROGRESS).

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition.

        Raises:
            CompoundWorkflowProgressError: If step_3_status is not
                currently IN_PROGRESS.
        """
        return self._compare_and_set(
            workflow_id,
            expected={"step_3_status": CompoundStepStatus.IN_PROGRESS.value},
            updates={
                "step_3_status": CompoundStepStatus.COMPLETED.value,
                "overall_status": CompoundOverallStatus.COMPLETED.value,
            },
        )

    def mark_step_3_failed(self, workflow_id: str) -> CompoundWorkflowProgressRecord:
        """Mark the ProjectState-show step failed - genuine partial
        completion: the phase update and its verification already
        succeeded (legal only from step_3_status=IN_PROGRESS).

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition.

        Raises:
            CompoundWorkflowProgressError: If step_3_status is not
                currently IN_PROGRESS.
        """
        return self._compare_and_set(
            workflow_id,
            expected={"step_3_status": CompoundStepStatus.IN_PROGRESS.value},
            updates={
                "step_3_status": CompoundStepStatus.FAILED.value,
                "overall_status": CompoundOverallStatus.FAILED.value,
            },
        )

    def mark_needs_reconciliation(
        self, workflow_id: str
    ) -> CompoundWorkflowProgressRecord:
        """Flag a row as needing reconciliation - for operator
        visibility only; never blocks the safe, automatic
        reconciliation logic this module also provides. Illegal once
        the workflow has already reached a terminal state.

        Args:
            workflow_id: The workflow id to update.

        Returns:
            The record after the transition.

        Raises:
            CompoundWorkflowProgressError: If overall_status is already
                COMPLETED or FAILED.
        """
        record = self.get(workflow_id)
        if record is None:
            raise CompoundWorkflowProgressError(
                f"No compound workflow progress row for workflow_id={workflow_id!r}."
            )
        if record.overall_status in (
            CompoundOverallStatus.COMPLETED,
            CompoundOverallStatus.FAILED,
        ):
            raise CompoundWorkflowProgressError(
                "Transition rejected: a terminal workflow cannot be marked "
                "as needing reconciliation."
            )
        return self._compare_and_set(
            workflow_id,
            expected={"overall_status": record.overall_status.value},
            updates={"overall_status": CompoundOverallStatus.NEEDS_RECONCILIATION.value},
        )


class ReconciliationConfidence(Enum):
    """The bounded, honest vocabulary reconcile_phase_update() may
    report. Deliberately never a bare boolean, and deliberately never
    an "executed exactly once" claim - see each member's own meaning
    below.

    Attributes:
        POSTCONDITION_NOT_SATISFIED: The durable phase value does not
            equal the approved value - the update has definitely not
            taken effect (whether never attempted, or superseded by an
            independent change).
        POSTCONDITION_SATISFIED_STATE_CHANGED: The durable phase value
            equals the approved value, AND real evidence (a differing
            pre-execution value, or a changed last_updated timestamp)
            shows the record was written to - the update appears to
            have taken effect. This is still not literal proof that
            *this* workflow's own tool call is what wrote it, merely
            that some write occurred and left the expected value.
        POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED: The durable
            phase value already equals the approved value, but no
            evidence (no differing pre-execution value, no changed
            timestamp) distinguishes "the tool executed and trivially
            rewrote the same value" from "the tool never executed at
            all, and the value was already correct beforehand." This
            case is reported honestly as unconfirmed - never claimed as
            executed.
    """

    POSTCONDITION_NOT_SATISFIED = "postcondition_not_satisfied"
    POSTCONDITION_SATISFIED_STATE_CHANGED = "postcondition_satisfied_state_changed"
    POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED = (
        "postcondition_satisfied_execution_unconfirmed"
    )


@dataclass(frozen=True, slots=True)
class PhaseUpdateReconciliation:
    """The result of one reconcile_phase_update() call.

    Attributes:
        confidence: The single, bounded ReconciliationConfidence value.
        detail: A short, honest, human-readable explanation - never a
            raw exception, raw tool output, or fabricated claim.
    """

    confidence: ReconciliationConfidence
    detail: str


def reconcile_phase_update(
    *,
    approved_phase_value: str,
    pre_execution_phase_value: str | None,
    pre_execution_last_updated: datetime | None,
    current_phase_value: str | None,
    current_last_updated: datetime | None,
) -> PhaseUpdateReconciliation:
    """Determine, honestly and only as far as real evidence permits,
    whether a phase-update write appears to have taken effect after a
    restart (Phase 98, Batch 1 - the Contract A reconciliation design
    from docs/phase_98_implementation_plan.md).

    This is a pure function - it never calls ProjectStateStore,
    ToolExecutor, ApprovalManager, or any tool itself; the caller
    (a later, separately-approved batch) is responsible for supplying
    already-observed, real values. It never claims "executed exactly
    once" merely because the final durable value matches the approved
    one - see ReconciliationConfidence's own docstring for the precise,
    narrower distinctions this function draws instead.

    Args:
        approved_phase_value: The exact, already-approved phase value.
        pre_execution_phase_value: The real phase value observed
            immediately before the write was attempted, or None if
            never recorded (e.g. a row created before this observation
            step existed, or a genuinely missing observation).
        pre_execution_last_updated: The real last_updated value
            observed at the same moment, or None.
        current_phase_value: The real, current phase value, observed
            now (at reconciliation time), or None if no ProjectState
            row exists at all.
        current_last_updated: The real, current last_updated value,
            observed now, or None.

    Returns:
        A PhaseUpdateReconciliation with the single, honest, bounded
        confidence level and a human-readable detail.
    """
    if current_phase_value != approved_phase_value:
        if (
            pre_execution_phase_value is not None
            and current_phase_value == pre_execution_phase_value
        ):
            detail = (
                "the durable phase value has not changed since before "
                "execution was attempted; the update has not taken effect"
            )
        else:
            detail = (
                "the durable phase value does not match the approved "
                "value, and differs from its own recorded pre-execution "
                "value; it may have been changed independently, or no "
                "pre-execution value was ever recorded"
            )
        return PhaseUpdateReconciliation(
            ReconciliationConfidence.POSTCONDITION_NOT_SATISFIED, detail
        )

    # current_phase_value == approved_phase_value from here on.
    if pre_execution_phase_value is None:
        return PhaseUpdateReconciliation(
            ReconciliationConfidence.POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED,
            "the durable phase value matches the approved value, but no "
            "pre-execution observation was recorded, so whether the "
            "update tool executed cannot be confirmed",
        )

    if pre_execution_phase_value != approved_phase_value:
        return PhaseUpdateReconciliation(
            ReconciliationConfidence.POSTCONDITION_SATISFIED_STATE_CHANGED,
            "the durable phase value changed from a different prior "
            "value to the approved value; the update appears to have "
            "taken effect",
        )

    # pre_execution_phase_value == approved_phase_value == current_phase_value:
    # matching value alone cannot distinguish "already correct, never
    # executed" from "executed and trivially rewrote the same value" -
    # consult the last_updated timestamp as the only further evidence.
    if (
        pre_execution_last_updated is not None
        and current_last_updated is not None
        and current_last_updated != pre_execution_last_updated
    ):
        return PhaseUpdateReconciliation(
            ReconciliationConfidence.POSTCONDITION_SATISFIED_STATE_CHANGED,
            "the durable phase value already matched the approved value "
            "before execution, but the record was written to since it "
            "was last observed; some update occurred",
        )

    return PhaseUpdateReconciliation(
        ReconciliationConfidence.POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED,
        "the durable phase value already matched the approved value "
        "before execution was attempted, and no evidence indicates the "
        "record was written to since; whether the update tool executed "
        "cannot be confirmed",
    )
