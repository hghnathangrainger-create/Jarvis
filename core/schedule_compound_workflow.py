"""
schedule_compound_workflow.py

Trusted, dormant orchestration-level logic for the second Phase 99
compound template (Batch 1 recognizer; Batch 2 lifecycle -
docs/phase_99_second_compound_template_planning.md):
SCHEDULE_ENABLE -> SCHEDULE_VERIFY_ENABLED_STATE -> SCHEDULE_SHOW_ENABLED_STATE.

Mirrors core/compound_workflow.py's own shape exactly in spirit - a
narrow, hand-authored structural fingerprint plus its own progress-
creation, approval-time validation, claimed-recovery, non-execution
terminalization, and six-outcome translation logic - but is its own,
wholly separate, parallel module: core/compound_workflow.py's own
recognizer, progress-creation, claimed-recovery, and translator logic
all remain untouched by this batch, and this module is never imported
by it, by core/orchestrator.py, or by main.py in Batch 2.

Responsibilities:
    - Recognize a Plan as the exact trusted schedule-compound
      fingerprint - never merely "three steps naming schedule
      capabilities." Every one of the following must hold exactly:
      three steps; step 1 is exactly SCHEDULE_ENABLE (never
      SCHEDULE_DISABLE); step 2 is exactly SCHEDULE_VERIFY_ENABLED_STATE;
      step 3 is exactly SCHEDULE_SHOW_ENABLED_STATE (never SCHEDULE_LIST
      or any other read capability); every step's own tool_input is
      exactly {"schedule_id": <int>} - no additional key, no omitted
      key; the identical schedule_id integer appears in all three
      steps; step 3's requires_verified_predecessor is True, its
      verification_field_name is exactly "enabled_str", and its
      verification_expected_value is exactly "true" (never "false" -
      no SCHEDULE_DISABLE-paired template exists yet); and every step's
      own stored tier matches its capability's declared
      max_execution_tier exactly (YELLOW, GREEN, GREEN).
    - Establish a ScheduleCompoundWorkflowProgress row immediately after
      the trusted plan first pauses, and terminally isolate the pending
      approval/paused workflow if that establishment cannot be trusted
      (Foundation F).
    - Idempotently repair, or terminally isolate, a pending compound
      approval whose progress row is missing because of a hard crash
      between pause and progress creation (Foundation F).
    - Validate, server-side, that a compound approval's progress
      foundation is intact immediately before it would transition to
      APPROVED_UNCONSUMED (Foundation G).
    - Recover an inherited CLAIMED schedule-compound workflow using its
      own durable step-level progress evidence, before any generic
      fallback ever sees it, and without a second claim CAS
      (Foundation H).
    - Translate a schedule-compound WorkflowResult into one of six
      honest, bounded outcomes (Foundation I).
    - Terminalize a declined-or-expired schedule-compound workflow's
      progress row as honestly NOT_EXECUTED - never FAILED - when a
      crash (or, for expiry, always) prevented live terminalization.

Does NOT:
    - Get imported by intelligence/planning.py, core/orchestrator.py, or
      main.py in Batch 2 - only this module's own dedicated tests
      import it. Wiring any of it into a live path is a later,
      separately-approved batch's own responsibility.
    - Call an AI provider, or accept anything from model output. Every
      function here only ever consults already-durable, non-model-
      controlled state.
    - Perform a second APPROVED_UNCONSUMED -> CLAIMED claim CAS for an
      already-CLAIMED row, or become a general "resume any claimed
      workflow" mechanism - resume_claimed_schedule_compound_workflow()
      refuses (returns NOT_RECOGNIZED) anything that does not pass the
      fingerprint check.
    - Fabricate a ScheduleCompoundVerificationOutcome from a bare
      enabled-value comparison outside the real verifier tool's own
      call.
    - Accept SCHEDULE_DISABLE in step 1's place, SCHEDULE_LIST in step
      3's place, a differing schedule_id across steps, an extra or
      missing tool_input key, or any three-step plan shape beyond this
      one hand-authored fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from approval.pending_approval_store import PendingApprovalRecord
from config.constants import SecurityTier, StepStatus
from core.request_models import JarvisResponse
from intelligence.capability_catalog import CAPABILITY_CATALOG, CapabilityId
from planner.plan_models import Plan, PlanStep
from security.security_manager import SecurityManager
from tools.base_tool import ToolResult
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from workflow.engine import WorkflowEngine
from workflow.paused_workflow_store import PausedWorkflowRecord
from workflow.schedule_compound_workflow_progress_store import (
    ALLOWED_SCHEDULE_TEMPLATE_ID,
    ScheduleCompoundOverallStatus,
    ScheduleCompoundStepStatus,
    ScheduleCompoundVerificationOutcome,
    ScheduleCompoundWorkflowProgressError,
    ScheduleCompoundWorkflowProgressRecord,
    ScheduleCompoundWorkflowProgressStore,
    ScheduleReconciliationConfidence,
    reconcile_schedule_enable,
)
from workflow.workflow_models import WorkflowResult

_WRITE_CAPABILITY_ID = CapabilityId.SCHEDULE_ENABLE
_VERIFY_CAPABILITY_ID = CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE
_SHOW_CAPABILITY_ID = CapabilityId.SCHEDULE_SHOW_ENABLED_STATE
_VERIFY_TOOL_NAME = "schedule_verify_enabled_state"
_SHOW_TOOL_NAME = "schedule_show_enabled_state"


class _PendingApprovalStoreProtocol(Protocol):
    """The minimal PendingApprovalStore surface this module depends on."""

    def list_by_handoff_status(self, status: object) -> list[PendingApprovalRecord]: ...

    def mark_consumed(self, request_id: str) -> bool: ...

    def mark_claim_interrupted(self, request_id: str) -> bool: ...


class _PausedWorkflowStoreProtocol(Protocol):
    """The minimal PausedWorkflowStore surface this module depends on."""

    def get(self, workflow_id: str) -> PausedWorkflowRecord | None: ...

    def delete(self, workflow_id: str) -> None: ...


class _ApprovalInvalidator(Protocol):
    """The minimal invalidation surface this module depends on -
    matches ApprovalManager.invalidate_pending()'s own signature."""

    def invalidate_pending(self, request_id: str, *, reason: str) -> bool: ...


