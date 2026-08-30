"""
test_plan_models.py

Focused unit tests for the Phase 15, Batch 1 PlanStep schema extension
(planner/plan_models.py): tool_name, tool_input, input_from_previous_step.

These prove:
    - Every existing Phase 1-14 PlanStep construction site continues to
      work unchanged (the three new fields are fully optional/defaulted).
    - The new fields hold only plain, unvalidated data - no ToolRegistry
      or SecurityManager dependency exists in this module.
    - input_from_previous_step is a narrow declarative boolean only: no
      depends_on, retry, on_failure, or status field exists on PlanStep.

Run with:
    pytest tests/unit/test_plan_models.py
"""

from __future__ import annotations

import dataclasses

from config.constants import SecurityTier
from planner.plan_models import Plan, PlanStep


def _legacy_step(number: int = 1) -> PlanStep:
    """Build a step exactly as every existing Phase 1-14 call site does -
    naming only the five original fields, positionally as the real
    Planner._classify() already does."""
    return PlanStep(
        number=number,
        description="Read the requested file.",
        action="read file report.txt",
        tier=SecurityTier.GREEN,
        reason="Reading a file is safe.",
    )


# --- Legacy compatibility ----------------------------------------------------


def test_legacy_construction_without_new_fields_still_works() -> None:
    step = _legacy_step()
    assert step.number == 1
    assert step.description == "Read the requested file."
    assert step.action == "read file report.txt"
    assert step.tier is SecurityTier.GREEN
    assert step.reason == "Reading a file is safe."


def test_legacy_step_new_fields_default_safely() -> None:
    step = _legacy_step()
    assert step.tool_name is None
    assert step.tool_input == {}
    assert step.input_from_previous_step is False


def test_legacy_original_fields_unchanged_in_name_and_meaning() -> None:
    """number/description/action/tier/reason are not reinterpreted."""
    step = _legacy_step(number=3)
    assert step.number == 3
    fields = {f.name for f in dataclasses.fields(PlanStep)}
    assert {"number", "description", "action", "tier", "reason"} <= fields


def test_plan_with_legacy_steps_still_constructs() -> None:
    plan = Plan(user_request="read file report.txt", steps=(_legacy_step(),))
    assert not plan.is_empty
    assert plan.steps[0].tool_name is None


def test_empty_plan_remains_valid() -> None:
    """Zero-step Plan remains a valid, legacy-compatible state."""
    plan = Plan(user_request="do nothing")
    assert plan.is_empty
    assert plan.steps == ()


# --- tool_name semantics -----------------------------------------------------


def test_tool_name_accepts_a_registered_style_name() -> None:
    step = dataclasses.replace(_legacy_step(), tool_name="memory")
    assert step.tool_name == "memory"


def test_tool_name_omitted_defaults_to_none() -> None:
    assert _legacy_step().tool_name is None


def test_tool_name_empty_string_is_not_rejected_by_the_model() -> None:
    """The model performs no ToolRegistry/SecurityManager validation -
    availability and non-blankness are execution-time (WorkflowEngine)
    concerns, not this immutable model's."""
    step = dataclasses.replace(_legacy_step(), tool_name="")
    assert step.tool_name == ""


def test_tool_name_whitespace_only_is_not_rejected_by_the_model() -> None:
    step = dataclasses.replace(_legacy_step(), tool_name="   ")
    assert step.tool_name == "   "


