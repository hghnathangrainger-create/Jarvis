"""
test_compound_claimed_recovery.py

Real, on-disk-database integration tests for core.compound_workflow's
Foundation H: the narrow, inherited-CLAIMED compound recovery path
(resume_claimed_compound_workflow / reconcile_claimed_compound_workflows)
and the exact crash-state matrix (Phase 98, Batch 2 -
docs/phase_98_live_compound_reentry_plan.md).

Dormant: not wired into main.reconcile_claimed_handoffs()'s own startup
ordering yet - these tests call the functions directly, exactly as
Batch 3's own future wiring will, using real
PendingApprovalStore/PausedWorkflowStore/CompoundWorkflowProgressStore/
WorkflowEngine/ToolExecutor/SecurityManager/ToolRegistry bound to a
real, temporary on-disk SQLite file - never :memory:, never in-memory
object reuse only, mirroring
tests/integration/test_yellow_workflow_restart_continuation.py's own
established convention.
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_models import PendingApprovalHandoffStatus  # noqa: E402
from approval.pending_approval_store import PendingApprovalStore  # noqa: E402
from config.constants import SecurityTier  # noqa: E402
from core.compound_workflow import (  # noqa: E402
    CompoundClaimedOutcome,
    CompoundClaimedReconciliationSummary,
    reconcile_claimed_compound_workflows,
    resume_claimed_compound_workflow,
)
from intelligence.capability_catalog import CAPABILITY_CATALOG  # noqa: E402
from intelligence.planning import (  # noqa: E402
    _build_phase_update_verify_show_workflow_plan,
)
from planner.plan_models import Plan, PlanStep  # noqa: E402
from project_state.project_state_store import ProjectStateStore  # noqa: E402
from security.security_manager import SecurityManager  # noqa: E402
from storage.database import create_session_factory, initialize_database  # noqa: E402
from tools.builtin.project_state_show_tool import ProjectStateShowTool  # noqa: E402
from tools.builtin.project_state_update_tool import ProjectStateUpdateTool  # noqa: E402
from tools.builtin.project_state_verify_tool import ProjectStateVerifyTool  # noqa: E402
from tools.executor import ToolExecutor  # noqa: E402
from tools.registry import ToolRegistry  # noqa: E402
from workflow.compound_workflow_progress_store import (  # noqa: E402
    ALLOWED_TEMPLATE_ID,
    CompoundOverallStatus,
    CompoundStepStatus,
    CompoundVerificationOutcome,
    CompoundWorkflowProgressStore,
)
from workflow.engine import WorkflowEngine  # noqa: E402
from workflow.paused_workflow_store import PausedWorkflowStore  # noqa: E402


def _session_factory_for(db_path: Path):
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(engine)
    return create_session_factory(engine)


class _Stack:
    """One full, real, durable-persistence stack for compound recovery
    tests - mirrors main.build_orchestrator()'s own composition order
    for the collaborators this feature needs."""

    def __init__(self, db_path: Path) -> None:
        self.session_factory = _session_factory_for(db_path)
        self.project_state_store = ProjectStateStore(self.session_factory)
        self.registry = ToolRegistry()
        self.registry.register_tool(ProjectStateShowTool(self.project_state_store))
        self.registry.register_tool(ProjectStateUpdateTool(self.project_state_store))
        self.registry.register_tool(ProjectStateVerifyTool(self.project_state_store))
        self.security = SecurityManager()
        self.executor = ToolExecutor(
            registry=self.registry, security_manager=self.security, logger=None
        )
        self.pending_store = PendingApprovalStore(self.session_factory)
        self.paused_store = PausedWorkflowStore(self.session_factory)
        self.progress_store = CompoundWorkflowProgressStore(self.session_factory)
        self.workflow_engine = WorkflowEngine(
            executor=self.executor, approvals=_NullApprovals(), paused_store=self.paused_store
        )

    def trusted_plan(self, value: str) -> Plan:
        plan = _build_phase_update_verify_show_workflow_plan(
            "update phase and then show project state",
            approved_phase_value=value,
            tool_registry=self.registry,
            security_manager=self.security,
            session_id=None,
            catalog=CAPABILITY_CATALOG,
        )
        assert isinstance(plan, Plan)
        return plan

    def seed_claimed_row(
        self, plan: Plan, *, workflow_id: str = "wf-1", value: str = "approved-value"
    ) -> str:
        """Create a durable CLAIMED pending-approval row, its paused
        plan, and (unless the caller wants to test the missing-progress
        case) its compound progress row - mirroring exactly what a real
        prior process would have left behind before crashing."""
        request = self.pending_store.save(
            request_id=f"req-{workflow_id}",
            action="update project state phase",
            reason="needs approval",
            security_tier="yellow",
            metadata={"workflow_id": workflow_id},
            tool_name="project_state_update",
            tool_input=dict(plan.steps[0].tool_input),
        )
        self.pending_store.mark_approved_unconsumed(request.request_id)
        self.pending_store.claim_for_resume(request.request_id)

        self.paused_store.save(
            workflow_id=workflow_id,
            session_id=None,
            request_id=request.request_id,
            user_request=plan.user_request,
            plan_steps=[WorkflowEngine._plan_step_to_dict(s) for s in plan.steps],
            completed_outcomes=[],
            waiting_step_index=0,
            resolved_tool_input=dict(plan.steps[0].tool_input),
        )
        return request.request_id

    def recover(self, request_id: str) -> CompoundClaimedOutcome:
        record = self.pending_store.get(request_id)
        assert record is not None
        return resume_claimed_compound_workflow(
            record,
            pending_store=self.pending_store,
            paused_workflow_store=self.paused_store,
            progress_store=self.progress_store,
            workflow_engine=self.workflow_engine,
            tool_registry=self.registry,
            security_manager=self.security,
            tool_executor=self.executor,
        )


class _NullApprovals:
    """A minimal ApprovalManager stand-in - the WorkflowEngine
    constructed here is only ever used for its
    reconstruct_claimed_compound_plan() accessor, never run()/resume(),
    so no real approval collaborator is needed."""

    def has_pending(self, request_id: str) -> bool:
        return False

    def get_decision(self, request_id: str):
        from approval.approval_models import ApprovalError

        raise ApprovalError("not used")

    def handoff_status_for(self, request_id: str):
        return None


# --- Missing progress after claim -------------------------------------------


def test_missing_progress_is_not_recognized_and_left_for_generic_fallback(
    tmp_path: Path,
) -> None:
    stack = _Stack(tmp_path / "missing_progress.db")
    plan = stack.trusted_plan("v1")
    request_id = stack.seed_claimed_row(plan, workflow_id="wf-1", value="v1")
    # No compound progress row created at all - simulating the crash
    # window between claim and the first checkpoint ever being written.

    outcome = stack.recover(request_id)
    assert outcome is CompoundClaimedOutcome.NOT_RECOGNIZED
    # Never executes anything, never reconstructs from model output -
    # the row is left exactly CLAIMED for the existing, unchanged
    # generic fallback to resolve (which will mark CLAIM_INTERRUPTED,
    # since no positive workflow-history terminal evidence exists).
    assert (
        stack.pending_store.get_handoff_status(request_id)
        == PendingApprovalHandoffStatus.CLAIMED
    )
    assert stack.project_state_store.get() is None


# --- Step 1 pending (never started) -----------------------------------------


def test_step_1_pending_fails_closed_without_starting_the_write(tmp_path: Path) -> None:
    stack = _Stack(tmp_path / "step1_pending.db")
    plan = stack.trusted_plan("v2")
    request_id = stack.seed_claimed_row(plan, workflow_id="wf-1", value="v2")
    stack.progress_store.create(
        workflow_id="wf-1",
        template_id=ALLOWED_TEMPLATE_ID,
        request_id=request_id,
        approved_phase_value="v2",
    )
    # step_1_status is PENDING - the pre-execution checkpoint (always
    # the first thing resume()'s observer does) was never committed,
    # proving the write provably never ran.

    outcome = stack.recover(request_id)
    assert outcome is CompoundClaimedOutcome.CLAIM_INTERRUPTED
    assert (
        stack.pending_store.get_handoff_status(request_id)
        == PendingApprovalHandoffStatus.CLAIM_INTERRUPTED
    )
    assert stack.project_state_store.get() is None  # never auto-started


# --- Step 1 active/in-progress: reconciliation classifications -------------


def test_step_1_active_not_satisfied_marks_failed_and_consumed(tmp_path: Path) -> None:
    stack = _Stack(tmp_path / "step1_not_satisfied.db")
    plan = stack.trusted_plan("v3")
    request_id = stack.seed_claimed_row(plan, workflow_id="wf-1", value="v3")
    stack.progress_store.create(
        workflow_id="wf-1",
        template_id=ALLOWED_TEMPLATE_ID,
        request_id=request_id,
        approved_phase_value="v3",
    )
    stack.progress_store.record_pre_execution_observation(
        "wf-1", phase_value="pre-existing-phase", last_updated=None
    )
    # ProjectState remains at its pre-existing value - the write
    # demonstrably never took effect.
    stack.project_state_store.update("phase", "pre-existing-phase")

    outcome = stack.recover(request_id)
    assert outcome is CompoundClaimedOutcome.CONSUMED
    record = stack.progress_store.get("wf-1")
    assert record.step_1_status is CompoundStepStatus.FAILED
    assert record.overall_status is CompoundOverallStatus.FAILED
    assert (
        stack.pending_store.get_handoff_status(request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )
    assert stack.project_state_store.get().phase == "pre-existing-phase"


def test_step_1_active_state_changed_continues_to_full_success(tmp_path: Path) -> None:
    stack = _Stack(tmp_path / "step1_state_changed.db")
    plan = stack.trusted_plan("v4")
    request_id = stack.seed_claimed_row(plan, workflow_id="wf-1", value="v4")
    stack.progress_store.create(
        workflow_id="wf-1",
        template_id=ALLOWED_TEMPLATE_ID,
        request_id=request_id,
        approved_phase_value="v4",
    )
    stack.progress_store.record_pre_execution_observation(
        "wf-1", phase_value="old-phase", last_updated=None
    )
    # The write DID happen (real evidence: the durable value now
    # matches approved_phase_value and differs from the pre-state).
    stack.project_state_store.update("phase", "v4")

    outcome = stack.recover(request_id)
    assert outcome is CompoundClaimedOutcome.CONSUMED
    record = stack.progress_store.get("wf-1")
    assert record.step_1_status is CompoundStepStatus.COMPLETED
    assert record.step_2_verification_outcome is CompoundVerificationOutcome.VERIFIED
    assert record.step_3_status is CompoundStepStatus.COMPLETED
    assert record.overall_status is CompoundOverallStatus.COMPLETED
    assert (
        stack.pending_store.get_handoff_status(request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )


def test_step_1_active_execution_unconfirmed_is_claim_interrupted(tmp_path: Path) -> None:
    stack = _Stack(tmp_path / "step1_unconfirmed.db")
    plan = stack.trusted_plan("v5")
    request_id = stack.seed_claimed_row(plan, workflow_id="wf-1", value="v5")
    stack.progress_store.create(
        workflow_id="wf-1",
        template_id=ALLOWED_TEMPLATE_ID,
        request_id=request_id,
        approved_phase_value="v5",
    )
    # Pre-state already matched the approved value, and no timestamp
    # evidence exists - genuinely ambiguous.
    stack.progress_store.record_pre_execution_observation(
        "wf-1", phase_value="v5", last_updated=None
    )
    stack.project_state_store.update("phase", "v5")

    outcome = stack.recover(request_id)
    assert outcome is CompoundClaimedOutcome.CLAIM_INTERRUPTED
    record = stack.progress_store.get("wf-1")
    assert record.overall_status is CompoundOverallStatus.NEEDS_RECONCILIATION
    assert (
        stack.pending_store.get_handoff_status(request_id)
        == PendingApprovalHandoffStatus.CLAIM_INTERRUPTED
    )


# --- Step 1 completed --------------------------------------------------------


def test_step_1_completed_never_reruns_the_write(tmp_path: Path) -> None:
    stack = _Stack(tmp_path / "step1_completed.db")
    plan = stack.trusted_plan("v6")
    request_id = stack.seed_claimed_row(plan, workflow_id="wf-1", value="v6")
    stack.progress_store.create(
        workflow_id="wf-1",
        template_id=ALLOWED_TEMPLATE_ID,
        request_id=request_id,
        approved_phase_value="v6",
    )
    stack.progress_store.record_pre_execution_observation(
        "wf-1", phase_value="old", last_updated=None
    )
    stack.progress_store.mark_step_1_completed("wf-1")
    stack.project_state_store.update("phase", "v6")

    outcome = stack.recover(request_id)
    assert outcome is CompoundClaimedOutcome.CONSUMED
    record = stack.progress_store.get("wf-1")
    assert record.step_2_verification_outcome is CompoundVerificationOutcome.VERIFIED
    assert record.overall_status is CompoundOverallStatus.COMPLETED


# --- Step 2 active/pending without a persisted outcome ----------------------


def test_step_2_pending_reruns_only_verification(tmp_path: Path) -> None:
    stack = _Stack(tmp_path / "step2_pending.db")
    plan = stack.trusted_plan("v7")
    request_id = stack.seed_claimed_row(plan, workflow_id="wf-1", value="v7")
    stack.progress_store.create(
        workflow_id="wf-1",
        template_id=ALLOWED_TEMPLATE_ID,
        request_id=request_id,
        approved_phase_value="v7",
    )
    stack.progress_store.record_pre_execution_observation(
        "wf-1", phase_value="old", last_updated=None
    )
    stack.progress_store.mark_step_1_completed("wf-1")
    stack.project_state_store.update("phase", "v7")

    outcome = stack.recover(request_id)
    assert outcome is CompoundClaimedOutcome.CONSUMED
    record = stack.progress_store.get("wf-1")
    assert record.step_2_status is CompoundStepStatus.COMPLETED
    assert record.step_2_verification_outcome is CompoundVerificationOutcome.VERIFIED
    assert record.step_3_status is CompoundStepStatus.COMPLETED


def test_step_2_verified_previously_persisted_never_reruns_verification_to_fail(
    tmp_path: Path,
) -> None:
    """Step 2 already COMPLETED with VERIFIED (from an earlier partial
    attempt) - recovery must never repeat the write and must continue
    straight to Step 3."""
    stack = _Stack(tmp_path / "step2_already_verified.db")
    plan = stack.trusted_plan("v8")
    request_id = stack.seed_claimed_row(plan, workflow_id="wf-1", value="v8")
    stack.progress_store.create(
        workflow_id="wf-1",
        template_id=ALLOWED_TEMPLATE_ID,
        request_id=request_id,
        approved_phase_value="v8",
    )
    stack.progress_store.record_pre_execution_observation(
        "wf-1", phase_value="old", last_updated=None
    )
    stack.progress_store.mark_step_1_completed("wf-1")
    stack.progress_store.start_step_2("wf-1")
    stack.progress_store.mark_step_2_completed(
        "wf-1", verification_outcome=CompoundVerificationOutcome.VERIFIED
    )
    stack.project_state_store.update("phase", "v8")

    outcome = stack.recover(request_id)
    assert outcome is CompoundClaimedOutcome.CONSUMED
    record = stack.progress_store.get("wf-1")
    assert record.step_3_status is CompoundStepStatus.COMPLETED


def test_step_2_failed_previously_never_runs_step_3(tmp_path: Path) -> None:
    stack = _Stack(tmp_path / "step2_failed.db")
    plan = stack.trusted_plan("v9")
    request_id = stack.seed_claimed_row(plan, workflow_id="wf-1", value="v9")
    stack.progress_store.create(
        workflow_id="wf-1",
        template_id=ALLOWED_TEMPLATE_ID,
        request_id=request_id,
        approved_phase_value="v9",
    )
    stack.progress_store.record_pre_execution_observation(
        "wf-1", phase_value="old", last_updated=None
    )
    stack.progress_store.mark_step_1_completed("wf-1")
    stack.progress_store.start_step_2("wf-1")
    stack.progress_store.mark_step_2_completed(
        "wf-1", verification_outcome=CompoundVerificationOutcome.FAILED
    )

    outcome = stack.recover(request_id)
    assert outcome is CompoundClaimedOutcome.CONSUMED
    record = stack.progress_store.get("wf-1")
    assert record.step_3_status is CompoundStepStatus.PENDING  # never started
    assert record.overall_status is CompoundOverallStatus.FAILED


# --- Step 3 active/pending without terminal checkpoint ----------------------


def test_step_3_pending_reruns_only_the_read(tmp_path: Path) -> None:
    stack = _Stack(tmp_path / "step3_pending.db")
    plan = stack.trusted_plan("v10")
    request_id = stack.seed_claimed_row(plan, workflow_id="wf-1", value="v10")
    stack.progress_store.create(
        workflow_id="wf-1",
        template_id=ALLOWED_TEMPLATE_ID,
        request_id=request_id,
        approved_phase_value="v10",
    )
    stack.progress_store.record_pre_execution_observation(
        "wf-1", phase_value="old", last_updated=None
    )
    stack.progress_store.mark_step_1_completed("wf-1")
    stack.progress_store.start_step_2("wf-1")
    stack.progress_store.mark_step_2_completed(
        "wf-1", verification_outcome=CompoundVerificationOutcome.VERIFIED
    )
    stack.project_state_store.update("phase", "v10")

    outcome = stack.recover(request_id)
    assert outcome is CompoundClaimedOutcome.CONSUMED
    record = stack.progress_store.get("wf-1")
    assert record.step_3_status is CompoundStepStatus.COMPLETED
    assert record.overall_status is CompoundOverallStatus.COMPLETED


# --- Step 3 completed --------------------------------------------------------


def test_step_3_completed_reruns_nothing(tmp_path: Path) -> None:
    stack = _Stack(tmp_path / "step3_completed.db")
    plan = stack.trusted_plan("v11")
    request_id = stack.seed_claimed_row(plan, workflow_id="wf-1", value="v11")
    stack.progress_store.create(
        workflow_id="wf-1",
        template_id=ALLOWED_TEMPLATE_ID,
        request_id=request_id,
        approved_phase_value="v11",
    )
    stack.progress_store.record_pre_execution_observation(
        "wf-1", phase_value="old", last_updated=None
    )
    stack.progress_store.mark_step_1_completed("wf-1")
    stack.progress_store.start_step_2("wf-1")
    stack.progress_store.mark_step_2_completed(
        "wf-1", verification_outcome=CompoundVerificationOutcome.VERIFIED
    )
    stack.progress_store.start_step_3("wf-1")
    stack.progress_store.mark_step_3_completed("wf-1")
    stack.project_state_store.update("phase", "v11")

    outcome = stack.recover(request_id)
    assert outcome is CompoundClaimedOutcome.CONSUMED
    assert (
        stack.pending_store.get_handoff_status(request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )


# --- No second claim, general recovery boundary -----------------------------


def test_no_second_claim_cas_is_ever_performed() -> None:
    """Structural proof: core/compound_workflow.py's own dependency
    Protocol for the pending store exposes no claim_for_resume() at
    all, so this module can never perform a second
    APPROVED_UNCONSUMED -> CLAIMED CAS."""
    import ast
    import inspect

    import core.compound_workflow as module

    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "claim_for_resume"
        ):
            pytest.fail("core/compound_workflow.py must never call claim_for_resume()")


def test_arbitrary_two_step_claimed_workflow_is_not_recognized(tmp_path: Path) -> None:
    """An ordinary, existing two-step YELLOW workflow's own inherited
    CLAIMED row must never be mistaken for this compound template."""
    stack = _Stack(tmp_path / "arbitrary_two_step.db")
    two_step_plan = Plan(
        user_request="update focus and verify",
        steps=(
            PlanStep(
                number=1,
                description="write",
                action="delete something",
                tier=SecurityTier.YELLOW,
                reason="needs approval",
                tool_name="project_state_update",
                tool_input={"field": "focus", "value": "some focus"},
            ),
            PlanStep(
                number=2,
                description="verify",
                action="read something",
                tier=SecurityTier.GREEN,
                reason="ok",
                tool_name="project_state_verify",
                tool_input={},
            ),
        ),
    )
    request_id = stack.seed_claimed_row(two_step_plan, workflow_id="wf-1", value="some focus")

    outcome = stack.recover(request_id)
    assert outcome is CompoundClaimedOutcome.NOT_RECOGNIZED


# --- The batch pass ----------------------------------------------------------


def test_reconcile_claimed_compound_workflows_processes_only_recognized_rows(
    tmp_path: Path,
) -> None:
    stack = _Stack(tmp_path / "batch_pass.db")

    # One fully recoverable compound row.
    plan_a = stack.trusted_plan("batch-value-a")
    request_a = stack.seed_claimed_row(plan_a, workflow_id="wf-a", value="batch-value-a")
    stack.progress_store.create(
        workflow_id="wf-a",
        template_id=ALLOWED_TEMPLATE_ID,
        request_id=request_a,
        approved_phase_value="batch-value-a",
    )
    stack.progress_store.record_pre_execution_observation(
        "wf-a", phase_value="old-a", last_updated=None
    )
    stack.project_state_store.update("phase", "batch-value-a")

    # One arbitrary, non-compound CLAIMED row - must be left untouched
    # for the generic fallback.
    two_step_plan = Plan(
        user_request="update focus and verify",
        steps=(
            PlanStep(
                number=1,
                description="write",
                action="delete something",
                tier=SecurityTier.YELLOW,
                reason="needs approval",
                tool_name="project_state_update",
                tool_input={"field": "focus", "value": "b"},
            ),
            PlanStep(
                number=2,
                description="verify",
                action="read something",
                tier=SecurityTier.GREEN,
                reason="ok",
                tool_name="project_state_verify",
                tool_input={},
            ),
        ),
    )
    request_b = stack.seed_claimed_row(two_step_plan, workflow_id="wf-b", value="b")

    summary = reconcile_claimed_compound_workflows(
        pending_store=stack.pending_store,
        paused_workflow_store=stack.paused_store,
        progress_store=stack.progress_store,
        workflow_engine=stack.workflow_engine,
        tool_registry=stack.registry,
        security_manager=stack.security,
        tool_executor=stack.executor,
        claimed_status=PendingApprovalHandoffStatus.CLAIMED,
    )

    assert summary == CompoundClaimedReconciliationSummary(
        consumed=1, interrupted=0, left_for_generic=1
    )
    assert (
        stack.pending_store.get_handoff_status(request_a)
        == PendingApprovalHandoffStatus.CONSUMED
    )
    assert (
        stack.pending_store.get_handoff_status(request_b)
        == PendingApprovalHandoffStatus.CLAIMED
    )  # untouched - left for the existing, unchanged generic pass
