"""
test_approval_models.py

Unit tests for the Jarvis approval data models (approval/approval_models.py).

These models are pure data with light validation, so the tests run fast and
need no database, AI, or network.

Run with:
    pytest tests/unit/test_approval_models.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from approval import (
    ApprovalDecision,
    ApprovalError,
    ApprovalRequest,
    ApprovalStatus,
)
from config.constants import SecurityTier


def _yellow_request(**overrides: object) -> ApprovalRequest:
    """Build a valid YELLOW ApprovalRequest, with optional field overrides."""
    kwargs: dict[str, object] = {
        "action": "send email to Alex",
        "reason": "Sending an email communicates on your behalf.",
        "security_tier": SecurityTier.YELLOW,
    }
    kwargs.update(overrides)
    return ApprovalRequest(**kwargs)  # type: ignore[arg-type]


# --- ApprovalRequest: valid creation -----------------------------------------


def test_valid_yellow_request_is_created() -> None:
    request = _yellow_request()
    assert request.action == "send email to Alex"
    assert request.security_tier is SecurityTier.YELLOW


def test_request_id_is_generated_automatically() -> None:
    request = _yellow_request()
    assert request.request_id


def test_created_at_is_set_automatically() -> None:
    request = _yellow_request()
    assert isinstance(request.created_at, datetime)


def test_metadata_defaults_to_empty_dict() -> None:
    request = _yellow_request()
    assert request.metadata == {}


def test_two_requests_have_different_ids() -> None:
    assert _yellow_request().request_id != _yellow_request().request_id


def test_explicit_id_and_timestamp_are_respected() -> None:
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    request = _yellow_request(request_id="fixed-id", created_at=when)
    assert request.request_id == "fixed-id"
    assert request.created_at == when


def test_metadata_can_be_supplied() -> None:
    request = _yellow_request(metadata={"to": "alex@example.com"})
    assert request.metadata["to"] == "alex@example.com"


# --- ApprovalRequest: validation rules ---------------------------------------


def test_green_request_is_rejected() -> None:
    with pytest.raises(ApprovalError):
        ApprovalRequest(
            action="search memories",
            reason="read only",
            security_tier=SecurityTier.GREEN,
        )


def test_red_request_is_rejected() -> None:
    with pytest.raises(ApprovalError):
        ApprovalRequest(
            action="format drive",
            reason="dangerous",
            security_tier=SecurityTier.RED,
        )


def test_empty_action_is_rejected() -> None:
    with pytest.raises(ApprovalError):
        ApprovalRequest(
            action="   ",
            reason="a reason",
            security_tier=SecurityTier.YELLOW,
        )


def test_empty_reason_is_rejected() -> None:
    with pytest.raises(ApprovalError):
        ApprovalRequest(
            action="send email",
            reason="   ",
            security_tier=SecurityTier.YELLOW,
        )


# --- ApprovalDecision --------------------------------------------------------


def test_approved_decision() -> None:
    request = _yellow_request()
    decision = ApprovalDecision(
        request_id=request.request_id, approved=True, decided_by="user"
    )
    assert decision.is_approved is True
    assert decision.is_declined is False
    assert decision.status is ApprovalStatus.APPROVED


def test_declined_decision() -> None:
    request = _yellow_request()
    decision = ApprovalDecision(
        request_id=request.request_id,
        approved=False,
        decided_by="user",
        reason="not now",
    )
    assert decision.is_declined is True
    assert decision.is_approved is False
    assert decision.status is ApprovalStatus.DECLINED
    assert decision.reason == "not now"


def test_decision_preserves_request_id() -> None:
    request = _yellow_request()
    decision = ApprovalDecision(
        request_id=request.request_id, approved=True, decided_by="user"
    )
    assert decision.request_id == request.request_id


def test_decided_at_is_set_automatically() -> None:
    decision = ApprovalDecision(request_id="abc", approved=True, decided_by="user")
    assert isinstance(decision.decided_at, datetime)


def test_decision_empty_request_id_is_rejected() -> None:
    with pytest.raises(ApprovalError):
        ApprovalDecision(request_id="   ", approved=True, decided_by="user")


def test_decision_empty_decided_by_is_rejected() -> None:
    with pytest.raises(ApprovalError):
        ApprovalDecision(request_id="abc", approved=True, decided_by="")


# --- request.decide() convenience --------------------------------------------


def test_request_decide_links_request_id() -> None:
    request = _yellow_request()
    decision = request.decide(approved=True, decided_by="user")
    assert decision.request_id == request.request_id
    assert decision.is_approved is True


# --- ApprovalStatus ----------------------------------------------------------


def test_approval_status_has_all_states() -> None:
    names = {status.name for status in ApprovalStatus}
    assert names == {"PENDING", "APPROVED", "DECLINED", "EXPIRED"}