"""
test_schedule_compound_workflow_recognizer.py

Unit tests for core.schedule_compound_workflow's exact trusted
recognizer (Phase 99, Batch 1 -
docs/phase_99_second_compound_template_planning.md):
matches_schedule_compound_plan_shape(), mirroring
test_compound_workflow_recognizer.py's own established pattern for the
second, dormant trusted three-step recognizer.

A three-step plan naming schedule capabilities alone is never
sufficient - each test mutates exactly one point away from the trusted
fingerprint and confirms it is rejected.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from config.constants import SecurityTier  # noqa: E402
from core.schedule_compound_workflow import (  # noqa: E402
    matches_schedule_compound_plan_shape,
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


def _registry_and_id() -> tuple[ToolRegistry, int]:
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    store = ScheduleStore(session_factory)
    record = store.create(query="q", time_of_day="09:00")
    store.disable(record.id)
    registry = ToolRegistry()
    registry.register_tool(ScheduleEnableTool(store))
    registry.register_tool(ScheduleVerifyEnabledStateTool(store))
    registry.register_tool(ScheduleShowEnabledStateTool(store))
    return registry, record.id


def _trusted_plan(schedule_id: int | None = None) -> Plan:
    registry, real_id = _registry_and_id()
    target_id = schedule_id if schedule_id is not None else real_id
    plan = _build_schedule_enable_verify_show_workflow_plan(
        f"enable schedule {target_id} and then check the enabled state "
        f"of schedule {target_id}",
        approved_schedule_id=target_id,
        tool_registry=registry,
        security_manager=SecurityManager(),
        session_id=None,
        catalog=CAPABILITY_CATALOG,
    )
    assert isinstance(plan, Plan)
    return plan


class TestTrustedPlanIsRecognized:
    def test_the_exact_trusted_plan_matches(self) -> None:
        assert matches_schedule_compound_plan_shape(_trusted_plan()) is True


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
        assert matches_schedule_compound_plan_shape(plan) is False

    def test_wrong_step_count_rejected(self) -> None:
        plan = _trusted_plan()
        two_steps = Plan(user_request=plan.user_request, steps=plan.steps[:2])
        assert matches_schedule_compound_plan_shape(two_steps) is False

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
        assert matches_schedule_compound_plan_shape(reversed_plan) is False


class TestEachFingerprintPointRejectsAMismatch:
    def test_schedule_disable_substituted_for_step_1_rejected(self) -> None:
        """The single most important boundary: SCHEDULE_DISABLE must
        never be silently accepted in SCHEDULE_ENABLE's place."""
        plan = _trusted_plan()
        mutated = replace(plan.steps[0], tool_name="schedule_disable")
        new_plan = Plan(
            user_request=plan.user_request, steps=(mutated,) + plan.steps[1:]
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_step_1_missing_schedule_id_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[0], tool_input={})
        new_plan = Plan(
            user_request=plan.user_request, steps=(mutated,) + plan.steps[1:]
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_step_1_extra_argument_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(
            plan.steps[0],
            tool_input={**plan.steps[0].tool_input, "extra": "value"},
        )
        new_plan = Plan(
            user_request=plan.user_request, steps=(mutated,) + plan.steps[1:]
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_step_1_non_int_schedule_id_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[0], tool_input={"schedule_id": "5"})
        new_plan = Plan(
            user_request=plan.user_request, steps=(mutated,) + plan.steps[1:]
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_step_1_bool_schedule_id_rejected(self) -> None:
        """isinstance(True, int) is True in Python - the recognizer
        must explicitly reject bool, exactly mirroring every schedule
        tool's own established _parse_id guard."""
        plan = _trusted_plan()
        mutated = replace(plan.steps[0], tool_input={"schedule_id": True})
        new_plan = Plan(
            user_request=plan.user_request, steps=(mutated,) + plan.steps[1:]
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_wrong_step_1_tier_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[0], tier=SecurityTier.GREEN)
        new_plan = Plan(
            user_request=plan.user_request, steps=(mutated,) + plan.steps[1:]
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_wrong_step_2_tool_identity_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[1], tool_name="schedule_enable")
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], mutated, plan.steps[2]),
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_step_2_missing_schedule_id_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[1], tool_input={})
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], mutated, plan.steps[2]),
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_step_2_schedule_id_disagrees_with_step_1_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[1], tool_input={"schedule_id": 999999})
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], mutated, plan.steps[2]),
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_schedule_list_substituted_for_step_3_rejected(self) -> None:
        """The single most important read-step boundary: SCHEDULE_LIST
        must never be silently accepted in
        SCHEDULE_SHOW_ENABLED_STATE's place."""
        plan = _trusted_plan()
        mutated = replace(plan.steps[2], tool_name="schedule_list", tool_input={})
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], plan.steps[1], mutated),
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_step_3_schedule_id_disagrees_with_step_1_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[2], tool_input={"schedule_id": 999999})
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], plan.steps[1], mutated),
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_step_3_without_verified_predecessor_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[2], requires_verified_predecessor=False)
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], plan.steps[1], mutated),
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_step_3_wrong_verification_field_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[2], verification_field_name="enabled")
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], plan.steps[1], mutated),
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_step_3_expected_value_false_rejected(self) -> None:
        """Only "true" is ever accepted - no SCHEDULE_DISABLE-paired
        template exists yet, so "false" must never be silently
        accepted as if it were."""
        plan = _trusted_plan()
        mutated = replace(plan.steps[2], verification_expected_value="false")
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], plan.steps[1], mutated),
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_wrong_step_3_tier_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(plan.steps[2], tier=SecurityTier.YELLOW)
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], plan.steps[1], mutated),
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False

    def test_step_3_extra_argument_rejected(self) -> None:
        plan = _trusted_plan()
        mutated = replace(
            plan.steps[2],
            tool_input={**plan.steps[2].tool_input, "extra": "value"},
        )
        new_plan = Plan(
            user_request=plan.user_request,
            steps=(plan.steps[0], plan.steps[1], mutated),
        )
        assert matches_schedule_compound_plan_shape(new_plan) is False


