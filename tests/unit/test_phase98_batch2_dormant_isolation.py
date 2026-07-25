"""
test_phase98_batch2_dormant_isolation.py

Structural proof that Phase 98, Batch 2's new trusted compound
lifecycle (docs/phase_98_live_compound_reentry_plan.md) adds zero live
compound wiring and zero user-visible behavior. No production request
path, help output, user guide, or prompt instruction may ever reach
peek_compound_decision(), the dormant plan builder, or any function in
core/compound_workflow.py.

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
    "intelligence/planning.py",
    "core/orchestrator.py",
    "main.py",
    "ui/cli.py",
    "core/command_router.py",
    "tools/builtin/help_tool.py",
)

_NEW_BATCH2_MODULE_NAMES = frozenset(
    {"compound_workflow", "compound_progress_observer"}
)


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
    are never imported by any live runtime module in Batch 2."""

    @pytest.mark.parametrize("relative_path", _LIVE_RUNTIME_MODULES)
    def test_module_does_not_import_batch2_internals(self, relative_path: str) -> None:
        source = _module_source(relative_path)
        referenced = _referenced_module_names(source)
        assert not (referenced & _NEW_BATCH2_MODULE_NAMES)


class TestSelectToolUnreachableToCompoundBuilder:
    def test_select_tool_never_calls_dormant_compound_plan_builder(self) -> None:
        """Duplicated, narrower proof alongside
        test_phase98_batch1_isolation.py's own equivalent test - kept
        here too so this file alone fully documents Batch 2's dormant
        boundary without depending on another file's own assertion."""
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

    def test_planning_module_never_calls_peek_compound_decision(self) -> None:
        """peek_compound_decision() is written and independently
        testable, but Batch 2 attaches no call site to it anywhere in
        planning.py - Batch 3's own, separately-approved wiring is the
        only place this may change."""
        source = _module_source("intelligence/planning.py")
        assert "peek_compound_decision" not in source


class TestNoOrchestratorOrMainCompoundBranch:
    def test_orchestrator_source_has_no_compound_workflow_reference(self) -> None:
        source = _module_source("core/orchestrator.py")
        assert "compound_workflow" not in source
        assert "CompoundStepObserver" not in source
        assert "resume_claimed_compound_workflow" not in source

    def test_main_source_has_no_compound_workflow_reference(self) -> None:
        source = _module_source("main.py")
        assert "compound_workflow" not in source
        assert "reconcile_claimed_compound_workflows" not in source


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