def _plan_from_raw_steps(
    plan_steps: list[dict[str, object]] | None, user_request: str | None
) -> Plan | None:
    """Purely, structurally decode a persisted plan_steps JSON list into
    a Plan - never re-validating tool registration or live security
    tier. Used only for recognition/identity checks that do not
    themselves execute anything.

    Args:
        plan_steps: The already-JSON-decoded list of plain step dicts,
            or None/empty.
        user_request: The persisted Plan.user_request text, or None.

    Returns:
        A Plan, or None if plan_steps is empty or malformed.
    """
    if not plan_steps:
        return None
    try:
        steps = tuple(
            PlanStep(
                number=s["number"],
                description=s["description"],
                action=s["action"],
                tier=SecurityTier(s["tier"]),
                reason=s["reason"],
                tool_name=s.get("tool_name"),
                tool_input=dict(s.get("tool_input") or {}),
                input_from_previous_step=bool(
                    s.get("input_from_previous_step", False)
                ),
                requires_verified_predecessor=bool(
                    s.get("requires_verified_predecessor", False)
                ),
                verification_field_name=s.get("verification_field_name"),
                verification_expected_value=s.get("verification_expected_value"),
            )
            for s in plan_steps
        )
    except (KeyError, TypeError, ValueError):
        return None
    return Plan(user_request=user_request or "", steps=steps)


def matches_schedule_compound_plan_shape(plan: Plan) -> bool:
    """The exact trusted fingerprint for the second Phase 99 compound
    template.

    Args:
        plan: The Plan to check - already reconstructed by the caller
            (from a live paused workflow, a freshly-built trusted plan,
            or a raw persisted record).

    Returns:
        True only if every structural requirement holds exactly. False
        for any mismatch, including an otherwise-arbitrary three-step
        plan naming schedule capabilities in some other combination or
        order.
    """
    steps = plan.steps
    if len(steps) != 3:
        return False
    step1, step2, step3 = steps

    write_adapter = CAPABILITY_CATALOG.get(_WRITE_CAPABILITY_ID)
    verify_adapter = CAPABILITY_CATALOG.get(_VERIFY_CAPABILITY_ID)
    show_adapter = CAPABILITY_CATALOG.get(_SHOW_CAPABILITY_ID)
    if write_adapter is None or verify_adapter is None or show_adapter is None:
        return False

    # Step 1: exactly SCHEDULE_ENABLE (never SCHEDULE_DISABLE, which
    # has a different tool_name entirely), exactly one key
    # ("schedule_id", a real, non-bool int), exact YELLOW tier.
    if step1.tool_name != write_adapter.tool_name:
        return False
    if set(step1.tool_input) != {"schedule_id"}:
        return False
    approved_schedule_id = step1.tool_input.get("schedule_id")
    if not isinstance(approved_schedule_id, int) or isinstance(
        approved_schedule_id, bool
    ):
        return False
    if step1.tier is not write_adapter.max_execution_tier:
        return False

    # Step 2: exactly SCHEDULE_VERIFY_ENABLED_STATE, exactly one key
    # ("schedule_id", identical to step 1's), exact GREEN tier.
    if step2.tool_name != verify_adapter.tool_name:
        return False
    if set(step2.tool_input) != {"schedule_id"}:
        return False
    if step2.tool_input.get("schedule_id") != approved_schedule_id:
        return False
    if step2.tier is not verify_adapter.max_execution_tier:
        return False

    # Step 3: exactly SCHEDULE_SHOW_ENABLED_STATE (never SCHEDULE_LIST
    # or any other read capability), exactly one key ("schedule_id",
    # identical to steps 1/2), exact GREEN tier, gated on a verified
    # predecessor expecting exactly "true" for the "enabled_str" field.
    if step3.tool_name != show_adapter.tool_name:
        return False
    if set(step3.tool_input) != {"schedule_id"}:
        return False
    if step3.tool_input.get("schedule_id") != approved_schedule_id:
        return False
    if step3.tier is not show_adapter.max_execution_tier:
        return False
    if not step3.requires_verified_predecessor:
        return False
    if step3.verification_field_name != "enabled_str":
        return False
    if step3.verification_expected_value != "true":
        return False

    return True


