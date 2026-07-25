"""
test_phase98_batch1_isolation.py

Structural proof that Phase 98 Batch 1's two new foundations (the
PlanStep verification gate and CompoundWorkflowProgressStore) added
zero live compound wiring and zero user-visible behavior at the time
(docs/phase_98_implementation_plan.md).

Phase 98, Batch 3 (docs/phase_98_live_compound_reentry_plan.md)
formally, atomically activated live wiring for CompoundWorkflowProgressStore
through exactly two call sites: main.py's build_orchestrator() (owns
the store instance) and core/orchestrator.py (consumes it through its
own new, narrow set of methods). Every assertion below that concerned
those two files is revised, not removed, to prove the reference is
confined exactly there - never a broader sprawl - while every other
module keeps the original, unchanged "must never import this" bar.
The PlanStep verification-gate assertions (requires_verified_predecessor)
are untouched: Batch 3 added no new reference to that gate outside the
one dormant-since-Batch-2 builder this file already accounted for.

Uses direct imports and module-source AST inspection - never brittle
raw-text search where a structural check is possible, matching the
established pattern from tests/unit/test_compound_isolation.py
(Phase 97).
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

_LIVE_RUNTIME_MODULES = (
    "intelligence/compound_structured_output.py",
    "intelligence/compound_grounding.py",
    "intelligence/structured_output.py",
    "intelligence/planning.py",
)

_NEW_BATCH1_MODULE_NAMES = frozenset({"compound_workflow_progress_store"})

#: Phase 98, Batch 3: the only two modules now legitimately importing
#: CompoundWorkflowProgressStore, and the only functions/methods within
#: them allowed to reference it or the store's own class name.
_BATCH3_PROGRESS_STORE_CONSUMERS = ("core/orchestrator.py", "main.py")

_ORCHESTRATOR_ALLOWED_PROGRESS_STORE_FUNCTIONS = frozenset(
    {
        "__init__",
        "validate_pending_approval_for_transition",
        "_claim_and_resume_workflow",
        "_compound_step_observer_for",
        "_start_compound_update_phase_and_show_workflow",
        "_terminalize_declined_compound_progress",
    }
)

_MAIN_ALLOWED_PROGRESS_STORE_FUNCTIONS = frozenset(
    {"build_orchestrator", "reconcile_claimed_handoffs"}
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


class TestNoLiveCompoundParserDispatch:
    def test_planning_module_does_not_import_new_progress_store(self) -> None:
        source = _module_source("intelligence/planning.py")
        referenced = _referenced_module_names(source)
        assert not (referenced & _NEW_BATCH1_MODULE_NAMES)

    def test_planning_module_source_has_no_compound_progress_reference(self) -> None:
        """Phase 98, Batch 1 built zero consumer of its own new
        verification-gate/progress foundations, so this test originally
        asserted planning.py referenced neither at all. Phase 98,
        Batch 2 (docs/phase_98_live_compound_reentry_plan.md,
        Foundation B) adds exactly one, dormant consumer:
        _build_phase_update_verify_show_workflow_plan(), a private
        helper never called by select_tool() or any other live entry
        point (see the companion test immediately below). Phase 99,
        Batch 1 adds a second, sibling dormant consumer,
        _build_schedule_enable_verify_show_workflow_plan(), for exactly
        the same reason (its own Step 3 needs the identical
        verification gate) - equally never called live (see
        test_phase99_batch1_isolation.py's own confinement proof). This
        test is updated, not weakened: it now proves the verification-
        gate reference is confined entirely to those two functions, and
        that CompoundWorkflowProgress itself is still never referenced
        by this module at all - progress persistence lives entirely in
        core/compound_workflow.py (ProjectState) and would live entirely
        in a future, separate schedule-specific store (Phase 99, Batch
        2+), never here."""
        source = _module_source("intelligence/planning.py")
        assert "CompoundWorkflowProgress" not in source

        tree = ast.parse(source)
        functions_referencing_gate: set[str] = set()
        for func_node in ast.walk(tree):
            if isinstance(func_node, ast.FunctionDef):
                segment = ast.get_source_segment(source, func_node) or ""
                if "requires_verified_predecessor" in segment:
                    functions_referencing_gate.add(func_node.name)

        assert functions_referencing_gate == {
            "_build_phase_update_verify_show_workflow_plan",
            "_build_schedule_enable_verify_show_workflow_plan",
        }

    def test_select_tool_never_calls_the_dormant_compound_plan_builder(self) -> None:
        """select_tool() is the one live entry point every "ask jarvis
        to:" request reaches; the dormant Batch 2 compound-plan builder
        must never be reachable from it (Foundation B's own "no live
        call site in Batch 2" requirement)."""
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

    def test_structured_output_unchanged_by_this_batch(self) -> None:
        source = _module_source("intelligence/structured_output.py")
        assert "requires_verified_predecessor" not in source
        assert "CompoundWorkflowProgress" not in source


class TestNoCompoundPlanConstruction:
    def test_compound_structured_output_does_not_import_new_progress_store(
        self,
    ) -> None:
        source = _module_source("intelligence/compound_structured_output.py")
        referenced = _referenced_module_names(source)
        assert not (referenced & _NEW_BATCH1_MODULE_NAMES)

    def test_compound_grounding_does_not_import_new_progress_store(self) -> None:
        source = _module_source("intelligence/compound_grounding.py")
        referenced = _referenced_module_names(source)
        assert not (referenced & _NEW_BATCH1_MODULE_NAMES)


class TestNoOrchestratorCompoundBranch:
    def test_orchestrator_imports_progress_store_only_for_compound_wiring(
        self,
    ) -> None:
        """Phase 98, Batch 3 activation: core/orchestrator.py now
        legitimately imports CompoundWorkflowProgressStore - but only
        as one of its Batch 3 compound-workflow collaborators, never
        as a general-purpose dependency injected elsewhere."""
        source = _module_source("core/orchestrator.py")
        referenced = _referenced_module_names(source)
        assert _NEW_BATCH1_MODULE_NAMES <= referenced

    def test_orchestrator_progress_reference_confined_to_named_methods(self) -> None:
        source = _module_source("core/orchestrator.py")
        hits = _functions_referencing(source, "CompoundWorkflowProgress")
        assert hits <= _ORCHESTRATOR_ALLOWED_PROGRESS_STORE_FUNCTIONS, (
            f"unexpected CompoundWorkflowProgress reference inside: "
            f"{hits - _ORCHESTRATOR_ALLOWED_PROGRESS_STORE_FUNCTIONS}"
        )
        # The PlanStep verification gate itself is still never
        # orchestrator.py's own concern - it is planning.py's fixed,
        # trusted plan-construction detail, and WorkflowEngine's own
        # internal gate check, never re-implemented or re-inspected here.
        assert "requires_verified_predecessor" not in source


class TestNoUserFacingExposure:
    def test_help_tool_has_no_gate_or_progress_reference(self) -> None:
        source = _module_source("tools/builtin/help_tool.py")
        assert "requires_verified_predecessor" not in source
        assert "CompoundWorkflowProgress" not in source
        assert "verification gate" not in source.casefold()

    def test_user_guide_has_no_gate_or_progress_reference(self) -> None:
        source = _module_source("docs/user_guide.md")
        assert "requires_verified_predecessor" not in source
        assert "CompoundWorkflowProgress" not in source

    def test_main_imports_progress_store_only_for_compound_wiring(self) -> None:
        """Phase 98, Batch 3 activation: main.py now legitimately
        imports CompoundWorkflowProgressStore inside build_orchestrator()
        (to construct the one real instance) and reconcile_claimed_
        handoffs() (compound-first startup recovery) - nowhere else."""
        source = _module_source("main.py")
        referenced = _referenced_module_names(source)
        assert _NEW_BATCH1_MODULE_NAMES <= referenced

        hits = _functions_referencing(source, "CompoundWorkflowProgress")
        assert hits <= _MAIN_ALLOWED_PROGRESS_STORE_FUNCTIONS, (
            f"unexpected CompoundWorkflowProgress reference inside: "
            f"{hits - _MAIN_ALLOWED_PROGRESS_STORE_FUNCTIONS}"
        )


class TestNoProductionCapabilityUsesNewMechanism:
    def test_capability_catalog_unchanged_by_this_batch(self) -> None:
        source = _module_source("intelligence/capability_catalog.py")
        assert "requires_verified_predecessor" not in source
        assert "CompoundWorkflowProgress" not in source


class TestStoreHasNoSideEffects:
    """The new store/reconciliation module itself never reaches into
    approval, execution, or tool machinery - proven via AST-based
    identifier detection (docstrings legitimately name these classes
    when explaining what is not done)."""

    def _identifiers(self) -> set[str]:
        source = _module_source(
            "workflow/compound_workflow_progress_store.py"
        )
        tree = ast.parse(source)
        identifiers: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
            elif isinstance(node, ast.Import):
                identifiers.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                identifiers.update(node.module.split("."))
        return identifiers

    def test_no_approval_or_tool_executor_call(self) -> None:
        identifiers = self._identifiers()
        assert "ApprovalManager" not in identifiers
        assert "ToolExecutor" not in identifiers
        assert "SecurityManager" not in identifiers

    def test_no_existing_production_capability_imports_new_module(self) -> None:
        for relative_path in _LIVE_RUNTIME_MODULES:
            source = _module_source(relative_path)
            referenced = _referenced_module_names(source)
            assert not (referenced & _NEW_BATCH1_MODULE_NAMES), (
                f"{relative_path} must not import compound_workflow_progress_store"
            )