def test_plan_models_module_imports_no_tool_registry_or_security_manager() -> None:
    """Structural proof, not just an assumption: plan_models.py has no
    *import* of ToolRegistry or SecurityManager (the names may still
    appear in prose docstrings explaining what this model does not do)."""
    import ast

    import planner.plan_models as module

    with open(module.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    assert "ToolRegistry" not in imported_names
    assert "SecurityManager" not in imported_names


# --- tool_input semantics ----------------------------------------------------


def test_tool_input_omitted_defaults_to_empty_dict() -> None:
    assert _legacy_step().tool_input == {}


def test_tool_input_accepts_normal_text() -> None:
    step = dataclasses.replace(
        _legacy_step(), tool_input={"content": "Buy milk"}
    )
    assert step.tool_input == {"content": "Buy milk"}


def test_tool_input_accepts_empty_string_value() -> None:
    step = dataclasses.replace(_legacy_step(), tool_input={"content": ""})
    assert step.tool_input == {"content": ""}


def test_tool_input_accepts_whitespace_value() -> None:
    step = dataclasses.replace(_legacy_step(), tool_input={"content": "   "})
    assert step.tool_input == {"content": "   "}


def test_tool_input_accepts_unicode_text() -> None:
    step = dataclasses.replace(
        _legacy_step(), tool_input={"content": "héllo wörld 你好"}
    )
    assert step.tool_input == {"content": "héllo wörld 你好"}


def test_two_plansteps_do_not_share_a_mutable_default_tool_input() -> None:
    """default_factory=dict must produce an independent dict per instance."""
    a = _legacy_step(number=1)
    b = _legacy_step(number=2)
    assert a.tool_input is not b.tool_input


# --- input_from_previous_step semantics --------------------------------------


def test_input_from_previous_step_defaults_to_false() -> None:
    assert _legacy_step().input_from_previous_step is False


def test_input_from_previous_step_can_be_explicitly_true() -> None:
    step = dataclasses.replace(_legacy_step(), input_from_previous_step=True)
    assert step.input_from_previous_step is True


def test_input_from_previous_step_is_a_plain_bool_not_a_reference() -> None:
    """Batch 1 represents only the declarative intent - no named
    reference, no key name, no expression - is stored anywhere on the
    model."""
    step = dataclasses.replace(_legacy_step(), input_from_previous_step=True)
    assert isinstance(step.input_from_previous_step, bool)


# --- Explicit absence of out-of-scope fields ---------------------------------


def test_plan_step_has_depends_on_field() -> None:
    """DAG workflow extension: depends_on defaults to empty list."""
    step = _legacy_step()
    assert step.depends_on == []
    step_with_deps = dataclasses.replace(step, depends_on=["step_1"])
    assert step_with_deps.depends_on == ["step_1"]


def test_plan_step_has_retry_fields() -> None:
    """DAG workflow extension: max_retries defaults to 0."""
    step = _legacy_step()
    assert step.max_retries == 0
    assert step.on_failure == "abort"


def test_plan_step_has_on_failure_field() -> None:
    """DAG workflow extension: on_failure defaults to 'abort'."""
    step = _legacy_step()
    assert step.on_failure == "abort"
    step_skip = dataclasses.replace(step, on_failure="skip")
    assert step_skip.on_failure == "skip"


def test_plan_step_has_no_status_field() -> None:
    """Runtime execution state lives in workflow.workflow_models, not on
    the immutable PlanStep itself."""
    fields = {f.name for f in dataclasses.fields(PlanStep)}
    assert "status" not in fields


def test_plan_step_has_the_approved_field_set() -> None:
    """PlanStep includes both original fields and DAG workflow extensions."""
    fields = {f.name for f in dataclasses.fields(PlanStep)}
    assert fields == {
        "number",
        "description",
        "action",
        "tier",
        "reason",
        "tool_name",
        "tool_input",
        "input_from_previous_step",
        # Phase 98, Batch 1 (docs/phase_98_implementation_plan.md): the
        # trusted verification-continuation gate. All three default to
        # values that leave every existing PlanStep unchanged.
        "requires_verified_predecessor",
        "verification_field_name",
        "verification_expected_value",
        # DAG workflow extensions (N-step execution with dependency
        # resolution). All default to values that leave every existing
        # PlanStep unchanged.
        "step_id",
        "depends_on",
        "on_failure",
        "max_retries",
        "compensate",
        "compensate_input",
    }


def test_plan_step_remains_frozen() -> None:
    step = _legacy_step()
    with_new_tool = dataclasses.replace(step, tool_name="memory")
    assert with_new_tool is not step
    try:
        step.tool_name = "memory"  # type: ignore[misc]
        assert False, "PlanStep must remain frozen"
    except dataclasses.FrozenInstanceError:
        pass
