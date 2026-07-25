"""
compound_workflow.py

Trusted, dormant orchestration-level logic for the one Phase 98
compound template (Phase 98, Batch 2 -
docs/phase_98_live_compound_reentry_plan.md, Foundations C/F/G/H/I):
PROJECT_STATE_UPDATE_PHASE -> internal phase verification ->
PROJECT_STATE_SHOW.

Responsibilities:
    - Recognize a persisted Plan as the exact trusted compound
      fingerprint (Foundation C) - never merely "three steps."
    - Establish a CompoundWorkflowProgress row immediately after the
      trusted plan first pauses, and terminally isolate the pending
      approval/paused workflow if that establishment cannot be
      trusted (Foundation F).
    - Idempotently repair, or terminally isolate, a pending compound
      approval whose progress row is missing because of a hard crash
      between pause and progress creation (Foundation F).
    - Validate, server-side, that a compound approval's progress
      foundation is intact immediately before it would transition to
      APPROVED_UNCONSUMED (Foundation G).
    - Recover an inherited CLAIMED compound workflow using its own
      durable step-level progress evidence, before any generic
      fallback ever sees it, and without a second claim CAS
      (Foundation H).
    - Translate a compound WorkflowResult into one of six honest,
      bounded outcomes (Foundation I).

Does NOT:
    - Get imported by intelligence/planning.py, core/orchestrator.py,
      or main.py. Only this module's own dedicated tests import it in
      Batch 2 - wiring any of it into a live path is Batch 3's own,
      separately-approved responsibility.
    - Call an AI provider, or accept anything from model output. Every
      function here only ever consults already-durable, non-model-
      controlled state (a persisted Plan's own steps, a
      CompoundWorkflowProgress row, a PendingApprovalRecord).
    - Perform a second APPROVED_UNCONSUMED -> CLAIMED claim CAS for an
      already-CLAIMED row, or become a general "resume any claimed
      workflow" mechanism - resume_claimed_compound_workflow() refuses
      (returns NOT_RECOGNIZED) anything that does not pass the
      fingerprint check.
    - Fabricate a VerificationOutcome from a bare ProjectState-value
      comparison outside the real verifier tool's own call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
from workflow.compound_workflow_progress_store import (
    ALLOWED_TEMPLATE_ID,
    CompoundStepStatus,
    CompoundVerificationOutcome,
    CompoundWorkflowProgressError,
    CompoundWorkflowProgressRecord,
    CompoundWorkflowProgressStore,
    ReconciliationConfidence,
    reconcile_phase_update,
)
from workflow.engine import WorkflowEngine
from workflow.paused_workflow_store import PausedWorkflowRecord
from workflow.workflow_models import WorkflowResult

#: The one trusted, static tool-name/capability-id triple this template
#: has ever used - matches intelligence.planning's own trusted plan
#: builder exactly. Never derived from model output.
_WRITE_CAPABILITY_ID = CapabilityId.PROJECT_STATE_UPDATE_PHASE
_VERIFY_CAPABILITY_ID = CapabilityId.PROJECT_STATE_VERIFY_FOCUS
_SHOW_CAPABILITY_ID = CapabilityId.PROJECT_STATE_SHOW
_VERIFY_TOOL_NAME = "project_state_verify"
_SHOW_TOOL_NAME = "project_state_show"

#: Mirrors intelligence.structured_output._MAX_STRING_ARGUMENT_CHARS -
#: declared independently here (this module has no dependency on
#: intelligence/), reused only as a bounded sanity check on an
#: already-durable, previously-validated value being re-inspected after
#: a restart, never as a first-time validation.
_MAX_APPROVED_VALUE_CHARS = 500


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


# ---------------------------------------------------------------------------
# Foundation C: the exact trusted compound recognizer
# ---------------------------------------------------------------------------


def _plan_from_raw_steps(
    plan_steps: list[dict[str, object]] | None, user_request: str | None
) -> Plan | None:
    """Purely, structurally decode a persisted plan_steps JSON list into
    a Plan - never re-validating tool registration or live security
    tier (that revalidation, when actually needed to execute anything,
    remains WorkflowEngine.reconstruct_claimed_compound_plan()'s own
    job). Used only for recognition/identity checks that do not
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