def schedule_compound_progress_identity_matches(
    plan: Plan,
    progress: ScheduleCompoundWorkflowProgressRecord,
    *,
    request_id: str,
    workflow_id: str,
) -> bool:
    """The durable identity cross-check: the linked progress row's own
    template/request/workflow identity and approved schedule_id must
    agree exactly with the paused plan and the caller's own already-
    durable identities. A mismatch fails closed.

    Args:
        plan: The already shape-matched Plan (callers should have
            already confirmed matches_schedule_compound_plan_shape(plan)).
        progress: The linked ScheduleCompoundWorkflowProgressRecord.
        request_id: The approval request id this workflow is linked to.
        workflow_id: This workflow's own correlation id.

    Returns:
        True only if template_id, workflow_id, request_id, and
        schedule_id all agree exactly.
    """
    if progress.template_id != ALLOWED_SCHEDULE_TEMPLATE_ID:
        return False
    if progress.workflow_id != workflow_id:
        return False
    if progress.request_id != request_id:
        return False
    approved_schedule_id = plan.steps[0].tool_input.get("schedule_id")
    if progress.schedule_id != approved_schedule_id:
        return False
    return True


def is_recognized_schedule_compound_workflow(
    plan: Plan,
    progress: ScheduleCompoundWorkflowProgressRecord | None,
    *,
    request_id: str,
    workflow_id: str,
) -> bool:
    """The complete recognizer: plan shape and durable identity
    cross-check both hold.

    Args:
        plan: The Plan to check.
        progress: The linked ScheduleCompoundWorkflowProgressRecord, or
            None if no such row exists.
        request_id: The approval request id this workflow is linked to.
        workflow_id: This workflow's own correlation id.

    Returns:
        True only if every point holds. False (never an exception) for
        any mismatch, including a missing progress row.
    """
    if not matches_schedule_compound_plan_shape(plan):
        return False
    if progress is None:
        return False
    return schedule_compound_progress_identity_matches(
        plan, progress, request_id=request_id, workflow_id=workflow_id
    )


# ---------------------------------------------------------------------------
# Foundation F: progress creation and approval-visibility gating
# ---------------------------------------------------------------------------


def _isolate_incomplete_schedule_compound_pause(
    *,
    approval_invalidator: _ApprovalInvalidator,
    paused_workflow_store: _PausedWorkflowStoreProtocol,
    request_id: str,
    workflow_id: str,
    reason: str,
) -> None:
    """Terminally isolate a pending approval/paused-workflow pair whose
    schedule compound progress foundation could not be established or
    repaired, using only existing, already-bounded APIs
    (ApprovalManager.invalidate_pending(), PausedWorkflowStore.delete())
    - never a new invalidation mechanism.

    Args:
        approval_invalidator: The real ApprovalManager (or a
            structurally-equivalent stand-in for tests).
        paused_workflow_store: The real PausedWorkflowStore.
        request_id: The approval request id to invalidate.
        workflow_id: The paused workflow id to delete.
        reason: A short, bounded, honest reason.
    """
    approval_invalidator.invalidate_pending(request_id, reason=reason)
    paused_workflow_store.delete(workflow_id)


def establish_schedule_compound_progress_or_isolate(
    *,
    plan: Plan,
    workflow_id: str,
    request_id: str,
    progress_store: ScheduleCompoundWorkflowProgressStore,
    approval_invalidator: _ApprovalInvalidator,
    paused_workflow_store: _PausedWorkflowStoreProtocol,
) -> ScheduleCompoundWorkflowProgressRecord | str:
    """The exact Foundation F creation contract: called immediately
    after the trusted schedule-compound plan's first pause
    (WorkflowEngine.run() returning WAITING), before its approval is
    ever treated as actionable or visible.

    On any failure - the plan does not match the trusted fingerprint,
    ScheduleCompoundWorkflowProgressStore.create() itself raises, or the
    freshly created row's own identity does not immediately match - the
    pending approval and paused workflow are terminally isolated via
    existing bounded APIs.

    Args:
        plan: The already-paused trusted compound Plan.
        workflow_id: The real workflow id WorkflowEngine.run() produced.
        request_id: The real approval request id the same pause
            produced.
        progress_store: The real ScheduleCompoundWorkflowProgressStore.
        approval_invalidator: The real ApprovalManager (or a
            structurally-equivalent stand-in for tests).
        paused_workflow_store: The real PausedWorkflowStore.

    Returns:
        The newly created, identity-validated
        ScheduleCompoundWorkflowProgressRecord on success. A short,
        bounded failure reason string on any failure - never an
        exception.
    """
    if not matches_schedule_compound_plan_shape(plan):
        return "the plan does not match the trusted schedule-compound fingerprint"

    approved_schedule_id = plan.steps[0].tool_input.get("schedule_id")
    assert isinstance(approved_schedule_id, int)  # guaranteed by the shape check

    try:
        record = progress_store.create(
            workflow_id=workflow_id,
            template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
            request_id=request_id,
            schedule_id=approved_schedule_id,
        )
    except Exception as exc:  # noqa: BLE001 - fail closed on any DB/infra error
        reason = f"schedule compound progress could not be established: {exc}"
        _isolate_incomplete_schedule_compound_pause(
            approval_invalidator=approval_invalidator,
            paused_workflow_store=paused_workflow_store,
            request_id=request_id,
            workflow_id=workflow_id,
            reason=reason,
        )
        return reason

    if not schedule_compound_progress_identity_matches(
        plan, record, request_id=request_id, workflow_id=workflow_id
    ):
        reason = "schedule compound progress identity mismatch immediately after creation"
        _isolate_incomplete_schedule_compound_pause(
            approval_invalidator=approval_invalidator,
            paused_workflow_store=paused_workflow_store,
            request_id=request_id,
            workflow_id=workflow_id,
            reason=reason,
        )
        return reason

    return record


