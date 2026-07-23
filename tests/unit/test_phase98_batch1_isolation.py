"""
test_phase98_batch1_isolation.py

Structural proof that Phase 98 Batch 1's two new foundations (the
PlanStep verification gate and CompoundWorkflowProgressStore) add zero
live compound wiring and zero user-visible behavior
(docs/phase_98_implementation_plan.md).

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
    "core/orchestrator.py",
    "main.py",
)

_NEW_BATCH1_MODULE_NAMES = frozenset({"compound_workflow_progress_store"})


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
        source = _module_source("intelligence/planning.py")
        assert "CompoundWorkflowProgress" not in source
        assert "requires_verified_predecessor" not in source

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
    def test_orchestrator_does_not_import_new_progress_store(self) -> None:
        source = _module_source("core/orchestrator.py")
        referenced = _referenced_module_names(source)
        assert not (referenced & _NEW_BATCH1_MODULE_NAMES)

    def test_orchestrator_source_has_no_compound_progress_reference(self) -> None:
        source = _module_source("core/orchestrator.py")
        assert "CompoundWorkflowProgress" not in source
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

    def test_main_does_not_import_new_progress_store(self) -> None:
        source = _module_source("main.py")
        referenced = _referenced_module_names(source)
        assert not (referenced & _NEW_BATCH1_MODULE_NAMES)


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
