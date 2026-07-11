"""
test_paused_workflow_store.py

Unit tests for PausedWorkflowStore (Phase 27, Batch 2).

These use a real in-memory SQLite database (not a fake), exercising the
same storage layer Jarvis uses at runtime: saving a paused workflow's
plan/completed-outcomes/resolved-input, listing/getting it back,
replacing it, and deleting it. A key set of tests locks in this table's
own safety boundary: corrupt plan_steps_json/completed_outcomes_json/
resolved_tool_input_json is reported via the record's `corrupt` flag
rather than raising or silently losing every other row.

These tests use a real database, so they are skipped automatically if
SQLAlchemy is not importable.

Run with:
    pytest tests/unit/test_paused_workflow_store.py
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from storage.database import create_session_factory, initialize_database
from storage.models import PausedWorkflowState
from workflow.paused_workflow_store import PausedWorkflowStore, SCHEMA_VERSION


@pytest.fixture()
def session_factory():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


@pytest.fixture()
def store(session_factory) -> PausedWorkflowStore:
    return PausedWorkflowStore(session_factory)


_PLAN_STEPS = [
    {
        "number": 1,
        "description": "Save a memory",
        "action": "save memory",
        "tier": "green",
        "reason": "Saving is safe.",
        "tool_name": "memory",
        "tool_input": {"content": "hello"},
        "input_from_previous_step": False,
    },
    {
        "number": 2,
        "description": "Forget the memory",
        "action": "forget memory",
        "tier": "yellow",
        "reason": "Forgetting must be confirmed.",
        "tool_name": "memory_forget",
        "tool_input": {},
        "input_from_previous_step": True,
    },
]

_COMPLETED_OUTCOMES = [
    {
        "step_number": 1,
        "tool_result": {
            "tool_name": "memory",
            "success": True,
            "output": "Saved as id 3.",
            "error": None,
            "requires_confirmation": False,
            "blocked": False,
            "metadata": {"memory_id": "3"},
        },
    }
]


def test_save_round_trips_every_field(store: PausedWorkflowStore) -> None:
    record = store.save(
        workflow_id="wf-1",
        session_id=9,
        request_id="req-1",
        user_request="remember this and forget it: hello",
        plan_steps=_PLAN_STEPS,
        completed_outcomes=_COMPLETED_OUTCOMES,
        waiting_step_index=1,
        resolved_tool_input={"memory_id": "3"},
    )
    assert record.workflow_id == "wf-1"
    assert record.session_id == 9
    assert record.request_id == "req-1"
    assert record.user_request == "remember this and forget it: hello"
    assert record.plan_steps == _PLAN_STEPS
    assert record.completed_outcomes == _COMPLETED_OUTCOMES
    assert record.waiting_step_index == 1
    assert record.resolved_tool_input == {"memory_id": "3"}
    assert record.schema_version == SCHEMA_VERSION
    assert record.corrupt is False
    assert record.created_at is not None


def test_save_replaces_an_existing_row_for_the_same_workflow_id(
    store: PausedWorkflowStore,
) -> None:
    store.save(
        workflow_id="wf-1",
        session_id=None,
        request_id="req-1",
        user_request="first",
        plan_steps=_PLAN_STEPS,
        completed_outcomes=[],
        waiting_step_index=0,
        resolved_tool_input={},
    )
    store.save(
        workflow_id="wf-1",
        session_id=None,
        request_id="req-2",
        user_request="second - replaced",
        plan_steps=_PLAN_STEPS,
        completed_outcomes=_COMPLETED_OUTCOMES,
        waiting_step_index=1,
        resolved_tool_input={"memory_id": "3"},
    )

    record = store.get("wf-1")
    assert record is not None
    assert record.request_id == "req-2"
    assert record.user_request == "second - replaced"
    assert record.waiting_step_index == 1


def test_get_returns_none_for_unknown_workflow_id(store: PausedWorkflowStore) -> None:
    assert store.get("does-not-exist") is None


def test_list_all_returns_every_row_oldest_first(store: PausedWorkflowStore) -> None:
    for wf_id in ("wf-a", "wf-b", "wf-c"):
        store.save(
            workflow_id=wf_id,
            session_id=None,
            request_id=f"req-{wf_id}",
            user_request="x",
            plan_steps=_PLAN_STEPS,
            completed_outcomes=[],
            waiting_step_index=0,
            resolved_tool_input={},
        )

    records = store.list_all()
    assert [r.workflow_id for r in records] == ["wf-a", "wf-b", "wf-c"]


def test_list_all_on_empty_table_returns_empty_list(
    store: PausedWorkflowStore,
) -> None:
    assert store.list_all() == []


def test_delete_removes_the_row(store: PausedWorkflowStore) -> None:
    store.save(
        workflow_id="wf-1",
        session_id=None,
        request_id="req-1",
        user_request="x",
        plan_steps=_PLAN_STEPS,
        completed_outcomes=[],
        waiting_step_index=0,
        resolved_tool_input={},
    )
    store.delete("wf-1")
    assert store.get("wf-1") is None


def test_delete_is_a_no_op_for_an_unknown_workflow_id(
    store: PausedWorkflowStore,
) -> None:
    store.delete("never-existed")  # must not raise
    assert store.list_all() == []


# --- corrupt-row isolation ---------------------------------------------------


def test_corrupt_plan_steps_json_is_reported_not_raised(
    store: PausedWorkflowStore, session_factory
) -> None:
    from storage.database import session_scope

    store.save(
        workflow_id="wf-1", session_id=None, request_id="req-1", user_request="x",
        plan_steps=_PLAN_STEPS, completed_outcomes=[], waiting_step_index=0,
        resolved_tool_input={},
    )

    with session_scope(session_factory) as db:
        entry = (
            db.query(PausedWorkflowState)
            .filter(PausedWorkflowState.workflow_id == "wf-1")
            .one()
        )
        entry.plan_steps_json = "{not valid json"

    record = store.get("wf-1")
    assert record is not None
    assert record.corrupt is True
    assert record.plan_steps is None


def test_corrupt_completed_outcomes_json_is_reported_not_raised(
    store: PausedWorkflowStore, session_factory
) -> None:
    from storage.database import session_scope

    store.save(
        workflow_id="wf-1", session_id=None, request_id="req-1", user_request="x",
        plan_steps=_PLAN_STEPS, completed_outcomes=_COMPLETED_OUTCOMES,
        waiting_step_index=1, resolved_tool_input={},
    )

    with session_scope(session_factory) as db:
        entry = (
            db.query(PausedWorkflowState)
            .filter(PausedWorkflowState.workflow_id == "wf-1")
            .one()
        )
        entry.completed_outcomes_json = "[not valid"

    record = store.get("wf-1")
    assert record is not None
    assert record.corrupt is True
    assert record.completed_outcomes is None


def test_corrupt_resolved_tool_input_json_is_reported_not_raised(
    store: PausedWorkflowStore, session_factory
) -> None:
    from storage.database import session_scope

    store.save(
        workflow_id="wf-1", session_id=None, request_id="req-1", user_request="x",
        plan_steps=_PLAN_STEPS, completed_outcomes=[], waiting_step_index=0,
        resolved_tool_input={"a": "b"},
    )

    with session_scope(session_factory) as db:
        entry = (
            db.query(PausedWorkflowState)
            .filter(PausedWorkflowState.workflow_id == "wf-1")
            .one()
        )
        entry.resolved_tool_input_json = "{{{not json"

    record = store.get("wf-1")
    assert record is not None
    assert record.corrupt is True
    assert record.resolved_tool_input is None


def test_one_corrupt_row_does_not_prevent_other_valid_rows_from_listing(
    store: PausedWorkflowStore, session_factory
) -> None:
    from storage.database import session_scope

    for wf_id in ("wf-good-1", "wf-bad", "wf-good-2"):
        store.save(
            workflow_id=wf_id, session_id=None, request_id=f"req-{wf_id}",
            user_request="x", plan_steps=_PLAN_STEPS, completed_outcomes=[],
            waiting_step_index=0, resolved_tool_input={},
        )

    with session_scope(session_factory) as db:
        entry = (
            db.query(PausedWorkflowState)
            .filter(PausedWorkflowState.workflow_id == "wf-bad")
            .one()
        )
        entry.plan_steps_json = "not json at all {{{"

    records = store.list_all()
    by_id = {r.workflow_id: r for r in records}
    assert len(records) == 3
    assert by_id["wf-good-1"].corrupt is False
    assert by_id["wf-good-2"].corrupt is False
    assert by_id["wf-bad"].corrupt is True


def test_non_list_plan_steps_json_is_treated_as_corrupt(
    store: PausedWorkflowStore, session_factory
) -> None:
    from storage.database import session_scope

    store.save(
        workflow_id="wf-1", session_id=None, request_id="req-1", user_request="x",
        plan_steps=_PLAN_STEPS, completed_outcomes=[], waiting_step_index=0,
        resolved_tool_input={},
    )

    with session_scope(session_factory) as db:
        entry = (
            db.query(PausedWorkflowState)
            .filter(PausedWorkflowState.workflow_id == "wf-1")
            .one()
        )
        entry.plan_steps_json = '{"not": "a list"}'

    record = store.get("wf-1")
    assert record is not None
    assert record.corrupt is True
