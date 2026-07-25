"""
test_phase98_batch2_dormant_isolation.py

Structural proof that Phase 98, Batch 2's new trusted compound
lifecycle (docs/phase_98_live_compound_reentry_plan.md) itself added
zero live compound wiring and zero user-visible behavior at the time.

Phase 98, Batch 3 formally, atomically activated this lifecycle
through exactly two call sites - intelligence/planning.py's
select_tool() (the live discriminator peek) and core/orchestrator.py
(consumes core/compound_workflow.py's functions and
workflow/compound_progress_observer.py's CompoundStepObserver, through
its own new, narrow set of methods) - plus main.py's compound-first
startup recovery wiring. Every assertion below that concerned those
specific modules/functions is revised, not removed, to prove the
activation is confined exactly there. help_tool.py/docs/user_guide.md/
ui/cli.py/core/command_router.py's own assertions are untouched here -
see the dedicated compound-example additions and their own test
coverage for what Batch 3 legitimately changed there.

Uses direct imports and module-source AST inspection - never brittle
raw-text search where a structural check is possible, mirroring
tests/unit/test_compound_isolation.py (Phase 97) and
tests/unit/test_phase98_batch1_isolation.py (Phase 98, Batch 1).
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_LIVE_RUNTIME_MODULES = (
    "intelligence/compound_structured_output.py",
    "intelligence/compound_grounding.py",
    "intelligence/structured_output.py",
    "ui/cli.py",
    "core/command_router.py",
)

_NEW_BATCH2_MODULE_NAMES = frozenset(
    {"compound_workflow", "compound_progress_observer"}
)

#: Phase 98, Batch 3: the only functions/methods in core/orchestrator.py
#: and main.py allowed to reference a Batch 2 compound-lifecycle name.
_ORCHESTRATOR_ALLOWED_COMPOUND_FUNCTIONS = frozenset(
    {
        "__init__",
        "validate_pending_approval_for_transition",
        "_claim_and_resume_workflow",
        "_compound_step_observer_for",
        "_start_compound_update_phase_and_show_workflow",
    }
)
_MAIN_ALLOWED_COMPOUND_FUNCTIONS = frozenset(
    {"build_orchestrator", "reconcile_claimed_handoffs", "invalidate_pending"}
)


def _functions_referencing(source: str, needle: str) -> set[str]:
    tree = ast.parse(source)
    hits: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        segment = ast.get_source_segment(source, node) or ""
        if needle in segment:
            hits.add(node.name)
    return hits


def _module_source(relative_path: str) -> str:
    return (_REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _referenced_module_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.update(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.update(node.module.split("."))
    return names


class TestNoLiveModuleImportsBatch2Internals:
    """core/compound_workflow.py and workflow/compound_progress_observer.py
    are never imported by any of these live runtime modules - the ones
    Batch 3 did not touch. (core/orchestrator.py and main.py are the
    two Batch 3 exceptions, covered by TestOrchestratorAndMainCompoundWiring
    below.)"""

    @pytest.mark.parametrize("relative_path", _LIVE_RUNTIME_MODULES)
    def test_module_does_not_import_batch2_internals(self, relative_path: str) -> None:
        source = _module_source(relative_path)
        referenced = _referenced_module_names(source)
        assert not (referenced & _NEW_BATCH2_MODULE_NAMES)


class TestSelectToolCompoundDispatch:
    """Phase 98, Batch 3 activation: select_tool() is now the one live
    call site for both peek_compound_decision() and the dormant-since-
    Batch-2 compound plan builder (indirectly, via its own dedicated
    _select_compound_tool_sequence() helper) - proven confined, not
    absent."""

    def test_select_tool_calls_the_compound_plan_builder_only_via_its_own_helper(
        self,
    ) -> None:
        """select_tool() itself must never call
        _build_phase_update_verify_show_workflow_plan() directly - only
        _select_compound_tool_sequence() may, keeping the delegation
        chain exactly one level deep."""
        source = _module_source("intelligence/planning.py")
        tree = ast.parse(source)
        select_tool_node = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "select_tool"
        )
        called_names = {
            call.func.id
            for call in ast.walk(select_tool_node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        }
        assert "_build_phase_update_verify_show_workflow_plan" not in called_names
        assert "_select_compound_tool_sequence" in called_names

    def test_planning_module_calls_peek_compound_decision_only_from_select_tool(
        self,
    ) -> None:
        """Phase 98, Batch 3: peek_compound_decision() is now live -
        actually *called* only from select_tool() itself. (Its own
        docstring in _select_compound_tool_sequence() names it too, to
        explain the calling contract, but that is a docstring mention,
        never a real ast.Call - only genuine calls count here.)"""
        source = _module_source("intelligence/planning.py")
        tree = ast.parse(source)
        calling_functions: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "peek_compound_decision"
                ):
                    calling_functions.add(node.name)
                    break
        assert calling_functions == {"select_tool"}


class TestOrchestratorAndMainCompoundWiring:
    """Phase 98, Batch 3 activation: core/orchestrator.py and main.py
    now legitimately reference Batch 2's compound lifecycle - proven
    confined to exactly the intended methods/functions, never a
    broader, uncontrolled sprawl through either module."""

    def test_orchestrator_compound_workflow_reference_confined_to_named_methods(
        self,
    ) -> None:
        source = _module_source("core/orchestrator.py")
        assert "compound_workflow" in source
        assert "CompoundStepObserver" in source
        # resume_claimed_compound_workflow() itself is never called here
        # - orchestrator.py attaches the observer to the existing,
        # unmodified WorkflowEngine.resume(), never a separate
        # compound-specific resume function.
        assert "resume_claimed_compound_workflow" not in source

        hits = _functions_referencing(source, "compound_workflow") | (
            _functions_referencing(source, "CompoundStepObserver")
        )
        assert hits <= _ORCHESTRATOR_ALLOWED_COMPOUND_FUNCTIONS, (
            f"unexpected compound-lifecycle reference inside: "
            f"{hits - _ORCHESTRATOR_ALLOWED_COMPOUND_FUNCTIONS}"
        )

    def test_main_compound_workflow_reference_confined_to_named_functions(
        self,
    ) -> None:
        source = _module_source("main.py")
        assert "compound_workflow" in source
        assert "reconcile_claimed_compound_workflows" in source

        hits = _functions_referencing(source, "compound_workflow")
        assert hits <= _MAIN_ALLOWED_COMPOUND_FUNCTIONS, (
            f"unexpected compound_workflow reference inside: "
            f"{hits - _MAIN_ALLOWED_COMPOUND_FUNCTIONS}"
        )


class TestNoUserFacingExposure:
    def test_help_tool_has_no_compound_reference(self) -> None:
        source = _module_source("tools/builtin/help_tool.py")
        assert "execute_sequence" not in source
        assert "compound" not in source.casefold()

    def test_user_guide_has_no_compound_reference(self) -> None:
        source = _module_source("docs/user_guide.md")
        assert "execute_sequence" not in source
        assert "compound workflow" not in source.casefold()

    def test_cli_has_no_compound_reference(self) -> None:
        source = _module_source("ui/cli.py")
        assert "compound_workflow" not in source
        assert "peek_compound_decision" not in source

    def test_command_router_has_no_compound_grammar(self) -> None:
        source = _module_source("core/command_router.py")
        assert "execute_sequence" not in source
        assert "compound_workflow" not in source


class TestObserverAttachmentBoundary:
    """WorkflowEngine.run() must structurally be unable to accept a
    step_observer - only resume()/_run_from() may."""

    def test_run_signature_has_no_step_observer_parameter(self) -> None:
        import workflow.engine as module

        tree = ast.parse(inspect.getsource(module))
        run_node = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        )
        arg_names = {arg.arg for arg in run_node.args.args} | {
            arg.arg for arg in run_node.args.kwonlyargs
        }
        assert "step_observer" not in arg_names

    def test_run_never_forwards_a_step_observer_to_run_from(self) -> None:
        import workflow.engine as module

        tree = ast.parse(inspect.getsource(module))
        run_node = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        )
        for call in ast.walk(run_node):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "_run_from"
            ):
                keyword_names = {kw.arg for kw in call.keywords}
                assert "step_observer" not in keyword_names

    def test_resume_and_run_from_both_default_step_observer_to_none(self) -> None:
        import workflow.engine as module

        tree = ast.parse(inspect.getsource(module))
        for func_name in ("resume", "_run_from"):
            node = next(
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == func_name
            )
            kwonly = dict(zip(node.args.kwonlyargs, node.args.kw_defaults))
            observer_arg = next(
                (arg for arg in kwonly if arg.arg == "step_observer"), None
            )
            assert observer_arg is not None, f"{func_name} must accept step_observer"
            default = kwonly[observer_arg]
            assert isinstance(default, ast.Constant) and default.value is None


class TestNoNormalRequestCreatesCompoundState:
    def test_capability_catalog_still_has_no_execute_sequence_capability(self) -> None:
        """The catalog's own bounded CapabilityId enum still has no
        compound-decision member - a normal single-decision request can
        never select or construct anything compound-shaped."""
        from intelligence.capability_catalog import CapabilityId

        member_values = {member.value for member in CapabilityId}
        assert "execute_sequence" not in member_values

    def test_structured_output_parser_still_rejects_execute_sequence(self) -> None:
        from intelligence.capability_catalog import CAPABILITY_CATALOG
        from intelligence.structured_output import (
            ToolSelectionParseError,
            parse_tool_selection,
        )

        with pytest.raises(ToolSelectionParseError):
            parse_tool_selection(
                '{"decision": "execute_sequence", "capability_id": null, '
                '"arguments": {}}',
                CAPABILITY_CATALOG,
            )
