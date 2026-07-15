"""
test_workflow_history_tool.py

Unit tests for WorkflowHistoryTool (Durable Workflow Lifecycle
Foundation - a prerequisite turn, not a numbered phase).

A fake, in-memory history store is used throughout - no real database is
needed to test formatting. (Constructing WorkflowHistoryTool still
requires SQLAlchemy to be importable, because WorkflowHistoryRecord is
defined alongside the real store; this file is skipped automatically if
SQLAlchemy is not importable, even though no real database is used.)

Run with:
    pytest tests/unit/test_workflow_history_tool.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from tools.base_tool import ToolRequest
from tools.builtin.workflow_history_tool import WorkflowHistoryTool
from workflow.workflow_history_store import (
    KNOWN_WORKFLOW_STATUSES,
    WorkflowHistoryRecord,
)

_CREATED = datetime(2026, 7, 10, 9, 15, 0, tzinfo=timezone.utc)


def _record(**overrides: object) -> WorkflowHistoryRecord:
    """Build a WorkflowHistoryRecord with sensible defaults for testing."""
    base: dict[str, object] = dict(
        id=1,
        workflow_id="wf-abc-123",
        session_id=None,
        status="workflow_started",
        step_number=None,
        step_total=2,
        tool_name=None,
        approval_request_id=None,
        detail=None,
        created_at=_CREATED,
    )
    base.update(overrides)
    return WorkflowHistoryRecord(**base)  # type: ignore[arg-type]


class _FakeHistoryStore:
    """A minimal in-memory stand-in for WorkflowHistoryStore.

    Only the read-side methods WorkflowHistoryTool actually calls are
    implemented. There is deliberately no write method here at all - this
    tool never needs one, since it only ever reads.
    """

    def __init__(self, records: list[WorkflowHistoryRecord]) -> None:
        self._records = records

    def list_recent(self, limit: int = 20) -> list[WorkflowHistoryRecord]:
        return list(self._records[:limit])

    def list_for_workflow(
        self, workflow_id: str, limit: int = 50
    ) -> list[WorkflowHistoryRecord]:
        return [r for r in self._records if r.workflow_id == workflow_id][:limit]

    def list_recent_workflow_ids(self, limit: int = 10) -> list[str]:
        """Distinct workflow ids, in first-occurrence order - mirroring
        this fake's own "records are already newest-first" convention
        (the same one list_recent() above already relies on)."""
        seen: list[str] = []
        for record in self._records:
            if record.workflow_id not in seen:
                seen.append(record.workflow_id)
        return seen[:limit]

    def latest_status_for(
        self, workflow_id: str
    ) -> WorkflowHistoryRecord | None:
        """The first matching record for this workflow_id - "first" being
        "most recent" under this fake's newest-first convention."""
        for record in self._records:
            if record.workflow_id == workflow_id:
                return record
        return None


def _request(operation: str = "history", **extra: object) -> ToolRequest:
    data = {"operation": operation, **extra}
    return ToolRequest(tool_name="workflow_history", input_data=data)


# --- action_for: the three operation-to-action-string mappings --------------
# These are the strings the Security Manager classifies. All three must
# classify GREEN via the existing "show" rule - see the integration test for
# the live classification check. This test just locks the strings in place.


def test_action_for_default_operation_is_history() -> None:
    tool = WorkflowHistoryTool(_FakeHistoryStore([]))
    assert tool.action_for(_request()) == "show workflow history"


def test_action_for_recent() -> None:
    tool = WorkflowHistoryTool(_FakeHistoryStore([]))
    assert tool.action_for(_request("recent")) == "show recent workflows"


def test_action_for_get() -> None:
    tool = WorkflowHistoryTool(_FakeHistoryStore([]))
    assert tool.action_for(_request("get")) == "show workflow details"


def test_action_for_unknown_operation_still_reads_as_history() -> None:
    tool = WorkflowHistoryTool(_FakeHistoryStore([]))
    assert tool.action_for(_request("nonsense")) == "show workflow history"


