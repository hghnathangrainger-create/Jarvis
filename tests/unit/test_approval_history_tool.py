"""
test_approval_history_tool.py

Unit tests for ApprovalHistoryTool (Phase 6, Batch 2).

Batch 1 only exercised this tool indirectly, through substring checks in an
integration test. This file tests it directly: every operation's action
string (the string the Security Manager classifies), and - the main purpose
of Batch 2 - that list-view output actually contains every required field
(request id, status, action, security tier, created time, and, only when
available, decided time, decided by, and decision reason), with decision-only
fields cleanly absent for pending records rather than shown blank.

A fake, in-memory history store is used throughout - no real database is
needed to test formatting. (Constructing ApprovalHistoryTool still requires
SQLAlchemy to be importable, because ApprovalHistoryRecord is defined
alongside the real store; this file is skipped automatically if SQLAlchemy is
not importable, even though no real database is used.)

Run with:
    pytest tests/unit/test_approval_history_tool.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_history_store import (
    KNOWN_APPROVAL_STATUSES,
    ApprovalHistoryRecord,
)
from tools.base_tool import ToolRequest
from tools.builtin.approval_history_tool import ApprovalHistoryTool

_CREATED = datetime(2026, 7, 4, 10, 22, 0, tzinfo=timezone.utc)
_DECIDED = datetime(2026, 7, 4, 10, 23, 5, tzinfo=timezone.utc)


def _record(**overrides: object) -> ApprovalHistoryRecord:
    """Build an ApprovalHistoryRecord with sensible defaults for testing."""
    base: dict[str, object] = dict(
        id=1,
        request_id="req-abc-123",
        session_id=None,
        action="update memory 3: corrected address",
        reason="Updating a memory changes stored content.",
        security_tier="yellow",
        status="pending",
        created_at=_CREATED,
        decided_at=None,
        decided_by=None,
        decision_reason=None,
    )
    base.update(overrides)
    return ApprovalHistoryRecord(**base)  # type: ignore[arg-type]


class _FakeHistoryStore:
    """A minimal in-memory stand-in for ApprovalHistoryStore.

    Only the read-side methods ApprovalHistoryTool actually calls are
    implemented. There is deliberately no write method here at all - this
    tool never needs one, since it only ever reads.
    """

    def __init__(self, records: list[ApprovalHistoryRecord]) -> None:
        self._records = records

    def list_recent(self, limit: int = 20) -> list[ApprovalHistoryRecord]:
        return list(self._records[:limit])

    def list_by_status(
        self, status: str, limit: int = 20
    ) -> list[ApprovalHistoryRecord]:
        return [r for r in self._records if r.status == status][:limit]

    def count_by_status(self, status: str) -> int:
        return sum(1 for r in self._records if r.status == status)

    def get(self, request_id: str) -> ApprovalHistoryRecord | None:
        for r in self._records:
            if r.request_id == request_id:
                return r
        return None


def _request(operation: str = "history", **extra: object) -> ToolRequest:
    data = {"operation": operation, **extra}
    return ToolRequest(tool_name="approval_history", input_data=data)


# --- action_for: the five operation-to-action-string mappings --------------
# These are the strings the Security Manager classifies. All five must
# classify GREEN via the existing "show" rule - see the integration test for
# the live classification check. This test just locks the strings in place.


def test_action_for_default_operation_is_history() -> None:
    tool = ApprovalHistoryTool(_FakeHistoryStore([]))
    assert tool.action_for(_request()) == "show approval history"


def test_action_for_recent() -> None:
    tool = ApprovalHistoryTool(_FakeHistoryStore([]))
    assert tool.action_for(_request("recent")) == "show recent approvals"


def test_action_for_approved() -> None:
    tool = ApprovalHistoryTool(_FakeHistoryStore([]))
    assert tool.action_for(_request("approved")) == "show approved actions"


def test_action_for_declined() -> None:
    tool = ApprovalHistoryTool(_FakeHistoryStore([]))
    assert tool.action_for(_request("declined")) == "show declined actions"


def test_action_for_get() -> None:
    tool = ApprovalHistoryTool(_FakeHistoryStore([]))
    assert tool.action_for(_request("get")) == "show approval details"


def test_action_for_unknown_operation_still_reads_as_history() -> None:
    # An honest fallback action string for security classification, even for
    # an operation the tool will later reject in run().
    tool = ApprovalHistoryTool(_FakeHistoryStore([]))
    assert tool.action_for(_request("nonsense")) == "show approval history"


# --- Required fields: pending -----------------------------------------------


def test_pending_record_shows_id_status_action_tier_created() -> None:
    record = _record(status="pending")
    tool = ApprovalHistoryTool(_FakeHistoryStore([record]))
    result = tool.run(_request("history"))
    assert result.success is True
    output = result.output
    assert "req-abc-123" in output
    assert "PENDING" in output
    assert "update memory 3: corrected address" in output
    assert "tier: yellow" in output
    assert "created: 2026-07-04T10:22:00" in output


def test_pending_record_omits_decision_fields_cleanly() -> None:
    record = _record(status="pending")
    tool = ApprovalHistoryTool(_FakeHistoryStore([record]))
    output = tool.run(_request("history")).output
    assert "decided" not in output
    assert "reason" not in output
    assert "by user" not in output
    assert "None" not in output  # never render a blank/None decision field


# --- Required fields: approved -----------------------------------------------


def test_approved_record_shows_all_required_fields() -> None:
    record = _record(
        status="approved",
        decided_at=_DECIDED,
        decided_by="user",
        decision_reason="looks right",
    )
    tool = ApprovalHistoryTool(_FakeHistoryStore([record]))
    output = tool.run(_request("approved")).output
    assert "req-abc-123" in output
    assert "APPROVED" in output
    assert "update memory 3: corrected address" in output
    assert "tier: yellow" in output
    assert "created: 2026-07-04T10:22:00" in output
    assert "decided: 2026-07-04T10:23:05" in output
    assert "by user" in output
    assert "reason: looks right" in output


def test_approved_record_without_reason_omits_reason_only() -> None:
    record = _record(status="approved", decided_at=_DECIDED, decided_by="user")
    tool = ApprovalHistoryTool(_FakeHistoryStore([record]))
    output = tool.run(_request("approved")).output
    assert "decided: 2026-07-04T10:23:05" in output
    assert "by user" in output
    assert "reason:" not in output


# --- Required fields: declined -----------------------------------------------


def test_declined_record_shows_all_required_fields() -> None:
    record = _record(
        status="declined",
        decided_at=_DECIDED,
        decided_by="user",
        decision_reason="not now",
    )
    tool = ApprovalHistoryTool(_FakeHistoryStore([record]))
    output = tool.run(_request("declined")).output
    assert "DECLINED" in output
    assert "decided: 2026-07-04T10:23:05" in output
    assert "by user" in output
    assert "reason: not now" in output


# --- Empty results -----------------------------------------------------------


def test_empty_history_reports_none_found() -> None:
    tool = ApprovalHistoryTool(_FakeHistoryStore([]))
    output = tool.run(_request("history")).output
    assert "none found" in output


def test_empty_declined_reports_none_found_with_correct_header() -> None:
    approved_only = _record(status="approved", decided_at=_DECIDED, decided_by="user")
    tool = ApprovalHistoryTool(_FakeHistoryStore([approved_only]))
    output = tool.run(_request("declined")).output
    assert "Declined actions: none found." == output


# --- Status breakdown in the default "history" header (Phase 73, Batch 1) ----


def test_history_header_shows_real_counts_for_every_known_status() -> None:
    records = [
        _record(request_id="r1", status="pending"),
        _record(request_id="r2", status="pending"),
        _record(request_id="r3", status="approved", decided_at=_DECIDED, decided_by="user"),
        _record(request_id="r4", status="approved", decided_at=_DECIDED, decided_by="user"),
        _record(request_id="r5", status="approved", decided_at=_DECIDED, decided_by="user"),
        _record(request_id="r6", status="approved", decided_at=_DECIDED, decided_by="user"),
        _record(request_id="r7", status="approved", decided_at=_DECIDED, decided_by="user"),
        _record(
            request_id="r8",
            status="declined",
            decided_at=_DECIDED,
            decided_by="user",
            decision_reason="not now",
        ),
    ]
    tool = ApprovalHistoryTool(_FakeHistoryStore(records))
    output = tool.run(_request("history")).output
    assert "Approval history (pending: 2, approved: 5, declined: 1, expired: 0):" in output


def test_history_header_shows_honest_zero_for_untouched_statuses() -> None:
    records = [_record(request_id="r1", status="pending")]
    tool = ApprovalHistoryTool(_FakeHistoryStore(records))
    output = tool.run(_request("history")).output
    assert "approved: 0" in output
    assert "declined: 0" in output
    assert "expired: 0" in output


def test_history_header_preserves_known_status_order_not_sorted_by_count() -> None:
    """Statuses must never be reordered by count - this would visually
    imply significance the data does not actually carry."""
    last_status = KNOWN_APPROVAL_STATUSES[-1]
    records = [
        _record(request_id=f"r{i}", status=last_status) for i in range(5)
    ]
    tool = ApprovalHistoryTool(_FakeHistoryStore(records))
    output = tool.run(_request("history")).output

    header_line = output.splitlines()[0]
    breakdown_text = header_line.split("(", 1)[1].rstrip("):")
    rendered_order = [entry.split(":")[0].strip() for entry in breakdown_text.split(",")]
    assert rendered_order == list(KNOWN_APPROVAL_STATUSES)


def test_history_rows_still_include_expected_details_alongside_breakdown() -> None:
    record = _record(status="pending")
    tool = ApprovalHistoryTool(_FakeHistoryStore([record]))
    output = tool.run(_request("history")).output
    assert "Approval history (" in output
    assert "[req-abc-123]" in output
    assert "PENDING" in output
    assert "tier: yellow" in output


def test_history_breakdown_does_not_mutate_or_requery_beyond_counts() -> None:
    """The breakdown must come from count_by_status() only - the same
    already-fetched `records` list is still what gets rendered below the
    header, never a second listing query."""
    records = [_record(request_id="r1", status="pending")]
    store = _FakeHistoryStore(records)
    tool = ApprovalHistoryTool(store)
    tool.run(_request("history"))
    tool.run(_request("history"))
    assert store._records == records


def test_recent_header_has_no_status_breakdown() -> None:
    records = [_record(request_id="r1", status="pending")]
    tool = ApprovalHistoryTool(_FakeHistoryStore(records))
    output = tool.run(_request("recent")).output
    assert output.startswith("Recent approvals:")
    assert "(" not in output.splitlines()[0]


def test_approved_header_has_no_status_breakdown() -> None:
    records = [_record(request_id="r1", status="approved", decided_at=_DECIDED, decided_by="user")]
    tool = ApprovalHistoryTool(_FakeHistoryStore(records))
    output = tool.run(_request("approved")).output
    assert output.startswith("Approved actions:")
    assert "(" not in output.splitlines()[0]


def test_declined_header_has_no_status_breakdown() -> None:
    records = [
        _record(
            request_id="r1",
            status="declined",
            decided_at=_DECIDED,
            decided_by="user",
            decision_reason="not now",
        )
    ]
    tool = ApprovalHistoryTool(_FakeHistoryStore(records))
    output = tool.run(_request("declined")).output
    assert output.startswith("Declined actions:")
    assert "(" not in output.splitlines()[0]


def test_get_operation_unaffected_by_history_breakdown() -> None:
    record = _record(status="approved", decided_at=_DECIDED, decided_by="user")
    tool = ApprovalHistoryTool(_FakeHistoryStore([record]))
    output = tool.run(_request("get", request_id="req-abc-123")).output
    assert "(" not in output.splitlines()[0]


# --- get: single-entry lookup (unchanged from Batch 1, re-verified here) ---


def test_get_returns_full_detail_including_all_fields() -> None:
    record = _record(
        status="approved",
        decided_at=_DECIDED,
        decided_by="user",
        decision_reason="looks right",
    )
    tool = ApprovalHistoryTool(_FakeHistoryStore([record]))
    output = tool.run(_request("get", request_id="req-abc-123")).output
    assert "req-abc-123" in output
    assert "status: approved" in output
    assert "tier: yellow" in output
    assert "decided_at:" in output
    assert "decided_by: user" in output
    assert "decision_reason: looks right" in output


def test_get_without_request_id_fails() -> None:
    tool = ApprovalHistoryTool(_FakeHistoryStore([]))
    result = tool.run(_request("get"))
    assert result.success is False
    assert result.error is not None


def test_get_unknown_request_id_fails() -> None:
    tool = ApprovalHistoryTool(_FakeHistoryStore([]))
    result = tool.run(_request("get", request_id="does-not-exist"))
    assert result.success is False
    assert result.error is not None


# --- Unknown operation ---------------------------------------------------


def test_unknown_operation_fails_with_helpful_message() -> None:
    tool = ApprovalHistoryTool(_FakeHistoryStore([]))
    result = tool.run(_request("nonsense"))
    assert result.success is False
    assert result.error is not None
    assert "history" in result.error
    assert "recent" in result.error