"""
test_workflow_plan_factory.py

Focused unit tests for the Phase 15, Batch 3 deterministic workflow plan
factory (workflow/workflow_plan_factory.py).

Run with:
    pytest tests/unit/test_workflow_plan_factory.py
"""

from __future__ import annotations

import ast
import inspect

from config.constants import SecurityTier
from workflow.workflow_plan_factory import (
    build_remember_and_forget_plan,
    build_remember_and_show_plan,
)

# --- build_remember_and_show_plan --------------------------------------------


def test_show_plan_has_exactly_two_steps() -> None:
    plan = build_remember_and_show_plan("Buy milk")
    assert len(plan.steps) == 2


def test_show_plan_step_order_is_save_then_get() -> None:
    plan = build_remember_and_show_plan("Buy milk")
    assert plan.steps[0].number == 1
    assert plan.steps[1].number == 2


def test_show_plan_exact_tool_names() -> None:
    plan = build_remember_and_show_plan("Buy milk")
    assert plan.steps[0].tool_name == "memory"
    assert plan.steps[1].tool_name == "memory"


def test_show_plan_exact_tool_input_shapes() -> None:
    plan = build_remember_and_show_plan("Buy milk")
    assert plan.steps[0].tool_input == {"operation": "save", "content": "Buy milk"}
    assert plan.steps[1].tool_input == {"operation": "get"}


def test_show_plan_propagation_flag_only_on_step_two() -> None:
    plan = build_remember_and_show_plan("Buy milk")
    assert plan.steps[0].input_from_previous_step is False
    assert plan.steps[1].input_from_previous_step is True


def test_show_plan_step_actions_match_security_manager_rule_table() -> None:
    """The exact action strings this factory uses must be the same ones
    ToolExecutor will independently, authoritatively classify at execution
    time - verified directly against the real SecurityManager, not
    assumed."""
    from security.security_manager import SecurityManager

    security = SecurityManager()
    plan = build_remember_and_show_plan("Buy milk")

    assert security.classify_action(plan.steps[0].action).tier is SecurityTier.GREEN
    assert security.classify_action(plan.steps[1].action).tier is SecurityTier.GREEN


def test_show_plan_display_tier_is_non_authoritative_metadata_only() -> None:
    """PlanStep.tier here is display metadata - this test does not claim it
    is authoritative; execution-time re-classification is proven separately
    by workflow.engine's own tests."""
    plan = build_remember_and_show_plan("Buy milk")
    assert plan.steps[0].tier is SecurityTier.GREEN
    assert plan.steps[1].tier is SecurityTier.GREEN


def test_show_plan_never_produces_a_third_step() -> None:
    plan = build_remember_and_show_plan("Buy milk")
    assert len(plan.steps) == 2


def test_show_plan_content_flows_only_into_step_one() -> None:
    plan = build_remember_and_show_plan("a very specific value")
    assert plan.steps[0].tool_input["content"] == "a very specific value"
    assert "content" not in plan.steps[1].tool_input


# --- build_remember_and_forget_plan ------------------------------------------


def test_forget_plan_has_exactly_two_steps() -> None:
    plan = build_remember_and_forget_plan("Temporary note")
    assert len(plan.steps) == 2


def test_forget_plan_exact_tool_names() -> None:
    plan = build_remember_and_forget_plan("Temporary note")
    assert plan.steps[0].tool_name == "memory"
    assert plan.steps[1].tool_name == "memory_forget"


def test_forget_plan_exact_tool_input_shapes() -> None:
    plan = build_remember_and_forget_plan("Temporary note")
    assert plan.steps[0].tool_input == {
        "operation": "save",
        "content": "Temporary note",
    }
    assert plan.steps[1].tool_input == {}


def test_forget_plan_propagation_flag_only_on_step_two() -> None:
    plan = build_remember_and_forget_plan("Temporary note")
    assert plan.steps[0].input_from_previous_step is False
    assert plan.steps[1].input_from_previous_step is True


def test_forget_plan_step_two_action_classifies_yellow() -> None:
    from security.security_manager import SecurityManager

    security = SecurityManager()
    plan = build_remember_and_forget_plan("Temporary note")

    assert security.classify_action(plan.steps[0].action).tier is SecurityTier.GREEN
    assert security.classify_action(plan.steps[1].action).tier is SecurityTier.YELLOW


def test_forget_plan_display_tier_matches_real_classification() -> None:
    plan = build_remember_and_forget_plan("Temporary note")
    assert plan.steps[0].tier is SecurityTier.GREEN
    assert plan.steps[1].tier is SecurityTier.YELLOW


def test_forget_plan_factory_does_not_create_an_approval() -> None:
    """The factory returns a plain Plan; nothing about its construction
    creates, references, or requires an ApprovalRequest."""
    plan = build_remember_and_forget_plan("Temporary note")
    assert not hasattr(plan, "approval_request")


def test_forget_plan_never_produces_a_third_step() -> None:
    plan = build_remember_and_forget_plan("Temporary note")
    assert len(plan.steps) == 2


# --- Planning-authority proof -------------------------------------------------


def test_factory_module_has_zero_forbidden_imports() -> None:
    """Structural proof, via real AST import inspection: the factory
    imports none of AIReasoningEngine, Planner, ToolExecutor,
    SecurityManager, ToolRegistry, or MemoryManager."""
    import workflow.workflow_plan_factory as module

    with open(module.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    for forbidden in (
        "AIReasoningEngine",
        "AIRouter",
        "Planner",
        "ToolExecutor",
        "SecurityManager",
        "ToolRegistry",
        "MemoryManager",
    ):
        assert forbidden not in imported_names


def test_factory_never_accepts_a_user_provided_tool_name() -> None:
    """Both public functions accept only free-text content - no parameter
    exists through which a caller could name an arbitrary tool."""
    import workflow.workflow_plan_factory as module

    show_params = list(inspect.signature(module.build_remember_and_show_plan).parameters)
    forget_params = list(
        inspect.signature(module.build_remember_and_forget_plan).parameters
    )
    assert show_params == ["content"]
    assert forget_params == ["content"]


def test_factory_is_not_routed_through_planner() -> None:
    """planner/planner.py is untouched by this batch - structural proof
    that Planner.create_plan() is never called from within the factory."""
    import workflow.workflow_plan_factory as module

    tree = ast.parse(inspect.getsource(module))
    called_names = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "create_plan" not in called_names
