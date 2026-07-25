"""
test_schedule_compound_plan_builder.py

Unit tests for
intelligence.planning._build_schedule_enable_verify_show_workflow_plan()
(Phase 99, Batch 1 - docs/phase_99_second_compound_template_planning.md),
mirroring test_compound_plan_builder.py's own established pattern for
the second, dormant trusted three-step plan builder.

Dormant: never called by select_tool() (see
tests/unit/test_phase99_batch1_isolation.py for the structural proof) -
these tests exercise it directly, mirroring
test_orchestrator_schedule_enable_workflow.py's own real-collaborator
setup (real ToolRegistry/SecurityManager/ScheduleStore/the real
production tools - no fakes for the execution-adjacent collaborators).
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402

from config.constants import SecurityTier  # noqa: E402
from intelligence.capability_catalog import CAPABILITY_CATALOG  # noqa: E402
from intelligence.planning import (  # noqa: E402
    _build_schedule_enable_verify_show_workflow_plan,
)
from planner.plan_models import Plan  # noqa: E402
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


def _registry() -> tuple[ToolRegistry, ScheduleStore, int]:
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    store = ScheduleStore(session_factory)
    record = store.create(query="test query", time_of_day="09:00")
    store.disable(record.id)  # start disabled, so "enable" is meaningful
    registry = ToolRegistry()
    registry.register_tool(ScheduleEnableTool(store))
    registry.register_tool(ScheduleVerifyEnabledStateTool(store))
    registry.register_tool(ScheduleShowEnabledStateTool(store))
    return registry, store, record.id


def _build(schedule_id: int | None = None) -> tuple[Plan | str, int]:
    registry, _store, real_id = _registry()
    target_id = schedule_id if schedule_id is not None else real_id
    security = SecurityManager()
    plan = _build_schedule_enable_verify_show_workflow_plan(
        f"enable schedule {target_id} and then check the enabled state "
        f"of schedule {target_id}",
        approved_schedule_id=target_id,
        tool_registry=registry,
        security_manager=security,
        session_id=None,
        catalog=CAPABILITY_CATALOG,
    )
    return plan, target_id


class TestExactThreeStepPlan:
    def test_builds_a_real_plan_with_exactly_three_steps(self) -> None:
        plan, _id = _build()
        assert isinstance(plan, Plan)
        assert len(plan.steps) == 3

    def test_step_1_is_schedule_enable_with_the_approved_id(self) -> None:
        plan, target_id = _build()
        assert isinstance(plan, Plan)
        assert plan.steps[0].tool_name == "schedule_enable"
        assert plan.steps[0].tool_input == {"schedule_id": target_id}

    def test_step_1_tier_is_yellow(self) -> None:
        plan, _id = _build()
        assert isinstance(plan, Plan)
        assert plan.steps[0].tier is SecurityTier.YELLOW

    def test_step_2_exact_verifier_is_inserted_with_the_same_id(self) -> None:
        plan, target_id = _build()
        assert isinstance(plan, Plan)
        assert plan.steps[1].tool_name == "schedule_verify_enabled_state"
        assert plan.steps[1].tool_input == {"schedule_id": target_id}
        assert plan.steps[1].tier is SecurityTier.GREEN

    def test_step_3_exact_show_identity_with_the_same_id(self) -> None:
        plan, target_id = _build()
        assert isinstance(plan, Plan)
        assert plan.steps[2].tool_name == "schedule_show_enabled_state"
        assert plan.steps[2].tool_input == {"schedule_id": target_id}
        assert plan.steps[2].tier is SecurityTier.GREEN

    def test_step_3_requires_verified_predecessor_expecting_true(self) -> None:
        plan, _id = _build()
        assert isinstance(plan, Plan)
        assert plan.steps[2].requires_verified_predecessor is True
        assert plan.steps[2].verification_field_name == "enabled_str"
        assert plan.steps[2].verification_expected_value == "true"

    def test_all_three_steps_carry_the_identical_schedule_id(self) -> None:
        plan, target_id = _build()
        assert isinstance(plan, Plan)
        assert plan.steps[0].tool_input["schedule_id"] == target_id
        assert plan.steps[1].tool_input["schedule_id"] == target_id
        assert plan.steps[2].tool_input["schedule_id"] == target_id


class TestUserRequestPreserved:
    def test_plan_user_request_is_the_verbatim_text(self) -> None:
        registry, _store, real_id = _registry()
        text = (
            f"enable schedule {real_id} and then check the enabled "
            f"state of schedule {real_id}"
        )
        plan = _build_schedule_enable_verify_show_workflow_plan(
            text,
            approved_schedule_id=real_id,
            tool_registry=registry,
            security_manager=SecurityManager(),
            session_id=None,
            catalog=CAPABILITY_CATALOG,
        )
        assert isinstance(plan, Plan)
        assert plan.user_request == text


class TestPreflightFailures:
    def test_unregistered_write_tool_fails_closed(self) -> None:
        registry = ToolRegistry()  # nothing registered
        result = _build_schedule_enable_verify_show_workflow_plan(
            "enable schedule 1 and then check the enabled state of schedule 1",
            approved_schedule_id=1,
            tool_registry=registry,
            security_manager=SecurityManager(),
            session_id=None,
            catalog=CAPABILITY_CATALOG,
        )
        assert isinstance(result, str)
        assert "no longer registered" in result

    def test_missing_show_tool_fails_closed(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        initialize_database(engine)
        session_factory = create_session_factory(engine)
        store = ScheduleStore(session_factory)
        registry = ToolRegistry()
        registry.register_tool(ScheduleEnableTool(store))
        registry.register_tool(ScheduleVerifyEnabledStateTool(store))
        # Deliberately omit ScheduleShowEnabledStateTool registration.

        result = _build_schedule_enable_verify_show_workflow_plan(
            "enable schedule 1 and then check the enabled state of schedule 1",
            approved_schedule_id=1,
            tool_registry=registry,
            security_manager=SecurityManager(),
            session_id=None,
            catalog=CAPABILITY_CATALOG,
        )
        assert isinstance(result, str)


class TestWorkflowEngineCompatibility:
    def test_plan_is_a_valid_executable_shape_for_workflow_engine(self) -> None:
        """WorkflowEngine._validate_executable_plan()'s own rules
        (sequential 1..3 numbering, non-blank tool_name, first step
        cannot require a verified predecessor) all hold - proving no
        schema/engine change was needed for this second three-step
        plan either."""
        from workflow.engine import WorkflowEngine

        plan, _id = _build()
        assert isinstance(plan, Plan)
        WorkflowEngine._validate_executable_plan(plan)  # raises on failure

    def test_plan_round_trips_through_paused_workflow_serialization(self) -> None:
        from workflow.engine import WorkflowEngine

        plan, target_id = _build()
        assert isinstance(plan, Plan)
        as_dicts = [WorkflowEngine._plan_step_to_dict(step) for step in plan.steps]
        assert as_dicts[2]["requires_verified_predecessor"] is True
        assert as_dicts[2]["verification_field_name"] == "enabled_str"
        assert as_dicts[2]["verification_expected_value"] == "true"
        assert as_dicts[0]["tool_input"]["schedule_id"] == target_id
