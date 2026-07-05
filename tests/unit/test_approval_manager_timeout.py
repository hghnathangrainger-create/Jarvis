"""
test_approval_manager_timeout.py

Unit tests for ApprovalManager's YELLOW approval-timeout enforcement
(Phase 6, Batch 3).

Timeout is enforced lazily: a pending request expires once its age
(now - created_at) is greater than or equal to the configured
timeout_seconds - not strictly greater than. These tests use an injected fake
clock so elapsed time can be simulated exactly, without any real sleeping.
A fake audit logger and a fake history recorder are used to verify the two
side effects of an expiry: an EventOutcome.TIMEOUT audit event, and a
record_timeout call in durable history - never record_decision.

Run with:
    pytest tests/unit/test_approval_manager_timeout.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from approval.approval_manager import ApprovalManager
from approval.approval_models import ApprovalError
from config.constants import EventOutcome, SecurityTier

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeClock:
    """A settable clock so tests can simulate elapsed time exactly."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


class _FakeLogger:
    """Records every emitted audit event for inspection."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(
        self,
        *,
        source: str,
        action_type: str,
        outcome: EventOutcome,
        detail: str | None = None,
        duration_ms: int | None = None,
        security_tier=None,
        session_id: int | None = None,
    ) -> str:
        self.events.append(
            {
                "source": source,
                "action_type": action_type,
                "outcome": outcome,
                "detail": detail,
                "security_tier": security_tier,
                "session_id": session_id,
            }
        )
        return "fake-event-id"


class _FakeHistory:
    """Records requests, decisions, and timeouts for inspection.

    Mirrors the real ApprovalHistoryStore's write-side interface. Keeping
    decisions and timeouts in separate lists makes it easy to assert that an
    expiry was written through record_timeout only, and never through
    record_decision.
    """

    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.decisions: list[dict[str, object]] = []
        self.timeouts: list[dict[str, object]] = []

    def record_request(self, **kwargs: object) -> None:
        self.requests.append(kwargs)

    def record_decision(self, **kwargs: object) -> None:
        self.decisions.append(kwargs)

    def record_timeout(self, **kwargs: object) -> None:
        self.timeouts.append(kwargs)


def _make_manager(
    *,
    timeout_seconds: int | None = 60,
    clock: _FakeClock | None = None,
    logger: _FakeLogger | None = None,
    history: _FakeHistory | None = None,
) -> ApprovalManager:
    return ApprovalManager(
        audit_logger=logger,
        history_store=history,
        timeout_seconds=timeout_seconds,
        clock=clock or _FakeClock(_START),
    )


def _make_request(manager: ApprovalManager):
    """Create a standard YELLOW pending request via the manager."""
    return manager.create_request(
        action="send email to Alex",
        reason="Sending an email communicates on your behalf.",
        security_tier=SecurityTier.YELLOW,
    )


# --- Constructor validation --------------------------------------------------


def test_timeout_seconds_none_disables_enforcement() -> None:
    """The default (no timeout configured) never expires anything."""
    clock = _FakeClock(_START)
    manager = _make_manager(timeout_seconds=None, clock=clock)
    request = _make_request(manager)

    clock.now = _START + timedelta(days=3650)  # absurdly far in the future
    assert manager.has_pending(request.request_id) is True
    assert manager.list_pending() == [request]


@pytest.mark.parametrize("bad_value", [0, -1, -60])
def test_non_positive_timeout_seconds_rejected(bad_value: int) -> None:
    with pytest.raises(ApprovalError):
        ApprovalManager(timeout_seconds=bad_value)


# --- The exact boundary: age >= timeout, not age > timeout -------------------


def test_expires_at_exactly_the_configured_timeout_not_before() -> None:
    """59.999s remains pending; exactly 60.000s has expired.

    This is the explicit boundary required for the default 60-second
    timeout: expiry uses `age >= timeout`, never `age > timeout`.
    """
    clock = _FakeClock(_START)
    manager = _make_manager(timeout_seconds=60, clock=clock)
    request = _make_request(manager)

    clock.now = _START + timedelta(seconds=59.999)
    assert manager.has_pending(request.request_id) is True

    clock.now = _START + timedelta(seconds=60)
    assert manager.has_pending(request.request_id) is False


# --- No longer approvable or deniable once expired ---------------------------


def test_approve_after_timeout_raises_and_does_not_succeed() -> None:
    clock = _FakeClock(_START)
    manager = _make_manager(timeout_seconds=60, clock=clock)
    request = _make_request(manager)

    clock.now = _START + timedelta(seconds=60)
    with pytest.raises(ApprovalError):
        manager.approve(request.request_id)

    # No decision was ever recorded for it - not approved, not declined.
    with pytest.raises(ApprovalError):
        manager.get_decision(request.request_id)


def test_decline_after_timeout_raises_and_does_not_succeed() -> None:
    clock = _FakeClock(_START)
    manager = _make_manager(timeout_seconds=60, clock=clock)
    request = _make_request(manager)

    clock.now = _START + timedelta(seconds=60)
    with pytest.raises(ApprovalError):
        manager.decline(request.request_id)

    with pytest.raises(ApprovalError):
        manager.get_decision(request.request_id)


def test_list_pending_excludes_expired_requests() -> None:
    clock = _FakeClock(_START)
    manager = _make_manager(timeout_seconds=60, clock=clock)
    still_fresh = manager.create_request(
        action="show project files",
        reason="Reading files is safe.",
        security_tier=SecurityTier.YELLOW,
    )

    clock.now = _START + timedelta(seconds=30)
    expiring = _make_request(manager)  # created at t=30s

    clock.now = _START + timedelta(seconds=90)  # still_fresh is 90s old (expired);
    # expiring is 60s old (exactly expired too)
    pending_ids = {r.request_id for r in manager.list_pending()}
    assert still_fresh.request_id not in pending_ids
    assert expiring.request_id not in pending_ids
    assert manager.list_pending() == []


# --- A request answered before the deadline is unaffected --------------------


def test_request_answered_before_deadline_is_unaffected() -> None:
    clock = _FakeClock(_START)
    manager = _make_manager(timeout_seconds=60, clock=clock)
    request = _make_request(manager)

    clock.now = _START + timedelta(seconds=59)
    decision = manager.approve(request.request_id)

    assert decision.is_approved
    assert manager.get_decision(request.request_id) is decision


# --- Timeout is represented explicitly, not as a decision --------------------


def test_timeout_emits_timeout_outcome_not_success_or_blocked() -> None:
    clock = _FakeClock(_START)
    logger = _FakeLogger()
    manager = _make_manager(timeout_seconds=60, clock=clock, logger=logger)
    request = _make_request(manager)

    clock.now = _START + timedelta(seconds=60)
    manager.has_pending(request.request_id)  # triggers the sweep

    assert len(logger.events) == 1
    event = logger.events[0]
    assert event["outcome"] is EventOutcome.TIMEOUT
    assert event["outcome"] is not EventOutcome.SUCCESS
    assert event["outcome"] is not EventOutcome.BLOCKED
    assert event["security_tier"] is SecurityTier.YELLOW
    assert request.request_id in event["detail"]


def test_timeout_records_history_via_record_timeout_not_record_decision() -> None:
    clock = _FakeClock(_START)
    history = _FakeHistory()
    manager = _make_manager(timeout_seconds=60, clock=clock, history=history)
    request = _make_request(manager)

    clock.now = _START + timedelta(seconds=60)
    manager.has_pending(request.request_id)  # triggers the sweep

    assert len(history.timeouts) == 1
    assert history.timeouts[0]["request_id"] == request.request_id
    # Never recorded as a decision - the two write paths are kept separate.
    assert history.decisions == []


# --- RED can never enter the timeout lifecycle -------------------------------


def test_red_action_cannot_become_a_pending_request_at_all() -> None:
    """RED is rejected at request creation, so it can never be pending, let
    alone time out. This guards the structural guarantee, not a policy one.
    """
    manager = _make_manager(timeout_seconds=60)
    with pytest.raises(ApprovalError):
        manager.create_request(
            action="delete all files",
            reason="Deleting everything is destructive.",
            security_tier=SecurityTier.RED,
        )
    assert manager.list_pending() == []
