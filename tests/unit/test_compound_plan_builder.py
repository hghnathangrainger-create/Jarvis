"""
test_compound_plan_builder.py

Unit tests for intelligence.planning._build_phase_update_verify_show_workflow_plan()
(Phase 98, Batch 2, Foundation B -
docs/phase_98_live_compound_reentry_plan.md).

Dormant: never called by select_tool() (see
test_phase98_batch2_dormant_isolation.py for the structural proof) -
these tests exercise it directly, mirroring
test_orchestrator_update_phase_workflow.py's own real-collaborator
setup (real ToolRegistry/SecurityManager/ProjectStateStore/the real
production tools - no fakes for the execution-adjacent collaborators).
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402

from config.constants import SecurityTier  # noqa: E402
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
from tools.registry import ToolRegistry  # noqa: E402


def _registry() -> tuple[ToolRegistry, ProjectStateStore]:
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    store = ProjectStateStore(session_factory)
    registry = ToolRegistry()
    registry.register_tool(ProjectStateShowTool(store))
    registry.register_tool(ProjectStateUpdateTool(store))
    registry.register_tool(ProjectStateVerifyTool(store))
    return registry, store


def _build(value: str = "Phase 98 Batch 2") -> Plan | str:
    registry, _store = _registry()
    security = SecurityManager()
    return _build_phase_update_verify_show_workflow_plan(
        "update phase to Phase 98 Batch 2 and then show project state",
        approved_phase_value=value,
        tool_registry=registry,
        security_manager=security,
        session_id=None,
        catalog=CAPABILITY_CATALOG,
    )


class TestExactThreeStepPlan:
    def test_builds_a_real_plan_with_exactly_three_steps(self) -> None:
        plan = _build()
        assert isinstance(plan, Plan)
        assert len(plan.steps) == 3

    def test_step_1_fixed_field_is_phase(self) -> None:
        plan = _build()
        assert isinstance(plan, Plan)
        assert plan.steps[0].tool_name == "project_state_update"
        assert plan.steps[0].tool_input["field"] == "phase"
        assert plan.steps[0].tool_input["value"] == "Phase 98 Batch 2"

    def test_step_1_tier_is_yellow(self) -> None:
        plan = _build()
        assert isinstance(plan, Plan)
        assert plan.steps[0].tier is SecurityTier.YELLOW

    def test_step_2_exact_verifier_is_inserted(self) -> None:
        plan = _build()
        assert isinstance(plan, Plan)
        assert plan.steps[1].tool_name == "project_state_verify"
        assert plan.steps[1].tool_input == {}
        assert plan.steps[1].tier is SecurityTier.GREEN

    def test_step_2_expected_value_matches_step_1(self) -> None:
        plan = _build("a specific value")
        assert isinstance(plan, Plan)
        assert plan.steps[0].tool_input["value"] == "a specific value"

    def test_step_3_exact_show_identity(self) -> None:
        plan = _build()
        assert isinstance(plan, Plan)
        assert plan.steps[2].tool_name == "project_state_show"
        assert plan.steps[2].tool_input == {}
        assert plan.steps[2].tier is SecurityTier.GREEN

    def test_step_3_requires_verified_predecessor(self) -> None:
        plan = _build("verify-me")
        assert isinstance(plan, Plan)
        assert plan.steps[2].requires_verified_predecessor is True
        assert plan.steps[2].verification_field_name == "phase"
        assert plan.steps[2].verification_expected_value == "verify-me"

    def test_no_model_controlled_input_on_step_3(self) -> None:
        plan = _build()
        assert isinstance(plan, Plan)
        assert plan.steps[2].tool_input == {}


class TestUserRequestPreserved:
    def test_plan_user_request_is_the_verbatim_text(self) -> None:
        plan = _build_phase_update_verify_show_workflow_plan(
            "update phase to X and then show project state",
            approved_phase_value="X",
            tool_registry=_registry()[0],
            security_manager=SecurityManager(),
            session_id=None,
            catalog=CAPABILITY_CATALOG,
        )
        assert isinstance(plan, Plan)
        assert plan.user_request == "update phase to X and then show project state"


class TestWorkflowEngineCompatibility:
    def test_plan_is_a_valid_executable_shape_for_workflow_engine(self) -> None:
        """WorkflowEngine._validate_executable_plan()'s own rules
        (sequential 1..3 numbering, non-blank tool_name, first step
        cannot require a verified predecessor) all hold - proving no
        schema/engine change was needed for a three-step plan."""
        from workflow.engine import WorkflowEngine

        plan = _build()
        assert isinstance(plan, Plan)
        WorkflowEngine._validate_executable_plan(plan)  # raises on failure

    def test_plan_round_trips_through_paused_workflow_serialization(self) -> None:
        """Confirms no schema change: the exact same
        _plan_step_to_dict()/_reconstruct_plan_and_outcomes() shape
        already round-trips every field this three-step plan uses."""
        from workflow.engine import WorkflowEngine

        plan = _build("round-trip-value")
        assert isinstance(plan, Plan)
        as_dicts = [WorkflowEngine._plan_step_to_dict(step) for step in plan.steps]
        assert as_dicts[2]["requires_verified_predecessor"] is True
        assert as_dicts[2]["verification_field_name"] == "phase"
        assert as_dicts[2]["verification_expected_value"] == "round-trip-value"