class TestDoesNotCollideWithProjectStateRecognizer:
    def test_the_project_state_trusted_plan_never_matches_this_recognizer(
        self,
    ) -> None:
        from intelligence.planning import (
            _build_phase_update_verify_show_workflow_plan,
        )
        from project_state.project_state_store import ProjectStateStore
        from tools.builtin.project_state_show_tool import ProjectStateShowTool
        from tools.builtin.project_state_update_tool import ProjectStateUpdateTool
        from tools.builtin.project_state_verify_tool import ProjectStateVerifyTool

        from sqlalchemy import create_engine

        engine = create_engine("sqlite:///:memory:")
        initialize_database(engine)
        session_factory = create_session_factory(engine)
        store = ProjectStateStore(session_factory)
        registry = ToolRegistry()
        registry.register_tool(ProjectStateShowTool(store))
        registry.register_tool(ProjectStateUpdateTool(store))
        registry.register_tool(ProjectStateVerifyTool(store))

        project_state_plan = _build_phase_update_verify_show_workflow_plan(
            "update phase and then show project state",
            approved_phase_value="v",
            tool_registry=registry,
            security_manager=SecurityManager(),
            session_id=None,
            catalog=CAPABILITY_CATALOG,
        )
        assert isinstance(project_state_plan, Plan)
        assert matches_schedule_compound_plan_shape(project_state_plan) is False

    def test_this_recognizer_never_matches_the_project_state_recognizer_either(
        self,
    ) -> None:
        from core.compound_workflow import matches_compound_plan_shape

        schedule_plan = _trusted_plan()
        assert matches_compound_plan_shape(schedule_plan) is False