def matches_compound_plan_shape(plan: Plan) -> bool:
    """The exact trusted fingerprint for the one Phase 98 compound
    template - points 1-12 of the amended plan's 14-point recognizer
    (docs/phase_98_live_compound_reentry_plan.md, Foundation C). A
    three-step plan alone is never sufficient.

    Args:
        plan: The Plan to check - already reconstructed by the caller
            (from a live paused workflow, a freshly-built trusted plan,
            or a raw persisted record via _plan_from_raw_steps()).

    Returns:
        True only if every one of points 1-12 holds exactly. False for
        any mismatch, including an otherwise-arbitrary three-step plan.
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

    # Points 2-5: Step 1 exact update identity, fixed field, bounded
    # approved value, exact YELLOW classification.
    if step1.tool_name != write_adapter.tool_name:
        return False
    if step1.tool_input.get("field") != "phase":
        return False
    approved_value = step1.tool_input.get("value")
    if not isinstance(approved_value, str):
        return False
    if not approved_value.strip() or len(approved_value) > _MAX_APPROVED_VALUE_CHARS:
        return False
    if step1.tier is not write_adapter.max_execution_tier:
        return False

    # Points 6-9: Step 2 exact internal verifier identity, no
    # model-controlled arguments, exact GREEN classification, and
    # (folded into points 7/11 below) the same value Step 3 will check.
    if step2.tool_name != verify_adapter.tool_name:
        return False
    if step2.tool_input:
        return False
    if step2.tier is not verify_adapter.max_execution_tier:
        return False

    # Points 10-13: Step 3 exact show identity, no model-controlled
    # input, exact GREEN classification, requires a verified
    # predecessor, and its verification field/expected value agree
    # with Step 1's own approved value.
    if step3.tool_name != show_adapter.tool_name:
        return False
    if step3.tool_input:
        return False
    if step3.tier is not show_adapter.max_execution_tier:
        return False
    if not step3.requires_verified_predecessor:
        return False
    if step3.verification_field_name != "phase":
        return False
    if step3.verification_expected_value != approved_value:
        return False

    return True


def compound_progress_identity_matches(
    plan: Plan,
    progress: CompoundWorkflowProgressRecord,
    *,
    request_id: str,
    workflow_id: str,
) -> bool:
    """Point 14 of the trusted recognizer: the linked progress row's
    own template/request/workflow identity and approved value must
    agree exactly with the paused plan and the caller's own already-
    durable identities. A mismatch fails closed.

    Args:
        plan: The already shape-matched Plan (callers should have
            already confirmed matches_compound_plan_shape(plan)).
        progress: The linked CompoundWorkflowProgressRecord.
        request_id: The approval request id this workflow is linked to.
        workflow_id: This workflow's own correlation id.

    Returns:
        True only if template_id, workflow_id, request_id, and
        approved_phase_value all agree exactly.
    """
    if progress.template_id != ALLOWED_TEMPLATE_ID:
        return False
    if progress.workflow_id != workflow_id:
        return False
    if progress.request_id != request_id:
        return False
    approved_value = plan.steps[0].tool_input.get("value")
    if progress.approved_phase_value != approved_value:
        return False
    return True


def is_recognized_compound_workflow(
    plan: Plan,
    progress: CompoundWorkflowProgressRecord | None,
    *,
    request_id: str,
    workflow_id: str,
) -> bool:
    """The complete 14-point recognizer: plan shape (points 1-12) and
    durable identity cross-check (points 13-14) both hold.

    Args:
        plan: The Plan to check.
        progress: The linked CompoundWorkflowProgressRecord, or None if
            no such row exists.
        request_id: The approval request id this workflow is linked to.
        workflow_id: This workflow's own correlation id.

    Returns:
        True only if every point holds. False (never an exception) for
        any mismatch, including a missing progress row.
    """
    if not matches_compound_plan_shape(plan):
        return False
    if progress is None:
        return False
    return compound_progress_identity_matches(
        plan, progress, request_id=request_id, workflow_id=workflow_id
    )


# ---------------------------------------------------------------------------
# Foundation F: progress creation and approval-visibility gating
# ---------------------------------------------------------------------------


def _isolate_incomplete_compound_pause(
    *,
    approval_invalidator: _ApprovalInvalidator,
    paused_workflow_store: _PausedWorkflowStoreProtocol,
    request_id: str,
    workflow_id: str,
    reason: str,
) -> None:
    """Terminally isolate a pending approval/paused-workflow pair whose
    compound progress foundation could not be established or repaired,
    using only existing, already-bounded APIs (ApprovalManager.
    invalidate_pending(), PausedWorkflowStore.delete()) - never a new
    invalidation mechanism.

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


