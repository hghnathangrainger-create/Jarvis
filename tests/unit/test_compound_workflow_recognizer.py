"""
test_compound_workflow_recognizer.py

Unit tests for core.compound_workflow's 14-point trusted compound
recognizer (Phase 98, Batch 2, Foundation C -
docs/phase_98_live_compound_reentry_plan.md): matches_compound_plan_shape()
(points 1-12), compound_progress_identity_matches() (points 13-14), and
is_recognized_compound_workflow() (all fourteen together).

A three-step plan alone is never sufficient - each test mutates exactly
one point away from the trusted fingerprint and confirms it is
rejected.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from config.constants import SecurityTier  # noqa: E402
from core.compound_workflow import (  # noqa: E402
    compound_progress_identity_matches,
    is_recognized_compound_workflow,
    matches_compound_plan_shape,
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


def _registry() -> ToolRegistry:
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    store = ProjectStateStore(session_factory)
    registry = ToolRegistry()
    registry.register_tool(ProjectStateShowTool(store))
    registry.register_tool(ProjectStateUpdateTool(store))
    registry.register_tool(ProjectStateVerifyTool(store))
    return registry


def _trusted_plan(value: str = "trusted-value") -> Plan:
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


def _progress_store() -> CompoundWorkflowProgressStore:
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return CompoundWorkflowProgressStore(create_session_factory(engine))


class TestTrustedPlanIsRecognized:
    def test_the_exact_trusted_plan_matches(self) -> None:
        assert matches_compound_plan_shape(_trusted_plan()) is True

    def test_full_identity_check_passes_with_matching_progress(self) -> None:
        plan = _trusted_plan("phase-x")
        store = _progress_store()
        record = store.create(
            workflow_id="wf-1",
            template_id=ALLOWED_TEMPLATE_ID,
            request_id="req-1",
            approved_phase_value="phase-x",
        )
        assert (
            is_recognized_compound_workflow(
                plan, record, request_id="req-1", workflow_id="wf-1"
            )
            is True
        )
        assert (
            compound_progress_identity_matches(
                plan, record, request_id="req-1", workflow_id="wf-1"
            )
            is True
        )


class TestArbitraryThreeStepPlanRejected:
    def test_three_unrelated_steps_do_not_match(self) -> None:
        steps = tuple(
            PlanStep(
                number=i + 1,
                description="d",
                action="a",
                tier=SecurityTier.GREEN,
                reason="r",
                tool_name="health_check",
                tool_input={},
            )
            for i in range(3)
        )
        plan = Plan(user_request="anything", steps=steps)
        assert matches_compound_plan_shape(plan) is False

    def test_wrong_step_count_rejected(self) -> None:
        plan = _trusted_plan()
        two_steps = Plan(user_request=plan.user_request, steps=plan.steps[:2])
        assert matches_compound_plan_shape(two_steps) is False

    def test_reversed_step_order_rejected(self) -> None:
        plan = _trusted_plan()
        reversed_plan = Plan(
            user_request=plan.user_request,
            steps=(
                replace(plan.steps[2], number=1),
                replace(plan.steps[1], number=2),
                replace(plan.steps[0], number=3),
            ),
        )
        assert matches_compound_plan_shape(reversed_plan) is False


class TestEachFingerprintPointRejectsAMismatch:
    def test_wrong_step_1_tool_identity_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[0], tool_name="schedule_enable")
        new_plan = Plan(user_request=plan.user_request, steps=(mutated,) + plan.steps[1:])
        assert matches_compound_plan_shape(new_plan) is False

    def test_wrong_fixed_field_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[0], tool_input={"field": "focus", "value": "x"})
        new_plan = Plan(user_request=plan.user_request, steps=(mutated,) + plan.steps[1:])
        assert matches_compound_plan_shape(new_plan) is False

    def test_empty_approved_value_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[0], tool_input={"field": "phase", "value": "   "})
        new_plan = Plan(user_request=plan.user_request, steps=(mutated,) + plan.steps[1:])
        assert matches_compound_plan_shape(new_plan) is False

    def test_oversized_approved_value_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(
            plan.steps[0], tool_input={"field": "phase", "value": "x" * 501}
        )
        new_plan = Plan(user_request=plan.user_request, steps=(mutated,) + plan.steps[1:])
        assert matches_compound_plan_shape(new_plan) is False

    def test_wrong_step_1_tier_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[0], tier=SecurityTier.GREEN)
        new_plan = Plan(user_request=plan.user_request, steps=(mutated,) + plan.steps[1:])
        assert matches_compound_plan_shape(new_plan) is False

    def test_wrong_step_2_tool_identity_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[1], tool_name="schedule_verify_enabled_state")
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], mutated, plan.steps[2]),
        )
        assert matches_compound_plan_shape(new_plan) is False

    def test_step_2_with_arguments_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[1], tool_input={"unexpected": "value"})
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], mutated, plan.steps[2]),
        )
        assert matches_compound_plan_shape(new_plan) is False

    def test_wrong_step_3_tool_identity_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[2], tool_name="schedule_list")
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], plan.steps[1], mutated),
        )
        assert matches_compound_plan_shape(new_plan) is False

    def test_step_3_without_verified_predecessor_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[2], requires_verified_predecessor=False)
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], plan.steps[1], mutated),
        )
        assert matches_compound_plan_shape(new_plan) is False

    def test_step_3_wrong_verification_field_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[2], verification_field_name="focus")
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], plan.steps[1], mutated),
        )
        assert matches_compound_plan_shape(new_plan) is False

    def test_step_3_expected_value_mismatch_with_step_1_rejected(self) -> None:
        plan = _trusted_plan("actual-approved-value")
        mutated = replace(plan.steps[2], verification_expected_value="a-different-value")
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], plan.steps[1], mutated),
        )
        assert matches_compound_plan_shape(new_plan) is False

    def test_wrong_step_3_tier_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[2], tier=SecurityTier.YELLOW)
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], plan.steps[1], mutated),
        )
        assert matches_compound_plan_shape(new_plan) is False

    def test_step_3_with_model_controlled_input_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[2], tool_input={"extra": "value"})
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], plan.steps[1], mutated),
        )
        assert matches_compound_plan_shape(new_plan) is False


class TestIdentityCrossCheckPoints1314:
    def test_wrong_template_id_rejected(self) -> None:
        plan = _trusted_plan("v")
        store = _progress_store()
        # A row with a genuinely different template_id cannot exist in
        # this one-template store today, so the mismatch is
        # constructed directly for the identity-check unit alone.
        from dataclasses import replace as dc_replace

        record = store.create(
            workflow_id="wf-2",
            template_id=ALLOWED_TEMPLATE_ID,
            request_id="req-2",
            approved_phase_value="v",
        )
        wrong_template = dc_replace(record, template_id="a_different_template")
        assert (
            compound_progress_identity_matches(
                plan, wrong_template, request_id="req-2", workflow_id="wf-2"
            )
            is False
        )

    def test_wrong_request_id_rejected(self) -> None:
        plan = _trusted_plan("v")
        store = _progress_store()
        record = store.create(
            workflow_id="wf-3",
            template_id=ALLOWED_TEMPLATE_ID,
            request_id="req-3",
            approved_phase_value="v",
        )
        assert (
            compound_progress_identity_matches(
                plan, record, request_id="a-different-request", workflow_id="wf-3"
            )
            is False
        )

    def test_wrong_workflow_id_rejected(self) -> None:
        plan = _trusted_plan("v")
        store = _progress_store()
        record = store.create(
            workflow_id="wf-4",
            template_id=ALLOWED_TEMPLATE_ID,
            request_id="req-4",
            approved_phase_value="v",
        )
        assert (
            compound_progress_identity_matches(
                plan, record, request_id="req-4", workflow_id="a-different-workflow"
            )
            is False
        )

    def test_wrong_approved_value_rejected(self) -> None:
        plan = _trusted_plan("approved-value")
        store = _progress_store()
        record = store.create(
            workflow_id="wf-5",
            template_id=ALLOWED_TEMPLATE_ID,
            request_id="req-5",
            approved_phase_value="a-different-value",
        )
        assert (
            compound_progress_identity_matches(
                plan, record, request_id="req-5", workflow_id="wf-5"
            )
            is False
        )

    def test_missing_progress_row_rejected(self) -> None:
        plan = _trusted_plan("v")
        assert (
            is_recognized_compound_workflow(
                plan, None, request_id="req-6", workflow_id="wf-6"
            )
            is False
        )
