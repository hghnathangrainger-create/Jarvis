"""
test_workflow_history_store.py

Unit tests for WorkflowHistoryStore (Durable Workflow Lifecycle
Foundation - a prerequisite turn, not a numbered phase).

These use a real in-memory SQLite database (not a fake), exercising the
same storage layer Jarvis uses at runtime: recording transitions and
querying them by recency, by workflow, and by "latest status."

Key tests lock in the foundation's safety boundary at the data-model
level: a returned record never carries a tool_input or resolved-step-input
field, because neither the table nor the record type has such a field -
nothing recorded here can ever be replayed or resumed.

These tests use a real database, so they are skipped automatically if
SQLAlchemy is not importable.

Run with:
    pytest tests/unit/test_workflow_history_store.py
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from workflow.workflow_history_store import WorkflowHistoryStore
from storage.database import create_session_factory, initialize_database


def _make_store() -> WorkflowHistoryStore:
    """Build a WorkflowHistoryStore backed by a fresh in-memory database."""
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return WorkflowHistoryStore(factory)


@pytest.fixture()
def store() -> WorkflowHistoryStore:
    return _make_store()


# --- record_transition -----------------------------------------------------


def test_record_transition_creates_row(store: WorkflowHistoryStore) -> None:
    record = store.record_transition(
        workflow_id="wf-1",
        status="workflow_started",
    )
    assert record.workflow_id == "wf-1"
    assert record.status == "workflow_started"
    assert record.session_id is None
    assert record.step_number is None
    assert record.step_total is None
    assert record.tool_name is None
    assert record.approval_request_id is None
    assert record.detail is None
    assert record.created_at is not None


def test_record_transition_stores_all_optional_fields(
    store: WorkflowHistoryStore,
) -> None:
    record = store.record_transition(
        workflow_id="wf-1",
        status="workflow_step_waiting",
        session_id=7,
        step_number=2,
        step_total=2,
        tool_name="memory_forget",
        approval_request_id="req-42",
        detail="Awaiting your confirmation.",
    )
    assert record.session_id == 7
    assert record.step_number == 2
    assert record.step_total == 2
    assert record.tool_name == "memory_forget"
    assert record.approval_request_id == "req-42"
    assert record.detail == "Awaiting your confirmation."


def test_history_row_has_no_replay_fields(store: WorkflowHistoryStore) -> None:
    """Structural guarantee: nothing stored here can ever be replayed.

    The schema has no tool_input / resolved_tool_input / serialised-plan
    columns at all, so this asserts the returned record type has no such
    attributes either. This is a deliberate foundation-turn boundary, not
    an omission to be "completed" later without a fresh safety review.
    """
    record = store.record_transition(workflow_id="wf-1", status="workflow_started")
    assert not hasattr(record, "tool_input")
    assert not hasattr(record, "resolved_tool_input")
    assert not hasattr(record, "plan")


def test_each_transition_is_a_separate_row(store: WorkflowHistoryStore) -> None:
    """Unlike approval history, a workflow_id is not unique - it accumulates
    one row per transition over its lifetime."""
    store.record_transition(workflow_id="wf-1", status="workflow_started")
    store.record_transition(workflow_id="wf-1", status="workflow_step_started")
    store.record_transition(workflow_id="wf-1", status="workflow_completed")

    rows = store.list_for_workflow("wf-1")
    assert len(rows) == 3


# --- list_recent ------------------------------------------------------------


def test_list_recent_returns_newest_first(store: WorkflowHistoryStore) -> None:
    store.record_transition(workflow_id="wf-1", status="workflow_started")
    store.record_transition(workflow_id="wf-2", status="workflow_started")
    store.record_transition(workflow_id="wf-3", status="workflow_started")

    rows = store.list_recent()
    assert [row.workflow_id for row in rows] == ["wf-3", "wf-2", "wf-1"]


def test_list_recent_respects_limit(store: WorkflowHistoryStore) -> None:
    for index in range(5):
        store.record_transition(workflow_id=f"wf-{index}", status="workflow_started")

    rows = store.list_recent(limit=2)
    assert len(rows) == 2


def test_list_recent_clamps_limit_below_one(store: WorkflowHistoryStore) -> None:
    store.record_transition(workflow_id="wf-1", status="workflow_started")
    rows = store.list_recent(limit=0)
    assert len(rows) == 1


def test_list_recent_clamps_limit_above_max(store: WorkflowHistoryStore) -> None:
    for index in range(60):
        store.record_transition(workflow_id=f"wf-{index}", status="workflow_started")
    rows = store.list_recent(limit=1000)
    assert len(rows) == 50


def test_list_recent_empty_store_returns_empty_list(
    store: WorkflowHistoryStore,
) -> None:
    assert store.list_recent() == []


# --- list_for_workflow -------------------------------------------------------


def test_list_for_workflow_returns_oldest_first(store: WorkflowHistoryStore) -> None:
    store.record_transition(workflow_id="wf-1", status="workflow_started")
    store.record_transition(workflow_id="wf-1", status="workflow_step_started")
    store.record_transition(workflow_id="wf-1", status="workflow_step_completed")
    store.record_transition(workflow_id="wf-1", status="workflow_completed")

    rows = store.list_for_workflow("wf-1")
    assert [row.status for row in rows] == [
        "workflow_started",
        "workflow_step_started",
        "workflow_step_completed",
        "workflow_completed",
    ]


def test_list_for_workflow_only_returns_matching_workflow(
    store: WorkflowHistoryStore,
) -> None:
    store.record_transition(workflow_id="wf-1", status="workflow_started")
    store.record_transition(workflow_id="wf-2", status="workflow_started")
    store.record_transition(workflow_id="wf-1", status="workflow_completed")

    rows = store.list_for_workflow("wf-1")
    assert len(rows) == 2
    assert all(row.workflow_id == "wf-1" for row in rows)


def test_list_for_workflow_unknown_id_returns_empty_list(
    store: WorkflowHistoryStore,
) -> None:
    assert store.list_for_workflow("does-not-exist") == []


def test_list_for_workflow_respects_limit(store: WorkflowHistoryStore) -> None:
    for _ in range(5):
        store.record_transition(workflow_id="wf-1", status="workflow_step_started")
    rows = store.list_for_workflow("wf-1", limit=2)
    assert len(rows) == 2


# --- latest_status_for --------------------------------------------------------


def test_latest_status_for_returns_most_recent_row(
    store: WorkflowHistoryStore,
) -> None:
    store.record_transition(workflow_id="wf-1", status="workflow_started")
    store.record_transition(workflow_id="wf-1", status="workflow_step_waiting")

    latest = store.latest_status_for("wf-1")
    assert latest is not None
    assert latest.status == "workflow_step_waiting"


def test_latest_status_for_unknown_workflow_returns_none(
    store: WorkflowHistoryStore,
) -> None:
    assert store.latest_status_for("does-not-exist") is None


def test_latest_status_for_is_derived_not_a_separate_field(
    store: WorkflowHistoryStore,
) -> None:
    """The 'current status' is always just the newest row - recording a
    new transition changes what latest_status_for returns without any
    separate update call."""
    store.record_transition(workflow_id="wf-1", status="workflow_started")
    assert store.latest_status_for("wf-1").status == "workflow_started"

    store.record_transition(workflow_id="wf-1", status="workflow_completed")
    assert store.latest_status_for("wf-1").status == "workflow_completed"


# --- isolation across workflows ----------------------------------------------


def test_multiple_workflows_do_not_interfere(store: WorkflowHistoryStore) -> None:
    store.record_transition(workflow_id="wf-1", status="workflow_started")
    store.record_transition(workflow_id="wf-2", status="workflow_started")
    store.record_transition(workflow_id="wf-1", status="workflow_completed")
    store.record_transition(workflow_id="wf-2", status="workflow_stopped")

    wf1_rows = store.list_for_workflow("wf-1")
    wf2_rows = store.list_for_workflow("wf-2")
    assert [row.status for row in wf1_rows] == [
        "workflow_started",
        "workflow_completed",
    ]
    assert [row.status for row in wf2_rows] == [
        "workflow_started",
        "workflow_stopped",
    ]