def establish_compound_progress_or_isolate(
    *,
    plan: Plan,
    workflow_id: str,
    request_id: str,
    progress_store: CompoundWorkflowProgressStore,
    approval_invalidator: _ApprovalInvalidator,
    paused_workflow_store: _PausedWorkflowStoreProtocol,
) -> CompoundWorkflowProgressRecord | str:
    """The exact Foundation F creation contract: called immediately
    after the trusted compound plan's first pause (WorkflowEngine.run()
    returning WAITING), before its approval is ever treated as
    actionable or visible.

    On any failure - the plan does not match the trusted fingerprint,
    CompoundWorkflowProgressStore.create() itself raises, or the freshly
    created row's own identity does not immediately match - the pending
    approval and paused workflow are terminally isolated via existing
    bounded APIs (never lazily left for a later repair; that narrower
    repair is reserved for a genuine, unrecoverable-in-process hard
    crash - see repair_or_isolate_pending_compound_progress()).

    Args:
        plan: The already-paused trusted compound Plan.
        workflow_id: The real workflow id WorkflowEngine.run() produced.
        request_id: The real approval request id the same pause
            produced.
        progress_store: The real CompoundWorkflowProgressStore.
        approval_invalidator: The real ApprovalManager (or a
            structurally-equivalent stand-in for tests).
        paused_workflow_store: The real PausedWorkflowStore.

    Returns:
        The newly created, identity-validated
        CompoundWorkflowProgressRecord on success. A short, bounded
        failure reason string on any failure - never an exception.
    """
    if not matches_compound_plan_shape(plan):
        return "the plan does not match the trusted compound fingerprint"

    approved_value = plan.steps[0].tool_input.get("value")
    assert isinstance(approved_value, str)  # guaranteed by matches_compound_plan_shape

    try:
        record = progress_store.create(
            workflow_id=workflow_id,
            template_id=ALLOWED_TEMPLATE_ID,
            request_id=request_id,
            approved_phase_value=approved_value,
        )
    except Exception as exc:  # noqa: BLE001 - fail closed on any DB/infra error,
        # not only CompoundWorkflowProgressError (e.g. a duplicate
        # workflow_id raises a raw IntegrityError, never this store's
        # own typed exception) - checkpoint-failure semantics require
        # fail-closed on any error, per docs/phase_98_live_compound_reentry_plan.md.
        reason = f"compound progress could not be established: {exc}"
        _isolate_incomplete_compound_pause(
            approval_invalidator=approval_invalidator,
            paused_workflow_store=paused_workflow_store,
            request_id=request_id,
            workflow_id=workflow_id,
            reason=reason,
        )
        return reason

    if not compound_progress_identity_matches(
        plan, record, request_id=request_id, workflow_id=workflow_id
    ):
        reason = "compound progress identity mismatch immediately after creation"
        _isolate_incomplete_compound_pause(
            approval_invalidator=approval_invalidator,
            paused_workflow_store=paused_workflow_store,
            request_id=request_id,
            workflow_id=workflow_id,
            reason=reason,
        )
        return reason

    return record


@dataclass(frozen=True, slots=True)
class CompoundProgressRepairSummary:
    """A small, honest summary of what
    repair_or_isolate_pending_compound_progress() did.

    Attributes:
        repaired: Number of PENDING, workflow-linked, compound-shaped
            rows whose missing progress row was idempotently created.
        isolated: Number of rows that could not be safely repaired and
            were terminally isolated instead.
    """

    repaired: int
    isolated: int


