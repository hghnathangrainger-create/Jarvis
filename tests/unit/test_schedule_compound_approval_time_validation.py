"""
test_schedule_compound_approval_time_validation.py

Unit tests for
core.schedule_compound_workflow.validate_schedule_compound_approval_before_transition()
(Phase 99, Batch 2, Foundation G -
docs/phase_99_second_compound_template_planning.md): the trusted,
server-side check a caller must run immediately before transitioning a
workflow-linked pending approval to APPROVED_UNCONSUMED, independent of
whether progress creation was ever attempted earlier. Mirrors
test_compound_approval_time_validation.py's own established pattern.

Dormant in Batch 2 - not called by ApprovalManager.approve() or any CLI
call site yet. These tests exercise it directly.
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402

from config.constants import SecurityTier  # noqa: E402
from core.schedule_compound_workflow import (  # noqa: E402
    ScheduleCompoundApprovalValidation,
    validate_schedule_compound_approval_before_transition,
)
from intelligence.capability_catalog import CAPABILITY_CATALOG  # noqa: E402
from intelligence.planning import (  # noqa: E402
    _build_schedule_enable_verify_show_workflow_plan,
)
from planner.plan_models import Plan, PlanStep  # noqa: E402
from scheduling.schedule_store import ScheduleStore  # noqa: E402
from security.security_manager import SecurityManager  # noqa: E402
from storage.database import create_session_factory, initialize_database  # noqa: E402
from tools.builtin.schedule_enable_tool import ScheduleEnableTool  # noqa: E402
from tools.builtin.schedule_show_enabled_state_tool import (  # noqa: E402
    ScheduleShowEnabledStateTool,
)
from tools.builtin.schedule_verify_enabled_state_tool import (  # noqa: E402
    ScheduleVerifyEnabledStateTool,
)
from tools.registry import ToolRegistry  # noqa: E402
from workflow.engine import WorkflowEngine  # noqa: E402
from workflow.paused_workflow_store import PausedWorkflowStore  # noqa: E402
from workflow.schedule_compound_workflow_progress_store import (  # noqa: E402
    ALLOWED_SCHEDULE_TEMPLATE_ID,
    ScheduleCompoundWorkflowProgressStore,
)


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


def _registry(session_factory) -> ToolRegistry:
    schedules = ScheduleStore(session_factory)
    registry = ToolRegistry()
    registry.register_tool(ScheduleEnableTool(schedules))
    registry.register_tool(ScheduleVerifyEnabledStateTool(schedules))
    registry.register_tool(ScheduleShowEnabledStateTool(schedules))
    return registry


def _trusted_plan(session_factory, schedule_id: int) -> Plan:
    plan = _build_schedule_enable_verify_show_workflow_plan(
        "enable schedule and then check its enabled state",
        approved_schedule_id=schedule_id,
        tool_registry=_registry(session_factory),
        security_manager=SecurityManager(),
        session_id=None,
        catalog=CAPABILITY_CATALOG,
    )
    assert isinstance(plan, Plan)
    return plan


class _Stack:
    def __init__(self) -> None:
        self.session_factory = _session_factory()
        self.paused_store = PausedWorkflowStore(self.session_factory)
        self.progress_store = ScheduleCompoundWorkflowProgressStore(
            self.session_factory
        )

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

    def trusted_plan(self, schedule_id: int = 1) -> Plan:
        return _trusted_plan(self.session_factory, schedule_id)


class TestNonCompoundApprovalsUnaffected:
    def test_no_paused_record_at_all_is_reported_not_applicable(self) -> None:
        stack = _Stack()
        result = validate_schedule_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="no-such-workflow",
        )
        assert result == ScheduleCompoundApprovalValidation(
            is_compound_workflow=False, valid=True
        )

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
                    tool_name="schedule_disable",
                    tool_input={"schedule_id": 1},
                ),
            ),
        )
        stack.save(non_compound_plan, workflow_id="wf-1", request_id="req-1")

        result = validate_schedule_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="wf-1",
        )
        assert result.is_compound_workflow is False
        assert result.valid is True

    def test_project_state_compound_plan_is_reported_not_applicable(self) -> None:
        """The existing, live Phase 98 ProjectState compound must never
        be treated as this template - this function's own recognizer
        rejects a plan shape it does not own."""
        stack = _Stack()
        non_matching_plan = Plan(
            user_request="anything",
            steps=(
                PlanStep(
                    number=1,
                    description="d",
                    action="delete something",
                    tier=SecurityTier.YELLOW,
                    reason="r",
                    tool_name="project_state_update",
                    tool_input={"field": "phase", "value": "x"},
                ),
            ),
        )
        stack.save(non_matching_plan, workflow_id="wf-1", request_id="req-1")

        result = validate_schedule_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="wf-1",
        )
        assert result.is_compound_workflow is False
        assert result.valid is True


class TestScheduleCompoundApprovalGating:
    def test_missing_progress_row_is_rejected(self) -> None:
        stack = _Stack()
        plan = stack.trusted_plan(1)
        stack.save(plan, workflow_id="wf-1", request_id="req-1")

        result = validate_schedule_compound_approval_before_transition(
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
        plan = stack.trusted_plan(1)
        stack.save(plan, workflow_id="wf-1", request_id="req-1")
        stack.progress_store.create(
            workflow_id="wf-1",
            template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
            request_id="req-1",
            schedule_id=1,
        )

        result = validate_schedule_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="wf-1",
        )
        assert result == ScheduleCompoundApprovalValidation(
            is_compound_workflow=True, valid=True
        )

    def test_mismatched_request_id_is_rejected(self) -> None:
        stack = _Stack()
        plan = stack.trusted_plan(1)
        stack.save(plan, workflow_id="wf-1", request_id="req-1")
        stack.progress_store.create(
            workflow_id="wf-1",
            template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
            request_id="a-different-request",
            schedule_id=1,
        )

        result = validate_schedule_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="wf-1",
        )
        assert result.is_compound_workflow is True
        assert result.valid is False

    def test_mismatched_workflow_id_is_rejected(self) -> None:
        stack = _Stack()
        plan = stack.trusted_plan(1)
        stack.save(plan, workflow_id="wf-1", request_id="req-1")
        stack.progress_store.create(
            workflow_id="a-different-workflow",
            template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
            request_id="req-1",
            schedule_id=1,
        )

        result = validate_schedule_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="wf-1",
        )
        assert result.is_compound_workflow is True
        assert result.valid is False

    def test_mismatched_schedule_id_is_rejected(self) -> None:
        stack = _Stack()
        plan = stack.trusted_plan(1)
        stack.save(plan, workflow_id="wf-1", request_id="req-1")
        stack.progress_store.create(
            workflow_id="wf-1",
            template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
            request_id="req-1",
            schedule_id=999,
        )

        result = validate_schedule_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="wf-1",
        )
        assert result.is_compound_workflow is True
        assert result.valid is False

    def test_does_not_depend_only_on_the_earlier_creation_attempt(self) -> None:
        stack = _Stack()
        plan = stack.trusted_plan(1)
        stack.save(plan, workflow_id="wf-1", request_id="req-1")
        record = stack.progress_store.create(
            workflow_id="wf-1",
            template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
            request_id="req-1",
            schedule_id=1,
        )
        assert record is not None

        with stack.progress_store._session_factory() as db:
            from storage.models import ScheduleCompoundWorkflowProgress

            db.query(ScheduleCompoundWorkflowProgress).filter(
                ScheduleCompoundWorkflowProgress.workflow_id == "wf-1"
            ).delete()
            db.commit()

        result = validate_schedule_compound_approval_before_transition(
            paused_workflow_store=stack.paused_store,
            progress_store=stack.progress_store,
            request_id="req-1",
            workflow_id="wf-1",
        )
        assert result.valid is False
