"""
test_interlock_batch1_isolation.py

Structural proof that the Approval-to-Resume Handoff Interlock, Batch 1
(runtime/process_lock.py's ExecutionProcessLock; the new
PendingApprovalHandoffStatus enum, handoff_status column, and
PendingApprovalStore CAS primitives) adds zero live wiring:
no startup lock acquisition, no ApprovalManager/orchestrator lifecycle
change, no startup recovery, no CLAIMED reconciliation, and no live
compound wiring (docs/phase_98_approval_handoff_plan.md, Section 15 -
"No ApprovalManager/orchestrator change yet; no main.py wiring yet").

Uses direct imports and module-source AST inspection - never brittle
raw-text search where a structural check is possible - matching the
established pattern from tests/unit/test_compound_isolation.py (Phase
97) and tests/unit/test_phase98_batch1_isolation.py (Phase 98, Batch 1).

Run with:
    pytest tests/unit/test_interlock_batch1_isolation.py
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every new identifier this batch introduces. None of them may be
#: referenced by any live production module outside the files this
#: batch itself adds/modifies.
_NEW_BATCH1_IDENTIFIERS = frozenset(
    {
        "ExecutionProcessLock",
        "ExecutionLockError",
        "InMemoryDatabaseLockError",
        "canonical_database_path",
        "lock_path_for",
        "PendingApprovalHandoffStatus",
        "mark_approved_unconsumed",
        "claim_for_resume",
        "mark_consumed",
        "mark_claim_interrupted",
        "mark_declined",
        "mark_expired",
        "get_handoff_status",
        "list_by_handoff_status",
    }
)

#: Names that would signal live recovery/reconciliation wiring, even
#: though the underlying functions do not exist yet in Batch 1 - a
#: guard against a future accidental reference before that batch is
#: accepted.
_FUTURE_BATCH_ONLY_NAMES = frozenset(
    {"start_execution_session", "reconcile_claimed_handoffs"}
)

#: Files this batch itself adds or modifies - the only files permitted
#: to reference the new identifiers above.
_BATCH1_OWN_FILES = frozenset(
    {
        "runtime/__init__.py",
        "runtime/process_lock.py",
        "approval/approval_models.py",
        "approval/pending_approval_store.py",
        "storage/models.py",
        "storage/database.py",
    }
)

#: Every live production entry point/module this batch must leave
#: completely untouched in behavior - checked individually, by name,
#: for the clearest possible failure message.
_LIVE_PRODUCTION_MODULES = (
    "main.py",
    "ui/cli.py",
    "core/orchestrator.py",
    "approval/approval_manager.py",
    "workflow/engine.py",
    "workflow/paused_workflow_store.py",
    "workflow/workflow_history_store.py",
    "workflow/compound_workflow_progress_store.py",
    "planner/plan_models.py",
    "intelligence/compound_grounding.py",
    "intelligence/compound_structured_output.py",
    "intelligence/planning.py",
    "intelligence/structured_output.py",
)

#: Every tracked, non-test .py file in the repository, for the
#: repo-wide sweep (excluding tests/, this file's own package, and
#: cache/build directories).
_EXCLUDED_DIR_PARTS = {"tests", "__pycache__", ".git", ".venv"}


def _all_production_py_files() -> list[Path]:
    files = []
    for path in _REPO_ROOT.rglob("*.py"):
        relative_parts = path.relative_to(_REPO_ROOT).parts
        if any(part in _EXCLUDED_DIR_PARTS for part in relative_parts):
            continue
        files.append(path)
    return files


def _module_source(relative_path: str) -> str:
    return (_REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _referenced_identifiers(source: str) -> set[str]:
    tree = ast.parse(source)
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.Import):
            identifiers.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            identifiers.update(node.module.split("."))
    return identifiers


# --- 36. OS lock is not wired into live CLI yet ------------------------------


def test_main_does_not_import_process_lock() -> None:
    source = _module_source("main.py")
    identifiers = _referenced_identifiers(source)
    assert "process_lock" not in identifiers
    assert "ExecutionProcessLock" not in identifiers
    assert "runtime" not in identifiers


def test_cli_does_not_import_process_lock() -> None:
    source = _module_source("ui/cli.py")
    identifiers = _referenced_identifiers(source)
    assert "process_lock" not in identifiers
    assert "ExecutionProcessLock" not in identifiers


# --- 37. ApprovalManager lifecycle is unchanged ------------------------------


def test_approval_manager_does_not_reference_handoff_primitives() -> None:
    source = _module_source("approval/approval_manager.py")
    identifiers = _referenced_identifiers(source)
    assert not (identifiers & _NEW_BATCH1_IDENTIFIERS)
    assert "handoff_status" not in source


# --- 38. Orchestrator resume behavior is unchanged ---------------------------


def test_orchestrator_does_not_reference_handoff_primitives_or_lock() -> None:
    source = _module_source("core/orchestrator.py")
    identifiers = _referenced_identifiers(source)
    assert not (identifiers & _NEW_BATCH1_IDENTIFIERS)
    assert "ExecutionProcessLock" not in identifiers
    assert "handoff_status" not in source


# --- 39. No startup recovery runs yet ----------------------------------------


def test_main_does_not_reference_future_batch_recovery_names() -> None:
    source = _module_source("main.py")
    identifiers = _referenced_identifiers(source)
    assert not (identifiers & _FUTURE_BATCH_ONLY_NAMES)
    for name in _FUTURE_BATCH_ONLY_NAMES:
        assert name not in source


def test_future_batch_only_names_are_not_defined_anywhere_yet() -> None:
    """start_execution_session()/reconcile_claimed_handoffs() are
    Batch 3/2 deliverables (per the plan's own final batch structure) -
    neither may exist as a real, callable definition yet."""
    for path in _all_production_py_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        defined_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not (defined_names & _FUTURE_BATCH_ONLY_NAMES), (
            f"{path.relative_to(_REPO_ROOT)} must not yet define "
            f"{defined_names & _FUTURE_BATCH_ONLY_NAMES}"
        )


# --- 40. No CLAIMED reconciliation runs yet ----------------------------------


def test_no_live_module_calls_the_new_cas_or_lock_primitives() -> None:
    """Every reference to a Batch 1 identifier anywhere in the
    repository's production code must live inside the files this batch
    itself owns - proving nothing else has started calling them yet."""
    for path in _all_production_py_files():
        relative = path.relative_to(_REPO_ROOT).as_posix()
        if relative in _BATCH1_OWN_FILES:
            continue
        source = path.read_text(encoding="utf-8")
        identifiers = _referenced_identifiers(source)
        found = identifiers & _NEW_BATCH1_IDENTIFIERS
        assert not found, f"{relative} must not reference {found} in Batch 1"


# --- 41. No live compound wiring exists (Phase 97/98 boundary unchanged) ----


def test_compound_modules_do_not_reference_new_lock_or_handoff_primitives() -> None:
    for relative in (
        "intelligence/compound_grounding.py",
        "intelligence/compound_structured_output.py",
    ):
        source = _module_source(relative)
        identifiers = _referenced_identifiers(source)
        assert not (identifiers & _NEW_BATCH1_IDENTIFIERS)


def test_planning_module_untouched_by_this_batch() -> None:
    source = _module_source("intelligence/planning.py")
    identifiers = _referenced_identifiers(source)
    assert not (identifiers & _NEW_BATCH1_IDENTIFIERS)


# --- 42. Phase 98 Batch 1 verification/progress foundation is unchanged -----


def test_plan_models_untouched_by_this_batch() -> None:
    source = _module_source("planner/plan_models.py")
    identifiers = _referenced_identifiers(source)
    assert not (identifiers & _NEW_BATCH1_IDENTIFIERS)
    assert "handoff_status" not in source


def test_compound_workflow_progress_store_untouched_by_this_batch() -> None:
    source = _module_source("workflow/compound_workflow_progress_store.py")
    identifiers = _referenced_identifiers(source)
    assert not (identifiers & _NEW_BATCH1_IDENTIFIERS)


def test_workflow_engine_untouched_by_this_batch() -> None:
    source = _module_source("workflow/engine.py")
    identifiers = _referenced_identifiers(source)
    assert not (identifiers & _NEW_BATCH1_IDENTIFIERS)
    assert "ExecutionProcessLock" not in identifiers


# --- existing store behavior: additive column only, no removed API ----------


def test_existing_pending_approval_store_public_methods_are_all_still_present() -> None:
    """The pre-existing public surface (save/delete/get/list_all) must
    remain exactly as it was - this batch only ever adds methods."""
    import inspect as py_inspect

    from approval.pending_approval_store import PendingApprovalStore

    members = {
        name for name, _ in py_inspect.getmembers(PendingApprovalStore)
        if not name.startswith("_")
    }
    assert {"save", "delete", "get", "list_all"} <= members


def test_approval_status_enum_values_are_unchanged() -> None:
    """ApprovalStatus (the decision lifecycle) must keep its exact,
    original four values - PendingApprovalHandoffStatus is a wholly
    separate, additive enum, never a replacement."""
    from approval.approval_models import ApprovalStatus

    assert {member.value for member in ApprovalStatus} == {
        "pending",
        "approved",
        "declined",
        "expired",
    }
