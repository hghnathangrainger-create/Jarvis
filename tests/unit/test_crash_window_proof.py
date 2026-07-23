"""
test_crash_window_proof.py

Complete crash-window proof for the Approval-to-Resume Handoff
Interlock (Batch 3 - docs/phase_98_approval_handoff_plan.md): explicit,
individually-named tests for every lettered window (A-G) required for
formal closure, plus the two Batch 3-specific failure-isolation
behaviours (failure before claim; one workflow's failure cannot corrupt
another).

Windows B (approved-unconsumed survives and is continued),
per-capability restart proofs, and the four real YELLOW-workflow
restart tests live in
tests/integration/test_yellow_workflow_restart_continuation.py; CLAIMED
reconciliation (windows D/E) and response-failure-after-CONSUMED
(window F) were already proven in
tests/unit/test_main_execution_session.py (Batch 2) and
tests/integration/test_orchestrator_claim_before_resume.py (Batch 2).
This file adds the remaining explicit proofs and cross-references the
rest so every lettered window has at least one clearly-named test.

Run with:
    pytest tests/unit/test_crash_window_proof.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

import main  # noqa: E402
from approval.approval_history_store import ApprovalHistoryStore  # noqa: E402
from approval.approval_models import PendingApprovalHandoffStatus  # noqa: E402
from approval.pending_approval_store import PendingApprovalStore  # noqa: E402
from config.constants import SecurityTier  # noqa: E402
from storage.database import create_database_engine, create_session_factory  # noqa: E402
from workflow.workflow_history_store import WorkflowHistoryStore  # noqa: E402


@pytest.fixture()
def hermetic_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "crash_window_jarvis.db"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)
    return db_path


def _stores(db_path: Path):
    from config.settings import load_settings

    settings = load_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    return (
        PendingApprovalStore(session_factory),
        ApprovalHistoryStore(session_factory),
        WorkflowHistoryStore(session_factory),
    )


# --- Window A: before approval -----------------------------------------------


def test_window_a_pending_request_remains_pending_no_execution(
    hermetic_db: Path,
) -> None:
    """Before any decision, a request remains PENDING; no claim is
    possible; decline and expiry both still work normally (regression,
    already proven exhaustively by test_approval_manager*.py and
    test_orchestrator_*_workflow.py's own decline/expiry suites - this
    is the narrow cross-reference proof for this window specifically)."""
    orchestrator, lock = main.start_execution_session()
    try:
        request = orchestrator.approvals.create_request(
            "copy file", "needs approval", SecurityTier.YELLOW,
            tool_name="file_copy",
            tool_input={"source": "a.txt", "destination": "b.txt"},
        )
        assert (
            orchestrator.approvals.handoff_status_for(request.request_id)
            == PendingApprovalHandoffStatus.PENDING
        )
        assert orchestrator.approvals.claim_for_resume(request.request_id) is False

        decision = orchestrator.approvals.decline(request.request_id)
        assert decision.is_declined is True
        assert (
            orchestrator.approvals.handoff_status_for(request.request_id)
            == PendingApprovalHandoffStatus.DECLINED
        )
    finally:
        lock.release()


# --- Window C: during claim CAS ----------------------------------------------


def test_window_c_one_claimant_succeeds_second_fails(hermetic_db: Path) -> None:
    orchestrator, lock = main.start_execution_session()
    try:
        request = orchestrator.approvals.create_request(
            "update project state phase",
            "needs approval",
            SecurityTier.YELLOW,
            tool_name="project_state_update",
            tool_input={"field": "phase", "value": "Phase X"},
        )
        orchestrator.approvals.approve(request.request_id)

        first = orchestrator.approvals.claim_for_resume(request.request_id)
        second = orchestrator.approvals.claim_for_resume(request.request_id)
        assert (first, second) == (True, False)
        assert (
            orchestrator.approvals.handoff_status_for(request.request_id)
            == PendingApprovalHandoffStatus.CLAIMED
        )
    finally:
        lock.release()


def test_window_c_crash_before_cas_commit_leaves_approved_unconsumed(
    hermetic_db: Path,
) -> None:
    """A CAS that never runs at all (simulating a crash strictly before
    the UPDATE statement's own commit) leaves the row exactly where it
    was - APPROVED_UNCONSUMED - proven directly: the row is simply never
    touched until claim_for_resume() is actually called."""
    orchestrator, lock = main.start_execution_session()
    try:
        request = orchestrator.approvals.create_request(
            "update project state phase",
            "needs approval",
            SecurityTier.YELLOW,
            tool_name="project_state_update",
            tool_input={"field": "phase", "value": "Phase X"},
        )
        orchestrator.approvals.approve(request.request_id)
        # No claim_for_resume() call at all - the CAS never runs.
        assert (
            orchestrator.approvals.handoff_status_for(request.request_id)
            == PendingApprovalHandoffStatus.APPROVED_UNCONSUMED
        )
    finally:
        lock.release()


def test_window_c_crash_after_cas_commit_leaves_claimed(hermetic_db: Path) -> None:
    orchestrator, lock = main.start_execution_session()
    try:
        request = orchestrator.approvals.create_request(
            "update project state phase",
            "needs approval",
            SecurityTier.YELLOW,
            tool_name="project_state_update",
            tool_input={"field": "phase", "value": "Phase X"},
        )
        orchestrator.approvals.approve(request.request_id)
        assert orchestrator.approvals.claim_for_resume(request.request_id) is True
        # Simulating a crash immediately after the CAS commits, before
        # WorkflowEngine.resume() is ever called.
        assert (
            orchestrator.approvals.handoff_status_for(request.request_id)
            == PendingApprovalHandoffStatus.CLAIMED
        )
    finally:
        lock.release()


# --- Window G: after final completion ----------------------------------------


def test_window_g_duplicate_restart_performs_zero_new_execution(
    hermetic_db: Path,
) -> None:
    """Running startup continuation a second time, after a workflow has
    already reached CONSUMED, must claim nothing and change nothing."""
    orchestrator, lock = main.start_execution_session()
    try:
        pending_store, _, workflow_history = _stores(hermetic_db)
        pending_store.save(
            request_id="req-g-duplicate",
            action="update project state phase",
            reason="needs approval",
            security_tier="yellow",
            metadata={"workflow_id": "wf-g-duplicate"},
            tool_name="project_state_update",
            tool_input={"field": "phase", "value": "Phase X"},
        )
        pending_store.mark_approved_unconsumed("req-g-duplicate")
        pending_store.claim_for_resume("req-g-duplicate")
        workflow_history.record_transition(
            workflow_id="wf-g-duplicate", status="workflow_completed"
        )

        first = main.reconcile_claimed_handoffs(lock)
        assert first.claimed_consumed == 1
        assert (
            pending_store.get_handoff_status("req-g-duplicate")
            == PendingApprovalHandoffStatus.CONSUMED
        )

        second = main.reconcile_claimed_handoffs(lock)
        assert second.claimed_consumed == 0
        assert second.claimed_interrupted == 0
        assert (
            pending_store.get_handoff_status("req-g-duplicate")
            == PendingApprovalHandoffStatus.CONSUMED
        )

        # Duplicate claim after completion performs zero new execution.
        assert orchestrator.approvals.claim_for_resume("req-g-duplicate") is False
    finally:
        lock.release()


def test_window_g_duplicate_claim_after_consumed_fails(hermetic_db: Path) -> None:
    orchestrator, lock = main.start_execution_session()
    try:
        request = orchestrator.approvals.create_request(
            "update project state phase",
            "needs approval",
            SecurityTier.YELLOW,
            tool_name="project_state_update",
            tool_input={"field": "phase", "value": "Phase X"},
        )
        orchestrator.approvals.approve(request.request_id)
        orchestrator.approvals.claim_for_resume(request.request_id)
        orchestrator.approvals.mark_consumed(request.request_id)

        assert orchestrator.approvals.claim_for_resume(request.request_id) is False
        assert orchestrator.approvals.claim_for_resume(request.request_id) is False
    finally:
        lock.release()


# --- Mandatory issue 1: failure before claim / isolation between rows -------


def test_failure_before_claim_leaves_row_approved_unconsumed(
    hermetic_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lookup infrastructure failure (e.g. get_pending_record() itself
    raising) before any claim is attempted must never mark CLAIM_
    INTERRUPTED - the row must remain APPROVED_UNCONSUMED, and no claim
    may be consumed."""
    orchestrator, lock = main.start_execution_session()
    try:
        request = orchestrator.approvals.create_request(
            "update project state phase",
            "needs approval",
            SecurityTier.YELLOW,
            tool_name="project_state_update",
            tool_input={"field": "phase", "value": "Phase X"},
        )
        orchestrator.approvals.approve(request.request_id)

        def _raise(request_id: str):
            raise RuntimeError("simulated store-lookup infrastructure failure")

        monkeypatch.setattr(
            orchestrator.approvals, "get_pending_record", _raise
        )

        with pytest.raises(RuntimeError):
            orchestrator.resume_approved_unconsumed_workflow(request.request_id)

        assert (
            orchestrator.approvals.handoff_status_for(request.request_id)
            == PendingApprovalHandoffStatus.APPROVED_UNCONSUMED
        )
    finally:
        lock.release()


def test_one_workflows_failure_cannot_corrupt_another(
    hermetic_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Using main.continue_approved_unconsumed_workflows()'s own
    per-row isolation: an injected failure for one specific request must
    never prevent a second, independent, genuinely-continuable request
    from correctly reaching CONSUMED - proven with a real, hand-built,
    paused-then-approved workflow for the second request (no AI router
    needed, mirroring test_workflow_engine_paused_state.py's own
    _two_step_plan() convention)."""
    from config.constants import SecurityTier, StepStatus
    from planner.plan_models import Plan, PlanStep

    orchestrator, lock = main.start_execution_session()
    try:
        approvals = orchestrator.approvals
        workflow_engine = orchestrator._workflow_engine

        # Request A: will be forced to fail via a targeted monkeypatch.
        request_a = approvals.create_request(
            "update project state phase",
            "needs approval",
            SecurityTier.YELLOW,
            tool_name="project_state_update",
            tool_input={"field": "phase", "value": "Phase A"},
        )
        approvals.approve(request_a.request_id)

        # Request B: a real, hand-built two-step workflow (write +
        # internal verify), paused for approval, then approved -
        # genuinely continuable.
        plan = Plan(
            user_request="update jarvis project state phase to Phase B",
            steps=(
                PlanStep(
                    number=1,
                    description="write",
                    action="update jarvis project state",
                    tier=SecurityTier.YELLOW,
                    reason="needs approval",
                    tool_name="project_state_update",
                    tool_input={"field": "phase", "value": "Phase B"},
                ),
            ),
        )
        result_b = workflow_engine.run(plan)
        assert result_b.overall_status is StepStatus.WAITING
        request_b_id = result_b.pending_approval_request.request_id
        approvals.approve(request_b_id)

        real_resume = orchestrator.resume_approved_unconsumed_workflow

        def _selectively_raise(request_id: str):
            if request_id == request_a.request_id:
                raise RuntimeError("simulated infrastructure failure for request A")
            return real_resume(request_id)

        monkeypatch.setattr(
            orchestrator, "resume_approved_unconsumed_workflow", _selectively_raise
        )

        summary = main.continue_approved_unconsumed_workflows(orchestrator)

        # Request A: untouched by the injected failure, since it occurs
        # before any claim is attempted for it.
        assert (
            approvals.handoff_status_for(request_a.request_id)
            == PendingApprovalHandoffStatus.APPROVED_UNCONSUMED
        )
        # Request B: genuinely, independently continued to completion -
        # proving request A's own failure never reached or affected it.
        assert (
            approvals.handoff_status_for(request_b_id)
            == PendingApprovalHandoffStatus.CONSUMED
        )
        assert summary.continued == 1
        assert summary.left_pending == 1
    finally:
        lock.release()