@dataclass(frozen=True, slots=True)
class ScheduleCompoundProgressRepairSummary:
    """A small, honest summary of what
    repair_or_isolate_pending_schedule_compound_progress() did.

    Attributes:
        repaired: Number of PENDING, workflow-linked, compound-shaped
            rows whose missing progress row was idempotently created.
        isolated: Number of rows that could not be safely repaired and
            were terminally isolated instead.
    """

    repaired: int
    isolated: int


def repair_or_isolate_pending_schedule_compound_progress(
    *,
    pending_store: _PendingApprovalStoreProtocol,
    paused_workflow_store: _PausedWorkflowStoreProtocol,
    progress_store: ScheduleCompoundWorkflowProgressStore,
    approval_invalidator: _ApprovalInvalidator,
    pending_status: object,
) -> ScheduleCompoundProgressRepairSummary:
    """Foundation F's hard-crash repair pass: detect an exact,
    trusted-fingerprint schedule-compound paused plan whose progress
    row is missing (or mismatched) because of a crash between pause and
    progress creation, and either idempotently repair it or terminally
    isolate it - before any pending approval is ever rebuilt or shown.

    Never touches a row that is not workflow-linked, whose paused plan
    cannot be reconstructed, or whose plan does not match the trusted
    schedule-compound fingerprint at all - those are left completely
    untouched.

    Args:
        pending_store: The real PendingApprovalStore.
        paused_workflow_store: The real PausedWorkflowStore.
        progress_store: The real ScheduleCompoundWorkflowProgressStore.
        approval_invalidator: The real ApprovalManager (or a
            structurally-equivalent stand-in for tests).
        pending_status: The PENDING PendingApprovalHandoffStatus value.

    Returns:
        A ScheduleCompoundProgressRepairSummary.
    """
    repaired = 0
    isolated = 0

    for record in pending_store.list_by_handoff_status(pending_status):
        workflow_id = record.metadata.get("workflow_id")
        if not workflow_id:
            continue

        paused_record = paused_workflow_store.get(workflow_id)
        if paused_record is None or paused_record.corrupt:
            continue

        plan = _plan_from_raw_steps(paused_record.plan_steps, paused_record.user_request)
        if plan is None or not matches_schedule_compound_plan_shape(plan):
            continue

        existing = progress_store.get(workflow_id)
        if existing is not None and schedule_compound_progress_identity_matches(
            plan, existing, request_id=record.request_id, workflow_id=workflow_id
        ):
            continue

        approved_schedule_id = plan.steps[0].tool_input.get("schedule_id")
        if existing is not None or not isinstance(approved_schedule_id, int):
            _isolate_incomplete_schedule_compound_pause(
                approval_invalidator=approval_invalidator,
                paused_workflow_store=paused_workflow_store,
                request_id=record.request_id,
                workflow_id=workflow_id,
                reason="schedule compound progress could not be unambiguously repaired",
            )
            isolated += 1
            continue

        try:
            progress_store.create(
                workflow_id=workflow_id,
                template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
                request_id=record.request_id,
                schedule_id=approved_schedule_id,
            )
            repaired += 1
        except Exception:  # noqa: BLE001 - fail closed on any DB/infra error
            _isolate_incomplete_schedule_compound_pause(
                approval_invalidator=approval_invalidator,
                paused_workflow_store=paused_workflow_store,
                request_id=record.request_id,
                workflow_id=workflow_id,
                reason="schedule compound progress could not be repaired",
            )
            isolated += 1

    return ScheduleCompoundProgressRepairSummary(repaired=repaired, isolated=isolated)


def terminalize_declined_or_expired_schedule_compound_progress(
    *,
    pending_store: _PendingApprovalStoreProtocol,
    progress_store: ScheduleCompoundWorkflowProgressStore,
    declined_status: object,
    expired_status: object,
) -> int:
    """Startup consistency repair for a declined or expired schedule-
    compound-linked progress row that was never terminalized live: the
    dedicated non-execution terminalization path's own crash-recovery
    backstop.

    A live decline would be terminalized synchronously by a future,
    separately-approved orchestrator wiring immediately after
    WorkflowEngine.resume() returns - this repair pass only ever needs
    to act when that call never happened (a crash between decline and
    terminalization) or could not have happened at all (expiry:
    WorkflowEngine's own lazy _reap_stale_paused() removes a paused
    workflow with no callback into this module whatsoever, so an
    expired schedule-compound workflow's progress row is *only* ever
    terminalized here).

    Never touches a row that is not linked to this exact trusted
    template. Never overwrites a row where execution genuinely began.

    Args:
        pending_store: The real PendingApprovalStore.
        progress_store: The real ScheduleCompoundWorkflowProgressStore.
        declined_status: The DECLINED PendingApprovalHandoffStatus
            value.
        expired_status: The EXPIRED PendingApprovalHandoffStatus value.

    Returns:
        The number of progress rows this call terminalized as
        NOT_EXECUTED. Idempotent - calling this repeatedly, including
        with nothing new to do, always returns 0 on every call after
        the first.
    """
    terminalized = 0
    for status in (declined_status, expired_status):
        for record in pending_store.list_by_handoff_status(status):
            workflow_id = record.metadata.get("workflow_id")
            if not workflow_id:
                continue

            progress = progress_store.get(workflow_id)
            if progress is None:
                continue
            if progress.template_id != ALLOWED_SCHEDULE_TEMPLATE_ID:
                continue
            if progress.request_id != record.request_id:
                continue
            if progress.overall_status is ScheduleCompoundOverallStatus.NOT_EXECUTED:
                # Already terminalized by an earlier call - counted once,
                # not on every subsequent repair pass that finds it.
                continue

            try:
                progress_store.mark_not_executed_before_start(workflow_id)
                terminalized += 1
            except ScheduleCompoundWorkflowProgressError:
                continue

    return terminalized


