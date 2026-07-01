"""
test_approval_manager.py

Unit tests for the Jarvis ApprovalManager (approval/approval_manager.py).

The manager is a pure, in-memory component, so these tests run fast and need
no database, audit log, AI, or network.

Run with:
    pytest tests/unit/test_approval_manager.py
"""

from __future__ import annotations

import pytest

from approval.approval_manager import ApprovalManager
from approval.approval_models import ApprovalError, ApprovalStatus
from config.constants import SecurityTier


@pytest.fixture()
def manager() -> ApprovalManager:
    """Return a fresh, empty ApprovalManager for each test."""
    return ApprovalManager()


def _make_request(manager: ApprovalManager):
    """Create a standard YELLOW pending request via the manager."""
    return manager.create_request(
        action="send email to Alex",
        reason="Sending an email communicates on your behalf.",
        security_tier=SecurityTier.YELLOW,
    )


# --- Creation and lookup -----------------------------------------------------


def test_create_pending_request(manager: ApprovalManager) -> None:
    request = _make_request(manager)
    assert manager.has_pending(request.request_id)


def test_list_pending(manager: ApprovalManager) -> None:
    _make_request(manager)
    _make_request(manager)
    assert len(manager.list_pending()) == 2


def test_get_pending_request(manager: ApprovalManager) -> None:
    request = _make_request(manager)
    assert manager.get_pending(request.request_id).request_id == request.request_id


def test_metadata_is_preserved(manager: ApprovalManager) -> None:
    request = manager.create_request(
        action="send email",
        reason="communicates on your behalf",
        security_tier=SecurityTier.YELLOW,
        metadata={"to": "alex@example.com"},
    )
    assert manager.get_pending(request.request_id).metadata["to"] == "alex@example.com"


def test_metadata_is_copied_not_shared(manager: ApprovalManager) -> None:
    source = {"key": "value"}
    request = manager.create_request(
        action="send email",
        reason="communicates on your behalf",
        security_tier=SecurityTier.YELLOW,
        metadata=source,
    )
    source["key"] = "changed"
    assert manager.get_pending(request.request_id).metadata["key"] == "value"


# --- Approve -----------------------------------------------------------------


def test_approve_produces_approved_decision(manager: ApprovalManager) -> None:
    request = _make_request(manager)
    decision = manager.approve(request.request_id)
    assert decision.is_approved is True
    assert decision.status is ApprovalStatus.APPROVED


def test_approved_request_removed_from_pending(manager: ApprovalManager) -> None:
    request = _make_request(manager)
    manager.approve(request.request_id)
    assert not manager.has_pending(request.request_id)
    assert manager.list_pending() == []


# --- Decline -----------------------------------------------------------------


def test_decline_produces_declined_decision(manager: ApprovalManager) -> None:
    request = _make_request(manager)
    decision = manager.decline(request.request_id, reason="not now")
    assert decision.is_declined is True
    assert decision.status is ApprovalStatus.DECLINED
    assert decision.reason == "not now"


def test_declined_request_removed_from_pending(manager: ApprovalManager) -> None:
    request = _make_request(manager)
    manager.decline(request.request_id)
    assert not manager.has_pending(request.request_id)


# --- Retrieve decisions ------------------------------------------------------


def test_completed_decision_can_be_retrieved(manager: ApprovalManager) -> None:
    request = _make_request(manager)
    manager.approve(request.request_id)
    assert manager.get_decision(request.request_id).is_approved is True


# --- Error handling ----------------------------------------------------------


def test_unknown_pending_raises(manager: ApprovalManager) -> None:
    with pytest.raises(ApprovalError):
        manager.get_pending("no-such-id")


def test_unknown_decision_raises(manager: ApprovalManager) -> None:
    with pytest.raises(ApprovalError):
        manager.get_decision("no-such-id")


def test_cannot_approve_twice(manager: ApprovalManager) -> None:
    request = _make_request(manager)
    manager.approve(request.request_id)
    with pytest.raises(ApprovalError):
        manager.approve(request.request_id)


def test_cannot_decline_twice(manager: ApprovalManager) -> None:
    request = _make_request(manager)
    manager.decline(request.request_id)
    with pytest.raises(ApprovalError):
        manager.decline(request.request_id)


def test_cannot_approve_after_decline(manager: ApprovalManager) -> None:
    request = _make_request(manager)
    manager.decline(request.request_id)
    with pytest.raises(ApprovalError):
        manager.approve(request.request_id)


# --- GREEN / RED rejected at creation ----------------------------------------


@pytest.mark.parametrize("tier", [SecurityTier.GREEN, SecurityTier.RED])
def test_non_yellow_requests_are_rejected(
    manager: ApprovalManager, tier: SecurityTier
) -> None:
    with pytest.raises(ApprovalError):
        manager.create_request(action="something", reason="x", security_tier=tier)