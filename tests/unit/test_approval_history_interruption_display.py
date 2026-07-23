"""
test_approval_history_interruption_display.py

Proves ApprovalHistoryTool's existing read path displays a claim-
interruption event truthfully (Approval-to-Resume Handoff Interlock,
Batch 2 - docs/phase_98_approval_handoff_plan.md): "The current
approval-history read path must display the interrupted status
truthfully."

Run with:
    pytest tests/unit/test_approval_history_interruption_display.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_history_store import ApprovalHistoryStore  # noqa: E402
from storage.database import create_session_factory, initialize_database  # noqa: E402
from tools.base_tool import ToolRequest  # noqa: E402
from tools.builtin.approval_history_tool import ApprovalHistoryTool  # noqa: E402


@pytest.fixture()
def history_store():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return ApprovalHistoryStore(factory)


def test_history_view_shows_interrupted_status_truthfully(
    history_store: ApprovalHistoryStore,
) -> None:
    history_store.record_request(
        request_id="req-interrupted",
        action="update project state phase",
        reason="needs approval",
        security_tier="yellow",
    )
    history_store.record_decision(
        request_id="req-interrupted",
        approved=True,
        decided_by="user",
        decided_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    history_store.record_interruption(
        request_id="req-interrupted",
        interrupted_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
    )

    tool = ApprovalHistoryTool(history_store)
    result = tool.run(ToolRequest(tool_name="approval_history", input_data={}))

    assert result.success is True
    assert "INTERRUPTED" in result.output
    assert "req-interrupted" in result.output


def test_get_operation_shows_interrupted_status_and_reason(
    history_store: ApprovalHistoryStore,
) -> None:
    history_store.record_request(
        request_id="req-interrupted-2",
        action="update project state phase",
        reason="needs approval",
        security_tier="yellow",
    )
    history_store.record_decision(
        request_id="req-interrupted-2",
        approved=True,
        decided_by="user",
        decided_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    history_store.record_interruption(
        request_id="req-interrupted-2",
        interrupted_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
    )

    tool = ApprovalHistoryTool(history_store)
    result = tool.run(
        ToolRequest(
            tool_name="approval_history",
            input_data={"operation": "get", "request_id": "req-interrupted-2"},
        )
    )

    assert result.success is True
    assert "interrupted" in result.output.lower()
    assert "automatic replay is not permitted" in result.output.lower()
    # Who/when originally approved remains visible - never overwritten.
    assert "decided_by: user" in result.output


def test_interruption_display_contains_no_prompt_or_stack_trace_content(
    history_store: ApprovalHistoryStore,
) -> None:
    history_store.record_request(
        request_id="req-bounded",
        action="update project state phase",
        reason="needs approval",
        security_tier="yellow",
    )
    history_store.record_decision(
        request_id="req-bounded",
        approved=True,
        decided_by="user",
        decided_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    history_store.record_interruption(
        request_id="req-bounded",
        interrupted_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
    )

    entry = history_store.get("req-bounded")
    assert entry is not None
    for forbidden in ("Traceback", "File \"", "raise ", "<system-reminder>"):
        assert forbidden not in (entry.decision_reason or "")
