"""
test_approval_manager_handoff_lifecycle.py

Unit tests for ApprovalManager's new durable handoff-lifecycle methods
(Approval-to-Resume Handoff Interlock, Batch 2 -
docs/phase_98_approval_handoff_plan.md): claim_for_resume(),
mark_consumed(), mark_claim_interrupted(), handoff_status_for(), and the
approve()/decline() CAS-based transition wiring (no longer deleting the
durable row on decision).

Uses a real in-memory SQLite database via PendingApprovalStore/
ApprovalHistoryStore (not fakes), mirroring
tests/unit/test_approval_manager_pending_state.py's own established
convention.

Run with:
    pytest tests/unit/test_approval_manager_handoff_lifecycle.py
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_history_store import ApprovalHistoryStore  # noqa: E402
from approval.approval_manager import ApprovalManager  # noqa: E402
from approval.approval_models import PendingApprovalHandoffStatus  # noqa: E402
from approval.pending_approval_store import PendingApprovalStore  # noqa: E402
from config.constants import SecurityTier  # noqa: E402
from storage.database import create_session_factory, initialize_database  # noqa: E402


@pytest.fixture()
def session_factory():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


@pytest.fixture()
def pending_store(session_factory) -> PendingApprovalStore:
    return PendingApprovalStore(session_factory)


@pytest.fixture()
def history_store(session_factory) -> ApprovalHistoryStore:
    return ApprovalHistoryStore(session_factory)


def _approved_request(manager: ApprovalManager) -> str:
    request = manager.create_request(
        "update project state phase",
        "reason",
        SecurityTier.YELLOW,
        tool_name="project_state_update",
        tool_input={"field": "phase", "value": "Phase 99"},
    )
    manager.approve(request.request_id)
    return request.request_id


# --- claim_for_resume ---------------------------------------------------


def test_claim_for_resume_succeeds_exactly_once(
    pending_store: PendingApprovalStore,
) -> None:
    manager = ApprovalManager(pending_store=pending_store)
    request_id = _approved_request(manager)

    assert manager.claim_for_resume(request_id) is True
    assert manager.claim_for_resume(request_id) is False  # second claim fails
    assert (
        manager.handoff_status_for(request_id)
        == PendingApprovalHandoffStatus.CLAIMED
    )


def test_claim_for_resume_fails_for_a_still_pending_request(
    pending_store: PendingApprovalStore,
) -> None:
    manager = ApprovalManager(pending_store=pending_store)
    request = manager.create_request(
        "update project state phase",
        "reason",
        SecurityTier.YELLOW,
        tool_name="project_state_update",
        tool_input={"field": "phase", "value": "Phase 99"},
    )
    assert manager.claim_for_resume(request.request_id) is False


def test_claim_for_resume_returns_true_with_no_pending_store_configured() -> None:
    """No durable state to race against - behaves exactly as before this
    feature existed, so every existing in-memory-only call site is
    unaffected."""
    manager = ApprovalManager()  # no pending_store at all
    assert manager.claim_for_resume("any-id") is True


def test_claim_does_not_change_approved_arguments_or_identity(
    pending_store: PendingApprovalStore,
) -> None:
    manager = ApprovalManager(pending_store=pending_store)
    request_id = _approved_request(manager)
    before = pending_store.get(request_id)

    manager.claim_for_resume(request_id)

    after = pending_store.get(request_id)
    assert after.request_id == before.request_id
    assert after.action == before.action
    assert after.tool_name == before.tool_name
    assert after.tool_input == before.tool_input


# --- mark_consumed -------------------------------------------------------


def test_mark_consumed_after_claim_succeeds(
    pending_store: PendingApprovalStore,
) -> None:
    manager = ApprovalManager(pending_store=pending_store)
    request_id = _approved_request(manager)
    manager.claim_for_resume(request_id)

    assert manager.mark_consumed(request_id) is True
    assert (
        manager.handoff_status_for(request_id)
        == PendingApprovalHandoffStatus.CONSUMED
    )


def test_mark_consumed_without_prior_claim_fails(
    pending_store: PendingApprovalStore,
) -> None:
    manager = ApprovalManager(pending_store=pending_store)
    request_id = _approved_request(manager)
    assert manager.mark_consumed(request_id) is False


def test_consumed_cannot_be_claimed_again(pending_store: PendingApprovalStore) -> None:
    manager = ApprovalManager(pending_store=pending_store)
    request_id = _approved_request(manager)
    manager.claim_for_resume(request_id)
    manager.mark_consumed(request_id)

    assert manager.claim_for_resume(request_id) is False


# --- mark_claim_interrupted + history --------------------------------------


def test_mark_claim_interrupted_after_claim_succeeds_and_records_history(
    pending_store: PendingApprovalStore, history_store: ApprovalHistoryStore
) -> None:
    manager = ApprovalManager(pending_store=pending_store, history_store=history_store)
    request_id = _approved_request(manager)
    manager.claim_for_resume(request_id)

    assert manager.mark_claim_interrupted(request_id, reason="test interruption") is True
    assert (
        manager.handoff_status_for(request_id)
        == PendingApprovalHandoffStatus.CLAIM_INTERRUPTED
    )
    entry = history_store.get(request_id)
    assert entry is not None
    assert entry.status == "interrupted"
    assert "test interruption" in (entry.decision_reason or "")


def test_mark_claim_interrupted_is_idempotent(
    pending_store: PendingApprovalStore, history_store: ApprovalHistoryStore
) -> None:
    manager = ApprovalManager(pending_store=pending_store, history_store=history_store)
    request_id = _approved_request(manager)
    manager.claim_for_resume(request_id)
    manager.mark_claim_interrupted(request_id, reason="first")

    # A second call is only possible if some caller re-attempts it; the
    # CAS itself would reject a second CLAIMED -> CLAIM_INTERRUPTED since
    # the row is already terminal - proving no duplicate transition.
    assert manager.mark_claim_interrupted(request_id, reason="second") is False
    entry = history_store.get(request_id)
    assert "first" in (entry.decision_reason or "")


def test_interrupted_workflow_remains_unclaimable(
    pending_store: PendingApprovalStore,
) -> None:
    manager = ApprovalManager(pending_store=pending_store)
    request_id = _approved_request(manager)
    manager.claim_for_resume(request_id)
    manager.mark_claim_interrupted(request_id)

    assert manager.claim_for_resume(request_id) is False


def test_mark_claim_interrupted_preserves_original_decided_by_and_at(
    pending_store: PendingApprovalStore, history_store: ApprovalHistoryStore
) -> None:
    manager = ApprovalManager(pending_store=pending_store, history_store=history_store)
    request = manager.create_request(
        "update project state phase",
        "reason",
        SecurityTier.YELLOW,
        tool_name="project_state_update",
        tool_input={"field": "phase", "value": "Phase 99"},
    )
    manager.approve(request.request_id, decided_by="nathan")
    manager.claim_for_resume(request.request_id)

    before = history_store.get(request.request_id)
    manager.mark_claim_interrupted(request.request_id)
    after = history_store.get(request.request_id)

    assert after.decided_by == before.decided_by == "nathan"
    assert after.decided_at == before.decided_at


# --- approve/decline no longer delete the row ------------------------------


def test_approve_raises_on_durable_inconsistency(
    pending_store: PendingApprovalStore,
) -> None:
    """A defensive proof that a genuine in-memory/durable disagreement is
    surfaced, never silently proceeded past."""
    manager = ApprovalManager(pending_store=pending_store)
    request = manager.create_request(
        "update project state phase",
        "reason",
        SecurityTier.YELLOW,
        tool_name="project_state_update",
        tool_input={"field": "phase", "value": "Phase 99"},
    )
    # Force the durable row out of PENDING behind the manager's back.
    pending_store.mark_declined(request.request_id)

    from approval.approval_models import ApprovalError

    with pytest.raises(ApprovalError):
        manager.approve(request.request_id)


def test_duplicate_approve_after_approval_fails(
    pending_store: PendingApprovalStore,
) -> None:
    manager = ApprovalManager(pending_store=pending_store)
    request = manager.create_request(
        "update project state phase",
        "reason",
        SecurityTier.YELLOW,
        tool_name="project_state_update",
        tool_input={"field": "phase", "value": "Phase 99"},
    )
    manager.approve(request.request_id)

    from approval.approval_models import ApprovalError

    with pytest.raises(ApprovalError):
        manager.approve(request.request_id)


# --- handoff_status_for -----------------------------------------------------


def test_handoff_status_for_returns_none_without_pending_store() -> None:
    manager = ApprovalManager()
    assert manager.handoff_status_for("any-id") is None


def test_handoff_status_for_returns_none_for_unknown_request(
    pending_store: PendingApprovalStore,
) -> None:
    manager = ApprovalManager(pending_store=pending_store)
    assert manager.handoff_status_for("does-not-exist") is None
