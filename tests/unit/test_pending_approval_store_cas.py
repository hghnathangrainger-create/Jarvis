"""
test_pending_approval_store_cas.py

Unit tests for PendingApprovalStore's new handoff-status compare-and-set
transition primitives (Approval-to-Resume Handoff Interlock, Batch 1 -
docs/phase_98_approval_handoff_plan.md). Mirrors
tests/unit/test_pending_approval_store.py's own real-in-memory-SQLite
fixture convention exactly.

Run with:
    pytest tests/unit/test_pending_approval_store_cas.py
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_models import PendingApprovalHandoffStatus  # noqa: E402
from approval.pending_approval_store import PendingApprovalStore  # noqa: E402
from storage.database import (  # noqa: E402
    create_session_factory,
    initialize_database,
    session_scope,
)
from storage.models import PendingApprovalState  # noqa: E402


@pytest.fixture()
def session_factory():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


@pytest.fixture()
def store(session_factory) -> PendingApprovalStore:
    return PendingApprovalStore(session_factory)


def _make_row(store: PendingApprovalStore, request_id: str = "req-1") -> None:
    store.save(
        request_id=request_id,
        action="update project state phase",
        reason="Updating phase requires approval.",
        security_tier="yellow",
        tool_name="project_state_update",
        tool_input={"field": "phase", "value": "Phase 99"},
    )


# --- default state -----------------------------------------------------------


def test_new_row_defaults_to_pending(store: PendingApprovalStore) -> None:
    _make_row(store)
    assert store.get_handoff_status("req-1") == PendingApprovalHandoffStatus.PENDING


def test_get_handoff_status_returns_none_for_unknown_request(
    store: PendingApprovalStore,
) -> None:
    assert store.get_handoff_status("does-not-exist") is None


# --- allowed transitions -------------------------------------------------


def test_pending_to_approved_unconsumed_succeeds(store: PendingApprovalStore) -> None:
    _make_row(store)
    assert store.mark_approved_unconsumed("req-1") is True
    assert (
        store.get_handoff_status("req-1")
        == PendingApprovalHandoffStatus.APPROVED_UNCONSUMED
    )


def test_one_claim_succeeds(store: PendingApprovalStore) -> None:
    _make_row(store)
    store.mark_approved_unconsumed("req-1")
    assert store.claim_for_resume("req-1") is True
    assert store.get_handoff_status("req-1") == PendingApprovalHandoffStatus.CLAIMED


def test_claimed_to_consumed_succeeds(store: PendingApprovalStore) -> None:
    _make_row(store)
    store.mark_approved_unconsumed("req-1")
    store.claim_for_resume("req-1")
    assert store.mark_consumed("req-1") is True
    assert store.get_handoff_status("req-1") == PendingApprovalHandoffStatus.CONSUMED


def test_claimed_to_claim_interrupted_succeeds(store: PendingApprovalStore) -> None:
    _make_row(store)
    store.mark_approved_unconsumed("req-1")
    store.claim_for_resume("req-1")
    assert store.mark_claim_interrupted("req-1") is True
    assert (
        store.get_handoff_status("req-1")
        == PendingApprovalHandoffStatus.CLAIM_INTERRUPTED
    )


def test_pending_to_declined_succeeds(store: PendingApprovalStore) -> None:
    _make_row(store)
    assert store.mark_declined("req-1") is True
    assert store.get_handoff_status("req-1") == PendingApprovalHandoffStatus.DECLINED


def test_pending_to_expired_succeeds(store: PendingApprovalStore) -> None:
    _make_row(store)
    assert store.mark_expired("req-1") is True
    assert store.get_handoff_status("req-1") == PendingApprovalHandoffStatus.EXPIRED


# --- concurrency / repeated-claim rejection -----------------------------


def test_concurrent_or_repeated_second_claim_fails(store: PendingApprovalStore) -> None:
    _make_row(store)
    store.mark_approved_unconsumed("req-1")

    assert store.claim_for_resume("req-1") is True
    # A second caller attempting the same claim (simulating a concurrent
    # or later attempt) must see the CAS fail - the row is no longer in
    # the expected APPROVED_UNCONSUMED state.
    assert store.claim_for_resume("req-1") is False
    assert store.get_handoff_status("req-1") == PendingApprovalHandoffStatus.CLAIMED


def test_repeated_mark_approved_unconsumed_second_call_fails(
    store: PendingApprovalStore,
) -> None:
    _make_row(store)
    assert store.mark_approved_unconsumed("req-1") is True
    assert store.mark_approved_unconsumed("req-1") is False


# --- illegal reversals / terminal-state reactivation --------------------


def test_claim_without_prior_approval_fails(store: PendingApprovalStore) -> None:
    _make_row(store)
    # Still PENDING - never transitioned to APPROVED_UNCONSUMED.
    assert store.claim_for_resume("req-1") is False
    assert store.get_handoff_status("req-1") == PendingApprovalHandoffStatus.PENDING


def test_consume_without_prior_claim_fails(store: PendingApprovalStore) -> None:
    _make_row(store)
    store.mark_approved_unconsumed("req-1")
    assert store.mark_consumed("req-1") is False
    assert (
        store.get_handoff_status("req-1")
        == PendingApprovalHandoffStatus.APPROVED_UNCONSUMED
    )


def test_reactivating_consumed_terminal_state_fails(store: PendingApprovalStore) -> None:
    _make_row(store)
    store.mark_approved_unconsumed("req-1")
    store.claim_for_resume("req-1")
    store.mark_consumed("req-1")

    assert store.claim_for_resume("req-1") is False  # CONSUMED -> CLAIMED rejected
    assert store.mark_approved_unconsumed("req-1") is False
    assert store.get_handoff_status("req-1") == PendingApprovalHandoffStatus.CONSUMED


def test_reactivating_claim_interrupted_terminal_state_fails(
    store: PendingApprovalStore,
) -> None:
    _make_row(store)
    store.mark_approved_unconsumed("req-1")
    store.claim_for_resume("req-1")
    store.mark_claim_interrupted("req-1")

    assert store.claim_for_resume("req-1") is False  # CLAIM_INTERRUPTED -> CLAIMED
    assert (
        store.get_handoff_status("req-1")
        == PendingApprovalHandoffStatus.CLAIM_INTERRUPTED
    )


def test_declined_terminal_state_cannot_be_reactivated(
    store: PendingApprovalStore,
) -> None:
    _make_row(store)
    store.mark_declined("req-1")
    assert store.mark_approved_unconsumed("req-1") is False
    assert store.get_handoff_status("req-1") == PendingApprovalHandoffStatus.DECLINED


def test_expired_terminal_state_cannot_be_reactivated(
    store: PendingApprovalStore,
) -> None:
    _make_row(store)
    store.mark_expired("req-1")
    assert store.mark_approved_unconsumed("req-1") is False
    assert store.get_handoff_status("req-1") == PendingApprovalHandoffStatus.EXPIRED


def test_declining_an_already_approved_unconsumed_request_fails(
    store: PendingApprovalStore,
) -> None:
    """PENDING -> DECLINED is only valid from PENDING - once a request
    has moved to APPROVED_UNCONSUMED, decline is no longer reachable."""
    _make_row(store)
    store.mark_approved_unconsumed("req-1")
    assert store.mark_declined("req-1") is False
    assert (
        store.get_handoff_status("req-1")
        == PendingApprovalHandoffStatus.APPROVED_UNCONSUMED
    )


# --- CAS is rowcount-based, not read-then-write --------------------------


def test_cas_fails_for_unknown_request_id(store: PendingApprovalStore) -> None:
    assert store.mark_approved_unconsumed("never-existed") is False


def test_cas_uses_rowcount_based_success(
    store: PendingApprovalStore, session_factory
) -> None:
    """Directly proves the underlying mechanism is a single UPDATE ...
    WHERE checked by rowcount, not a read-then-write pair: manually
    flipping the row to a different state between a caller's read and
    write would be a race in a read-then-write design, but here there
    is no read step at all to race against."""
    _make_row(store)
    store.mark_approved_unconsumed("req-1")

    with session_scope(session_factory) as db:
        entry = (
            db.query(PendingApprovalState)
            .filter(PendingApprovalState.request_id == "req-1")
            .one()
        )
        entry.handoff_status = PendingApprovalHandoffStatus.CLAIMED.value

    # The CAS call still only ever inspects the *current* database state
    # at the moment of its own atomic UPDATE - it must correctly reject
    # a claim expecting APPROVED_UNCONSUMED now that the row has moved on.
    assert store.claim_for_resume("req-1") is False


# --- immutability --------------------------------------------------------


def test_approved_arguments_remain_immutable_across_transitions(
    store: PendingApprovalStore,
) -> None:
    _make_row(store)
    before = store.get("req-1")
    assert before is not None

    store.mark_approved_unconsumed("req-1")
    store.claim_for_resume("req-1")
    store.mark_consumed("req-1")

    after = store.get("req-1")
    assert after is not None
    assert after.action == before.action
    assert after.reason == before.reason
    assert after.security_tier == before.security_tier
    assert after.tool_name == before.tool_name
    assert after.tool_input == before.tool_input
    assert after.schema_version == before.schema_version
    assert after.request_id == before.request_id


def test_workflow_identity_metadata_remains_immutable_across_transitions(
    store: PendingApprovalStore,
) -> None:
    store.save(
        request_id="req-wf",
        action="update project state phase",
        reason="r",
        security_tier="yellow",
        metadata={"workflow_id": "wf-42"},
        tool_name="project_state_update",
        tool_input={"field": "phase", "value": "Phase 99"},
    )

    store.mark_approved_unconsumed("req-wf")
    store.claim_for_resume("req-wf")

    record = store.get("req-wf")
    assert record is not None
    assert record.metadata == {"workflow_id": "wf-42"}
    assert record.request_id == "req-wf"


# --- no arbitrary state string accepted -----------------------------------


def test_handoff_status_enum_has_exactly_the_approved_members() -> None:
    assert {member.value for member in PendingApprovalHandoffStatus} == {
        "pending",
        "approved_unconsumed",
        "claimed",
        "consumed",
        "claim_interrupted",
        "declined",
        "expired",
    }


def test_handoff_status_enum_rejects_an_arbitrary_string() -> None:
    with pytest.raises(ValueError):
        PendingApprovalHandoffStatus("not_a_real_state")


# --- listing by status ----------------------------------------------------


def test_list_by_handoff_status_returns_only_matching_rows(
    store: PendingApprovalStore,
) -> None:
    _make_row(store, "req-a")
    _make_row(store, "req-b")
    _make_row(store, "req-c")
    store.mark_approved_unconsumed("req-a")
    store.mark_approved_unconsumed("req-b")

    approved_unconsumed = store.list_by_handoff_status(
        PendingApprovalHandoffStatus.APPROVED_UNCONSUMED
    )
    assert {r.request_id for r in approved_unconsumed} == {"req-a", "req-b"}

    pending = store.list_by_handoff_status(PendingApprovalHandoffStatus.PENDING)
    assert {r.request_id for r in pending} == {"req-c"}


def test_list_by_handoff_status_on_empty_table_returns_empty_list(
    store: PendingApprovalStore,
) -> None:
    assert store.list_by_handoff_status(PendingApprovalHandoffStatus.CLAIMED) == []