# ---------------------------------------------------------------------------
# Foundation G: approval-time progress validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScheduleCompoundApprovalValidation:
    """The result of one
    validate_schedule_compound_approval_before_transition() call.

    Attributes:
        is_compound_workflow: False if the linked paused plan does not
            match the trusted schedule-compound fingerprint at all - in
            this case `valid` is always True and `reason` always None.
        valid: True if the transition may proceed. False only when this
            is a recognized schedule-compound workflow whose progress is
            missing or mismatched.
        reason: Set only when valid is False.
    """

    is_compound_workflow: bool
    valid: bool
    reason: str | None = None


def validate_schedule_compound_approval_before_transition(
    *,
    paused_workflow_store: _PausedWorkflowStoreProtocol,
    progress_store: ScheduleCompoundWorkflowProgressStore,
    request_id: str,
    workflow_id: str,
) -> ScheduleCompoundApprovalValidation:
    """Foundation G: the trusted, server-side check a caller must run
    immediately before transitioning a workflow-linked pending approval
    to APPROVED_UNCONSUMED, independent of whether progress creation was
    ever attempted earlier.

    Existing non-compound approvals (and the existing ProjectState
    compound) are always reported is_compound_workflow=False, valid=True
    - this function never restricts anything it does not recognize as
    this one trusted template.

    Args:
        paused_workflow_store: The real PausedWorkflowStore.
        progress_store: The real ScheduleCompoundWorkflowProgressStore.
        request_id: The approval request about to be decided.
        workflow_id: The linked workflow id.

    Returns:
        A ScheduleCompoundApprovalValidation.
    """
    paused_record = paused_workflow_store.get(workflow_id)
    if paused_record is None or paused_record.corrupt:
        return ScheduleCompoundApprovalValidation(is_compound_workflow=False, valid=True)

    plan = _plan_from_raw_steps(paused_record.plan_steps, paused_record.user_request)
    if plan is None or not matches_schedule_compound_plan_shape(plan):
        return ScheduleCompoundApprovalValidation(is_compound_workflow=False, valid=True)

    progress = progress_store.get(workflow_id)
    if progress is None:
        return ScheduleCompoundApprovalValidation(
            is_compound_workflow=True,
            valid=False,
            reason="no schedule compound progress row exists for this workflow",
        )
    if not schedule_compound_progress_identity_matches(
        plan, progress, request_id=request_id, workflow_id=workflow_id
    ):
        return ScheduleCompoundApprovalValidation(
            is_compound_workflow=True,
            valid=False,
            reason="schedule compound progress identity does not match this request",
        )
    return ScheduleCompoundApprovalValidation(is_compound_workflow=True, valid=True)


# ---------------------------------------------------------------------------
# Foundation H: compound-specific inherited-CLAIMED recovery
# ---------------------------------------------------------------------------


class ScheduleCompoundClaimedOutcome(Enum):
    """The bounded outcome of one
    resume_claimed_schedule_compound_workflow() call. NOT_RECOGNIZED
    means this row was not this trusted template - the caller must
    leave it completely untouched for the existing, unchanged generic
    CLAIMED fallback."""

    CONSUMED = "consumed"
    CLAIM_INTERRUPTED = "claim_interrupted"
    NOT_RECOGNIZED = "not_recognized"


def _verification_outcome_for_plan(
    plan: Plan, tool_result: ToolResult
) -> ScheduleCompoundVerificationOutcome:
    """The same exact-match verification logic
    workflow.schedule_compound_progress_observer.ScheduleCompoundStepObserver
    uses, applied here for the CLAIMED-recovery rerun path.

    Args:
        plan: The reconstructed, already fingerprint-matched Plan.
        tool_result: The freshly-obtained verifier ToolResult.

    Returns:
        VERIFIED, FAILED, or UNAVAILABLE - never fabricated from a bare
        success flag alone.
    """
    if not tool_result.success:
        return ScheduleCompoundVerificationOutcome.UNAVAILABLE
    step_3 = plan.steps[2]
    field_name = step_3.verification_field_name or "enabled_str"
    expected_value = step_3.verification_expected_value
    actual = tool_result.metadata.get(field_name)
    if not isinstance(actual, str) or expected_value is None:
        return ScheduleCompoundVerificationOutcome.UNAVAILABLE
    if actual == expected_value:
        return ScheduleCompoundVerificationOutcome.VERIFIED
    return ScheduleCompoundVerificationOutcome.FAILED


