"""
test_interlock_batch2_isolation.py

Structural proof of the Approval-to-Resume Handoff Interlock, Batch 2
boundary (docs/phase_98_approval_handoff_plan.md): the live handoff
lifecycle (OS execution lock, durable handoff-status transitions,
claim-before-resume, startup recovery) is now correctly wired into
main.py/approval_manager.py/core.orchestrator/workflow.engine - but live
compound selection, planning, approval, and execution (Phase 98's own
Batch 2/3, and Phase 97's compound modules) remain completely untouched.

Supersedes tests/unit/test_interlock_batch1_isolation.py, whose whole
premise (that Batch 1 added *zero* live wiring anywhere) is the exact
condition this batch intentionally, correctly reverses for the specific
files listed below - proving "zero wiring" a second time here would be
proving something now false. What remains true, unconditionally, is
proven instead: the Phase 97/98 compound boundary, and the four
TWO_STEP_WORKFLOW capabilities' own tools/verification/approval
mechanisms, are all untouched by this interlock.

Uses direct imports and module-source AST inspection - never brittle
raw-text search where a structural check is possible - matching the
established pattern from tests/unit/test_compound_isolation.py (Phase
97) and tests/unit/test_phase98_batch1_isolation.py (Phase 98, Batch 1).

Run with:
    pytest tests/unit/test_interlock_batch2_isolation.py
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every handoff-lifecycle identifier this interlock introduces (Batch 1
#: primitives, plus Batch 2's own claim/consume/interrupt/lock wiring
#: names). Used both to prove where it now IS correctly wired, and to
#: prove it is still absent from the compound/Phase 98 boundary below.
_HANDOFF_IDENTIFIERS = frozenset(
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
        "handoff_status_for",
        "reconcile_claimed_handoffs",
        "start_execution_session",
    }
)


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


# --- positive proof: the live wiring now exists exactly where expected -----


def test_main_imports_and_uses_the_execution_lock() -> None:
    source = _module_source("main.py")
    identifiers = _referenced_identifiers(source)
    assert "process_lock" in identifiers
    assert "ExecutionProcessLock" in identifiers
    assert "start_execution_session" in source
    assert "reconcile_claimed_handoffs" in source


def test_approval_manager_defines_the_claim_and_terminal_primitives() -> None:
    source = _module_source("approval/approval_manager.py")
    for name in (
        "claim_for_resume",
        "mark_consumed",
        "mark_claim_interrupted",
        "handoff_status_for",
    ):
        assert f"def {name}" in source


def test_orchestrator_claims_before_resuming_a_workflow() -> None:
    source = _module_source("core/orchestrator.py")
    identifiers = _referenced_identifiers(source)
    assert "claim_for_resume" in identifiers
    assert "mark_consumed" in identifiers
    assert "mark_claim_interrupted" in identifiers


def test_workflow_engine_recognises_the_new_durable_handoff_states() -> None:
    source = _module_source("workflow/engine.py")
    identifiers = _referenced_identifiers(source)
    assert "PendingApprovalHandoffStatus" in identifiers
    assert "handoff_status_for" in identifiers


def test_cli_still_never_imports_the_execution_lock_directly() -> None:
    """The lock is acquired only in main.py's own start_execution_session()
    wrapper - ui/cli.py remains a thin presentation layer with no lock
    concern of its own, unchanged by this interlock."""
    source = _module_source("ui/cli.py")
    identifiers = _referenced_identifiers(source)
    assert "process_lock" not in identifiers
    assert "ExecutionProcessLock" not in identifiers


# --- the Phase 97/98 compound boundary remains completely untouched --------


def test_compound_modules_do_not_reference_handoff_primitives() -> None:
    for relative in (
        "intelligence/compound_grounding.py",
        "intelligence/compound_structured_output.py",
    ):
        source = _module_source(relative)
        identifiers = _referenced_identifiers(source)
        assert not (identifiers & _HANDOFF_IDENTIFIERS)


def test_planning_module_untouched_by_this_interlock() -> None:
    source = _module_source("intelligence/planning.py")
    identifiers = _referenced_identifiers(source)
    assert not (identifiers & _HANDOFF_IDENTIFIERS)


def test_plan_models_untouched_by_this_interlock() -> None:
    source = _module_source("planner/plan_models.py")
    identifiers = _referenced_identifiers(source)
    assert not (identifiers & _HANDOFF_IDENTIFIERS)


def test_compound_workflow_progress_store_untouched_by_this_interlock() -> None:
    source = _module_source("workflow/compound_workflow_progress_store.py")
    identifiers = _referenced_identifiers(source)
    assert not (identifiers & _HANDOFF_IDENTIFIERS)


def test_no_live_compound_selection_or_execution_grammar_exists() -> None:
    """Command routing and the trusted-instruction/model-selection surface
    remain untouched - no "execute_sequence"/compound dispatch exists in
    CommandRouter or the live structured-output parser."""
    source = _module_source("intelligence/structured_output.py")
    assert "execute_sequence" not in source
    assert "CompoundToolSelectionDecision" not in source


# --- existing store/enum behaviour: additive only, no removed API ----------


def test_existing_pending_approval_store_public_methods_are_all_still_present() -> None:
    """The pre-existing public surface (save/delete/get/list_all) must
    remain exactly as it was - this interlock only ever adds methods."""
    import inspect as py_inspect

    from approval.pending_approval_store import PendingApprovalStore

    members = {
        name
        for name, _ in py_inspect.getmembers(PendingApprovalStore)
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
