"""
test_dashboard_read_model.py

Unit tests for dashboard/read_model.py (Phase 19, Batch 1; extended Phase
20, Batch 2 for the inbox; extended Phase 21, Batch 3 for schedules;
extended Phase 39, Batch 1 for quarantine visibility; extended across
the Phase 62-66 "Visible Jarvis Dashboard" upgrade series with system
status, store reachability, a recent-activity feed, and a real-count
breakdown/summary method per domain - MemoryCategoryCount,
ApprovalStatusCount, WorkflowStatusCount, InboxSourceTypeCount,
ScheduleStatusCount, QuarantineSummary; Phase 67 made a wording-only
consistency pass, adding no new behavior): the narrow, read-only
composition layer over MemoryManager, ApprovalHistoryStore,
WorkflowHistoryStore, InboxStore, ScheduleStore, and (optionally)
QuarantineStore that the dashboard UI depends on.

These use a real in-memory SQLite database (not a fake), exercising the
same storage layer Jarvis uses at runtime, plus a structural (AST-based)
test proving dashboard/read_model.py never calls a write-capable method on
any of the six stores.

Run with:
    pytest tests/unit/test_dashboard_read_model.py
"""

from __future__ import annotations

import ast
import hashlib
import inspect
from dataclasses import asdict
from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine

from approval.approval_history_store import ApprovalHistoryStore
from config.settings import Settings
from dashboard.read_model import DashboardReadModel
from inbox.inbox_store import InboxStore
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from quarantine.quarantine_store import QuarantineStore
from scheduling.schedule_store import ScheduleStore
from storage.database import create_session_factory, initialize_database
from workflow.workflow_history_store import WorkflowHistoryStore

import dashboard.read_model as read_model_module


def _make_read_model() -> tuple[
    DashboardReadModel,
    MemoryManager,
    ApprovalHistoryStore,
    WorkflowHistoryStore,
    InboxStore,
    ScheduleStore,
    QuarantineStore,
]:
    """Build a DashboardReadModel over six stores sharing one fresh
    in-memory database, plus the six underlying stores themselves so
    tests can seed real data through their own real write methods."""
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)

    memory = MemoryManager(EpisodicMemoryStore(factory))
    approvals = ApprovalHistoryStore(factory)
    workflows = WorkflowHistoryStore(factory)
    inbox = InboxStore(factory)
    schedules = ScheduleStore(factory)
    quarantine = QuarantineStore(factory)
    read_model = DashboardReadModel(
        memory, approvals, workflows, inbox, schedules, quarantine
    )
    return read_model, memory, approvals, workflows, inbox, schedules, quarantine


@pytest.fixture()
def rm() -> tuple[
    DashboardReadModel,
    MemoryManager,
    ApprovalHistoryStore,
    WorkflowHistoryStore,
    InboxStore,
    ScheduleStore,
    QuarantineStore,
]:
    return _make_read_model()


def _make_read_model_with_settings(
    settings: Settings | None,
) -> tuple[
    DashboardReadModel,
    MemoryManager,
    ApprovalHistoryStore,
    WorkflowHistoryStore,
    InboxStore,
    ScheduleStore,
    QuarantineStore,
]:
    """Build a DashboardReadModel the same way _make_read_model() does,
    but also threading a Settings object through (Phase 62, Batch 1) -
    kept as a separate helper so _make_read_model()'s own 7-tuple shape,
    and every existing test destructuring it, are completely unaffected.
    """
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)

    memory = MemoryManager(EpisodicMemoryStore(factory))
    approvals = ApprovalHistoryStore(factory)
    workflows = WorkflowHistoryStore(factory)
    inbox = InboxStore(factory)
    schedules = ScheduleStore(factory)
    quarantine = QuarantineStore(factory)
    read_model = DashboardReadModel(
        memory, approvals, workflows, inbox, schedules, quarantine, settings
    )
    return read_model, memory, approvals, workflows, inbox, schedules, quarantine


