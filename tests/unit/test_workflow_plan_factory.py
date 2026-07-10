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
    build_create_and_read_plan,
    build_remember_and_forget_plan,
    build_remember_and_show_plan,
    build_update_and_show_plan,
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


# --- build_create_and_read_plan (Phase 17, Batch 1) ---------------------------


def test_create_read_plan_exact_user_request_title() -> None:
    plan = build_create_and_read_plan("notes.txt", "hello")
    assert plan.user_request == "create file notes.txt with hello and show it"


def test_create_read_plan_has_exactly_two_steps() -> None:
    plan = build_create_and_read_plan("notes.txt", "hello")
    assert len(plan.steps) == 2


def test_create_read_plan_consecutive_step_numbers() -> None:
    plan = build_create_and_read_plan("notes.txt", "hello")
    assert plan.steps[0].number == 1
    assert plan.steps[1].number == 2


def test_create_read_plan_exact_tool_names() -> None:
    plan = build_create_and_read_plan("notes.txt", "hello")
    assert plan.steps[0].tool_name == "file_create"
    assert plan.steps[1].tool_name == "file_read"


def test_create_read_plan_exact_tool_input_shapes() -> None:
    plan = build_create_and_read_plan("notes.txt", "hello world")
    assert plan.steps[0].tool_input == {"path": "notes.txt", "content": "hello world"}
    assert plan.steps[1].tool_input == {"path": "notes.txt"}


def test_create_read_plan_identical_literal_path_in_both_steps() -> None:
    plan = build_create_and_read_plan("a/very/specific/path.txt", "content")
    assert plan.steps[0].tool_input["path"] == "a/very/specific/path.txt"
    assert plan.steps[1].tool_input["path"] == "a/very/specific/path.txt"
    assert plan.steps[0].tool_input["path"] == plan.steps[1].tool_input["path"]


def test_create_read_plan_propagation_flag_false_on_both_steps() -> None:
    """Unlike the memory workflows, neither step uses engine propagation -
    the factory itself shares the literal path across both steps."""
    plan = build_create_and_read_plan("notes.txt", "hello")
    assert plan.steps[0].input_from_previous_step is False
    assert plan.steps[1].input_from_previous_step is False


def test_create_read_plan_step_actions_match_security_manager_rule_table() -> None:
    from security.security_manager import SecurityManager

    security = SecurityManager()
    plan = build_create_and_read_plan("notes.txt", "hello")

    assert (
        security.classify_action(plan.steps[0].action).tier is SecurityTier.YELLOW
    )
    assert security.classify_action(plan.steps[1].action).tier is SecurityTier.GREEN


def test_create_read_plan_display_tier_is_non_authoritative_metadata_only() -> None:
    plan = build_create_and_read_plan("notes.txt", "hello")
    assert plan.steps[0].tier is SecurityTier.YELLOW
    assert plan.steps[1].tier is SecurityTier.GREEN


def test_create_read_plan_never_produces_a_third_step() -> None:
    plan = build_create_and_read_plan("notes.txt", "hello")
    assert len(plan.steps) == 2


def test_create_read_plan_content_flows_only_into_step_one() -> None:
    plan = build_create_and_read_plan("notes.txt", "a very specific value")
    assert plan.steps[0].tool_input["content"] == "a very specific value"
    assert "content" not in plan.steps[1].tool_input


# --- build_update_and_show_plan (Phase 17, Batch 1) ----------------------------


def test_update_show_plan_exact_user_request_title() -> None:
    plan = build_update_and_show_plan(5, "new content")
    assert plan.user_request == "update memory 5: new content and show it back"


def test_update_show_plan_has_exactly_two_steps() -> None:
    plan = build_update_and_show_plan(5, "new content")
    assert len(plan.steps) == 2


def test_update_show_plan_consecutive_step_numbers() -> None:
    plan = build_update_and_show_plan(5, "new content")
    assert plan.steps[0].number == 1
    assert plan.steps[1].number == 2


def test_update_show_plan_exact_tool_names() -> None:
    plan = build_update_and_show_plan(5, "new content")
    assert plan.steps[0].tool_name == "memory_update"
    assert plan.steps[1].tool_name == "memory"


def test_update_show_plan_exact_step_one_input_shape() -> None:
    plan = build_update_and_show_plan(5, "new content")
    assert plan.steps[0].tool_input == {
        "operation": "update",
        "memory_id": 5,
        "content": "new content",
    }


def test_update_show_plan_exact_step_two_input_shape() -> None:
    plan = build_update_and_show_plan(5, "new content")
    assert plan.steps[1].tool_input == {"operation": "get"}


def test_update_show_plan_step_two_has_no_manually_prefilled_memory_id() -> None:
    """Step 2 must rely entirely on WorkflowEngine's existing runtime
    propagation - the factory must never copy the originally-parsed
    memory_id into step 2's own tool_input itself."""
    plan = build_update_and_show_plan(5, "new content")
    assert "memory_id" not in plan.steps[1].tool_input


def test_update_show_plan_propagation_flag_only_on_step_two() -> None:
    plan = build_update_and_show_plan(5, "new content")
    assert plan.steps[0].input_from_previous_step is False
    assert plan.steps[1].input_from_previous_step is True


def test_update_show_plan_step_actions_match_security_manager_rule_table() -> None:
    from security.security_manager import SecurityManager

    security = SecurityManager()
    plan = build_update_and_show_plan(5, "new content")

    assert (
        security.classify_action(plan.steps[0].action).tier is SecurityTier.YELLOW
    )
    assert security.classify_action(plan.steps[1].action).tier is SecurityTier.GREEN


def test_update_show_plan_display_tier_is_non_authoritative_metadata_only() -> None:
    plan = build_update_and_show_plan(5, "new content")
    assert plan.steps[0].tier is SecurityTier.YELLOW
    assert plan.steps[1].tier is SecurityTier.GREEN


def test_update_show_plan_never_produces_a_third_step() -> None:
    plan = build_update_and_show_plan(5, "new content")
    assert len(plan.steps) == 2


def test_update_show_plan_content_flows_only_into_step_one() -> None:
    plan = build_update_and_show_plan(5, "a very specific replacement")
    assert plan.steps[0].tool_input["content"] == "a very specific replacement"
    assert "content" not in plan.steps[1].tool_input


def test_update_show_plan_accepts_various_memory_ids() -> None:
    plan = build_update_and_show_plan(1, "x")
    assert plan.steps[0].tool_input["memory_id"] == 1
    plan = build_update_and_show_plan(9999, "x")
    assert plan.steps[0].tool_input["memory_id"] == 9999


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
    """No public function's parameters name an arbitrary tool - each takes
    only plain data (free-text content, a path, or a memory id)."""
    import workflow.workflow_plan_factory as module

    show_params = list(inspect.signature(module.build_remember_and_show_plan).parameters)
    forget_params = list(
        inspect.signature(module.build_remember_and_forget_plan).parameters
    )
    create_read_params = list(
        inspect.signature(module.build_create_and_read_plan).parameters
    )
    update_show_params = list(
        inspect.signature(module.build_update_and_show_plan).parameters
    )
    assert show_params == ["content"]
    assert forget_params == ["content"]
    assert create_read_params == ["path", "content"]
    assert update_show_params == ["memory_id", "content"]


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
