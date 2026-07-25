"""
test_compound_lifecycle_dormant_end_to_end.py

Real, on-disk-database end-to-end tests for the complete dormant Phase
98 compound lifecycle (Batch 2 -
docs/phase_98_live_compound_reentry_plan.md): trusted plan
construction -> WorkflowEngine.run() pause -> progress establishment
(Foundation F) -> approval -> WorkflowEngine.resume() with the real
CompoundStepObserver attached (Foundation E) -> durable per-step
checkpoints written at the exact moments they become true -> the
dormant result translator (Foundation I).

Not reachable from any live request path - this test wires the pieces
together manually, exactly as a future, separately-approved Batch 3
would, to prove the complete lifecycle is correct end-to-end while
still fully dormant.
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_manager import ApprovalManager  # noqa: E402
from approval.pending_approval_store import PendingApprovalStore  # noqa: E402
from core.compound_workflow import (  # noqa: E402
    CompoundResultKind,
    establish_compound_progress_or_isolate,
    matches_compound_plan_shape,
    translate_compound_workflow_result,
)
from intelligence.capability_catalog import CAPABILITY_CATALOG  # noqa: E402
from intelligence.planning import (  # noqa: E402
    _build_phase_update_verify_show_workflow_plan,
)
from planner.plan_models import Plan  # noqa: E402
from project_state.project_state_store import ProjectStateStore  # noqa: E402
from security.security_manager import SecurityManager  # noqa: E402
from storage.database import create_session_factory, initialize_database  # noqa: E402
from tools.builtin.project_state_show_tool import ProjectStateShowTool  # noqa: E402
from tools.builtin.project_state_update_tool import ProjectStateUpdateTool  # noqa: E402
from tools.builtin.project_state_verify_tool import ProjectStateVerifyTool  # noqa: E402
from tools.executor import ToolExecutor  # noqa: E402
from tools.registry import ToolRegistry  # noqa: E402
from workflow.compound_progress_observer import CompoundStepObserver  # noqa: E402
from workflow.compound_workflow_progress_store import (  # noqa: E402
    CompoundOverallStatus,
    CompoundStepStatus,
    CompoundVerificationOutcome,
    CompoundWorkflowProgressStore,
)
from workflow.engine import WorkflowEngine  # noqa: E402
from workflow.paused_workflow_store import PausedWorkflowStore  # noqa: E402


class _Stack:
    def __init__(self, db_path: Path) -> None:
        from sqlalchemy import create_engine

        engine = create_engine(f"sqlite:///{db_path}")
        initialize_database(engine)
        self.session_factory = create_session_factory(engine)

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
        self.approvals = ApprovalManager(pending_store=self.pending_store)
        self.paused_store = PausedWorkflowStore(self.session_factory)
        self.progress_store = CompoundWorkflowProgressStore(self.session_factory)
        self.workflow_engine = WorkflowEngine(
            executor=self.executor, approvals=self.approvals, paused_store=self.paused_store
        )

    def build_plan(self, value: str) -> Plan:
        plan = _build_phase_update_verify_show_workflow_plan(
            f"update phase to {value} and then show project state",
            approved_phase_value=value,
            tool_registry=self.registry,
            security_manager=self.security,
            session_id=None,
            catalog=CAPABILITY_CATALOG,
        )
        assert isinstance(plan, Plan)
        return plan


def test_full_success_writes_every_checkpoint_in_order_and_translates_success(
    tmp_path: Path,
) -> None:
    stack = _Stack(tmp_path / "full_success.db")
    plan = stack.build_plan("Phase 98 Batch 2 dormant proof")
    assert matches_compound_plan_shape(plan)

    pause_result = stack.workflow_engine.run(plan)
    request_id = pause_result.pending_approval_request.request_id
    workflow_id = pause_result.workflow_id

    established = establish_compound_progress_or_isolate(
        plan=plan,
        workflow_id=workflow_id,
        request_id=request_id,
        progress_store=stack.progress_store,
        approval_invalidator=stack.approvals,
        paused_workflow_store=stack.paused_store,
    )
    assert not isinstance(established, str)
    assert established.step_1_status is CompoundStepStatus.PENDING  # not yet started

    decision = stack.approvals.approve(request_id, decided_by="nathan")
    observer = CompoundStepObserver(
        plan=plan,
        progress_store=stack.progress_store,
        executor=stack.executor,
        session_id=None,
    )
    result = stack.workflow_engine.resume(workflow_id, decision, step_observer=observer)

    from config.constants import StepStatus

    assert result.overall_status is StepStatus.COMPLETED

    final_progress = stack.progress_store.get(workflow_id)
    assert final_progress.step_1_status is CompoundStepStatus.COMPLETED
    assert final_progress.step_2_status is CompoundStepStatus.COMPLETED
    assert final_progress.step_2_verification_outcome is CompoundVerificationOutcome.VERIFIED
    assert final_progress.step_3_status is CompoundStepStatus.COMPLETED
    assert final_progress.overall_status is CompoundOverallStatus.COMPLETED
    # No ProjectState row existed before this write, so the real,
    # honest pre-execution observation is an empty string (never None -
    # ProjectStateVerifyTool always reports a usable, if empty, value).
    assert final_progress.pre_execution_phase_value == ""

    assert stack.project_state_store.get().phase == "Phase 98 Batch 2 dormant proof"

    response, kind = translate_compound_workflow_result(result)
    assert kind is CompoundResultKind.FULL_SUCCESS
    assert response.success is True
    assert "Phase 98 Batch 2 dormant proof" in response.message


def test_checkpoint_failure_stops_before_the_write_and_leaves_claimed(
    tmp_path: Path,
) -> None:
    """Simulates the exact fail-closed contract: if the pre-execution
    checkpoint cannot be durably recorded (here, because no progress
    row exists at all for this workflow_id - the observer's own
    record_pre_execution_observation() call will raise), the write
    tool must never be invoked, and the handoff must remain CLAIMED
    for startup reconciliation - never silently repaired in-process."""
    stack = _Stack(tmp_path / "checkpoint_failure.db")
    plan = stack.build_plan("should-never-be-written")

    pause_result = stack.workflow_engine.run(plan)
    request_id = pause_result.pending_approval_request.request_id
    workflow_id = pause_result.workflow_id
    # Deliberately skip establish_compound_progress_or_isolate() - no
    # CompoundWorkflowProgress row exists for this workflow_id.

    decision = stack.approvals.approve(request_id, decided_by="nathan")
    assert stack.pending_store.claim_for_resume(request_id) is True

    observer = CompoundStepObserver(
        plan=plan,
        progress_store=stack.progress_store,
        executor=stack.executor,
        session_id=None,
    )
    result = stack.workflow_engine.resume(workflow_id, decision, step_observer=observer)

    from config.constants import StepStatus

    assert result.overall_status is StepStatus.FAILED
    assert stack.project_state_store.get() is None  # the write never ran
    assert "checkpoint" in (result.step_outcomes[-1].tool_result.error or "").casefold()

    # The claim is left exactly as it is - CLAIMED - for the exclusive
    # startup-recovery/compound-reconciliation pass to resolve; this
    # in-process failure never repairs or repeats anything itself.
    from approval.approval_models import PendingApprovalHandoffStatus

    assert (
        stack.pending_store.get_handoff_status(request_id)
        == PendingApprovalHandoffStatus.CLAIMED
    )


def test_verification_mismatch_stops_before_show_and_translates_honestly(
    tmp_path: Path,
) -> None:
    """A real write+verify+show tool sequence, running single-threaded
    within one resume() call, cannot itself produce a genuine
    post-write mismatch (the write is always the last word before the
    verifier reads it). To honestly exercise the FAILED verification
    gate end-to-end, the registered verify tool is substituted with one
    that reports a different, real value than what was approved - a
    genuine mismatch, still detected via the identical real gate/
    observer/translator path every other assertion in this file uses
    unmodified."""
    stack = _Stack(tmp_path / "verification_mismatch.db")
    plan = stack.build_plan("expected-value")

    pause_result = stack.workflow_engine.run(plan)
    request_id = pause_result.pending_approval_request.request_id
    workflow_id = pause_result.workflow_id
    establish_compound_progress_or_isolate(
        plan=plan,
        workflow_id=workflow_id,
        request_id=request_id,
        progress_store=stack.progress_store,
        approval_invalidator=stack.approvals,
        paused_workflow_store=stack.paused_store,
    )
    decision = stack.approvals.approve(request_id, decided_by="nathan")

    # Swap in a verifier that honestly reports a different real value
    # than the one just approved and written.
    from tools.base_tool import BaseTool, ToolRequest, ToolResult

    class _MismatchedVerifyTool(BaseTool):
        @property
        def name(self) -> str:
            return "project_state_verify"

        @property
        def description(self) -> str:
            return "A substitute verifier reporting a genuine mismatch."

        def action_for(self, request: ToolRequest) -> str:
            return "show jarvis project state"

        def run(self, request: ToolRequest) -> ToolResult:
            return ToolResult(
                tool_name=self.name,
                success=True,
                output="mismatched",
                metadata={"phase": "a-genuinely-different-value"},
            )

    # Swap the already-registered real verifier for the substitute -
    # ToolRegistry.register_tool() itself refuses a duplicate name, so
    # the replacement is made directly, exactly as if a fresh
    # ToolRegistry had been built with the substitute from the start.
    stack.registry._tools["project_state_verify"] = _MismatchedVerifyTool()

    observer = CompoundStepObserver(
        plan=plan,
        progress_store=stack.progress_store,
        executor=stack.executor,
        session_id=None,
    )
    result = stack.workflow_engine.resume(workflow_id, decision, step_observer=observer)

    from config.constants import StepStatus

    assert result.overall_status is StepStatus.FAILED  # the gate stopped Step 3
    final_progress = stack.progress_store.get(workflow_id)
    assert final_progress.step_1_status is CompoundStepStatus.COMPLETED
    assert final_progress.step_2_verification_outcome is CompoundVerificationOutcome.FAILED
    assert final_progress.step_3_status is CompoundStepStatus.PENDING  # show never ran
    assert final_progress.overall_status is CompoundOverallStatus.FAILED

    response, kind = translate_compound_workflow_result(result)
    assert kind is CompoundResultKind.VERIFICATION_MISMATCH
    assert response.success is False
    assert "not confirmed" in response.message
