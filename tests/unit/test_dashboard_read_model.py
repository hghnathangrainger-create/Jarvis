"""
test_dashboard_read_model.py

Unit tests for dashboard/read_model.py (Phase 19, Batch 1): the narrow,
read-only composition layer over MemoryManager, ApprovalHistoryStore, and
WorkflowHistoryStore that the dashboard UI (Batch 2) depends on.

These use a real in-memory SQLite database (not a fake), exercising the
same storage layer Jarvis uses at runtime, plus a structural (AST-based)
test proving dashboard/read_model.py never calls a write-capable method on
any of the three stores.

Run with:
    pytest tests/unit/test_dashboard_read_model.py
"""

from __future__ import annotations

import ast
import inspect

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine

from approval.approval_history_store import ApprovalHistoryStore
from dashboard.read_model import DashboardReadModel
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from storage.database import create_session_factory, initialize_database
from workflow.workflow_history_store import WorkflowHistoryStore

import dashboard.read_model as read_model_module


def _make_read_model() -> tuple[
    DashboardReadModel, MemoryManager, ApprovalHistoryStore, WorkflowHistoryStore
]:
    """Build a DashboardReadModel over three stores sharing one fresh
    in-memory database, plus the three underlying stores themselves so
    tests can seed real data through their own real write methods."""
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)

    memory = MemoryManager(EpisodicMemoryStore(factory))
    approvals = ApprovalHistoryStore(factory)
    workflows = WorkflowHistoryStore(factory)
    read_model = DashboardReadModel(memory, approvals, workflows)
    return read_model, memory, approvals, workflows


@pytest.fixture()
def rm() -> tuple[
    DashboardReadModel, MemoryManager, ApprovalHistoryStore, WorkflowHistoryStore
]:
    return _make_read_model()


# --- get_recent_memories / previews -------------------------------------------


def test_recent_memories_are_newest_first(rm) -> None:
    read_model, memory, _, _ = rm
    memory.save("first")
    memory.save("second")
    memory.save("third")

    rows = read_model.get_recent_memories()
    assert [row.full_content for row in rows] == ["third", "second", "first"]


def test_memory_preview_unchanged_at_exactly_120_chars(rm) -> None:
    read_model, memory, _, _ = rm
    content = "x" * 120
    memory.save(content)

    row = read_model.get_recent_memories()[0]
    assert row.preview == content
    assert row.full_content == content


def test_memory_preview_truncated_above_120_chars(rm) -> None:
    read_model, memory, _, _ = rm
    content = "y" * 121
    memory.save(content)

    row = read_model.get_recent_memories()[0]
    assert row.preview == ("y" * 120) + "..."
    assert row.full_content == content  # untruncated, for the detail view only


def test_memory_row_fields_map_from_real_record(rm) -> None:
    read_model, memory, _, _ = rm
    memory.save("budget notes", category="project")

    row = read_model.get_recent_memories()[0]
    assert row.category == "project"
    assert isinstance(row.id, int)
    assert row.created_at is not None


def test_memory_category_filter_is_honoured(rm) -> None:
    read_model, memory, _, _ = rm
    memory.save("a", category="project")
    memory.save("b", category="personal")

    rows = read_model.get_recent_memories(category="project")
    assert [row.full_content for row in rows] == ["a"]


def test_memory_rows_remain_usable_after_call_returns(rm) -> None:
    """Detached data: no lazy-loading, no dependency on an open session."""
    read_model, memory, _, _ = rm
    memory.save("detached check")

    rows = read_model.get_recent_memories()
    # Accessing fields well after the read-model call returned must not
    # touch a database session at all.
    row = rows[0]
    assert row.full_content == "detached check"
    assert row.preview == "detached check"


def test_recent_memories_empty_store_returns_empty_list(rm) -> None:
    read_model, _, _, _ = rm
    assert read_model.get_recent_memories() == []


# --- get_recent_approvals -----------------------------------------------------


def test_approval_row_fields_map_exactly_from_history(rm) -> None:
    read_model, _, approvals, _ = rm
    approvals.record_request(
        request_id="req-1",
        action="forget memory",
        reason="Forgetting a memory removes it and must be confirmed.",
        security_tier="yellow",
    )

    row = read_model.get_recent_approvals()[0]
    assert row.request_id == "req-1"
    assert row.action == "forget memory"
    assert row.security_tier == "yellow"
    assert row.status == "pending"
    assert row.decided_at is None
    assert row.decided_by is None


def test_approval_row_reflects_a_recorded_decision(rm) -> None:
    from datetime import datetime, timezone

    read_model, _, approvals, _ = rm
    approvals.record_request(
        request_id="req-2",
        action="update memory",
        reason="Updating a memory changes stored content and must be confirmed.",
        security_tier="yellow",
    )
    approvals.record_decision(
        request_id="req-2",
        approved=True,
        decided_by="user",
        decided_at=datetime.now(timezone.utc),
    )

    row = read_model.get_recent_approvals()[0]
    assert row.status == "approved"
    assert row.decided_by == "user"
    assert row.decided_at is not None


def test_recent_approvals_empty_store_returns_empty_list(rm) -> None:
    read_model, _, _, _ = rm
    assert read_model.get_recent_approvals() == []


# --- get_recent_workflows / get_workflow_transitions --------------------------