# --- run(): history/recent ----------------------------------------------------


def test_history_operation_shows_workflow_id_and_status() -> None:
    record = _record(status="workflow_started")
    tool = WorkflowHistoryTool(_FakeHistoryStore([record]))
    result = tool.run(_request("history"))
    assert result.success is True
    assert "wf-abc-123" in result.output
    assert "workflow_started" in result.output


def test_history_operation_shows_step_context_when_present() -> None:
    record = _record(
        status="workflow_step_completed",
        step_number=1,
        step_total=2,
        tool_name="memory",
    )
    tool = WorkflowHistoryTool(_FakeHistoryStore([record]))
    output = tool.run(_request("history")).output
    assert "step 1/2" in output
    assert "tool: memory" in output


def test_history_operation_shows_approval_correlation_when_present() -> None:
    record = _record(
        status="workflow_step_waiting",
        step_number=2,
        approval_request_id="req-42",
        detail="Awaiting your confirmation.",
    )
    tool = WorkflowHistoryTool(_FakeHistoryStore([record]))
    output = tool.run(_request("history")).output
    assert "approval: req-42" in output
    assert "detail: Awaiting your confirmation." in output


def test_history_operation_no_records_reports_none_found() -> None:
    tool = WorkflowHistoryTool(_FakeHistoryStore([]))
    output = tool.run(_request("history")).output
    assert "none found" in output


def test_recent_operation_uses_recent_header() -> None:
    tool = WorkflowHistoryTool(_FakeHistoryStore([_record()]))
    output = tool.run(_request("recent")).output
    assert "Recent workflows" in output


# --- Status breakdown in list-operation headers (Phase 73, Batch 2) ----------


def test_history_header_counts_distinct_workflows_not_raw_transitions() -> None:
    """Critical correctness proof: a workflow with multiple transitions
    must be counted once, by its latest status - never once per
    transition row, which would double-count a busy workflow."""
    records = [
        _record(
            id=3,
            workflow_id="wf-busy",
            status="workflow_completed",
            step_number=2,
        ),
        _record(
            id=2,
            workflow_id="wf-busy",
            status="workflow_step_completed",
            step_number=1,
        ),
        _record(id=1, workflow_id="wf-busy", status="workflow_started"),
    ]
    tool = WorkflowHistoryTool(_FakeHistoryStore(records))
    output = tool.run(_request("history")).output
    header_line = output.splitlines()[0]
    # wf-busy has three transition rows but must be tallied exactly once,
    # under its latest status only.
    assert "workflow_completed: 1" in header_line
    assert "workflow_started: 0" in header_line
    assert "workflow_step_completed: 0" in header_line


def test_history_header_shows_honest_zero_for_untouched_statuses() -> None:
    record = _record(workflow_id="wf-1", status="workflow_started")
    tool = WorkflowHistoryTool(_FakeHistoryStore([record]))
    output = tool.run(_request("history")).output
    header_line = output.splitlines()[0]
    for status in KNOWN_WORKFLOW_STATUSES:
        if status != "workflow_started":
            assert f"{status}: 0" in header_line


def test_history_header_preserves_known_status_order_not_sorted_by_count() -> None:
    """Statuses must never be reordered by count - this would visually
    imply significance the data does not actually carry."""
    last_status = KNOWN_WORKFLOW_STATUSES[-1]
    records = [
        _record(id=i, workflow_id=f"wf-{i}", status=last_status)
        for i in range(5)
    ]
    tool = WorkflowHistoryTool(_FakeHistoryStore(records))
    output = tool.run(_request("history")).output

    header_line = output.splitlines()[0]
    breakdown_text = header_line.split("recent activity: ", 1)[1].rstrip("):")
    rendered_order = [entry.split(":")[0].strip() for entry in breakdown_text.split(",")]
    assert rendered_order == list(KNOWN_WORKFLOW_STATUSES)


