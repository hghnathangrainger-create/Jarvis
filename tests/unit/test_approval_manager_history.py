"""
test_approval_manager_history.py

Unit tests for ApprovalManager's optional history recording (Phase 6, Batch 1).

These use a fake history recorder (no database) to verify that ApprovalManager
writes a pending row on create_request and updates it on approve/decline, that
it behaves exactly as before when no history_store is supplied, and - the
critical safety guarantee for this batch - that a freshly constructed
ApprovalManager never rehydrates pending requests from history. A restart
clears pending approvals exactly as it always has; only the historical record
survives.

Run with:
    pytest tests/unit/test_approval_manager_history.py
"""

from __future__ import annotations

from datetime import datetime

import pytest

from approval.approval_manager import ApprovalManager
from approval.approval_models import ApprovalError
from config.constants import SecurityTier


class _FakeHistory:
    """A minimal in-memory stand-in for ApprovalHistoryStore.

    Deliberately has no method that lists or returns "pending" requests -
    only write-side methods, matching the real store's interface and the
    Protocol ApprovalManager depends on.
    """

    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.decisions: list[dict[str, object]] = []
        self.timeouts: list[dict[str, object]] = []

    def record_request(
        self,
        *,
        request_id: str,
        action: str,
        reason: str,
        security_tier: str,
        session_id: int | None = None,
    ) -> None:
        self.requests.append(
            {
                "request_id": request_id,
                "action": action,
                "reason": reason,
                "security_tier": security_tier,
                "session_id": session_id,
            }
        )

    def record_decision(
        self,
        *,
        request_id: str,
        approved: bool,
        decided_by: str,
        decided_at: datetime,
        reason: str | None = None,
    ) -> None:
        self.decisions.append(
            {
                "request_id": request_id,
                "approved": approved,
                "decided_by": decided_by,
                "decided_at": decided_at,
                "reason": reason,
            }
        )

    def record_timeout(
        self,
        *,
        request_id: str,
        timed_out_at: datetime,
        reason: str | None = None,
    ) -> None:
        self.timeouts.append(
            {
                "request_id": request_id,
                "timed_out_at": timed_out_at,
                "reason": reason,
            }
        )


# --- create_request records a pending row -------------------------------


def test_create_request_records_pending_history() -> None:
    history = _FakeHistory()
    manager = ApprovalManager(history_store=history)
    request = manager.create_request(
        "send email to Alex",
        "Sending an email communicates on your behalf.",
        SecurityTier.YELLOW,
    )
    assert len(history.requests) == 1
    recorded = history.requests[0]
    assert recorded["request_id"] == request.request_id
    assert recorded["action"] == "send email to Alex"
    assert recorded["security_tier"] == "yellow"
    assert recorded["session_id"] is None


def test_create_request_records_session_id() -> None:
    history = _FakeHistory()
    manager = ApprovalManager(history_store=history)
    manager.create_request(
        "install software package",
        "Installing changes the system.",
        SecurityTier.YELLOW,
        session_id=42,
    )
    assert history.requests[0]["session_id"] == 42


def test_create_request_without_history_store_does_not_error() -> None:
    manager = ApprovalManager()
    request = manager.create_request(
        "send email to Alex",
        "Sending an email communicates on your behalf.",
        SecurityTier.YELLOW,
    )
    assert request.request_id  # created fine with no history_store at all


# --- approve / decline record decisions -----------------------------------


def test_approve_records_decision_history() -> None:
    history = _FakeHistory()
    manager = ApprovalManager(history_store=history)
    request = manager.create_request(
        "install software package",
        "Installing changes the system.",
        SecurityTier.YELLOW,
    )
    manager.approve(request.request_id)
    assert len(history.decisions) == 1
    recorded = history.decisions[0]
    assert recorded["request_id"] == request.request_id
    assert recorded["approved"] is True
    assert recorded["decided_by"] == "user"


def test_decline_records_decision_history() -> None:
    history = _FakeHistory()
    manager = ApprovalManager(history_store=history)
    request = manager.create_request(
        "delete file old.txt",
        "Deletion changes state and should be confirmed.",
        SecurityTier.YELLOW,
    )
    manager.decline(request.request_id, reason="not now")
    assert len(history.decisions) == 1
    recorded = history.decisions[0]
    assert recorded["approved"] is False
    assert recorded["reason"] == "not now"


def test_manager_without_history_store_behaves_as_before() -> None:
    manager = ApprovalManager()
    request = manager.create_request(
        "send email to Alex",
        "Sending an email communicates on your behalf.",
        SecurityTier.YELLOW,
    )
    decision = manager.approve(request.request_id)
    assert decision.is_approved is True  # no exception, no history dependency


# --- The critical Batch 1 safety guarantee ------------------------------


def test_fresh_manager_does_not_rehydrate_pending_from_history() -> None:
    """A restart must NOT bring old pending approvals back into memory.

    Even though a history store already has a row that looks pending
    (simulating a request that existed before a restart), a brand-new
    ApprovalManager built on that same store must start with an empty pending
    set. Nothing in __init__ reads history back into _pending - this test
    would fail immediately if that ever changed.
    """
    history = _FakeHistory()
    old_manager = ApprovalManager(history_store=history)
    old_request = old_manager.create_request(
        "update memory 3: corrected address",
        "Updating a memory changes stored content and must be confirmed.",
        SecurityTier.YELLOW,
    )
    # old_manager is discarded here without deciding old_request, simulating
    # a restart with one truly pending approval left over.
    assert len(history.requests) == 1  # the request WAS recorded to history...

    fresh_manager = ApprovalManager(history_store=history)

    assert fresh_manager.list_pending() == []  # ...but nothing came back
    with pytest.raises(ApprovalError):
        fresh_manager.approve(old_request.request_id)
    with pytest.raises(ApprovalError):
        fresh_manager.decline(old_request.request_id)


def test_two_managers_sharing_a_history_store_have_independent_pending_state() -> (
    None
):
    """History is shared and durable; _pending is per-instance and is not."""
    history = _FakeHistory()
    manager_a = ApprovalManager(history_store=history)
    manager_b = ApprovalManager(history_store=history)

    request = manager_a.create_request(
        "forget memory 9",
        "Forgetting a memory removes it.",
        SecurityTier.YELLOW,
    )

    assert manager_a.list_pending() == [request]
    assert manager_b.list_pending() == []
    with pytest.raises(ApprovalError):
        manager_b.approve(request.request_id)