def test_recent_workflow_ids_are_distinct(rm) -> None:
    read_model, _, _, workflows = rm
    workflows.record_transition(workflow_id="wf-1", status="workflow_started")
    workflows.record_transition(workflow_id="wf-1", status="workflow_completed")

    rows = read_model.get_recent_workflows()
    assert [row.workflow_id for row in rows] == ["wf-1"]


def test_recent_workflows_ordering_is_deterministic(rm) -> None:
    read_model, _, _, workflows = rm
    workflows.record_transition(workflow_id="wf-1", status="workflow_started")
    workflows.record_transition(workflow_id="wf-2", status="workflow_started")
    workflows.record_transition(workflow_id="wf-1", status="workflow_completed")

    rows = read_model.get_recent_workflows()
    assert [row.workflow_id for row in rows] == ["wf-1", "wf-2"]


def test_transition_heavy_workflow_does_not_crowd_out_others_in_read_model(
    rm,
) -> None:
    read_model, _, _, workflows = rm
    workflows.record_transition(workflow_id="wf-quiet", status="workflow_started")
    for step in range(1, 8):
        workflows.record_transition(
            workflow_id="wf-chatty",
            status="workflow_step_started",
            step_number=step,
            step_total=7,
        )

    rows = read_model.get_recent_workflows(limit=5)
    ids = [row.workflow_id for row in rows]
    assert ids.count("wf-chatty") == 1
    assert "wf-quiet" in ids


def test_workflow_row_latest_status_matches_store_semantics(rm) -> None:
    read_model, _, _, workflows = rm
    workflows.record_transition(workflow_id="wf-1", status="workflow_started")
    workflows.record_transition(workflow_id="wf-1", status="workflow_step_waiting")

    row = read_model.get_recent_workflows()[0]
    expected = workflows.latest_status_for("wf-1")
    assert row.latest_status == expected.status
    assert row.latest_step_number == expected.step_number


def test_workflow_transitions_are_oldest_first(rm) -> None:
    read_model, _, _, workflows = rm
    workflows.record_transition(workflow_id="wf-1", status="workflow_started")
    workflows.record_transition(workflow_id="wf-1", status="workflow_completed")

    rows = read_model.get_workflow_transitions("wf-1")
    assert [row.status for row in rows] == ["workflow_started", "workflow_completed"]


def test_workflow_transitions_unknown_id_returns_empty_list(rm) -> None:
    read_model, _, _, _ = rm
    assert read_model.get_workflow_transitions("does-not-exist") == []


def test_recent_workflows_empty_store_returns_empty_list(rm) -> None:
    read_model, _, _, _ = rm
    assert read_model.get_recent_workflows() == []


# --- get_overview --------------------------------------------------------------


def test_overview_total_memory_count_uses_the_existing_count_path(rm) -> None:
    read_model, memory, _, _ = rm
    memory.save("one")
    memory.save("two")
    memory.save("three")

    overview = read_model.get_overview()
    assert overview.total_memory_count == memory.count() == 3


def test_overview_recent_approvals_and_workflows_populated(rm) -> None:
    read_model, _, approvals, workflows = rm
    approvals.record_request(
        request_id="req-1",
        action="delete file",
        reason="Deleting a file changes state and should be confirmed.",
        security_tier="yellow",
    )
    workflows.record_transition(workflow_id="wf-1", status="workflow_started")

    overview = read_model.get_overview()
    assert len(overview.recent_approvals) == 1
    assert len(overview.recent_workflows) == 1


def test_overview_on_empty_database_is_a_valid_empty_view_model(rm) -> None:
    read_model, _, _, _ = rm
    overview = read_model.get_overview()
    assert overview.total_memory_count == 0
    assert overview.recent_approvals == ()
    assert overview.recent_workflows == ()


# --- structural: no write path -------------------------------------------------

#: Method names, on any of the three stores, that imply a mutation. If
#: dashboard/read_model.py ever calls any of these, the read-only boundary
#: is broken.
_WRITE_METHOD_NAMES = frozenset(
    {
        "save",
        "update_content",
        "update_category",
        "move_category",
        "forget",
        "delete",
        "record_request",
        "record_decision",
        "record_timeout",
        "record_transition",
    }
)


def test_read_model_module_calls_no_write_method() -> None:
    """AST-based structural proof (not a substring search - see this
    repository's established convention) that no attribute call anywhere
    in dashboard/read_model.py uses a write-implying method name."""
    source = inspect.getsource(read_model_module)
    tree = ast.parse(source)

    called_attribute_names = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    forbidden_calls = called_attribute_names & _WRITE_METHOD_NAMES
    assert forbidden_calls == set()


def test_read_model_module_imports_no_execution_component() -> None:
    """Structural proof that dashboard/read_model.py cannot reach
    CommandRouter, ToolExecutor, the live ApprovalManager, WorkflowEngine,
    AIReasoningEngine, AIRouter, or WebSearchTool - it only imports the
    three approved read-side managers/stores."""
    source = inspect.getsource(read_model_module)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    forbidden = {
        "CommandRouter",
        "ToolExecutor",
        "ApprovalManager",
        "WorkflowEngine",
        "AIReasoningEngine",
        "AIRouter",
        "WebSearchTool",
    }
    assert imported_names & forbidden == set()