def test_history_header_discloses_recent_activity_scope() -> None:
    record = _record(workflow_id="wf-1", status="workflow_started")
    tool = WorkflowHistoryTool(_FakeHistoryStore([record]))
    output = tool.run(_request("history")).output
    header_line = output.splitlines()[0]
    assert "recent activity" in header_line.lower()


def test_recent_header_also_shows_status_breakdown() -> None:
    record = _record(workflow_id="wf-1", status="workflow_completed")
    tool = WorkflowHistoryTool(_FakeHistoryStore([record]))
    output = tool.run(_request("recent")).output
    header_line = output.splitlines()[0]
    assert "recent activity" in header_line.lower()
    assert "workflow_completed: 1" in header_line


def test_history_rows_still_include_expected_details_alongside_breakdown() -> None:
    record = _record(workflow_id="wf-1", status="workflow_started")
    tool = WorkflowHistoryTool(_FakeHistoryStore([record]))
    output = tool.run(_request("history")).output
    assert "recent activity" in output
    assert "wf-1" in output
    assert "workflow_started" in output


def test_empty_history_header_is_unchanged_by_batch_2() -> None:
    """Phase 73, Batch 2 only changes the non-empty header - the empty
    state must remain exactly as it was before this batch."""
    tool = WorkflowHistoryTool(_FakeHistoryStore([]))
    output = tool.run(_request("history")).output
    assert output == "Workflow history: none found."


def test_get_operation_has_no_status_breakdown() -> None:
    """Single-workflow detail output must be completely unaffected."""
    record = _record(workflow_id="wf-1", status="workflow_started")
    tool = WorkflowHistoryTool(_FakeHistoryStore([record]))
    output = tool.run(_request("get", workflow_id="wf-1")).output
    assert "recent activity" not in output
    assert "(" not in output.splitlines()[0]


def test_breakdown_does_not_mutate_history() -> None:
    records = [_record(workflow_id="wf-1", status="workflow_started")]
    store = _FakeHistoryStore(records)
    tool = WorkflowHistoryTool(store)
    tool.run(_request("history"))
    tool.run(_request("recent"))
    assert store._records == records


# --- run(): get ---------------------------------------------------------------


def test_get_operation_requires_workflow_id() -> None:
    tool = WorkflowHistoryTool(_FakeHistoryStore([]))
    result = tool.run(_request("get"))
    assert result.success is False
    assert "workflow_id" in result.error


def test_get_operation_reports_missing_workflow() -> None:
    tool = WorkflowHistoryTool(_FakeHistoryStore([]))
    result = tool.run(_request("get", workflow_id="does-not-exist"))
    assert result.success is False
    assert "does-not-exist" in result.error


def test_get_operation_shows_full_history_for_one_workflow() -> None:
    records = [
        _record(status="workflow_started", step_number=None),
        _record(status="workflow_step_completed", step_number=1, tool_name="memory"),
        _record(status="workflow_completed", step_number=None),
    ]
    tool = WorkflowHistoryTool(_FakeHistoryStore(records))
    result = tool.run(_request("get", workflow_id="wf-abc-123"))
    assert result.success is True
    assert "Workflow wf-abc-123" in result.output
    assert "workflow_started" in result.output
    assert "workflow_step_completed" in result.output
    assert "workflow_completed" in result.output


# --- run(): unknown operation --------------------------------------------------


def test_unknown_operation_fails_cleanly() -> None:
    tool = WorkflowHistoryTool(_FakeHistoryStore([]))
    result = tool.run(_request("nonsense"))
    assert result.success is False
    assert "nonsense" in result.error


# --- Structural guarantee: no replay/resumption surface ------------------------


def test_tool_result_never_carries_replay_fields() -> None:
    """The tool's output is formatted text only - there is no code path
    that returns a tool_name/tool_input for a past workflow, so nothing
    shown by this tool can ever be replayed or resumed."""
    record = _record(status="workflow_step_completed", tool_name="memory")
    tool = WorkflowHistoryTool(_FakeHistoryStore([record]))
    result = tool.run(_request("history"))
    assert not hasattr(result, "tool_input")
