"""
test_approval_audit.py

Unit tests for approval audit logging (approval/approval_manager.py, Phase 2
Step 8).

These tests confirm that when an audit logger is supplied, every approve and
decline emits a structured event carrying the request_id, action, outcome,
decider, and reason; and that without a logger the manager still works purely
in memory. A spy logger stands in for the real EventLogger, so no database is
needed.

Run with:
    pytest tests/unit/test_approval_audit.py
"""

from __future__ import annotations

import pytest

from approval.approval_manager import ApprovalManager
from config.constants import EventOutcome, SecurityTier


class _SpyLogger:
    """Captures emitted events instead of writing to the audit log."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


def _request(manager: ApprovalManager, **overrides: object):
    kwargs: dict[str, object] = {
        "action": "send email to Alex",
        "reason": "Sending an email communicates on your behalf.",
        "security_tier": SecurityTier.YELLOW,
    }
    kwargs.update(overrides)
    return manager.create_request(**kwargs)  # type: ignore[arg-type]


# --- Logging happens ---------------------------------------------------------


def test_approving_with_logger_records_event() -> None:
    logger = _SpyLogger()
    manager = ApprovalManager(audit_logger=logger)
    request = _request(manager)
    manager.approve(request.request_id)
    assert len(logger.events) == 1


def test_declining_with_logger_records_event() -> None:
    logger = _SpyLogger()
    manager = ApprovalManager(audit_logger=logger)
    request = _request(manager)
    manager.decline(request.request_id)
    assert len(logger.events) == 1


# --- Works without a logger --------------------------------------------------


def test_manager_works_without_logger() -> None:
    manager = ApprovalManager()
    request = _request(manager)
    decision = manager.approve(request.request_id)
    assert decision.is_approved is True
    assert not manager.has_pending(request.request_id)


def test_no_logger_still_records_decision() -> None:
    manager = ApprovalManager()
    request = _request(manager)
    manager.decline(request.request_id)
    assert manager.get_decision(request.request_id).is_declined is True


# --- Event contents ----------------------------------------------------------


def test_event_contains_request_id() -> None:
    logger = _SpyLogger()
    manager = ApprovalManager(audit_logger=logger)
    request = _request(manager)
    manager.approve(request.request_id)
    assert f"request_id={request.request_id}" in str(logger.events[0]["detail"])


def test_event_contains_outcome() -> None:
    logger = _SpyLogger()
    manager = ApprovalManager(audit_logger=logger)
    approved = _request(manager)
    manager.approve(approved.request_id)
    declined = _request(manager)
    manager.decline(declined.request_id)
    assert "outcome=approved" in str(logger.events[0]["detail"])
    assert "outcome=declined" in str(logger.events[1]["detail"])


def test_event_contains_decided_by() -> None:
    logger = _SpyLogger()
    manager = ApprovalManager(audit_logger=logger)
    request = _request(manager)
    manager.approve(request.request_id, decided_by="nathan")
    assert "decided_by=nathan" in str(logger.events[0]["detail"])


def test_event_includes_reason_when_supplied() -> None:
    logger = _SpyLogger()
    manager = ApprovalManager(audit_logger=logger)
    request = _request(manager)
    manager.approve(request.request_id, reason="looks fine")
    assert "reason=looks fine" in str(logger.events[0]["detail"])


def test_event_omits_reason_when_not_supplied() -> None:
    logger = _SpyLogger()
    manager = ApprovalManager(audit_logger=logger)
    request = _request(manager)
    manager.decline(request.request_id)
    assert "reason=" not in str(logger.events[0]["detail"])


def test_event_contains_action() -> None:
    logger = _SpyLogger()
    manager = ApprovalManager(audit_logger=logger)
    request = _request(manager)
    manager.approve(request.request_id)
    assert "action=send email to Alex" in str(logger.events[0]["detail"])


# --- Outcome enum mapping ----------------------------------------------------


def test_approve_maps_to_success_outcome() -> None:
    logger = _SpyLogger()
    manager = ApprovalManager(audit_logger=logger)
    request = _request(manager)
    manager.approve(request.request_id)
    assert logger.events[0]["outcome"] is EventOutcome.SUCCESS


def test_decline_maps_to_blocked_outcome() -> None:
    logger = _SpyLogger()
    manager = ApprovalManager(audit_logger=logger)
    request = _request(manager)
    manager.decline(request.request_id)
    assert logger.events[0]["outcome"] is EventOutcome.BLOCKED


# --- Event metadata ----------------------------------------------------------


def test_event_has_source_and_action_type() -> None:
    logger = _SpyLogger()
    manager = ApprovalManager(audit_logger=logger)
    request = _request(manager)
    manager.approve(request.request_id)
    event = logger.events[0]
    assert event["source"] == "approval_manager"
    assert event["action_type"] == "approval_decision"
    assert event["security_tier"] is SecurityTier.YELLOW


def test_event_carries_session_id() -> None:
    logger = _SpyLogger()
    manager = ApprovalManager(audit_logger=logger)
    request = _request(manager, session_id=42)
    manager.approve(request.request_id)
    assert logger.events[0]["session_id"] == 42