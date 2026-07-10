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
from workflow.workflow_history_store import WorkflowHistoryRecord

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
