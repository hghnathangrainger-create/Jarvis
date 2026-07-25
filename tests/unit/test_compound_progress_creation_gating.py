"""
test_compound_progress_creation_gating.py

Unit tests for core.compound_workflow's Foundation F: progress creation
immediately after a compound plan's first pause
(establish_compound_progress_or_isolate) and the dormant, hard-crash
repair pass over PENDING rows (repair_or_isolate_pending_compound_progress)
(Phase 98, Batch 2 - docs/phase_98_live_compound_reentry_plan.md).

Uses a real ApprovalManager (backed by a real PendingApprovalStore) as
the approval_invalidator, and a real PausedWorkflowStore/
CompoundWorkflowProgressStore - all bound to the same real, in-memory
SQLite database, so invalidate_pending()/delete() are exercised for
real, not mocked.
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402

from approval.approval_manager import ApprovalManager  # noqa: E402
from approval.approval_models import PendingApprovalHandoffStatus  # noqa: E402
from approval.pending_approval_store import PendingApprovalStore  # noqa: E402
from config.constants import SecurityTier  # noqa: E402
from core.compound_workflow import (  # noqa: E402
    CompoundProgressRepairSummary,
    establish_compound_progress_or_isolate,
    repair_or_isolate_pending_compound_progress,
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
from tools.registry import ToolRegistry  # noqa: E402
from workflow.compound_workflow_progress_store import (  # noqa: E402
    ALLOWED_TEMPLATE_ID,
    CompoundWorkflowProgressStore,
)
from workflow.engine import WorkflowEngine  # noqa: E402
from workflow.paused_workflow_store import PausedWorkflowStore  # noqa: E402


def _shared_session_factory():
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


def _registry() -> ToolRegistry:
    session_factory = _shared_session_factory()
    store = ProjectStateStore(session_factory)
    registry = ToolRegistry()
    registry.register_tool(ProjectStateShowTool(store))
    registry.register_tool(ProjectStateUpdateTool(store))
    registry.register_tool(ProjectStateVerifyTool(store))
    return registry


def _trusted_plan(value: str = "approved-value") -> Plan:
    plan = _build_phase_update_verify_show_workflow_plan(
        "update phase and then show project state",
        approved_phase_value=value,
        tool_registry=_registry(),
        security_manager=SecurityManager(),
        session_id=None,
        catalog=CAPABILITY_CATALOG,
    )
    assert isinstance(plan, Plan)
    return plan


class _Stack:
    def __init__(self) -> None:
        self.session_factory = _shared_session_factory()
        self.pending_store = PendingApprovalStore(self.session_factory)
        self.paused_store = PausedWorkflowStore(self.session_factory)
        self.progress_store = CompoundWorkflowProgressStore(self.session_factory)
        self.approvals = ApprovalManager(pending_store=self.pending_store)

    def create_pending_request(self, *, workflow_id: str = "wf-1") -> str:
        request = self.approvals.create_request(
            "update project state phase",
            "needs approval",
            SecurityTier.YELLOW,
            metadata={"workflow_id": workflow_id},
            tool_name="project_state_update",
            tool_input={"field": "phase", "value": "approved-value"},
        )
        return request.request_id

    def save_paused_plan(self, plan: Plan, *, workflow_id: str, request_id: str) -> None:
        self.paused_store.save(
            workflow_id=workflow_id,
            session_id=None,
            request_id=request_id,
            user_request=plan.user_request,
            plan_steps=[WorkflowEngine._plan_step_to_dict(s) for s in plan.steps],
            completed_outcomes=[],
            waiting_step_index=0,
            resolved_tool_input=dict(plan.steps[0].tool_input),
        )


class TestEstablishProgressSuccess:
    def test_creates_a_matching_progress_row(self) -> None:
        stack = _Stack()
        plan = _trusted_plan("phase-x")
        result = establish_compound_progress_or_isolate(
            plan=plan,
            workflow_id="wf-1",
            request_id="req-1",
            progress_store=stack.progress_store,
            approval_invalidator=stack.approvals,
            paused_workflow_store=stack.paused_store,
        )
        assert not isinstance(result, str)
        assert result.workflow_id == "wf-1"
        assert result.request_id == "req-1"
        assert result.template_id == ALLOWED_TEMPLATE_ID
        assert result.approved_phase_value == "phase-x"

    def test_does_not_touch_approval_or_paused_state_on_success(self) -> None:
        stack = _Stack()
        request_id = stack.create_pending_request(workflow_id="wf-1")
        plan = _trusted_plan("phase-x")
        stack.save_paused_plan(plan, workflow_id="wf-1", request_id=request_id)

        establish_compound_progress_or_isolate(
            plan=plan,
            workflow_id="wf-1",
            request_id=request_id,
            progress_store=stack.progress_store,
            approval_invalidator=stack.approvals,
            paused_workflow_store=stack.paused_store,
        )

        assert stack.pending_store.get_handoff_status(request_id) == (
            PendingApprovalHandoffStatus.PENDING
        )
        assert stack.paused_store.get("wf-1") is not None


class TestEstablishProgressCreationFailure:
    def test_duplicate_workflow_id_isolates_the_pending_approval(self) -> None:
        stack = _Stack()
        plan = _trusted_plan("phase-x")
        request_id = stack.create_pending_request(workflow_id="wf-1")
        stack.save_paused_plan(plan, workflow_id="wf-1", request_id=request_id)

        # Pre-create a row for this workflow_id so the real creation
        # attempt below genuinely raises (a duplicate, unique-constrained
        # workflow_id) - exercising a real database error, not a mock.
        stack.progress_store.create(
            workflow_id="wf-1",
            template_id=ALLOWED_TEMPLATE_ID,
            request_id="a-different-request",
            approved_phase_value="a-different-value",
        )

        result = establish_compound_progress_or_isolate(
            plan=plan,
            workflow_id="wf-1",
            request_id=request_id,
            progress_store=stack.progress_store,
            approval_invalidator=stack.approvals,
            paused_workflow_store=stack.paused_store,
        )

        assert isinstance(result, str)
        # Terminally isolated using existing bounded APIs: no longer
        # pending, and the paused plan is gone.
        assert stack.pending_store.get_handoff_status(request_id) not in (
            PendingApprovalHandoffStatus.PENDING,
        )
        assert stack.paused_store.get("wf-1") is None

    def test_plan_not_matching_shape_returns_a_reason_without_isolating(self) -> None:
        """This function is only ever meant to be called after the
        caller has already confirmed the plan is compound-shaped - a
        defensive, non-isolating short-circuit for the case it is not,
        so this function never mistakenly isolates an unrelated,
        non-compound approval."""
        stack = _Stack()
        request_id = stack.create_pending_request(workflow_id="wf-1")
        non_compound_plan = Plan(
            user_request="anything",
            steps=(
                PlanStep(
                    number=1,
                    description="d",
                    action="a",
                    tier=SecurityTier.GREEN,
                    reason="r",
                    tool_name="health_check",
                    tool_input={},
                ),
            ),
        )
        stack.save_paused_plan(non_compound_plan, workflow_id="wf-1", request_id=request_id)

        result = establish_compound_progress_or_isolate(
            plan=non_compound_plan,
            workflow_id="wf-1",
            request_id=request_id,
            progress_store=stack.progress_store,
            approval_invalidator=stack.approvals,
            paused_workflow_store=stack.paused_store,
        )

        assert isinstance(result, str)
        assert stack.pending_store.get_handoff_status(request_id) == (
            PendingApprovalHandoffStatus.PENDING
        )
        assert stack.paused_store.get("wf-1") is not None


class TestRepairOrIsolatePendingCompoundProgress:
    def test_untouched_when_not_workflow_linked(self) -> None:
        stack = _Stack()
        stack.approvals.create_request(
            "some plain action", "needs approval", SecurityTier.YELLOW
        )
        summary = repair_or_isolate_pending_compound_progress(
            pending_store=stack.pending_store,
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            approval_invalidator=stack.approvals,
            pending_status=PendingApprovalHandoffStatus.PENDING,
        )
        assert summary == CompoundProgressRepairSummary(repaired=0, isolated=0)

    def test_untouched_when_not_compound_shaped(self) -> None:
        stack = _Stack()
        request_id = stack.create_pending_request(workflow_id="wf-1")
        non_compound_plan = Plan(
            user_request="anything",
            steps=(
                PlanStep(
                    number=1,
                    description="d",
                    action="delete something",
                    tier=SecurityTier.YELLOW,
                    reason="r",
                    tool_name="project_state_update",
                    tool_input={"field": "focus", "value": "x"},
                ),
            ),
        )
        stack.save_paused_plan(non_compound_plan, workflow_id="wf-1", request_id=request_id)

        summary = repair_or_isolate_pending_compound_progress(
            pending_store=stack.pending_store,
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            approval_invalidator=stack.approvals,
            pending_status=PendingApprovalHandoffStatus.PENDING,
        )
        assert summary == CompoundProgressRepairSummary(repaired=0, isolated=0)
        assert stack.paused_store.get("wf-1") is not None

    def test_repairs_missing_progress_idempotently(self) -> None:
        stack = _Stack()
        plan = _trusted_plan("recoverable-value")
        request_id = stack.create_pending_request(workflow_id="wf-1")
        stack.save_paused_plan(plan, workflow_id="wf-1", request_id=request_id)

        assert stack.progress_store.get("wf-1") is None

        summary = repair_or_isolate_pending_compound_progress(
            pending_store=stack.pending_store,
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            approval_invalidator=stack.approvals,
            pending_status=PendingApprovalHandoffStatus.PENDING,
        )

        assert summary == CompoundProgressRepairSummary(repaired=1, isolated=0)
        record = stack.progress_store.get("wf-1")
        assert record is not None
        assert record.approved_phase_value == "recoverable-value"
        assert record.request_id == request_id
        # The approval remains untouched - still actionable now that
        # its progress foundation exists.
        assert stack.pending_store.get_handoff_status(request_id) == (
            PendingApprovalHandoffStatus.PENDING
        )

    def test_repair_is_idempotent_on_a_second_run(self) -> None:
        stack = _Stack()
        plan = _trusted_plan("recoverable-value")
        request_id = stack.create_pending_request(workflow_id="wf-1")
        stack.save_paused_plan(plan, workflow_id="wf-1", request_id=request_id)

        repair_or_isolate_pending_compound_progress(
            pending_store=stack.pending_store,
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            approval_invalidator=stack.approvals,
            pending_status=PendingApprovalHandoffStatus.PENDING,
        )
        second_summary = repair_or_isolate_pending_compound_progress(
            pending_store=stack.pending_store,
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            approval_invalidator=stack.approvals,
            pending_status=PendingApprovalHandoffStatus.PENDING,
        )
        assert second_summary == CompoundProgressRepairSummary(repaired=0, isolated=0)

    def test_ambiguous_mismatch_is_isolated_not_repaired(self) -> None:
        """An existing progress row whose identity does not match the
        paused plan is too ambiguous to overwrite - isolate instead."""
        stack = _Stack()
        plan = _trusted_plan("value-a")
        request_id = stack.create_pending_request(workflow_id="wf-1")
        stack.save_paused_plan(plan, workflow_id="wf-1", request_id=request_id)
        stack.progress_store.create(
            workflow_id="wf-1",
            template_id=ALLOWED_TEMPLATE_ID,
            request_id="a-stale-unrelated-request",
            approved_phase_value="a-stale-unrelated-value",
        )

        summary = repair_or_isolate_pending_compound_progress(
            pending_store=stack.pending_store,
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            approval_invalidator=stack.approvals,
            pending_status=PendingApprovalHandoffStatus.PENDING,
        )

        assert summary == CompoundProgressRepairSummary(repaired=0, isolated=1)
        assert stack.paused_store.get("wf-1") is None
        assert stack.pending_store.get_handoff_status(request_id) not in (
            PendingApprovalHandoffStatus.PENDING,
        )

    def test_already_matching_progress_is_left_completely_untouched(self) -> None:
        stack = _Stack()
        plan = _trusted_plan("value-a")
        request_id = stack.create_pending_request(workflow_id="wf-1")
        stack.save_paused_plan(plan, workflow_id="wf-1", request_id=request_id)
        stack.progress_store.create(
            workflow_id="wf-1",
            template_id=ALLOWED_TEMPLATE_ID,
            request_id=request_id,
            approved_phase_value="value-a",
        )

        summary = repair_or_isolate_pending_compound_progress(
            pending_store=stack.pending_store,
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            approval_invalidator=stack.approvals,
            pending_status=PendingApprovalHandoffStatus.PENDING,
        )
        assert summary == CompoundProgressRepairSummary(repaired=0, isolated=0)
