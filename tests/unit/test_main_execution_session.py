"""
test_main_execution_session.py

Unit tests for main.start_execution_session()/reconcile_claimed_handoffs()
(Approval-to-Resume Handoff Interlock, Batch 2 -
docs/phase_98_approval_handoff_plan.md): live OS-lock wiring, lock
lifetime/failure behaviour, and exclusive startup recovery (approval-
history consistency repair and inherited-CLAIMED reconciliation).

Uses real tmp_path-backed SQLite databases (never :memory:, since the
execution lock requires a real file) and calls main's own functions
directly - the underlying OS-lock mechanism itself was already proven
against real subprocesses in Interlock Batch 1
(tests/integration/test_process_lock_subprocess.py); this file proves
the *wiring* around it.

Run with:
    pytest tests/unit/test_main_execution_session.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

import main  # noqa: E402
from approval.approval_history_store import ApprovalHistoryStore  # noqa: E402
from approval.approval_models import PendingApprovalHandoffStatus  # noqa: E402
from approval.pending_approval_store import PendingApprovalStore  # noqa: E402
from runtime.process_lock import ExecutionProcessLock  # noqa: E402
from storage.database import create_database_engine, create_session_factory  # noqa: E402
from workflow.workflow_history_store import WorkflowHistoryStore  # noqa: E402


@pytest.fixture()
def hermetic_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "shared_test_jarvis.db"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)
    return db_path


def _stores(db_path: Path) -> tuple[PendingApprovalStore, ApprovalHistoryStore, WorkflowHistoryStore]:
    from config.settings import load_settings

    settings = load_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    return (
        PendingApprovalStore(session_factory),
        ApprovalHistoryStore(session_factory),
        WorkflowHistoryStore(session_factory),
    )


# --- 1-4: acquisition order, lifetime, failure release -----------------------


def test_start_execution_session_acquires_the_lock(hermetic_db: Path) -> None:
    orchestrator, lock = main.start_execution_session()
    try:
        assert lock.is_acquired is True
        assert orchestrator is not None
    finally:
        lock.release()


def test_lock_remains_held_across_recovery_and_is_releasable_after(
    hermetic_db: Path,
) -> None:
    orchestrator, lock = main.start_execution_session()
    assert lock.is_acquired is True
    lock.release()
    assert lock.is_acquired is False

    # A fresh attempt must now succeed - proving release genuinely dropped
    # the OS lock, not merely flipped an internal flag.
    second_lock = ExecutionProcessLock(lock.database_path)
    second_lock.acquire()
    second_lock.release()


def test_build_orchestrator_failure_releases_the_lock(
    hermetic_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise() -> None:
        raise RuntimeError("simulated startup failure")

    monkeypatch.setattr(main, "build_orchestrator", _raise)

    with pytest.raises(RuntimeError, match="simulated startup failure"):
        main.start_execution_session()

    # The lock must have been released - a fresh acquisition must succeed.
    from config.settings import load_settings

    settings = load_settings()
    fresh_lock = ExecutionProcessLock(settings.database_path)
    fresh_lock.acquire()
    fresh_lock.release()


def test_main_releases_the_lock_when_cli_run_raises(
    hermetic_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ui.cli import JarvisCLI

    def _raising_run(self) -> None:
        raise RuntimeError("simulated CLI crash")

    monkeypatch.setattr(JarvisCLI, "run", _raising_run)

    with pytest.raises(RuntimeError, match="simulated CLI crash"):
        main.main(argv=[])

    from config.settings import load_settings

    settings = load_settings()
    fresh_lock = ExecutionProcessLock(settings.database_path)
    fresh_lock.acquire()
    fresh_lock.release()


# --- 5: second CLI performs no recovery or mutation --------------------------


def test_second_start_execution_session_is_rejected_and_mutates_nothing(
    hermetic_db: Path,
) -> None:
    holder = ExecutionProcessLock(hermetic_db)
    holder.acquire()
    try:
        with pytest.raises(main.AlreadyRunningError):
            main.start_execution_session()
    finally:
        holder.release()

    # Nothing was initialized - the database file was never even created
    # by the rejected attempt (holder itself never touched it either).
    assert not hermetic_db.exists()


def test_main_prints_honest_message_and_returns_when_already_running(
    hermetic_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    holder = ExecutionProcessLock(hermetic_db)
    holder.acquire()
    try:
        main.main(argv=[])  # must not raise, must not start a CLI loop
    finally:
        holder.release()

    captured = capsys.readouterr()
    assert "already" in captured.out.lower()
    assert "running" in captured.out.lower()


# --- 6-7: dashboard/scheduler boundaries (documentation-proof) ---------------


def test_dashboard_module_never_imports_the_execution_lock() -> None:
    source = Path("dashboard.py").read_text(encoding="utf-8")
    assert "process_lock" not in source
    assert "ExecutionProcessLock" not in source


def test_scheduler_module_never_imports_the_execution_lock() -> None:
    """Documents the disclosed Batch 2 limitation truthfully: the
    scheduler is a separate execution-capable process that does not
    participate in this interlock's lock - concurrent scheduler + CLI
    use of the same database remains explicitly unsupported, not
    falsely covered."""
    source = Path("scheduler.py").read_text(encoding="utf-8")
    assert "process_lock" not in source
    assert "ExecutionProcessLock" not in source


# --- startup recovery: approval-history consistency repair -------------------


def test_repair_backfills_missing_history_row(hermetic_db: Path) -> None:
    orchestrator, lock = main.start_execution_session()
    pending_store, history_store, _ = _stores(hermetic_db)
    try:
        pending_store.save(
            request_id="req-missing-history",
            action="copy file",
            reason="needs approval",
            security_tier="yellow",
        )
        assert history_store.get("req-missing-history") is None

        summary = main.reconcile_claimed_handoffs(lock)
        assert summary.history_repaired >= 1
        entry = history_store.get("req-missing-history")
        assert entry is not None
        assert entry.status == "pending"
    finally:
        lock.release()


def test_repair_backfills_missing_decision_without_overwriting_correct_ones(
    hermetic_db: Path,
) -> None:
    orchestrator, lock = main.start_execution_session()
    pending_store, history_store, _ = _stores(hermetic_db)
    try:
        pending_store.save(
            request_id="req-approved-no-decision",
            action="copy file",
            reason="needs approval",
            security_tier="yellow",
        )
        pending_store.mark_approved_unconsumed("req-approved-no-decision")
        # Simulate the base "pending" history row existing (as
        # create_request() always writes) but the decision write having
        # failed at the time it was approved.
        history_store.record_request(
            request_id="req-approved-no-decision",
            action="copy file",
            reason="needs approval",
            security_tier="yellow",
        )

        summary = main.reconcile_claimed_handoffs(lock)
        assert summary.history_repaired >= 1
        entry = history_store.get("req-approved-no-decision")
        assert entry is not None
        assert entry.status == "approved"
        assert entry.decided_by == "system_repair"

        # Repeating repair must not contradict the now-correct record.
        main.reconcile_claimed_handoffs(lock)
        entry_again = history_store.get("req-approved-no-decision")
        assert entry_again.status == "approved"
        assert entry_again.decided_by == "system_repair"
    finally:
        lock.release()


def test_repair_does_not_touch_an_already_decided_history_row(
    hermetic_db: Path,
) -> None:
    orchestrator, lock = main.start_execution_session()
    pending_store, history_store, _ = _stores(hermetic_db)
    try:
        pending_store.save(
            request_id="req-live-decided",
            action="copy file",
            reason="needs approval",
            security_tier="yellow",
        )
        pending_store.mark_approved_unconsumed("req-live-decided")
        history_store.record_request(
            request_id="req-live-decided",
            action="copy file",
            reason="needs approval",
            security_tier="yellow",
        )
        from datetime import datetime, timezone

        history_store.record_decision(
            request_id="req-live-decided",
            approved=True,
            decided_by="user",
            decided_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            reason="Looks good.",
        )

        main.reconcile_claimed_handoffs(lock)

        entry = history_store.get("req-live-decided")
        assert entry.decided_by == "user"
        assert entry.decision_reason == "Looks good."
    finally:
        lock.release()


# --- startup recovery: CLAIMED reconciliation --------------------------------


def _make_claimed_row(
    pending_store: PendingApprovalStore, request_id: str, workflow_id: str
) -> None:
    pending_store.save(
        request_id=request_id,
        action="update project state phase",
        reason="needs approval",
        security_tier="yellow",
        metadata={"workflow_id": workflow_id},
        tool_name="project_state_update",
        tool_input={"field": "phase", "value": "Phase 99"},
    )
    pending_store.mark_approved_unconsumed(request_id)
    pending_store.claim_for_resume(request_id)


def test_claimed_with_workflow_completed_becomes_consumed(hermetic_db: Path) -> None:
    orchestrator, lock = main.start_execution_session()
    pending_store, history_store, workflow_history = _stores(hermetic_db)
    try:
        _make_claimed_row(pending_store, "req-a", "wf-completed")
        workflow_history.record_transition(
            workflow_id="wf-completed", status="workflow_started"
        )
        workflow_history.record_transition(
            workflow_id="wf-completed", status="workflow_completed"
        )

        summary = main.reconcile_claimed_handoffs(lock)
        assert summary.claimed_consumed == 1
        assert summary.claimed_interrupted == 0
        assert (
            pending_store.get_handoff_status("req-a")
            == PendingApprovalHandoffStatus.CONSUMED
        )
    finally:
        lock.release()


def test_claimed_with_workflow_stopped_becomes_consumed(hermetic_db: Path) -> None:
    orchestrator, lock = main.start_execution_session()
    pending_store, history_store, workflow_history = _stores(hermetic_db)
    try:
        _make_claimed_row(pending_store, "req-b", "wf-stopped")
        workflow_history.record_transition(
            workflow_id="wf-stopped", status="workflow_stopped"
        )

        summary = main.reconcile_claimed_handoffs(lock)
        assert summary.claimed_consumed == 1
        assert (
            pending_store.get_handoff_status("req-b")
            == PendingApprovalHandoffStatus.CONSUMED
        )
    finally:
        lock.release()


def test_non_terminal_history_does_not_reconcile_to_consumed(
    hermetic_db: Path,
) -> None:
    orchestrator, lock = main.start_execution_session()
    pending_store, history_store, workflow_history = _stores(hermetic_db)
    try:
        _make_claimed_row(pending_store, "req-c", "wf-mid-flight")
        workflow_history.record_transition(
            workflow_id="wf-mid-flight", status="workflow_started"
        )
        workflow_history.record_transition(
            workflow_id="wf-mid-flight", status="workflow_step_started"
        )

        summary = main.reconcile_claimed_handoffs(lock)
        assert summary.claimed_consumed == 0
        assert summary.claimed_interrupted == 1
        assert (
            pending_store.get_handoff_status("req-c")
            == PendingApprovalHandoffStatus.CLAIM_INTERRUPTED
        )
    finally:
        lock.release()


def test_missing_terminal_history_produces_claim_interrupted(
    hermetic_db: Path,
) -> None:
    orchestrator, lock = main.start_execution_session()
    pending_store, history_store, workflow_history = _stores(hermetic_db)
    try:
        _make_claimed_row(pending_store, "req-d", "wf-no-history-at-all")

        summary = main.reconcile_claimed_handoffs(lock)
        assert summary.claimed_interrupted == 1
        assert (
            pending_store.get_handoff_status("req-d")
            == PendingApprovalHandoffStatus.CLAIM_INTERRUPTED
        )
    finally:
        lock.release()


def test_another_workflows_history_cannot_reconcile_the_row(
    hermetic_db: Path,
) -> None:
    orchestrator, lock = main.start_execution_session()
    pending_store, history_store, workflow_history = _stores(hermetic_db)
    try:
        _make_claimed_row(pending_store, "req-e", "wf-own-id")
        # A different, unrelated workflow's own terminal history exists -
        # it must never be mistaken for req-e's own evidence.
        workflow_history.record_transition(
            workflow_id="wf-completely-different", status="workflow_completed"
        )

        summary = main.reconcile_claimed_handoffs(lock)
        assert summary.claimed_consumed == 0
        assert summary.claimed_interrupted == 1
        assert (
            pending_store.get_handoff_status("req-e")
            == PendingApprovalHandoffStatus.CLAIM_INTERRUPTED
        )
    finally:
        lock.release()


def test_repeated_startup_recovery_is_idempotent(hermetic_db: Path) -> None:
    orchestrator, lock = main.start_execution_session()
    pending_store, history_store, workflow_history = _stores(hermetic_db)
    try:
        _make_claimed_row(pending_store, "req-f", "wf-idempotent")
        workflow_history.record_transition(
            workflow_id="wf-idempotent", status="workflow_completed"
        )

        first = main.reconcile_claimed_handoffs(lock)
        assert first.claimed_consumed == 1

        # Second pass: the row is already CONSUMED (terminal) - it is no
        # longer CLAIMED, so it is not visited again at all.
        second = main.reconcile_claimed_handoffs(lock)
        assert second.claimed_consumed == 0
        assert second.claimed_interrupted == 0
        assert (
            pending_store.get_handoff_status("req-f")
            == PendingApprovalHandoffStatus.CONSUMED
        )
    finally:
        lock.release()


def test_repeated_recovery_creates_no_duplicate_interruption_event(
    hermetic_db: Path,
) -> None:
    orchestrator, lock = main.start_execution_session()
    pending_store, history_store, workflow_history = _stores(hermetic_db)
    try:
        _make_claimed_row(pending_store, "req-g", "wf-interrupted-twice")

        main.reconcile_claimed_handoffs(lock)
        entry_after_first = history_store.get("req-g")
        assert entry_after_first.status == "interrupted"
        first_reason = entry_after_first.decision_reason

        # The row is now CLAIM_INTERRUPTED (terminal) - a second recovery
        # pass does not revisit it (list_by_handoff_status(CLAIMED) no
        # longer includes it), so the reason text is unchanged - proving
        # no duplicate event and no altered reason.
        main.reconcile_claimed_handoffs(lock)
        entry_after_second = history_store.get("req-g")
        assert entry_after_second.status == "interrupted"
        assert entry_after_second.decision_reason == first_reason
    finally:
        lock.release()


def test_reconcile_claimed_handoffs_requires_an_acquired_lock(
    hermetic_db: Path,
) -> None:
    unacquired = ExecutionProcessLock(hermetic_db)
    with pytest.raises(RuntimeError):
        main.reconcile_claimed_handoffs(unacquired)


# --- ordinary reload never mutates CLAIMED -----------------------------------


def test_ordinary_reload_pending_does_not_mutate_claimed_rows(
    hermetic_db: Path,
) -> None:
    from approval.approval_manager import ApprovalManager
    from tools.registry import ToolRegistry

    orchestrator, lock = main.start_execution_session()
    pending_store, history_store, workflow_history = _stores(hermetic_db)
    try:
        _make_claimed_row(pending_store, "req-h", "wf-untouched-by-reload")

        fresh_manager = ApprovalManager(pending_store=pending_store)
        fresh_manager.reload_pending(registry=ToolRegistry())

        assert (
            pending_store.get_handoff_status("req-h")
            == PendingApprovalHandoffStatus.CLAIMED
        )
        assert fresh_manager.has_pending("req-h") is False
    finally:
        lock.release()