def resume_claimed_schedule_compound_workflow(
    record: PendingApprovalRecord,
    *,
    pending_store: _PendingApprovalStoreProtocol,
    paused_workflow_store: _PausedWorkflowStoreProtocol,
    progress_store: ScheduleCompoundWorkflowProgressStore,
    workflow_engine: WorkflowEngine,
    tool_registry: ToolRegistry,
    security_manager: SecurityManager,
    tool_executor: ToolExecutor,
) -> ScheduleCompoundClaimedOutcome:
    """The narrow, Foundation H inherited-CLAIMED continuation path -
    never a general "resume any claimed workflow" mechanism.

    Performs no second APPROVED_UNCONSUMED -> CLAIMED claim CAS: `record`
    must already be CLAIMED. Selects recovery only from trusted,
    durable, non-model-controlled state. Never re-invokes Step 1's
    write tool under any circumstance; only Steps 2/3 (both read-only)
    are ever (re)run, and only when the matrix says that is safe.

    Args:
        record: The already-CLAIMED PendingApprovalRecord.
        pending_store: The real PendingApprovalStore.
        paused_workflow_store: The real PausedWorkflowStore.
        progress_store: The real ScheduleCompoundWorkflowProgressStore.
        workflow_engine: The real, already-restarted WorkflowEngine,
            used only for its read-only reconstruct_claimed_compound_plan().
        tool_registry: The live ToolRegistry, for plan revalidation.
        security_manager: The live SecurityManager, for plan
            revalidation.
        tool_executor: The real ToolExecutor, used to (re)run Steps
            2/3 only.

    Returns:
        CONSUMED if a known terminal result was reached. CLAIM_INTERRUPTED
        if safe continuation could not be established. NOT_RECOGNIZED if
        this row is not (or no longer verifiably) this one trusted
        template.
    """
    workflow_id = record.metadata.get("workflow_id")
    if not workflow_id:
        return ScheduleCompoundClaimedOutcome.NOT_RECOGNIZED

    paused_record = paused_workflow_store.get(workflow_id)
    if paused_record is None:
        return ScheduleCompoundClaimedOutcome.NOT_RECOGNIZED

    shape_plan = _plan_from_raw_steps(paused_record.plan_steps, paused_record.user_request)
    if shape_plan is None or not matches_schedule_compound_plan_shape(shape_plan):
        return ScheduleCompoundClaimedOutcome.NOT_RECOGNIZED

    progress = progress_store.get(workflow_id)
    if progress is None or not schedule_compound_progress_identity_matches(
        shape_plan, progress, request_id=record.request_id, workflow_id=workflow_id
    ):
        return ScheduleCompoundClaimedOutcome.NOT_RECOGNIZED

    plan, reason = workflow_engine.reconstruct_claimed_compound_plan(
        paused_record, registry=tool_registry, security_manager=security_manager
    )
    if plan is None:
        pending_store.mark_claim_interrupted(record.request_id)
        return ScheduleCompoundClaimedOutcome.CLAIM_INTERRUPTED

    return _continue_recognized_schedule_compound_workflow(
        plan,
        progress,
        workflow_id=workflow_id,
        request_id=record.request_id,
        pending_store=pending_store,
        progress_store=progress_store,
        tool_executor=tool_executor,
    )


def _read_current_schedule_enabled(
    tool_executor: ToolExecutor, schedule_id: int
) -> bool | None:
    """Read the real, current ScheduleEntry.enabled via the one real,
    audited schedule_verify_enabled_state tool call - never a raw store
    read.

    Args:
        tool_executor: The real ToolExecutor.
        schedule_id: The trusted schedule id to read back.

    Returns:
        The real enabled value, or None if the read itself did not
        succeed or returned no usable value.
    """
    result = tool_executor.execute(
        _VERIFY_TOOL_NAME, {"schedule_id": schedule_id}, session_id=None
    )
    if not result.success:
        return None
    enabled_value = result.metadata.get("enabled")
    return enabled_value if isinstance(enabled_value, bool) else None