def _test_settings(**overrides: object) -> Settings:
    """Build a real Settings object for Phase 62 status-panel tests,
    mirroring test_web_search_summary_workflow.py's own established
    _settings() helper pattern."""
    defaults: dict[str, object] = dict(
        anthropic_api_key="test-key-not-real",
        ai_model="test-model",
        ai_max_tokens=1024,
        database_path=Path("unused.db"),
        log_level="INFO",
        approval_timeout_seconds=60,
        debug=False,
        ai_reasoning_enabled=False,
        voice_enabled=False,
        voice_speak_mode="off",
        voice_provider="none",
        voice_input_enabled=False,
        voice_input_provider="none",
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class _RaisingMemoryManager:
    """A duck-typed MemoryManager stand-in whose count() always raises
    (Phase 62, Batch 1) - proves get_store_reachability() isolates one
    store's failure from the rest, mirroring this project's established
    _Raising*Store precedent (e.g. test_web_search_summary_workflow.py's
    own _RaisingInboxStore)."""

    def count(self) -> int:
        raise RuntimeError("simulated memory read failure")


# --- get_recent_memories / previews -------------------------------------------


def test_recent_memories_are_newest_first(rm) -> None:
    read_model, memory, _, _, _, _, _ = rm
    memory.save("first")
    memory.save("second")
    memory.save("third")

    rows = read_model.get_recent_memories()
    assert [row.full_content for row in rows] == ["third", "second", "first"]


def test_memory_preview_unchanged_at_exactly_120_chars(rm) -> None:
    read_model, memory, _, _, _, _, _ = rm
    content = "x" * 120
    memory.save(content)

    row = read_model.get_recent_memories()[0]
    assert row.preview == content
    assert row.full_content == content


def test_memory_preview_truncated_above_120_chars(rm) -> None:
    read_model, memory, _, _, _, _, _ = rm
    content = "y" * 121
    memory.save(content)

    row = read_model.get_recent_memories()[0]
    assert row.preview == ("y" * 120) + "..."
    assert row.full_content == content  # untruncated, for the detail view only


def test_memory_row_fields_map_from_real_record(rm) -> None:
    read_model, memory, _, _, _, _, _ = rm
    memory.save("budget notes", category="project")

    row = read_model.get_recent_memories()[0]
    assert row.category == "project"
    assert isinstance(row.id, int)
    assert row.created_at is not None


def test_memory_category_filter_is_honoured(rm) -> None:
    read_model, memory, _, _, _, _, _ = rm
    memory.save("a", category="project")
    memory.save("b", category="personal")

    rows = read_model.get_recent_memories(category="project")
    assert [row.full_content for row in rows] == ["a"]


def test_memory_rows_remain_usable_after_call_returns(rm) -> None:
    """Detached data: no lazy-loading, no dependency on an open session."""
    read_model, memory, _, _, _, _, _ = rm
    memory.save("detached check")

    rows = read_model.get_recent_memories()
    # Accessing fields well after the read-model call returned must not
    # touch a database session at all.
    row = rows[0]
    assert row.full_content == "detached check"
    assert row.preview == "detached check"


def test_recent_memories_empty_store_returns_empty_list(rm) -> None:
    read_model, _, _, _, _, _, _ = rm
    assert read_model.get_recent_memories() == []


# --- get_memory_category_breakdown (Phase 63, Batch 1) -----------------------


def test_memory_category_breakdown_includes_all_known_categories(rm) -> None:
    from memory.memory_models import KNOWN_CATEGORIES

    read_model, *_ = rm

    breakdown = read_model.get_memory_category_breakdown()

    assert [row.category for row in breakdown] == list(KNOWN_CATEGORIES)


def test_memory_category_breakdown_reports_real_counts(rm) -> None:
    read_model, memory, *_ = rm
    memory.save("a", category="project")
    memory.save("b", category="project")
    memory.save("c", category="general")

    breakdown = {row.category: row.count for row in read_model.get_memory_category_breakdown()}

    assert breakdown["project"] == 2
    assert breakdown["general"] == 1


def test_memory_category_breakdown_includes_zero_count_categories_honestly(
    rm,
) -> None:
    read_model, memory, *_ = rm
    memory.save("only a general memory", category="general")

    breakdown = {row.category: row.count for row in read_model.get_memory_category_breakdown()}

    assert breakdown["personal"] == 0
    assert breakdown["project"] == 0
    assert breakdown["preference"] == 0
    assert breakdown["note"] == 0


def test_memory_category_breakdown_total_matches_real_memory_total(rm) -> None:
    read_model, memory, *_ = rm
    memory.save("a", category="project")
    memory.save("b", category="personal")
    memory.save("c", category="general")
    memory.save("d", category="note")
    memory.save("e", category="preference")

    breakdown = read_model.get_memory_category_breakdown()
    assert sum(row.count for row in breakdown) == memory.count()


def test_memory_category_breakdown_preserves_known_category_order_not_sorted_by_count(
    rm,
) -> None:
    """Categories must never be reordered by count - this would visually
    imply a ranking/importance the data does not actually carry."""
    from memory.memory_models import KNOWN_CATEGORIES

    read_model, memory, *_ = rm
    # Give the LAST known category the highest count, to prove sorting
    # by count is never applied.
    for _ in range(10):
        memory.save("x", category=KNOWN_CATEGORIES[-1])

    breakdown = read_model.get_memory_category_breakdown()
    assert [row.category for row in breakdown] == list(KNOWN_CATEGORIES)


def test_memory_category_breakdown_empty_store_still_lists_every_category(
    rm,
) -> None:
    from memory.memory_models import KNOWN_CATEGORIES

    read_model, *_ = rm

    breakdown = read_model.get_memory_category_breakdown()

    assert len(breakdown) == len(KNOWN_CATEGORIES)
    assert all(row.count == 0 for row in breakdown)


def test_memory_category_breakdown_does_not_mutate_memory_state(rm) -> None:
    read_model, memory, *_ = rm
    memory.save("a", category="project")
    before = memory.count()

    read_model.get_memory_category_breakdown()

    assert memory.count() == before


# --- get_recent_approvals -----------------------------------------------------


def test_approval_row_fields_map_exactly_from_history(rm) -> None:
    read_model, _, approvals, _, _, _, _ = rm
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

    read_model, _, approvals, _, _, _, _ = rm
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
    read_model, _, _, _, _, _, _ = rm
    assert read_model.get_recent_approvals() == []


def test_approval_row_reason_maps_from_real_record(rm) -> None:
    read_model, _, approvals, _, _, _, _ = rm
    approvals.record_request(
        request_id="req-1",
        action="forget memory",
        reason="Forgetting a memory removes it and must be confirmed.",
        security_tier="yellow",
    )

    row = read_model.get_recent_approvals()[0]
    assert row.reason == "Forgetting a memory removes it and must be confirmed."


def test_approval_row_decision_reason_is_none_while_pending(rm) -> None:
    read_model, _, approvals, _, _, _, _ = rm
    approvals.record_request(
        request_id="req-1", action="a", reason="r", security_tier="yellow"
    )

    row = read_model.get_recent_approvals()[0]
    assert row.decision_reason is None


def test_approval_row_decision_reason_maps_from_real_decision(rm) -> None:
    from datetime import datetime, timezone

    read_model, _, approvals, _, _, _, _ = rm
    approvals.record_request(
        request_id="req-1", action="a", reason="r", security_tier="yellow"
    )
    approvals.record_decision(
        request_id="req-1",
        approved=True,
        decided_by="user",
        decided_at=datetime.now(timezone.utc),
        reason="looks safe",
    )

    row = read_model.get_recent_approvals()[0]
    assert row.decision_reason == "looks safe"


# --- get_approval_status_breakdown (Phase 64, Batch 1) -----------------------


def test_approval_status_breakdown_includes_all_known_statuses(rm) -> None:
    from approval.approval_history_store import KNOWN_APPROVAL_STATUSES

    read_model, *_ = rm

    breakdown = read_model.get_approval_status_breakdown()

    assert [row.status for row in breakdown] == list(KNOWN_APPROVAL_STATUSES)


def test_approval_status_breakdown_reports_real_counts(rm) -> None:
    from datetime import datetime, timezone

    read_model, _, approvals, _, _, _, _ = rm
    approvals.record_request(
        request_id="req-1", action="a", reason="r", security_tier="yellow"
    )
    approvals.record_request(
        request_id="req-2", action="b", reason="r", security_tier="yellow"
    )
    approvals.record_decision(
        request_id="req-1",
        approved=True,
        decided_by="user",
        decided_at=datetime.now(timezone.utc),
    )

    breakdown = {row.status: row.count for row in read_model.get_approval_status_breakdown()}
    assert breakdown["approved"] == 1
    assert breakdown["pending"] == 1
    assert breakdown["declined"] == 0
    assert breakdown["expired"] == 0


def test_approval_status_breakdown_empty_store_shows_every_status_at_zero(
    rm,
) -> None:
    from approval.approval_history_store import KNOWN_APPROVAL_STATUSES

    read_model, *_ = rm

    breakdown = read_model.get_approval_status_breakdown()

    assert len(breakdown) == len(KNOWN_APPROVAL_STATUSES)
    assert all(row.count == 0 for row in breakdown)


def test_approval_status_breakdown_preserves_known_order_not_sorted_by_count(
    rm,
) -> None:
    """Statuses must never be reordered by count - this would visually
    imply significance the data does not actually carry."""
    from approval.approval_history_store import KNOWN_APPROVAL_STATUSES

    read_model, _, approvals, _, _, _, _ = rm
    # Give the LAST known status the highest count, to prove sorting by
    # count is never applied.
    last_status = KNOWN_APPROVAL_STATUSES[-1]
    for i in range(5):
        approvals.record_request(
            request_id=f"req-{i}", action="a", reason="r", security_tier="yellow"
        )
        if last_status == "expired":
            from datetime import datetime, timezone

            approvals.record_timeout(
                request_id=f"req-{i}", timed_out_at=datetime.now(timezone.utc)
            )

    breakdown = read_model.get_approval_status_breakdown()
    assert [row.status for row in breakdown] == list(KNOWN_APPROVAL_STATUSES)


def test_approval_status_breakdown_does_not_mutate_state(rm) -> None:
    read_model, _, approvals, _, _, _, _ = rm
    approvals.record_request(
        request_id="req-1", action="a", reason="r", security_tier="yellow"
    )
    before = approvals.get("req-1")

    read_model.get_approval_status_breakdown()

    after = approvals.get("req-1")
    assert before == after


# --- get_recent_workflows / get_workflow_transitions --------------------------


def test_recent_workflow_ids_are_distinct(rm) -> None:
    read_model, _, _, workflows, _, _, _ = rm
    workflows.record_transition(workflow_id="wf-1", status="workflow_started")
    workflows.record_transition(workflow_id="wf-1", status="workflow_completed")

    rows = read_model.get_recent_workflows()
    assert [row.workflow_id for row in rows] == ["wf-1"]


def test_recent_workflows_ordering_is_deterministic(rm) -> None:
    read_model, _, _, workflows, _, _, _ = rm
    workflows.record_transition(workflow_id="wf-1", status="workflow_started")
    workflows.record_transition(workflow_id="wf-2", status="workflow_started")
    workflows.record_transition(workflow_id="wf-1", status="workflow_completed")

    rows = read_model.get_recent_workflows()
    assert [row.workflow_id for row in rows] == ["wf-1", "wf-2"]


def test_transition_heavy_workflow_does_not_crowd_out_others_in_read_model(
    rm,
) -> None:
    read_model, _, _, workflows, _, _, _ = rm
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
    read_model, _, _, workflows, _, _, _ = rm
    workflows.record_transition(workflow_id="wf-1", status="workflow_started")
    workflows.record_transition(workflow_id="wf-1", status="workflow_step_waiting")

    row = read_model.get_recent_workflows()[0]
    expected = workflows.latest_status_for("wf-1")
    assert row.latest_status == expected.status
    assert row.latest_step_number == expected.step_number


def test_workflow_transitions_are_oldest_first(rm) -> None:
    read_model, _, _, workflows, _, _, _ = rm
    workflows.record_transition(workflow_id="wf-1", status="workflow_started")
    workflows.record_transition(workflow_id="wf-1", status="workflow_completed")

    rows = read_model.get_workflow_transitions("wf-1")
    assert [row.status for row in rows] == ["workflow_started", "workflow_completed"]


def test_workflow_transitions_unknown_id_returns_empty_list(rm) -> None:
    read_model, _, _, _, _, _, _ = rm
    assert read_model.get_workflow_transitions("does-not-exist") == []


def test_recent_workflows_empty_store_returns_empty_list(rm) -> None:
    read_model, _, _, _, _, _, _ = rm
    assert read_model.get_recent_workflows() == []


def test_workflow_transition_row_approval_request_id_maps_when_present(rm) -> None:
    read_model, _, _, workflows, _, _, _ = rm
    workflows.record_transition(
        workflow_id="wf-1",
        status="workflow_step_waiting",
        approval_request_id="req-1",
    )

    row = read_model.get_workflow_transitions("wf-1")[0]
    assert row.approval_request_id == "req-1"


def test_workflow_transition_row_approval_request_id_is_none_when_absent(rm) -> None:
    read_model, _, _, workflows, _, _, _ = rm
    workflows.record_transition(workflow_id="wf-1", status="workflow_started")

    row = read_model.get_workflow_transitions("wf-1")[0]
    assert row.approval_request_id is None


# --- get_workflow_status_breakdown (Phase 64, Batch 1) ------------------------


def test_workflow_status_breakdown_includes_all_known_statuses(rm) -> None:
    from workflow.workflow_history_store import KNOWN_WORKFLOW_STATUSES

    read_model, *_ = rm

    breakdown = read_model.get_workflow_status_breakdown()

    assert [row.status for row in breakdown] == list(KNOWN_WORKFLOW_STATUSES)


def test_workflow_status_breakdown_reports_real_counts_among_recent_workflows(
    rm,
) -> None:
    read_model, _, _, workflows, _, _, _ = rm
    workflows.record_transition(workflow_id="wf-1", status="workflow_started")
    workflows.record_transition(workflow_id="wf-1", status="workflow_completed")
    workflows.record_transition(workflow_id="wf-2", status="workflow_started")

    breakdown = {
        row.status: row.count for row in read_model.get_workflow_status_breakdown()
    }
    assert breakdown["workflow_completed"] == 1
    assert breakdown["workflow_started"] == 1
    assert breakdown["workflow_stopped"] == 0


def test_workflow_status_breakdown_empty_store_shows_every_status_at_zero(
    rm,
) -> None:
    from workflow.workflow_history_store import KNOWN_WORKFLOW_STATUSES

    read_model, *_ = rm

    breakdown = read_model.get_workflow_status_breakdown()

    assert len(breakdown) == len(KNOWN_WORKFLOW_STATUSES)
    assert all(row.count == 0 for row in breakdown)


def test_workflow_status_breakdown_preserves_known_order_not_sorted_by_count(
    rm,
) -> None:
    from workflow.workflow_history_store import KNOWN_WORKFLOW_STATUSES

    read_model, _, _, workflows, _, _, _ = rm
    # Give the LAST known status the highest count, to prove sorting by
    # count is never applied.
    last_status = KNOWN_WORKFLOW_STATUSES[-1]
    for i in range(5):
        workflows.record_transition(workflow_id=f"wf-{i}", status=last_status)

    breakdown = read_model.get_workflow_status_breakdown()
    assert [row.status for row in breakdown] == list(KNOWN_WORKFLOW_STATUSES)


def test_workflow_status_breakdown_is_scoped_to_recently_active_workflows_only(
    rm,
) -> None:
    """Honestly scoped: only the workflows get_recent_workflows(limit=...)
    would itself return are tallied - this is never an all-time total
    across every workflow ever recorded."""
    read_model, _, _, workflows, _, _, _ = rm
    for i in range(15):
        workflows.record_transition(workflow_id=f"wf-{i}", status="workflow_started")

    breakdown_default = {
        row.status: row.count for row in read_model.get_workflow_status_breakdown()
    }
    breakdown_limit_3 = {
        row.status: row.count
        for row in read_model.get_workflow_status_breakdown(limit=3)
    }
    # Default limit mirrors get_recent_workflows()'s own default (10).
    assert breakdown_default["workflow_started"] == 10
    assert breakdown_limit_3["workflow_started"] == 3


def test_workflow_status_breakdown_does_not_mutate_state(rm) -> None:
    read_model, _, _, workflows, _, _, _ = rm
    workflows.record_transition(workflow_id="wf-1", status="workflow_started")
    before = workflows.latest_status_for("wf-1")

    read_model.get_workflow_status_breakdown()

    after = workflows.latest_status_for("wf-1")
    assert before == after


# --- get_overview --------------------------------------------------------------


def test_overview_total_memory_count_uses_the_existing_count_path(rm) -> None:
    read_model, memory, _, _, _, _, _ = rm
    memory.save("one")
    memory.save("two")
    memory.save("three")

    overview = read_model.get_overview()
    assert overview.total_memory_count == memory.count() == 3


def test_overview_recent_approvals_and_workflows_populated(rm) -> None:
    read_model, _, approvals, workflows, inbox, _, _ = rm
    approvals.record_request(
        request_id="req-1",
        action="delete file",
        reason="Deleting a file changes state and should be confirmed.",
        security_tier="yellow",
    )
    workflows.record_transition(workflow_id="wf-1", status="workflow_started")
    inbox.append(source_type="web_search_summary", source_query="q", body="b")

    overview = read_model.get_overview()
    assert len(overview.recent_approvals) == 1
    assert len(overview.recent_workflows) == 1
    assert overview.total_inbox_count == 1
    assert len(overview.recent_inbox_entries) == 1


def test_overview_on_empty_database_is_a_valid_empty_view_model(rm) -> None:
    read_model, _, _, _, _, _, _ = rm
    overview = read_model.get_overview()
    assert overview.total_memory_count == 0
    assert overview.recent_approvals == ()
    assert overview.recent_workflows == ()
    assert overview.total_inbox_count == 0
    assert overview.recent_inbox_entries == ()
    assert overview.total_scheduled_inbox_count == 0
    assert overview.latest_scheduled_inbox_created_at is None


def test_overview_scheduled_inbox_count_excludes_interactive_entries(rm) -> None:
    read_model, _, _, _, inbox, _, _ = rm
    inbox.append(source_type="web_search_summary", source_query="interactive", body="b")
    inbox.append(
        source_type="scheduled_web_search_summary", source_query="scheduled", body="b"
    )

    overview = read_model.get_overview()
    assert overview.total_inbox_count == 2
    assert overview.total_scheduled_inbox_count == 1
    assert overview.latest_scheduled_inbox_created_at is not None


def test_overview_scheduled_inbox_count_is_independent_of_any_marker(rm) -> None:
    """The Overview's scheduled-inbox total is a plain, real count - it
    never reads or depends on notice/scheduled_inbox_notice_store.py's
    own CLI-owned marker, so it always reflects every scheduled entry
    ever created, not "since the CLI last checked"."""
    read_model, _, _, _, inbox, _, _ = rm
    inbox.append(source_type="scheduled_web_search_summary", source_query="q1", body="b")
    inbox.append(source_type="scheduled_web_search_summary", source_query="q2", body="b")

    overview = read_model.get_overview()
    assert overview.total_scheduled_inbox_count == 2


# --- get_recent_inbox_entries --------------------------------------------------


def test_recent_inbox_entries_are_newest_first(rm) -> None:
    read_model, _, _, _, inbox, _, _ = rm
    inbox.append(source_type="web_search_summary", source_query="first", body="b")
    inbox.append(source_type="web_search_summary", source_query="second", body="b")
    inbox.append(source_type="web_search_summary", source_query="third", body="b")

    rows = read_model.get_recent_inbox_entries()
    assert [row.source_query for row in rows] == ["third", "second", "first"]


def test_inbox_row_fields_map_from_real_record(rm) -> None:
    read_model, _, _, _, inbox, _, _ = rm
    inbox.append(
        source_type="web_search_summary",
        source_query="jarvis news",
        body="[AI web search summary] some synthesis",
        included_count=3,
    )

    row = read_model.get_recent_inbox_entries()[0]
    assert row.source_query == "jarvis news"
    assert row.full_body == "[AI web search summary] some synthesis"
    assert row.included_count == 3
    assert isinstance(row.id, int)
    assert row.created_at is not None


def test_webpage_summary_source_type_renders_like_any_other_entry(rm) -> None:
    """A "webpage_summary" entry (Phase 61) flows through identically to
    any other source type - including its source_type field (Phase 65,
    Batch 1 restored InboxRow.source_type; this test's docstring
    previously said InboxRow never referenced source_type at all - that
    is no longer true, updated here as an intentional part of this
    batch, not a regression)."""
    read_model, _, _, _, inbox, _, _ = rm
    inbox.append(
        source_type="webpage_summary",
        source_query="https://example.com/article",
        body="[AI webpage summary - based on one fetched page] A synthesis.",
    )

    row = read_model.get_recent_inbox_entries()[0]
    assert row.source_query == "https://example.com/article"
    assert row.full_body == (
        "[AI webpage summary - based on one fetched page] A synthesis."
    )
    assert row.source_type == "webpage_summary"
    assert isinstance(row.id, int)
    assert row.created_at is not None


def test_inbox_row_source_type_maps_from_real_record(rm) -> None:
    read_model, _, _, _, inbox, _, _ = rm
    inbox.append(
        source_type="scheduled_web_search_summary", source_query="q", body="b"
    )

    row = read_model.get_recent_inbox_entries()[0]
    assert row.source_type == "scheduled_web_search_summary"


def test_inbox_preview_truncated_above_120_chars(rm) -> None:
    read_model, _, _, _, inbox, _, _ = rm
    long_body = "z" * 121
    inbox.append(source_type="web_search_summary", source_query="q", body=long_body)

    row = read_model.get_recent_inbox_entries()[0]
    assert row.preview == ("z" * 120) + "..."
    assert row.full_body == long_body


def test_recent_inbox_entries_empty_store_returns_empty_list(rm) -> None:
    read_model, _, _, _, _, _, _ = rm
    assert read_model.get_recent_inbox_entries() == []


# --- get_inbox_source_type_breakdown (Phase 65, Batch 1) ----------------------


def test_inbox_source_type_breakdown_includes_all_known_source_types(rm) -> None:
    from inbox.inbox_store import KNOWN_INBOX_SOURCE_TYPES

    read_model, *_ = rm

    breakdown = read_model.get_inbox_source_type_breakdown()

    assert [row.source_type for row in breakdown] == list(KNOWN_INBOX_SOURCE_TYPES)


def test_inbox_source_type_breakdown_reports_real_counts(rm) -> None:
    read_model, _, _, _, inbox, _, _ = rm
    inbox.append(source_type="web_search_summary", source_query="a", body="b")
    inbox.append(source_type="web_search_summary", source_query="c", body="d")
    inbox.append(
        source_type="scheduled_web_search_summary", source_query="e", body="f"
    )

    breakdown = {
        row.source_type: row.count
        for row in read_model.get_inbox_source_type_breakdown()
    }
    assert breakdown["web_search_summary"] == 2
    assert breakdown["scheduled_web_search_summary"] == 1
    assert breakdown["webpage_summary"] == 0


def test_inbox_source_type_breakdown_empty_store_shows_every_type_at_zero(
    rm,
) -> None:
    from inbox.inbox_store import KNOWN_INBOX_SOURCE_TYPES

    read_model, *_ = rm

    breakdown = read_model.get_inbox_source_type_breakdown()

    assert len(breakdown) == len(KNOWN_INBOX_SOURCE_TYPES)
    assert all(row.count == 0 for row in breakdown)


def test_inbox_source_type_breakdown_preserves_known_order_not_sorted_by_count(
    rm,
) -> None:
    """Source types must never be reordered by count - this would
    visually imply significance the data does not actually carry."""
    from inbox.inbox_store import KNOWN_INBOX_SOURCE_TYPES

    read_model, _, _, _, inbox, _, _ = rm
    # Give the LAST known source type the highest count, to prove
    # sorting by count is never applied.
    last_source_type = KNOWN_INBOX_SOURCE_TYPES[-1]
    for i in range(5):
        inbox.append(source_type=last_source_type, source_query=f"q{i}", body="b")

    breakdown = read_model.get_inbox_source_type_breakdown()
    assert [row.source_type for row in breakdown] == list(KNOWN_INBOX_SOURCE_TYPES)


def test_inbox_source_type_breakdown_total_matches_real_inbox_total(rm) -> None:
    read_model, _, _, _, inbox, _, _ = rm
    inbox.append(source_type="web_search_summary", source_query="a", body="b")
    inbox.append(source_type="scheduled_web_search_summary", source_query="c", body="d")
    inbox.append(source_type="webpage_summary", source_query="e", body="f")

    breakdown = read_model.get_inbox_source_type_breakdown()
    assert sum(row.count for row in breakdown) == inbox.count()


def test_inbox_source_type_breakdown_does_not_mutate_inbox_state(rm) -> None:
    read_model, _, _, _, inbox, _, _ = rm
    inbox.append(source_type="web_search_summary", source_query="a", body="b")
    before = inbox.count()

    read_model.get_inbox_source_type_breakdown()

    assert inbox.count() == before


# --- get_schedules ---------------------------------------------------------------


def test_get_schedules_empty_store_returns_empty_list(rm) -> None:
    read_model, _, _, _, _, _, _ = rm
    assert read_model.get_schedules() == []


def test_get_schedules_returns_real_data_in_id_ascending_order(rm) -> None:
    read_model, _, _, _, _, schedules, _ = rm
    schedules.create(query="first", time_of_day="08:00")
    schedules.create(query="second", time_of_day="09:00")

    rows = read_model.get_schedules()
    assert [row.query_preview for row in rows] == ["first", "second"]


def test_schedule_row_fields_map_from_real_record(rm) -> None:
    read_model, _, _, _, _, schedules, _ = rm
    schedules.create(query="jarvis ai news", time_of_day="08:30", name="Morning news")

    row = read_model.get_schedules()[0]
    assert row.name == "Morning news"
    assert row.query_preview == "jarvis ai news"
    assert row.time_of_day == "08:30"
    assert row.enabled is True
    assert row.last_run_at is None
    assert row.created_at is not None


def test_schedule_row_shows_disabled_state(rm) -> None:
    read_model, _, _, _, _, schedules, _ = rm
    record = schedules.create(query="q", time_of_day="08:00")
    schedules.disable(record.id)

    row = read_model.get_schedules()[0]
    assert row.enabled is False


def test_schedule_row_shows_last_run_at_after_a_claim(rm) -> None:
    from datetime import datetime, timezone

    read_model, _, _, _, _, schedules, _ = rm
    record = schedules.create(query="q", time_of_day="00:00")
    now = datetime.now(timezone.utc)
    schedules.claim_due(record.id, now=now)

    row = read_model.get_schedules()[0]
    assert row.last_run_at is not None


def test_schedule_query_preview_truncated_above_120_chars(rm) -> None:
    read_model, _, _, _, _, schedules, _ = rm
    long_query = "z" * 200
    schedules.create(query=long_query, time_of_day="08:00")

    row = read_model.get_schedules()[0]
    assert row.query_preview == ("z" * 120) + "..."


# --- get_schedule_enabled_breakdown (Phase 65, Batch 1) -------------------------


def test_schedule_enabled_breakdown_returns_enabled_and_disabled_counts(rm) -> None:
    read_model, _, _, _, _, schedules, _ = rm
    enabled_one = schedules.create(query="a", time_of_day="08:00")
    schedules.create(query="b", time_of_day="09:00")
    schedules.disable(enabled_one.id)

    breakdown = {row.enabled: row.count for row in read_model.get_schedule_enabled_breakdown()}
    assert breakdown[True] == 1
    assert breakdown[False] == 1


def test_schedule_enabled_breakdown_empty_store_shows_both_states_at_zero(rm) -> None:
    read_model, *_ = rm

    breakdown = read_model.get_schedule_enabled_breakdown()

    assert len(breakdown) == 2
    assert all(row.count == 0 for row in breakdown)


def test_schedule_enabled_breakdown_preserves_fixed_order_not_sorted_by_count(
    rm,
) -> None:
    """"enabled" must always come before "disabled" - even when disabled
    schedules outnumber enabled ones - since this would otherwise
    visually imply significance the data does not actually carry."""
    read_model, _, _, _, _, schedules, _ = rm
    for i in range(5):
        record = schedules.create(query=f"q{i}", time_of_day="08:00")
        schedules.disable(record.id)

    breakdown = read_model.get_schedule_enabled_breakdown()
    assert [row.enabled for row in breakdown] == [True, False]


def test_schedule_enabled_breakdown_total_matches_real_schedule_total(rm) -> None:
    read_model, _, _, _, _, schedules, _ = rm
    schedules.create(query="a", time_of_day="08:00")
    schedules.create(query="b", time_of_day="09:00")
    schedules.create(query="c", time_of_day="10:00")

    breakdown = read_model.get_schedule_enabled_breakdown()
    assert sum(row.count for row in breakdown) == len(schedules.list_all())


def test_schedule_enabled_breakdown_does_not_mutate_schedule_state(rm) -> None:
    read_model, _, _, _, _, schedules, _ = rm
    schedules.create(query="a", time_of_day="08:00")
    before = len(schedules.list_all())

    read_model.get_schedule_enabled_breakdown()

    assert len(schedules.list_all()) == before


# --- get_quarantine_entries (Phase 39, Batch 1) ---------------------------------


def test_get_quarantine_entries_empty_store_returns_empty_list(rm) -> None:
    read_model, _, _, _, _, _, _ = rm
    assert read_model.get_quarantine_entries() == []


def test_get_quarantine_entries_returns_no_store_supplied_safely(
    rm,
) -> None:
    """A read model constructed with no QuarantineStore at all (the
    Phase 39 default) must return an empty list, never fail - backward
    compatible with any caller predating this phase."""
    from dashboard.read_model import DashboardReadModel

    read_model, memory, approvals, workflows, inbox, schedules, _ = rm
    no_quarantine_model = DashboardReadModel(
        memory, approvals, workflows, inbox, schedules
    )
    assert no_quarantine_model.get_quarantine_entries() == []


def test_get_quarantine_entries_returns_real_data_newest_first(rm) -> None:
    read_model, _, _, _, _, _, quarantine = rm
    quarantine.record_quarantine(
        original_path="/a/first.txt",
        quarantine_path="/trash/first__11111111.txt",
    )
    quarantine.record_quarantine(
        original_path="/b/second.txt",
        quarantine_path="/trash/second__22222222.txt",
    )

    rows = read_model.get_quarantine_entries()
    assert [row.original_path for row in rows] == ["/b/second.txt", "/a/first.txt"]


def test_quarantine_row_fields_map_from_real_record(rm) -> None:
    read_model, _, _, _, _, _, quarantine = rm
    quarantine.record_quarantine(
        original_path="/home/nathan/notes.txt",
        quarantine_path="/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt",
        session_id=7,
    )

    row = read_model.get_quarantine_entries()[0]
    assert row.original_path == "/home/nathan/notes.txt"
    assert row.quarantine_path == "/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt"
    assert row.quarantine_name == "notes__a1b2c3d4.txt"
    assert row.session_id == 7
    assert row.quarantined_at is not None


def test_quarantine_row_session_id_defaults_to_none(rm) -> None:
    read_model, _, _, _, _, _, quarantine = rm
    quarantine.record_quarantine(
        original_path="/a/notes.txt",
        quarantine_path="/trash/notes__11111111.txt",
    )

    row = read_model.get_quarantine_entries()[0]
    assert row.session_id is None


def test_get_quarantine_entries_respects_limit(rm) -> None:
    read_model, _, _, _, _, _, quarantine = rm
    for i in range(5):
        quarantine.record_quarantine(
            original_path=f"/a/file{i}.txt",
            quarantine_path=f"/trash/file{i}__{i:08d}.txt",
        )

    rows = read_model.get_quarantine_entries(limit=2)
    assert len(rows) == 2


# --- get_quarantine_summary (Phase 66, Batch 1) ---------------------------------


def test_quarantine_summary_reports_real_total_count(rm) -> None:
    read_model, _, _, _, _, _, quarantine = rm
    quarantine.record_quarantine(
        original_path="/a/first.txt", quarantine_path="/trash/first__1.txt"
    )
    quarantine.record_quarantine(
        original_path="/b/second.txt", quarantine_path="/trash/second__2.txt"
    )

    summary = read_model.get_quarantine_summary()
    assert summary.total_count == 2


def test_quarantine_summary_reports_real_latest_timestamp(rm) -> None:
    """Compares against list_recent()'s own re-queried value (not the
    freshly-created record.quarantined_at) since a freshly-flushed
    record's timestamp is still timezone-aware while a value re-read
    from SQLite comes back naive - the same documented UTC-in-substance-
    but-naive-on-reload quirk every other timestamp in this project
    already has (see docs/phase_19_implementation_plan.md section 8/12).
    """
    read_model, _, _, _, _, _, quarantine = rm
    quarantine.record_quarantine(
        original_path="/a/first.txt", quarantine_path="/trash/first__1.txt"
    )
    quarantine.record_quarantine(
        original_path="/b/second.txt", quarantine_path="/trash/second__2.txt"
    )
    expected = quarantine.list_recent(limit=1)[0].quarantined_at

    summary = read_model.get_quarantine_summary()
    assert summary.latest_quarantined_at == expected


def test_quarantine_summary_empty_store_reports_honest_zero_and_none(rm) -> None:
    read_model, *_ = rm

    summary = read_model.get_quarantine_summary()
    assert summary.total_count == 0
    assert summary.latest_quarantined_at is None


def test_quarantine_summary_no_store_supplied_reports_honest_zero_and_none(
    rm,
) -> None:
    """Backward compatible with any caller predating Phase 39: no
    QuarantineStore supplied at all must return the same honest empty
    summary as an empty store, never fail."""
    from dashboard.read_model import DashboardReadModel

    read_model, memory, approvals, workflows, inbox, schedules, _ = rm
    no_quarantine_model = DashboardReadModel(
        memory, approvals, workflows, inbox, schedules
    )
    summary = no_quarantine_model.get_quarantine_summary()
    assert summary.total_count == 0
    assert summary.latest_quarantined_at is None


def test_quarantine_summary_does_not_mutate_quarantine_state(rm) -> None:
    read_model, _, _, _, _, _, quarantine = rm
    quarantine.record_quarantine(
        original_path="/a/notes.txt", quarantine_path="/trash/notes__1.txt"
    )
    before = len(quarantine.list_recent())

    read_model.get_quarantine_summary()

    assert len(quarantine.list_recent()) == before


def test_quarantine_summary_total_matches_real_quarantine_count(rm) -> None:
    read_model, _, _, _, _, _, quarantine = rm
    for i in range(5):
        quarantine.record_quarantine(
            original_path=f"/a/file{i}.txt",
            quarantine_path=f"/trash/file{i}__{i:08d}.txt",
        )

    summary = read_model.get_quarantine_summary()
    assert summary.total_count == quarantine.count()


# --- get_system_status (Phase 62, Batch 1) --------------------------------------


def test_system_status_maps_from_real_settings() -> None:
    settings = _test_settings(
        ai_model="claude-test-model",
        ai_reasoning_enabled=True,
        voice_enabled=True,
        voice_provider="fake",
        voice_input_enabled=True,
        voice_input_provider="fake",
        log_level="DEBUG",
        approval_timeout_seconds=45,
        database_path=Path("data/test_jarvis.db"),
    )
    read_model, *_ = _make_read_model_with_settings(settings)

    status = read_model.get_system_status()

    assert status.available is True
    assert status.ai_reasoning_enabled is True
    assert status.ai_model == "claude-test-model"
    assert status.voice_enabled is True
    assert status.voice_provider == "fake"
    assert status.voice_input_enabled is True
    assert status.voice_input_provider == "fake"
    assert status.log_level == "DEBUG"
    assert status.database_path == str(Path("data/test_jarvis.db"))
    assert status.approval_timeout_seconds == 45
    assert status.api_key_status == "configured"


def test_system_status_reports_api_key_not_configured_when_blank() -> None:
    settings = _test_settings(anthropic_api_key="   ")
    read_model, *_ = _make_read_model_with_settings(settings)

    status = read_model.get_system_status()
    assert status.api_key_status == "not configured"


def test_system_status_never_exposes_api_key_value_mask_length_or_hash() -> None:
    secret = "sk-super-secret-value-should-never-appear-anywhere"
    settings = _test_settings(anthropic_api_key=secret)
    read_model, *_ = _make_read_model_with_settings(settings)

    status = read_model.get_system_status()
    rendered = " ".join(str(value) for value in asdict(status).values())

    assert secret not in rendered
    assert str(len(secret)) not in rendered
    assert hashlib.sha256(secret.encode()).hexdigest() not in rendered
    assert hashlib.md5(secret.encode()).hexdigest() not in rendered  # noqa: S324


def test_system_status_unavailable_when_no_settings_configured() -> None:
    read_model, *_ = _make_read_model_with_settings(None)

    status = read_model.get_system_status()

    assert status.available is False
    assert status.ai_reasoning_enabled is None
    assert status.ai_model is None
    assert status.voice_enabled is None
    assert status.voice_provider is None
    assert status.voice_input_enabled is None
    assert status.voice_input_provider is None
    assert status.log_level is None
    assert status.database_path is None
    assert status.approval_timeout_seconds is None
    assert status.api_key_status is None


# --- get_store_reachability (Phase 62, Batch 1) ---------------------------------


def test_store_reachability_reports_reachable_for_real_stores() -> None:
    read_model, *_ = _make_read_model_with_settings(None)

    results = {row.name: row for row in read_model.get_store_reachability()}

    assert results["memory"].reachable is True
    assert results["approvals"].reachable is True
    assert results["workflow_history"].reachable is True
    assert results["inbox"].reachable is True
    assert results["schedules"].reachable is True
    assert results["quarantine"].reachable is True
    for row in results.values():
        assert row.detail is None


def test_store_reachability_reports_not_reachable_for_a_raising_store_without_breaking_others() -> (
    None
):
    _, _, approvals, workflows, inbox, schedules, quarantine = (
        _make_read_model_with_settings(None)
    )
    read_model = DashboardReadModel(
        _RaisingMemoryManager(),  # type: ignore[arg-type]
        approvals,
        workflows,
        inbox,
        schedules,
        quarantine,
    )

    results = {row.name: row for row in read_model.get_store_reachability()}

    assert results["memory"].reachable is False
    assert "simulated memory read failure" in (results["memory"].detail or "")
    assert results["approvals"].reachable is True
    assert results["workflow_history"].reachable is True
    assert results["inbox"].reachable is True
    assert results["schedules"].reachable is True
    assert results["quarantine"].reachable is True


def test_store_reachability_quarantine_not_configured_is_honest_not_reachable() -> (
    None
):
    _, memory, approvals, workflows, inbox, schedules, _ = (
        _make_read_model_with_settings(None)
    )
    read_model_no_quarantine = DashboardReadModel(
        memory, approvals, workflows, inbox, schedules
    )

    results = {
        row.name: row for row in read_model_no_quarantine.get_store_reachability()
    }

    assert results["quarantine"].reachable is False
    assert results["quarantine"].detail == "not configured"


def test_store_reachability_never_mutates_any_store() -> None:
    read_model, memory, approvals, workflows, inbox, schedules, quarantine = (
        _make_read_model_with_settings(None)
    )
    memory.save("existing memory")
    inbox.append(source_type="web_search_summary", source_query="q", body="b")
    before = (
        memory.count(),
        inbox.count(),
        len(schedules.list_all()),
        len(quarantine.list_recent()),
    )

    read_model.get_store_reachability()

    after = (
        memory.count(),
        inbox.count(),
        len(schedules.list_all()),
        len(quarantine.list_recent()),
    )
    assert before == after


# --- get_recent_activity (Phase 62, Batch 1) ------------------------------------


def test_recent_activity_merges_multiple_domains() -> None:
    read_model, memory, approvals, workflows, inbox, _, quarantine = (
        _make_read_model_with_settings(None)
    )
    memory.save("buy milk")
    approvals.record_request(
        request_id="req-1", action="delete file", reason="r", security_tier="yellow"
    )
    workflows.record_transition(workflow_id="wf-1", status="workflow_started")
    inbox.append(source_type="web_search_summary", source_query="q", body="b")
    quarantine.record_quarantine(
        original_path="/a/notes.txt", quarantine_path="/trash/notes__1.txt"
    )

    rows = read_model.get_recent_activity()

    domains = {row.domain for row in rows}
    assert domains == {"memory", "approval", "workflow", "inbox", "quarantine"}


def test_recent_activity_sorts_by_timestamp_descending() -> None:
    read_model, memory, *_ = _make_read_model_with_settings(None)
    memory.save("first")
    memory.save("second")
    memory.save("third")

    rows = read_model.get_recent_activity()

    timestamps = [row.created_at for row in rows]
    assert timestamps == sorted(timestamps, reverse=True)


def test_recent_activity_respects_the_cap() -> None:
    read_model, memory, *_ = _make_read_model_with_settings(None)
    for i in range(10):
        memory.save(f"memory {i}")

    rows = read_model.get_recent_activity(limit=3)
    assert len(rows) == 3


def test_recent_activity_summary_is_deterministic_and_traceable_to_real_fields() -> (
    None
):
    read_model, memory, *_ = _make_read_model_with_settings(None)
    memory.save("a very specific note about the quarterly budget")

    first = read_model.get_recent_activity()
    second = read_model.get_recent_activity()

    assert first == second
    memory_entry = next(row for row in first if row.domain == "memory")
    assert "quarterly budget" in memory_entry.summary


def test_recent_activity_empty_when_no_data_exists() -> None:
    read_model, *_ = _make_read_model_with_settings(None)
    assert read_model.get_recent_activity() == []


def test_recent_activity_omits_a_domain_with_no_data() -> None:
    read_model, memory, *_ = _make_read_model_with_settings(None)
    memory.save("only a memory exists")

    rows = read_model.get_recent_activity()

    domains = {row.domain for row in rows}
    assert domains == {"memory"}


def test_recent_activity_never_uses_ai_or_fabricated_text() -> None:
    """Structural proof: get_recent_activity() never imports or calls
    anything AI-related - its summaries are plain string formatting of
    already-real fields only."""
    source = inspect.getsource(read_model_module.DashboardReadModel.get_recent_activity)
    for forbidden in ("reason(", "AIReasoningEngine", "AIRouter", "reasoning"):
        assert forbidden not in source


# --- structural: no write path -------------------------------------------------

#: Method names, on any of the six stores, that imply a mutation. If
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
        "enable",
        "disable",
        "claim_due",
        "record_quarantine",
        # Deliberately NOT "append" or "create": InboxStore.append() and
        # ScheduleStore.create() are real write methods, but this AST scan
        # matches any Call(Attribute) node's attribute name regardless of
        # the object it's called on, and get_recent_workflows already
        # legitimately calls Python's own list.append() to build its
        # return value, while nothing in this module calls anything named
        # "create" at all today - included here as a deliberately absent
        # entry, not an oversight. test_read_model_module_never_calls_
        # inbox_append and test_read_model_module_never_calls_schedule_
        # mutating_methods below prove the InboxStore/ScheduleStore-
        # specific cases precisely instead.
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


def test_read_model_module_never_calls_schedule_create() -> None:
    """Precise structural proof for ScheduleStore.create() specifically -
    the generic _WRITE_METHOD_NAMES scan above deliberately omits "create"
    since it is not otherwise a generic collision risk in this module, but
    this test still proves the specific `self._schedules.create(...)`
    shape never appears, for parity with the inbox_append proof below."""
    source = inspect.getsource(read_model_module)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "create":
            continue
        target = node.func.value
        is_self_schedules = (
            isinstance(target, ast.Attribute)
            and target.attr == "_schedules"
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        )
        assert not is_self_schedules, (
            "dashboard/read_model.py must never call self._schedules.create()"
        )


def test_read_model_module_never_calls_inbox_append() -> None:
    """Precise structural proof for InboxStore.append() specifically -
    unlike the generic _WRITE_METHOD_NAMES scan above, this only matches
    a call shaped exactly like `self._inbox.append(...)`, so it cannot be
    confused with the legitimate `list.append()` calls this module's
    get_recent_workflows already makes."""
    source = inspect.getsource(read_model_module)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "append":
            continue
        target = node.func.value
        is_self_inbox = (
            isinstance(target, ast.Attribute)
            and target.attr == "_inbox"
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        )
        assert not is_self_inbox, "dashboard/read_model.py must never call self._inbox.append()"


def test_read_model_module_imports_no_execution_component() -> None:
    """Structural proof that dashboard/read_model.py cannot reach
    CommandRouter, ToolExecutor, the live ApprovalManager, WorkflowEngine,
    AIReasoningEngine, AIRouter, or WebSearchTool - it only imports the
    five approved read-side managers/stores."""
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
        # Phase 22: the Overview's scheduled-inbox total/latest timestamp
        # comes from InboxStore.count_since() only - this read model must
        # never import or depend on the CLI's own last-seen marker store.
        "ScheduledInboxNoticeStore",
    }
    assert imported_names & forbidden == set()