def repair_or_isolate_pending_compound_progress(
    *,
    pending_store: _PendingApprovalStoreProtocol,
    paused_workflow_store: _PausedWorkflowStoreProtocol,
    progress_store: CompoundWorkflowProgressStore,
    approval_invalidator: _ApprovalInvalidator,
    pending_status: object,
) -> CompoundProgressRepairSummary:
    """Foundation F's hard-crash repair pass: detect an exact,
    trusted-fingerprint compound paused plan whose progress row is
    missing (or mismatched) because of a crash between pause and
    progress creation, and either idempotently repair it or terminally
    isolate it - before any pending approval is ever rebuilt or shown.

    Never touches a row that is not workflow-linked, whose paused plan
    cannot be reconstructed, or whose plan does not match the trusted
    compound fingerprint at all - those are left completely untouched,
    exactly as every existing non-compound YELLOW workflow already is.

    Args:
        pending_store: The real PendingApprovalStore.
        paused_workflow_store: The real PausedWorkflowStore.
        progress_store: The real CompoundWorkflowProgressStore.
        approval_invalidator: The real ApprovalManager (or a
            structurally-equivalent stand-in for tests).
        pending_status: The PENDING PendingApprovalHandoffStatus value
            (passed in rather than imported, to avoid this module
            depending on approval.approval_models for one enum value).

    Returns:
        A CompoundProgressRepairSummary.
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
        if plan is None or not matches_compound_plan_shape(plan):
            continue

        existing = progress_store.get(workflow_id)
        if existing is not None and compound_progress_identity_matches(
            plan, existing, request_id=record.request_id, workflow_id=workflow_id
        ):
            continue

        approved_value = plan.steps[0].tool_input.get("value")
        if existing is not None or not isinstance(approved_value, str):
            # Either a mismatched, already-existing row (too ambiguous
            # to overwrite) or an unusable approved value - neither can
            # be safely repaired.
            _isolate_incomplete_compound_pause(
                approval_invalidator=approval_invalidator,
                paused_workflow_store=paused_workflow_store,
                request_id=record.request_id,
                workflow_id=workflow_id,
                reason="compound progress could not be unambiguously repaired",
            )
            isolated += 1
            continue

        try:
            progress_store.create(
                workflow_id=workflow_id,
                template_id=ALLOWED_TEMPLATE_ID,
                request_id=record.request_id,
                approved_phase_value=approved_value,
            )
            repaired += 1
        except Exception:  # noqa: BLE001 - fail closed on any DB/infra error
            _isolate_incomplete_compound_pause(
                approval_invalidator=approval_invalidator,
                paused_workflow_store=paused_workflow_store,
                request_id=record.request_id,
                workflow_id=workflow_id,
                reason="compound progress could not be repaired",
            )
            isolated += 1

    return CompoundProgressRepairSummary(repaired=repaired, isolated=isolated)


# ---------------------------------------------------------------------------
# Foundation G: approval-time progress validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompoundApprovalValidation:
    """The result of one validate_compound_approval_before_transition()
    call.

    Attributes:
        is_compound_workflow: False if the linked paused plan does not
            match the trusted compound fingerprint at all - in this
            case `valid` is always True and `reason` always None: this
            validation simply does not apply, and every existing
            non-compound approval must remain unaffected.
        valid: True if the transition may proceed (either because this
            is not a compound-linked approval at all, or because its
            progress foundation is intact). False only when this is a
            recognized compound workflow whose progress is missing or
            mismatched.
        reason: Set only when valid is False - a short, bounded, honest
            explanation.
    """

    is_compound_workflow: bool
    valid: bool
    reason: str | None = None


def validate_compound_approval_before_transition(
    *,
    paused_workflow_store: _PausedWorkflowStoreProtocol,
    progress_store: CompoundWorkflowProgressStore,
    request_id: str,
    workflow_id: str,
) -> CompoundApprovalValidation:
    """Foundation G: the trusted, server-side check a caller must run
    immediately before transitioning a workflow-linked pending approval
    to APPROVED_UNCONSUMED, independent of whether progress creation
    was ever attempted earlier.

    Existing non-compound approvals are always reported
    is_compound_workflow=False, valid=True - this function never
    restricts anything it does not recognize as this one trusted
    template.

    Args:
        paused_workflow_store: The real PausedWorkflowStore.
        progress_store: The real CompoundWorkflowProgressStore.
        request_id: The approval request about to be decided.
        workflow_id: The linked workflow id, from the same request's
            own ApprovalRequest.metadata - never derived any other way.

    Returns:
        A CompoundApprovalValidation.
    """
    paused_record = paused_workflow_store.get(workflow_id)
    if paused_record is None or paused_record.corrupt:
        return CompoundApprovalValidation(is_compound_workflow=False, valid=True)

    plan = _plan_from_raw_steps(paused_record.plan_steps, paused_record.user_request)
    if plan is None or not matches_compound_plan_shape(plan):
        return CompoundApprovalValidation(is_compound_workflow=False, valid=True)

    progress = progress_store.get(workflow_id)
    if progress is None:
        return CompoundApprovalValidation(
            is_compound_workflow=True,
            valid=False,
            reason="no compound progress row exists for this workflow",
        )
    if not compound_progress_identity_matches(
        plan, progress, request_id=request_id, workflow_id=workflow_id
    ):
        return CompoundApprovalValidation(
            is_compound_workflow=True,
            valid=False,
            reason="compound progress identity does not match this request",
        )
    return CompoundApprovalValidation(is_compound_workflow=True, valid=True)


# ---------------------------------------------------------------------------
# Foundation H: compound-specific inherited-CLAIMED recovery
# ---------------------------------------------------------------------------


class CompoundClaimedOutcome(Enum):
    """The bounded outcome of one resume_claimed_compound_workflow()
    call. NOT_RECOGNIZED means this row was not this trusted template
    (or its identity did not match) - the caller must leave it
    completely untouched for the existing, unchanged generic CLAIMED
    fallback."""

    CONSUMED = "consumed"
    CLAIM_INTERRUPTED = "claim_interrupted"
    NOT_RECOGNIZED = "not_recognized"


def _verification_outcome_for_plan(
    plan: Plan, tool_result: ToolResult
) -> CompoundVerificationOutcome:
    """The same exact-match verification logic
    workflow.compound_progress_observer.CompoundStepObserver uses,
    applied here for the CLAIMED-recovery rerun path (Section 15 of the
    amended plan: "Step 2 active without persisted outcome... rerun the
    trusted exact verifier; persist its new VerificationResult").

    Args:
        plan: The reconstructed, already fingerprint-matched Plan.
        tool_result: The freshly-obtained verifier ToolResult.

    Returns:
        VERIFIED, FAILED, or UNAVAILABLE - never fabricated from a bare
        success flag alone.
    """
    if not tool_result.success:
        return CompoundVerificationOutcome.UNAVAILABLE
    step_3 = plan.steps[2]
    field_name = step_3.verification_field_name or "phase"
    expected_value = step_3.verification_expected_value
    actual = tool_result.metadata.get(field_name)
    if not isinstance(actual, str) or expected_value is None:
        return CompoundVerificationOutcome.UNAVAILABLE
    if actual == expected_value:
        return CompoundVerificationOutcome.VERIFIED
    return CompoundVerificationOutcome.FAILED


def resume_claimed_compound_workflow(
    record: PendingApprovalRecord,
    *,
    pending_store: _PendingApprovalStoreProtocol,
    paused_workflow_store: _PausedWorkflowStoreProtocol,
    progress_store: CompoundWorkflowProgressStore,
    workflow_engine: WorkflowEngine,
    tool_registry: ToolRegistry,
    security_manager: SecurityManager,
    tool_executor: ToolExecutor,
) -> CompoundClaimedOutcome:
    """The narrow, Foundation H inherited-CLAIMED continuation path -
    never a general "resume any claimed workflow" mechanism.

    Performs no second APPROVED_UNCONSUMED -> CLAIMED claim CAS: `record`
    must already be CLAIMED (the caller's own responsibility to have
    fetched it that way). Selects recovery only from trusted, durable,
    non-model-controlled state: the persisted plan's own fingerprint,
    the linked progress row's own identity, and the crash-state matrix
    below. Never re-invokes Step 1's write tool under any circumstance;
    only Steps 2/3 (both read-only) are ever (re)run, and only when the
    matrix says that is safe.

    Args:
        record: The already-CLAIMED PendingApprovalRecord.
        pending_store: The real PendingApprovalStore.
        paused_workflow_store: The real PausedWorkflowStore.
        progress_store: The real CompoundWorkflowProgressStore.
        workflow_engine: The real, already-restarted WorkflowEngine,
            used only for its read-only reconstruct_claimed_compound_plan().
        tool_registry: The live ToolRegistry, for plan revalidation.
        security_manager: The live SecurityManager, for plan
            revalidation.
        tool_executor: The real ToolExecutor, used to (re)run Steps
            2/3 only.

    Returns:
        CONSUMED if a known terminal result was reached (success or
        honest failure). CLAIM_INTERRUPTED if safe continuation could
        not be established. NOT_RECOGNIZED if this row is not (or no
        longer verifiably) this one trusted template - the caller must
        leave it for the existing, unchanged generic CLAIMED fallback.
    """
    workflow_id = record.metadata.get("workflow_id")
    if not workflow_id:
        return CompoundClaimedOutcome.NOT_RECOGNIZED

    paused_record = paused_workflow_store.get(workflow_id)
    if paused_record is None:
        return CompoundClaimedOutcome.NOT_RECOGNIZED

    shape_plan = _plan_from_raw_steps(paused_record.plan_steps, paused_record.user_request)
    if shape_plan is None or not matches_compound_plan_shape(shape_plan):
        return CompoundClaimedOutcome.NOT_RECOGNIZED

    progress = progress_store.get(workflow_id)
    if progress is None or not compound_progress_identity_matches(
        shape_plan, progress, request_id=record.request_id, workflow_id=workflow_id
    ):
        return CompoundClaimedOutcome.NOT_RECOGNIZED

    # From here on this row IS the recognized compound template - every
    # remaining outcome is either CONSUMED or CLAIM_INTERRUPTED, never
    # a silent fall-through to the generic fallback.
    plan, reason = workflow_engine.reconstruct_claimed_compound_plan(
        paused_record, registry=tool_registry, security_manager=security_manager
    )
    if plan is None:
        pending_store.mark_claim_interrupted(record.request_id)
        return CompoundClaimedOutcome.CLAIM_INTERRUPTED

    return _continue_recognized_compound_workflow(
        plan,
        progress,
        workflow_id=workflow_id,
        request_id=record.request_id,
        pending_store=pending_store,
        progress_store=progress_store,
        tool_executor=tool_executor,
    )


def _read_current_project_state(
    tool_executor: ToolExecutor,
) -> tuple[str | None, datetime | None]:
    """Read the real, current ProjectState phase/last_updated via the
    one real, audited project_state_verify tool call - never a raw
    store read.

    Args:
        tool_executor: The real ToolExecutor.

    Returns:
        (phase_value, last_updated_at), either possibly None if the
        read itself did not succeed or returned no usable value.
    """
    result = tool_executor.execute(_VERIFY_TOOL_NAME, {}, session_id=None)
    if not result.success:
        return None, None
    phase_value = result.metadata.get("phase")
    last_updated = result.metadata.get("last_updated_at")
    return (
        phase_value if isinstance(phase_value, str) else None,
        last_updated if isinstance(last_updated, datetime) else None,
    )


def _continue_recognized_compound_workflow(
    plan: Plan,
    progress: CompoundWorkflowProgressRecord,
    *,
    workflow_id: str,
    request_id: str,
    pending_store: _PendingApprovalStoreProtocol,
    progress_store: CompoundWorkflowProgressStore,
    tool_executor: ToolExecutor,
) -> CompoundClaimedOutcome:
    """The exact crash-state matrix (Section 15 of the amended plan),
    applied once `plan`/`progress` are already known to be the
    recognized, revalidated compound template.

    Never re-invokes Step 1's write tool under any circumstance.
    """
    # --- Step 1 ---------------------------------------------------------
    if progress.step_1_status is CompoundStepStatus.PENDING:
        # The pre-execution observation/active checkpoint (Section 12,
        # item 1) is always the very first thing resume()'s observer
        # does, before the write tool is ever invoked - PENDING here
        # proves the write provably never ran. Still never auto-started
        # from this recovery path (no automatic replay of a CLAIMED
        # workflow's write) - fail closed.
        pending_store.mark_claim_interrupted(request_id)
        return CompoundClaimedOutcome.CLAIM_INTERRUPTED

    if progress.step_1_status is CompoundStepStatus.IN_PROGRESS:
        current_phase, current_last_updated = _read_current_project_state(tool_executor)
        reconciliation = reconcile_phase_update(
            approved_phase_value=progress.approved_phase_value,
            pre_execution_phase_value=progress.pre_execution_phase_value,
            pre_execution_last_updated=progress.pre_execution_last_updated,
            current_phase_value=current_phase,
            current_last_updated=current_last_updated,
        )
        if reconciliation.confidence is ReconciliationConfidence.POSTCONDITION_NOT_SATISFIED:
            try:
                progress = progress_store.mark_step_1_failed(workflow_id)
            except CompoundWorkflowProgressError:
                pass
            pending_store.mark_consumed(request_id)
            return CompoundClaimedOutcome.CONSUMED
        if (
            reconciliation.confidence
            is ReconciliationConfidence.POSTCONDITION_SATISFIED_STATE_CHANGED
        ):
            progress = progress_store.mark_step_1_completed(workflow_id)
            # Falls through to Step 2 evaluation below.
        else:
            # POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED - genuinely
            # ambiguous; never claim exactly-once execution. Flag for
            # operator visibility (never blocking) and fail closed.
            try:
                progress_store.mark_needs_reconciliation(workflow_id)
            except CompoundWorkflowProgressError:
                pass
            pending_store.mark_claim_interrupted(request_id)
            return CompoundClaimedOutcome.CLAIM_INTERRUPTED

    # --- Step 2 -----------------------------------------------------------
    if progress.step_2_status in (
        CompoundStepStatus.PENDING,
        CompoundStepStatus.IN_PROGRESS,
    ):
        if progress.step_2_status is CompoundStepStatus.PENDING:
            progress = progress_store.start_step_2(workflow_id)
        verify_result = tool_executor.execute(_VERIFY_TOOL_NAME, {}, session_id=None)
        outcome = _verification_outcome_for_plan(plan, verify_result)
        progress = progress_store.mark_step_2_completed(
            workflow_id, verification_outcome=outcome
        )
        if outcome is not CompoundVerificationOutcome.VERIFIED:
            pending_store.mark_consumed(request_id)
            return CompoundClaimedOutcome.CONSUMED

    if progress.step_2_verification_outcome is not CompoundVerificationOutcome.VERIFIED:
        # Already completed in an earlier attempt with a non-VERIFIED
        # outcome - a known, terminal (non-success) result.
        pending_store.mark_consumed(request_id)
        return CompoundClaimedOutcome.CONSUMED

    # --- Step 3 -----------------------------------------------------------
    if progress.step_3_status in (
        CompoundStepStatus.PENDING,
        CompoundStepStatus.IN_PROGRESS,
    ):
        if progress.step_3_status is CompoundStepStatus.PENDING:
            progress_store.start_step_3(workflow_id)
        show_result = tool_executor.execute(_SHOW_TOOL_NAME, {}, session_id=None)
        if show_result.success:
            progress_store.mark_step_3_completed(workflow_id)
        else:
            progress_store.mark_step_3_failed(workflow_id)
        pending_store.mark_consumed(request_id)
        return CompoundClaimedOutcome.CONSUMED

    # step_3_status already COMPLETED or FAILED - nothing left to (re)run.
    pending_store.mark_consumed(request_id)
    return CompoundClaimedOutcome.CONSUMED


@dataclass(frozen=True, slots=True)
class CompoundClaimedReconciliationSummary:
    """A small, honest summary of what
    reconcile_claimed_compound_workflows() did.

    Attributes:
        consumed: Number of recognized compound CLAIMED rows resolved
            to CONSUMED.
        interrupted: Number resolved to CLAIM_INTERRUPTED.
        left_for_generic: Number not recognized as this template at
            all - left completely untouched for the existing, unchanged
            generic CLAIMED fallback to process next.
    """

    consumed: int
    interrupted: int
    left_for_generic: int


def reconcile_claimed_compound_workflows(
    *,
    pending_store: _PendingApprovalStoreProtocol,
    paused_workflow_store: _PausedWorkflowStoreProtocol,
    progress_store: CompoundWorkflowProgressStore,
    workflow_engine: WorkflowEngine,
    tool_registry: ToolRegistry,
    security_manager: SecurityManager,
    tool_executor: ToolExecutor,
    claimed_status: object,
) -> CompoundClaimedReconciliationSummary:
    """Foundation H's own dormant startup pass: reconcile every
    inherited CLAIMED row this template recognizes, using its own
    durable step-level progress evidence - intended (in a future,
    separately-approved Batch 3 wiring) to run strictly before the
    existing, unchanged generic `main._reconcile_claimed_rows()` pass,
    so a recoverable compound workflow is never marked terminal
    CLAIM_INTERRUPTED by the generic rule before this pass ever sees
    it. Not wired into main.py's own startup ordering in Batch 2 -
    provided here, fully tested, for that future wiring.

    Args:
        pending_store: The real PendingApprovalStore.
        paused_workflow_store: The real PausedWorkflowStore.
        progress_store: The real CompoundWorkflowProgressStore.
        workflow_engine: The real, already-restarted WorkflowEngine.
        tool_registry: The live ToolRegistry.
        security_manager: The live SecurityManager.
        tool_executor: The real ToolExecutor.
        claimed_status: The CLAIMED PendingApprovalHandoffStatus value
            (passed in rather than imported, mirroring
            repair_or_isolate_pending_compound_progress()'s own
            convention).

    Returns:
        A CompoundClaimedReconciliationSummary. Rows counted in
        left_for_generic are left with their handoff_status still
        CLAIMED, exactly as found - the caller's own subsequent,
        unchanged generic pass is what processes them next.
    """
    consumed = 0
    interrupted = 0
    left_for_generic = 0

    for record in pending_store.list_by_handoff_status(claimed_status):
        outcome = resume_claimed_compound_workflow(
            record,
            pending_store=pending_store,
            paused_workflow_store=paused_workflow_store,
            progress_store=progress_store,
            workflow_engine=workflow_engine,
            tool_registry=tool_registry,
            security_manager=security_manager,
            tool_executor=tool_executor,
        )
        if outcome is CompoundClaimedOutcome.CONSUMED:
            consumed += 1
        elif outcome is CompoundClaimedOutcome.CLAIM_INTERRUPTED:
            interrupted += 1
        else:
            left_for_generic += 1

    return CompoundClaimedReconciliationSummary(
        consumed=consumed, interrupted=interrupted, left_for_generic=left_for_generic
    )


# ---------------------------------------------------------------------------
# Foundation I: the dormant compound result translator
# ---------------------------------------------------------------------------


class CompoundResultKind(Enum):
    """The exact six outcomes translate_compound_workflow_result() ever
    produces - never a seventh, never collapsed into fewer."""

    FULL_SUCCESS = "full_success"
    UPDATE_FAILURE = "update_failure"
    VERIFICATION_MISMATCH = "verification_mismatch"
    VERIFICATION_UNAVAILABLE = "verification_unavailable"
    FINAL_SHOW_FAILURE = "final_show_failure"
    INTERRUPTED = "interrupted"


_INTERRUPTED_MESSAGE = (
    "This request's outcome could not be safely proven after an "
    "interruption, and automatic replay was prohibited."
)


def translate_compound_workflow_result(
    result: WorkflowResult | None,
) -> tuple[JarvisResponse, CompoundResultKind]:
    """Foundation I: translate a real compound WorkflowResult into one
    of exactly six honest, bounded outcomes. Never wired into any live
    user path in Batch 2 - only this module's own dedicated tests call
    it directly.

    Args:
        result: The real WorkflowResult from WorkflowEngine.run()/
            resume(), or None for the CLAIM_INTERRUPTED case, which has
            no live WorkflowResult to translate at all.

    Returns:
        A tuple of (JarvisResponse, CompoundResultKind). No raw tool
        output beyond the final, real project_state_show text is ever
        included; no prompts, AI rationale, or stack traces are ever
        present.
    """
    if result is None:
        return (
            JarvisResponse(success=False, message=_INTERRUPTED_MESSAGE),
            CompoundResultKind.INTERRUPTED,
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
                    "The project-state phase update did not complete, so "
                    "no verification or final read was attempted."
                ),
                plan=result.plan,
                tool_result=write_outcome.tool_result if write_outcome else None,
            ),
            CompoundResultKind.UPDATE_FAILURE,
        )

    approved_value = str(write_outcome.step.tool_input.get("value", ""))

    if verify_outcome is None or verify_outcome.tool_result is None:
        return (
            JarvisResponse(
                success=False,
                message=(
                    "The update was applied, but verification could not "
                    "be completed, so the update is not confirmed."
                ),
                plan=result.plan,
                tool_result=write_outcome.tool_result,
            ),
            CompoundResultKind.VERIFICATION_UNAVAILABLE,
        )

    verification_outcome = _verification_outcome_for_plan(
        result.plan, verify_outcome.tool_result
    )
    if verification_outcome is CompoundVerificationOutcome.UNAVAILABLE:
        return (
            JarvisResponse(
                success=False,
                message=(
                    "The update was applied, but verification could not "
                    "be completed, so the update is not confirmed."
                ),
                plan=result.plan,
                tool_result=verify_outcome.tool_result,
            ),
            CompoundResultKind.VERIFICATION_UNAVAILABLE,
        )
    if verification_outcome is CompoundVerificationOutcome.FAILED:
        return (
            JarvisResponse(
                success=False,
                message=(
                    "The update tool reported success, but the structured "
                    "read-back found a different value than requested - "
                    "the update is not confirmed."
                ),
                plan=result.plan,
                tool_result=verify_outcome.tool_result,
            ),
            CompoundResultKind.VERIFICATION_MISMATCH,
        )

    # VERIFIED from here on.
    if show_outcome is None or show_outcome.status is not StepStatus.COMPLETED:
        return (
            JarvisResponse(
                success=False,
                message=(
                    f"The update to '{approved_value}' was verified, but "
                    "the final project-state read failed."
                ),
                plan=result.plan,
                tool_result=show_outcome.tool_result if show_outcome else None,
            ),
            CompoundResultKind.FINAL_SHOW_FAILURE,
        )

    return (
        JarvisResponse(
            success=True,
            message=(
                f"Jarvis updated the project phase to: {approved_value}. "
                "Verification succeeded, and the current project state is "
                f"shown below.\n\n{show_outcome.tool_result.output}"
            ),
            plan=result.plan,
            tool_result=show_outcome.tool_result,
        ),
        CompoundResultKind.FULL_SUCCESS,
    )