def _continue_recognized_schedule_compound_workflow(
    plan: Plan,
    progress: ScheduleCompoundWorkflowProgressRecord,
    *,
    workflow_id: str,
    request_id: str,
    pending_store: _PendingApprovalStoreProtocol,
    progress_store: ScheduleCompoundWorkflowProgressStore,
    tool_executor: ToolExecutor,
) -> ScheduleCompoundClaimedOutcome:
    """The exact crash-state matrix, applied once `plan`/`progress` are
    already known to be the recognized, revalidated schedule-compound
    template.

    Never re-invokes Step 1's write tool under any circumstance.
    """
    # --- Step 1 ---------------------------------------------------------
    if progress.step_1_status is ScheduleCompoundStepStatus.PENDING:
        pending_store.mark_claim_interrupted(request_id)
        return ScheduleCompoundClaimedOutcome.CLAIM_INTERRUPTED

    if progress.step_1_status is ScheduleCompoundStepStatus.IN_PROGRESS:
        current_enabled = _read_current_schedule_enabled(
            tool_executor, progress.schedule_id
        )
        reconciliation = reconcile_schedule_enable(
            pre_execution_enabled=progress.pre_execution_enabled,
            current_enabled=current_enabled,
        )
        if (
            reconciliation.confidence
            is ScheduleReconciliationConfidence.POSTCONDITION_NOT_SATISFIED
        ):
            try:
                progress = progress_store.mark_step_1_failed(workflow_id)
            except ScheduleCompoundWorkflowProgressError:
                pass
            pending_store.mark_consumed(request_id)
            return ScheduleCompoundClaimedOutcome.CONSUMED
        if (
            reconciliation.confidence
            is ScheduleReconciliationConfidence.POSTCONDITION_SATISFIED_STATE_CHANGED
        ):
            progress = progress_store.mark_step_1_completed(workflow_id)
            # Falls through to Step 2 evaluation below.
        else:
            # POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED - genuinely
            # ambiguous; never claim exactly-once execution.
            try:
                progress_store.mark_needs_reconciliation(workflow_id)
            except ScheduleCompoundWorkflowProgressError:
                pass
            pending_store.mark_claim_interrupted(request_id)
            return ScheduleCompoundClaimedOutcome.CLAIM_INTERRUPTED

    # --- Step 2 -----------------------------------------------------------
    if progress.step_2_status in (
        ScheduleCompoundStepStatus.PENDING,
        ScheduleCompoundStepStatus.IN_PROGRESS,
    ):
        if progress.step_2_status is ScheduleCompoundStepStatus.PENDING:
            progress = progress_store.start_step_2(workflow_id)
        verify_result = tool_executor.execute(
            _VERIFY_TOOL_NAME, {"schedule_id": progress.schedule_id}, session_id=None
        )
        outcome = _verification_outcome_for_plan(plan, verify_result)
        progress = progress_store.mark_step_2_completed(
            workflow_id, verification_outcome=outcome
        )
        if outcome is not ScheduleCompoundVerificationOutcome.VERIFIED:
            pending_store.mark_consumed(request_id)
            return ScheduleCompoundClaimedOutcome.CONSUMED

    if progress.step_2_verification_outcome is not ScheduleCompoundVerificationOutcome.VERIFIED:
        pending_store.mark_consumed(request_id)
        return ScheduleCompoundClaimedOutcome.CONSUMED

    # --- Step 3 -----------------------------------------------------------
    if progress.step_3_status in (
        ScheduleCompoundStepStatus.PENDING,
        ScheduleCompoundStepStatus.IN_PROGRESS,
    ):
        if progress.step_3_status is ScheduleCompoundStepStatus.PENDING:
            progress_store.start_step_3(workflow_id)
        show_result = tool_executor.execute(
            _SHOW_TOOL_NAME, {"schedule_id": progress.schedule_id}, session_id=None
        )
        if show_result.success:
            progress_store.mark_step_3_completed(workflow_id)
        else:
            progress_store.mark_step_3_failed(workflow_id)
        pending_store.mark_consumed(request_id)
        return ScheduleCompoundClaimedOutcome.CONSUMED

    # step_3_status already COMPLETED or FAILED - nothing left to (re)run.
    pending_store.mark_consumed(request_id)
    return ScheduleCompoundClaimedOutcome.CONSUMED


@dataclass(frozen=True, slots=True)
class ScheduleCompoundClaimedReconciliationSummary:
    """A small, honest summary of what
    reconcile_claimed_schedule_compound_workflows() did.

    Attributes:
        consumed: Number of recognized schedule-compound CLAIMED rows
            resolved to CONSUMED.
        interrupted: Number resolved to CLAIM_INTERRUPTED.
        left_for_generic: Number not recognized as this template at all
            - left completely untouched for the existing, unchanged
            generic CLAIMED fallback to process next.
    """

    consumed: int
    interrupted: int
    left_for_generic: int


def reconcile_claimed_schedule_compound_workflows(
    *,
    pending_store: _PendingApprovalStoreProtocol,
    paused_workflow_store: _PausedWorkflowStoreProtocol,
    progress_store: ScheduleCompoundWorkflowProgressStore,
    workflow_engine: WorkflowEngine,
    tool_registry: ToolRegistry,
    security_manager: SecurityManager,
    tool_executor: ToolExecutor,
    claimed_status: object,
) -> ScheduleCompoundClaimedReconciliationSummary:
    """Foundation H's own dormant startup pass: reconcile every
    inherited CLAIMED row this template recognizes, using its own
    durable step-level progress evidence. Not wired into main.py's own
    startup ordering in Batch 2 - provided here, fully tested, for a
    future, separately-approved wiring.

    Args:
        pending_store: The real PendingApprovalStore.
        paused_workflow_store: The real PausedWorkflowStore.
        progress_store: The real ScheduleCompoundWorkflowProgressStore.
        workflow_engine: The real, already-restarted WorkflowEngine.
        tool_registry: The live ToolRegistry.
        security_manager: The live SecurityManager.
        tool_executor: The real ToolExecutor.
        claimed_status: The CLAIMED PendingApprovalHandoffStatus value.

    Returns:
        A ScheduleCompoundClaimedReconciliationSummary.
    """
    consumed = 0
    interrupted = 0
    left_for_generic = 0

    for record in pending_store.list_by_handoff_status(claimed_status):
        outcome = resume_claimed_schedule_compound_workflow(
            record,
            pending_store=pending_store,
            paused_workflow_store=paused_workflow_store,
            progress_store=progress_store,
            workflow_engine=workflow_engine,
            tool_registry=tool_registry,
            security_manager=security_manager,
            tool_executor=tool_executor,
        )
        if outcome is ScheduleCompoundClaimedOutcome.CONSUMED:
            consumed += 1
        elif outcome is ScheduleCompoundClaimedOutcome.CLAIM_INTERRUPTED:
            interrupted += 1
        else:
            left_for_generic += 1

    return ScheduleCompoundClaimedReconciliationSummary(
        consumed=consumed, interrupted=interrupted, left_for_generic=left_for_generic
    )


