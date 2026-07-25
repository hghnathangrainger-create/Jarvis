"""
test_compound_approval_time_validation.py

Unit tests for core.compound_workflow.validate_compound_approval_before_transition()
(Phase 98, Batch 2, Foundation G -
docs/phase_98_live_compound_reentry_plan.md): the trusted, server-side
check a caller must run immediately before transitioning a workflow-
linked pending approval to APPROVED_UNCONSUMED, independent of whether
progress creation was ever attempted earlier.

Dormant in Batch 2 - not called by ApprovalManager.approve() or any CLI
call site yet (see test_phase98_batch2_dormant_isolation.py). These
tests exercise it directly.
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402

from config.constants import SecurityTier  # noqa: E402
from core.compound_workflow import (  # noqa: E402
    CompoundApprovalValidation,
    validate_compound_approval_before_transition,
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


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


def _registry() -> ToolRegistry:
    store = ProjectStateStore(_session_factory())
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
        session_factory = _session_factory()
        self.paused_store = PausedWorkflowStore(session_factory)
        self.progress_store = CompoundWorkflowProgressStore(session_factory)

    def save(self, plan: Plan, *, workflow_id: str, request_id: str) -> None:
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


class TestNonCompoundApprovalsUnaffected:
    def test_no_paused_record_at_all_is_reported_not_applicable(self) -> None:
        stack = _Stack()
        result = validate_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="no-such-workflow",
        )
        assert result == CompoundApprovalValidation(is_compound_workflow=False, valid=True)

    def test_non_compound_shaped_plan_is_reported_not_applicable(self) -> None:
        stack = _Stack()
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
        stack.save(non_compound_plan, workflow_id="wf-1", request_id="req-1")

        result = validate_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="wf-1",
        )
        assert result.is_compound_workflow is False
        assert result.valid is True


class TestCompoundApprovalGating:
    def test_missing_progress_row_is_rejected(self) -> None:
        stack = _Stack()
        plan = _trusted_plan("v")
        stack.save(plan, workflow_id="wf-1", request_id="req-1")

        result = validate_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="wf-1",
        )
        assert result.is_compound_workflow is True
        assert result.valid is False
        assert result.reason is not None

    def test_matching_progress_row_is_accepted(self) -> None:
        stack = _Stack()
        plan = _trusted_plan("v")
        stack.save(plan, workflow_id="wf-1", request_id="req-1")
        stack.progress_store.create(
            workflow_id="wf-1",
            template_id=ALLOWED_TEMPLATE_ID,
            request_id="req-1",
            approved_phase_value="v",
        )

        result = validate_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="wf-1",
        )
        assert result == CompoundApprovalValidation(is_compound_workflow=True, valid=True)

    def test_mismatched_request_id_is_rejected(self) -> None:
        stack = _Stack()
        plan = _trusted_plan("v")
        stack.save(plan, workflow_id="wf-1", request_id="req-1")
        stack.progress_store.create(
            workflow_id="wf-1",
            template_id=ALLOWED_TEMPLATE_ID,
            request_id="a-different-request",
            approved_phase_value="v",
        )

        result = validate_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="wf-1",
        )
        assert result.is_compound_workflow is True
        assert result.valid is False

    def test_mismatched_workflow_id_is_rejected(self) -> None:
        stack = _Stack()
        plan = _trusted_plan("v")
        stack.save(plan, workflow_id="wf-1", request_id="req-1")
        stack.progress_store.create(
            workflow_id="a-different-workflow",
            template_id=ALLOWED_TEMPLATE_ID,
            request_id="req-1",
            approved_phase_value="v",
        )

        result = validate_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="wf-1",
        )
        assert result.is_compound_workflow is True
        assert result.valid is False

    def test_mismatched_approved_value_is_rejected(self) -> None:
        stack = _Stack()
        plan = _trusted_plan("the-real-value")
        stack.save(plan, workflow_id="wf-1", request_id="req-1")
        stack.progress_store.create(
            workflow_id="wf-1",
            template_id=ALLOWED_TEMPLATE_ID,
            request_id="req-1",
            approved_phase_value="a-different-value",
        )

        result = validate_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="wf-1",
        )
        assert result.is_compound_workflow is True
        assert result.valid is False

    def test_does_not_depend_only_on_the_earlier_creation_attempt(self) -> None:
        """Re-fetches progress fresh at validation time - a row created
        then later corrupted/deleted between pause and this check is
        still caught, not merely trusted from an earlier attempt."""
        stack = _Stack()
        plan = _trusted_plan("v")
        stack.save(plan, workflow_id="wf-1", request_id="req-1")
        record = stack.progress_store.create(
            workflow_id="wf-1",
            template_id=ALLOWED_TEMPLATE_ID,
            request_id="req-1",
            approved_phase_value="v",
        )
        assert record is not None  # the earlier creation attempt succeeded

        # Simulate the row having since vanished (e.g. a separate,
        # narrow cleanup bug) - the check must not simply trust that
        # creation once succeeded.
        with stack.progress_store._session_factory() as db:
            from storage.models import CompoundWorkflowProgress

            db.query(CompoundWorkflowProgress).filter(
                CompoundWorkflowProgress.workflow_id == "wf-1"
            ).delete()
            db.commit()

        result = validate_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="wf-1",
        )
        assert result.valid is False