# ---------------------------------------------------------------------------
# Foundation I: the dormant schedule-compound result translator
# ---------------------------------------------------------------------------


class ScheduleCompoundResultKind(Enum):
    """The exact six outcomes translate_schedule_compound_workflow_result()
    ever produces - never a seventh, never collapsed into fewer. Mirrors
    core.compound_workflow.CompoundResultKind's own exact six-category
    shape, audited directly against the final e8183d4 implementation."""

    FULL_SUCCESS = "full_success"
    ENABLE_FAILURE = "enable_failure"
    VERIFICATION_MISMATCH = "verification_mismatch"
    VERIFICATION_UNAVAILABLE = "verification_unavailable"
    FINAL_SHOW_FAILURE = "final_show_failure"
    INTERRUPTED = "interrupted"


_INTERRUPTED_MESSAGE = (
    "This request's outcome could not be safely proven after an "
    "interruption, and automatic replay was prohibited."
)


def translate_schedule_compound_workflow_result(
    result: WorkflowResult | None,
) -> tuple[JarvisResponse, ScheduleCompoundResultKind]:
    """Foundation I: translate a real schedule-compound WorkflowResult
    into one of exactly six honest, bounded outcomes. Never wired into
    any live user path in Batch 2 - only this module's own dedicated
    tests call it directly.

    Args:
        result: The real WorkflowResult from WorkflowEngine.run()/
            resume(), or None for the CLAIM_INTERRUPTED case, which has
            no live WorkflowResult to translate at all.

    Returns:
        A tuple of (JarvisResponse, ScheduleCompoundResultKind). No raw
        tool output beyond the final, real schedule_show_enabled_state
        text is ever included; no prompts, AI rationale, or stack
        traces are ever present.
    """
    if result is None:
        return (
            JarvisResponse(success=False, message=_INTERRUPTED_MESSAGE),
            ScheduleCompoundResultKind.INTERRUPTED,
        )

    outcomes = result.step_outcomes
    write_outcome = outcomes[0] if len(outcomes) > 0 else None
    verify_outcome = outcomes[1] if len(outcomes) > 1 else None
    show_outcome = outcomes[2] if len(outcomes) > 2 else None

    if write_outcome is None or write_outcome.status is not StepStatus.COMPLETED:
        return (
            JarvisResponse(
                success=False,
                message=(
                    "The schedule enable did not complete, so no "
                    "verification or final read was attempted."
                ),
                plan=result.plan,
                tool_result=write_outcome.tool_result if write_outcome else None,
            ),
            ScheduleCompoundResultKind.ENABLE_FAILURE,
        )

    approved_schedule_id = write_outcome.step.tool_input.get("schedule_id")

    if verify_outcome is None or verify_outcome.tool_result is None:
        return (
            JarvisResponse(
                success=False,
                message=(
                    "The schedule was enabled, but verification could not "
                    "be completed, so the enable is not confirmed."
                ),
                plan=result.plan,
                tool_result=write_outcome.tool_result,
            ),
            ScheduleCompoundResultKind.VERIFICATION_UNAVAILABLE,
        )

    verification_outcome = _verification_outcome_for_plan(
        result.plan, verify_outcome.tool_result
    )
    if verification_outcome is ScheduleCompoundVerificationOutcome.UNAVAILABLE:
        return (
            JarvisResponse(
                success=False,
                message=(
                    "The schedule was enabled, but verification could not "
                    "be completed, so the enable is not confirmed."
                ),
                plan=result.plan,
                tool_result=verify_outcome.tool_result,
            ),
            ScheduleCompoundResultKind.VERIFICATION_UNAVAILABLE,
        )
    if verification_outcome is ScheduleCompoundVerificationOutcome.FAILED:
        return (
            JarvisResponse(
                success=False,
                message=(
                    "The enable tool reported success, but the structured "
                    "read-back found the schedule not enabled - the "
                    "enable is not confirmed."
                ),
                plan=result.plan,
                tool_result=verify_outcome.tool_result,
            ),
            ScheduleCompoundResultKind.VERIFICATION_MISMATCH,
        )

    # VERIFIED from here on.
    if show_outcome is None or show_outcome.status is not StepStatus.COMPLETED:
        return (
            JarvisResponse(
                success=False,
                message=(
                    f"Schedule {approved_schedule_id} was enabled and "
                    "verified, but the final enabled-state read failed."
                ),
                plan=result.plan,
                tool_result=show_outcome.tool_result if show_outcome else None,
            ),
            ScheduleCompoundResultKind.FINAL_SHOW_FAILURE,
        )

    return (
        JarvisResponse(
            success=True,
            message=(
                f"Jarvis enabled schedule {approved_schedule_id}. "
                "Verification succeeded, and its current enabled state "
                f"is shown below.\n\n{show_outcome.tool_result.output}"
            ),
            plan=result.plan,
            tool_result=show_outcome.tool_result,
        ),
        ScheduleCompoundResultKind.FULL_SUCCESS,
    )
