"""
test_dashboard_app.py

Tests for ui/dashboard_app.py (Phase 19, Batch 2; extended Phase 39,
Batch 2 with the Quarantine tab; extended across the Phase 62-66
"Visible Jarvis Dashboard" upgrade series with a Category/Status/
Source/Enabled-Disabled Breakdown panel or Summary panel and richer
selection detail on most tabs; Phase 67 made a wording-only
consistency pass, adding no new behavior): the tkinter/ttk presentation
layer for the local, read-only Jarvis dashboard.

Most assertions are pure state/view-model/render-structure checks (no Tk
instantiation) per the authorizing instructions' preference against
brittle pixel-perfect screenshot tests. A smaller set of tests build a
real, withdrawn (never shown) Tk root - a standard, accepted pattern for
testing tkinter code - to confirm actual widget wiring: tabs exist, rows
render, refresh replaces stale state, errors are isolated per panel, and
no forbidden callback or import exists.

Run with:
    pytest tests/unit/test_dashboard_app.py
"""

from __future__ import annotations

import ast
import inspect
import time
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine

from approval.approval_history_store import ApprovalHistoryStore
from config.settings import Settings
from dashboard.read_model import (
    ActivityRow,
    ApprovalRow,
    ApprovalStatusCount,
    BrainStatus,
    DashboardOverview,
    DashboardReadModel,
    DashboardSystemStatus,
    InboxRow,
    InboxSourceTypeCount,
    MemoryCategoryCount,
    MemoryRow,
    QuarantineRow,
    QuarantineSummary,
    ScheduleRow,
    ScheduleStatusCount,
    StoreReachability,
    WorkflowRow,
    WorkflowStatusCount,
    WorkflowTransitionRow,
)
from inbox.inbox_store import InboxStore
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from quarantine.quarantine_store import QuarantineStore
from scheduling.schedule_store import ScheduleStore
from storage.database import create_session_factory, initialize_database
from workflow.workflow_history_store import WorkflowHistoryStore

import ui.dashboard_app as dashboard_app_module
from ui.dashboard_app import (
    BRAIN_CAPTION,
    BRAIN_HEADER,
    BRAIN_KNOWN_LIMITS,
    BRAIN_PROMPT_STUDIO_CAPTION,
    BRAIN_PROMPT_STUDIO_COMMANDS,
    DashboardApp,
    OVERVIEW_HEADER,
    WINDOW_TITLE,
    activity_row_to_tree_values,
    approval_detail_text,
    approval_status_breakdown_line,
    brain_memory_line,
    format_error_state,
    format_timestamp,
    inbox_detail_text,
    inbox_source_type_breakdown_line,
    memory_category_breakdown_line,
    memory_detail_text,
    memory_row_to_tree_values,
    approval_row_to_tree_values,
    overview_summary_lines,
    quarantine_row_to_tree_values,
    quarantine_summary_lines,
    schedule_enabled_breakdown_line,
    schedule_row_to_tree_values,
    store_reachability_line,
    system_status_lines,
    workflow_row_to_tree_values,
    workflow_status_breakdown_line,
    workflow_transition_row_to_tree_values,
)


#: This environment intermittently raises a transient TclError on the
#: very first tk.Tk() call of a process ("Can't find a usable init.tcl" /
#: "invalid command name tcl_findLibrary"), confirmed NOT to be caused by
#: repeated create/destroy cycles (a bare script creating ten Tk roots in
#: a row succeeds reliably) - it reproduces only intermittently, somewhere
#: in this test suite's much larger import graph. This matches a known
#: class of Windows flakiness where a real-time antivirus scan
#: transiently locks a just-touched file (here, Tcl's own init.tcl) at
#: the moment it is opened. A short, bounded retry is the standard,
#: honest mitigation for that class of transient OS-level failure - it
#: does not paper over a real defect in this module's own code, which the
#: many non-Tk tests above already prove correct independent of Tk
#: entirely.
_TK_CREATE_RETRIES = 3
_TK_CREATE_RETRY_DELAY_SECONDS = 0.2


def _create_tk_root_with_retry() -> tk.Tk:
    last_error: tk.TclError | None = None
    for _ in range(_TK_CREATE_RETRIES):
        try:
            return tk.Tk()
        except tk.TclError as exc:
            last_error = exc
            time.sleep(_TK_CREATE_RETRY_DELAY_SECONDS)
    assert last_error is not None
    raise last_error


def _tk_available() -> bool:
    """Whether a real Tk root can be constructed in this environment."""
    try:
        root = _create_tk_root_with_retry()
        root.destroy()
        return True
    except tk.TclError:
        return False


_TK_AVAILABLE = _tk_available()
requires_tk = pytest.mark.skipif(not _TK_AVAILABLE, reason="no Tk display available")


def _make_real_stack() -> tuple[
    DashboardReadModel,
    MemoryManager,
    ApprovalHistoryStore,
    WorkflowHistoryStore,
    InboxStore,
    ScheduleStore,
    QuarantineStore,
]:
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    memory = MemoryManager(EpisodicMemoryStore(factory))
    approvals = ApprovalHistoryStore(factory)
    workflows = WorkflowHistoryStore(factory)
    inbox = InboxStore(factory)
    schedules = ScheduleStore(factory)
    quarantine = QuarantineStore(factory)
    return (
        DashboardReadModel(
            memory, approvals, workflows, inbox, schedules, quarantine
        ),
        memory,
        approvals,
        workflows,
        inbox,
        schedules,
        quarantine,
    )


def _make_real_stack_with_settings(
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
    """Build the same real stack _make_real_stack() does, but also
    threading a Settings object through (Phase 62, Batch 3) - kept
    separate so _make_real_stack()'s own 7-tuple shape and every
    existing test destructuring it are completely unaffected."""
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    memory = MemoryManager(EpisodicMemoryStore(factory))
    approvals = ApprovalHistoryStore(factory)
    workflows = WorkflowHistoryStore(factory)
    inbox = InboxStore(factory)
    schedules = ScheduleStore(factory)
    quarantine = QuarantineStore(factory)
    return (
        DashboardReadModel(
            memory, approvals, workflows, inbox, schedules, quarantine, settings
        ),
        memory,
        approvals,
        workflows,
        inbox,
        schedules,
        quarantine,
    )


def _test_settings(**overrides: object) -> Settings:
    """Build a real Settings object for Phase 62, Batch 3 smoke tests,
    mirroring test_dashboard_read_model.py's own established
    _test_settings() helper pattern."""
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


class _RaisingReadModel:
    """A duck-typed stand-in that raises on every query, to test error isolation."""

    def get_overview(self) -> DashboardOverview:
        raise RuntimeError("simulated overview failure")

    def get_recent_memories(self, limit: int = 20, *, category: str | None = None):
        raise RuntimeError("simulated memory query failure")

    def get_recent_approvals(self, limit: int = 20):
        raise RuntimeError("simulated approval query failure")

    def get_recent_workflows(self, limit: int = 10):
        raise RuntimeError("simulated workflow query failure")

    def get_workflow_transitions(self, workflow_id: str, limit: int = 50):
        raise RuntimeError("simulated transitions query failure")

    def get_recent_inbox_entries(self, limit: int = 20):
        raise RuntimeError("simulated inbox query failure")

    def get_schedules(self, limit: int = 50):
        raise RuntimeError("simulated schedules query failure")

    def get_quarantine_entries(self, limit: int = 50):
        raise RuntimeError("simulated quarantine query failure")

    def get_quarantine_summary(self):
        raise RuntimeError("simulated quarantine summary query failure")

    def get_system_status(self):
        raise RuntimeError("simulated system status query failure")

    def get_store_reachability(self):
        raise RuntimeError("simulated store reachability query failure")

    def get_recent_activity(self, limit: int = 20):
        raise RuntimeError("simulated recent activity query failure")

    def get_memory_category_breakdown(self):
        raise RuntimeError("simulated memory category breakdown query failure")

    def get_approval_status_breakdown(self):
        raise RuntimeError("simulated approval status breakdown query failure")

    def get_workflow_status_breakdown(self, limit: int = 10):
        raise RuntimeError("simulated workflow status breakdown query failure")

    def get_inbox_source_type_breakdown(self):
        raise RuntimeError("simulated inbox source type breakdown query failure")

    def get_schedule_enabled_breakdown(self, limit: int = 50):
        raise RuntimeError("simulated schedule enabled breakdown query failure")

    def get_brain_status(self):
        raise RuntimeError("simulated brain status query failure")


# --- pure formatting/mapping functions (no Tk) --------------------------------


def test_format_timestamp_appends_literal_utc_suffix() -> None:
    naive = datetime(2026, 7, 10, 12, 30, 45)
    assert format_timestamp(naive) == "2026-07-10 12:30:45 UTC"


def test_format_timestamp_does_not_rely_on_tzinfo() -> None:
    """Whether the value is naive or aware, the literal suffix is the
    same - it is never derived from value.tzinfo."""
    naive = datetime(2026, 7, 10, 12, 30, 45)
    aware = datetime(2026, 7, 10, 12, 30, 45, tzinfo=timezone.utc)
    assert format_timestamp(naive) == format_timestamp(aware)


def test_format_error_state_names_the_domain_and_reason() -> None:
    message = format_error_state("memories", RuntimeError("db locked"))
    assert message == "Could not read memories: db locked"


def test_memory_row_to_tree_values_maps_real_fields() -> None:
    row = MemoryRow(
        id=3,
        category="project",
        preview="short preview",
        full_content="short preview",
        created_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    values = memory_row_to_tree_values(row)
    assert values == ("3", "project", "short preview", "2026-01-01 00:00:00 UTC")


def test_memory_category_breakdown_line_formats_real_count() -> None:
    row = MemoryCategoryCount(category="project", count=3)
    assert memory_category_breakdown_line(row) == "project: 3"


def test_memory_category_breakdown_line_formats_honest_zero() -> None:
    row = MemoryCategoryCount(category="personal", count=0)
    assert memory_category_breakdown_line(row) == "personal: 0"


def test_memory_detail_text_includes_id_category_created_at_and_full_content() -> (
    None
):
    row = MemoryRow(
        id=7,
        category="project",
        preview="buy milk",
        full_content="buy milk",
        created_at=datetime(2026, 1, 1, 12, 0, 0),
    )
    text = memory_detail_text(row)
    assert "ID: 7" in text
    assert "Category: project" in text
    assert "2026-01-01 12:00:00 UTC" in text
    assert "buy milk" in text


def test_memory_detail_text_never_truncates_full_content() -> None:
    long_content = "z" * 500
    row = MemoryRow(
        id=1,
        category="general",
        preview=long_content[:120] + "...",
        full_content=long_content,
        created_at=datetime(2026, 1, 1),
    )
    assert long_content in memory_detail_text(row)


def test_approval_status_breakdown_line_formats_real_count() -> None:
    row = ApprovalStatusCount(status="approved", count=3)
    assert approval_status_breakdown_line(row) == "approved: 3"


def test_approval_status_breakdown_line_formats_honest_zero() -> None:
    row = ApprovalStatusCount(status="expired", count=0)
    assert approval_status_breakdown_line(row) == "expired: 0"


def test_brain_memory_line_formats_real_count() -> None:
    brain = BrainStatus(
        system_status=DashboardSystemStatus(available=False),
        memory_count=3,
        approval_breakdown=(),
        workflow_breakdown=(),
    )
    assert brain_memory_line(brain) == "Total memories stored: 3"


def test_brain_memory_line_formats_honest_zero() -> None:
    brain = BrainStatus(
        system_status=DashboardSystemStatus(available=False),
        memory_count=0,
        approval_breakdown=(),
        workflow_breakdown=(),
    )
    assert brain_memory_line(brain) == "Total memories stored: 0"


def test_workflow_status_breakdown_line_formats_real_count() -> None:
    row = WorkflowStatusCount(status="workflow_completed", count=2)
    assert workflow_status_breakdown_line(row) == "workflow_completed: 2"


def test_workflow_status_breakdown_line_formats_honest_zero() -> None:
    row = WorkflowStatusCount(status="workflow_stopped", count=0)
    assert workflow_status_breakdown_line(row) == "workflow_stopped: 0"


def test_approval_detail_text_includes_all_real_fields() -> None:
    row = ApprovalRow(
        request_id="req-1",
        action="delete file",
        security_tier="yellow",
        status="approved",
        created_at=datetime(2026, 1, 1, 0, 0, 0),
        decided_at=datetime(2026, 1, 1, 0, 5, 0),
        decided_by="user",
        reason="Deleting a file changes state and should be confirmed.",
        decision_reason="looks safe",
    )
    text = approval_detail_text(row)
    assert "Request ID: req-1" in text
    assert "Action: delete file" in text
    assert "Tier: yellow" in text
    assert "Status: approved" in text
    assert "Reason: Deleting a file changes state and should be confirmed." in text
    assert "Decision reason: looks safe" in text
    assert "2026-01-01 00:00:00 UTC" in text
    assert "2026-01-01 00:05:00 UTC" in text
    assert "user" in text


def test_inbox_source_type_breakdown_line_formats_real_count() -> None:
    row = InboxSourceTypeCount(source_type="web_search_summary", count=3)
    assert inbox_source_type_breakdown_line(row) == "web_search_summary: 3"


def test_inbox_source_type_breakdown_line_formats_honest_zero() -> None:
    row = InboxSourceTypeCount(source_type="webpage_summary", count=0)
    assert inbox_source_type_breakdown_line(row) == "webpage_summary: 0"


def test_schedule_enabled_breakdown_line_formats_enabled_count() -> None:
    row = ScheduleStatusCount(enabled=True, count=2)
    assert schedule_enabled_breakdown_line(row) == "enabled: 2"


def test_schedule_enabled_breakdown_line_formats_disabled_honest_zero() -> None:
    row = ScheduleStatusCount(enabled=False, count=0)
    assert schedule_enabled_breakdown_line(row) == "disabled: 0"


def test_inbox_detail_text_includes_all_real_fields() -> None:
    row = InboxRow(
        id=5,
        source_query="jarvis news",
        preview="A synthesis.",
        full_body="[AI web search summary] A synthesis.",
        included_count=4,
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        source_type="web_search_summary",
    )
    text = inbox_detail_text(row)
    assert "Source type: web_search_summary" in text
    assert "Source query: jarvis news" in text
    assert "2026-01-01 12:00:00 UTC" in text
    assert "Included count: 4" in text
    assert "[AI web search summary] A synthesis." in text


def test_inbox_detail_text_shows_dash_for_missing_included_count() -> None:
    row = InboxRow(
        id=1,
        source_query="q",
        preview="b",
        full_body="b",
        included_count=None,
        created_at=datetime(2026, 1, 1),
        source_type="webpage_summary",
    )
    text = inbox_detail_text(row)
    assert "Included count: —" in text


def test_inbox_detail_text_shows_dash_for_missing_source_type() -> None:
    """Backward compatibility: InboxRow.source_type defaults to "" for
    any call site predating Phase 65 - the detail pane must render an
    honest "—" rather than a blank or fabricated value."""
    row = InboxRow(
        id=1,
        source_query="q",
        preview="b",
        full_body="b",
        included_count=None,
        created_at=datetime(2026, 1, 1),
    )
    text = inbox_detail_text(row)
    assert "Source type: —" in text


def test_inbox_detail_text_never_truncates_full_body() -> None:
    long_body = "z" * 500
    row = InboxRow(
        id=1,
        source_query="q",
        preview=long_body[:120] + "...",
        full_body=long_body,
        included_count=None,
        created_at=datetime(2026, 1, 1),
        source_type="web_search_summary",
    )
    assert long_body in inbox_detail_text(row)


def test_approval_detail_text_shows_placeholder_for_missing_decision_reason() -> None:
    row = ApprovalRow(
        request_id="req-1",
        action="delete file",
        security_tier="yellow",
        status="pending",
        created_at=datetime(2026, 1, 1, 0, 0, 0),
        decided_at=None,
        decided_by=None,
        reason="r",
        decision_reason=None,
    )
    text = approval_detail_text(row)
    assert "Decision reason: —" in text
    assert "Decided: —" in text
    assert "Decided by: —" in text


def test_approval_row_to_tree_values_shows_placeholder_for_undecided() -> None:
    row = ApprovalRow(
        request_id="req-1",
        action="delete file",
        security_tier="yellow",
        status="pending",
        created_at=datetime(2026, 1, 1, 0, 0, 0),
        decided_at=None,
        decided_by=None,
    )
    values = approval_row_to_tree_values(row)
    assert values[-2:] == ("—", "—")


def test_approval_row_to_tree_values_shows_decision_when_present() -> None:
    row = ApprovalRow(
        request_id="req-1",
        action="delete file",
        security_tier="yellow",
        status="approved",
        created_at=datetime(2026, 1, 1, 0, 0, 0),
        decided_at=datetime(2026, 1, 1, 0, 5, 0),
        decided_by="user",
    )
    values = approval_row_to_tree_values(row)
    assert values[-2:] == ("2026-01-01 00:05:00 UTC", "user")


def test_workflow_row_to_tree_values_formats_step_fraction() -> None:
    row = WorkflowRow(
        workflow_id="wf-1",
        latest_status="workflow_step_waiting",
        latest_step_number=2,
        latest_step_total=3,
        latest_created_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    values = workflow_row_to_tree_values(row)
    assert values[2] == "2/3"


def test_workflow_row_to_tree_values_shows_placeholder_with_no_step() -> None:
    row = WorkflowRow(
        workflow_id="wf-1",
        latest_status="workflow_started",
        latest_step_number=None,
        latest_step_total=None,
        latest_created_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    values = workflow_row_to_tree_values(row)
    assert values[2] == "—"


def test_workflow_transition_row_to_tree_values_shows_tool_name() -> None:
    row = WorkflowTransitionRow(
        status="workflow_step_completed",
        step_number=1,
        step_total=2,
        tool_name="memory",
        detail=None,
        created_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    values = workflow_transition_row_to_tree_values(row)
    assert values == (
        "workflow_step_completed",
        "1/2",
        "memory",
        "2026-01-01 00:00:00 UTC",
        "—",
    )


def test_workflow_transition_row_to_tree_values_shows_approval_request_id_when_present() -> (
    None
):
    row = WorkflowTransitionRow(
        status="workflow_step_waiting",
        step_number=1,
        step_total=2,
        tool_name="file_delete",
        detail=None,
        created_at=datetime(2026, 1, 1, 0, 0, 0),
        approval_request_id="req-1",
    )
    values = workflow_transition_row_to_tree_values(row)
    assert values[-1] == "req-1"


def test_schedule_row_to_tree_values_maps_real_fields() -> None:
    row = ScheduleRow(
        id=3,
        name="Morning news",
        query_preview="jarvis ai news",
        time_of_day="08:30",
        enabled=True,
        last_run_at=None,
        created_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    values = schedule_row_to_tree_values(row)
    assert values == (
        "3",
        "Morning news",
        "jarvis ai news",
        "08:30",
        "Yes",
        "—",
        "2026-01-01 00:00:00 UTC",
    )


def test_schedule_row_to_tree_values_shows_placeholders_for_no_name_or_last_run() -> None:
    row = ScheduleRow(
        id=1,
        name=None,
        query_preview="q",
        time_of_day="08:00",
        enabled=False,
        last_run_at=None,
        created_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    values = schedule_row_to_tree_values(row)
    assert values[1] == "—"
    assert values[4] == "No"
    assert values[5] == "—"


def test_quarantine_row_to_tree_values_maps_real_fields() -> None:
    row = QuarantineRow(
        quarantine_path="/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt",
        quarantine_name="notes__a1b2c3d4.txt",
        original_path="/home/nathan/notes.txt",
        quarantined_at=datetime(2026, 1, 1, 0, 0, 0),
        session_id=7,
    )
    values = quarantine_row_to_tree_values(row)
    assert values == (
        "notes__a1b2c3d4.txt",
        "/home/nathan/notes.txt",
        "/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt",
        "2026-01-01 00:00:00 UTC",
        "7",
    )


def test_quarantine_row_to_tree_values_shows_placeholder_for_no_session_id() -> None:
    row = QuarantineRow(
        quarantine_path="/trash/notes__1.txt",
        quarantine_name="notes__1.txt",
        original_path="/a/notes.txt",
        quarantined_at=datetime(2026, 1, 1, 0, 0, 0),
        session_id=None,
    )
    values = quarantine_row_to_tree_values(row)
    assert values[4] == "—"


def test_quarantine_summary_lines_show_real_count_and_timestamp() -> None:
    summary = QuarantineSummary(
        total_count=3, latest_quarantined_at=datetime(2026, 1, 1, 12, 0, 0)
    )
    lines = quarantine_summary_lines(summary)
    assert "Total quarantined files: 3" in lines
    assert "Most recently quarantined: 2026-01-01 12:00:00 UTC" in lines


def test_quarantine_summary_lines_show_honest_empty_state() -> None:
    summary = QuarantineSummary(total_count=0, latest_quarantined_at=None)
    lines = quarantine_summary_lines(summary)
    assert "Total quarantined files: 0" in lines
    assert "Most recently quarantined: —" in lines


def test_overview_summary_lines_contain_only_real_counts() -> None:
    overview = DashboardOverview(
        total_memory_count=7,
        recent_approvals=(),
        recent_workflows=(),
        total_inbox_count=3,
        recent_inbox_entries=(),
        total_scheduled_inbox_count=2,
        latest_scheduled_inbox_created_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    lines = overview_summary_lines(overview)
    assert lines == [
        "Total memories stored: 7",
        "Recent approval decisions shown below: 0",
        "Recently active workflows shown below: 0",
        "Total inbox entries: 3",
        "Scheduled inbox entries: 2 (most recent: 2026-01-01 00:00:00 UTC)",
    ]
    joined = " ".join(lines).lower()
    for forbidden in (
        "intelligence",
        "readiness",
        "confidence",
        "health score",
        "efficiency",
        "online",
        "offline",
        "unread",
        "dismiss",
        "since your last",
        "since you last",
    ):
        assert forbidden not in joined


# --- system_status_lines / store_reachability_line / activity_row_to_tree_values
# --- (Phase 62, Batch 2) --------------------------------------------------------


def test_system_status_lines_render_real_fields() -> None:
    status = DashboardSystemStatus(
        available=True,
        ai_reasoning_enabled=True,
        ai_model="claude-test-model",
        voice_enabled=False,
        voice_provider="none",
        voice_input_enabled=False,
        voice_input_provider="none",
        log_level="INFO",
        database_path="data/jarvis.db",
        approval_timeout_seconds=60,
        api_key_status="configured",
    )
    lines = system_status_lines(status)
    joined = "\n".join(lines)
    assert "AI reasoning enabled: True" in joined
    assert "AI model: claude-test-model" in joined
    assert "Log level: INFO" in joined
    assert "Database path: data/jarvis.db" in joined
    assert "Approval timeout (seconds): 60" in joined
    assert "Anthropic API key: configured" in joined


def test_system_status_lines_show_not_configured_when_api_key_absent() -> None:
    status = DashboardSystemStatus(available=True, api_key_status="not configured")
    lines = system_status_lines(status)
    assert "Anthropic API key: not configured" in "\n".join(lines)


def test_system_status_lines_never_show_api_key_value_mask_length_or_hash() -> None:
    import hashlib

    secret = "sk-super-secret-value-should-never-appear-in-the-ui"
    status = DashboardSystemStatus(
        available=True, ai_model="m", api_key_status="configured"
    )
    lines = system_status_lines(status)
    joined = "\n".join(lines)
    assert secret not in joined
    assert str(len(secret)) not in joined
    assert hashlib.sha256(secret.encode()).hexdigest() not in joined
    for forbidden in ("mask", "hash", "fingerprint", "sk-"):
        assert forbidden not in joined.lower()


def test_system_status_lines_honest_when_unavailable() -> None:
    status = DashboardSystemStatus(available=False)
    lines = system_status_lines(status)
    assert len(lines) == 1
    assert "unavailable" in lines[0].lower()


def test_store_reachability_line_formats_reachable_state() -> None:
    row = StoreReachability(name="memory", reachable=True)
    assert store_reachability_line(row) == "memory: reachable"


def test_store_reachability_line_formats_not_reachable_state_with_detail() -> None:
    row = StoreReachability(
        name="quarantine", reachable=False, detail="not configured"
    )
    assert store_reachability_line(row) == "quarantine: not reachable (not configured)"


def test_store_reachability_line_formats_workflow_history_label_readably() -> None:
    row = StoreReachability(name="workflow_history", reachable=True)
    assert store_reachability_line(row) == "workflow history: reachable"


def test_activity_row_to_tree_values_maps_real_fields() -> None:
    row = ActivityRow(
        domain="memory",
        summary="Saved memory (general): buy milk",
        created_at=datetime(2026, 1, 1, 12, 0, 0),
    )
    values = activity_row_to_tree_values(row)
    assert values == ("2026-01-01 12:00:00 UTC", "memory", "Saved memory (general): buy milk")


def test_activity_row_summary_is_never_ai_generated_language() -> None:
    """Structural sanity check mirroring the help_tool/health_check
    precedent: no activity summary wording resembles an AI disclaimer,
    since ActivityRow.summary is always plain string formatting."""
    row = ActivityRow(domain="inbox", summary="Saved inbox entry: q", created_at=datetime(2026, 1, 1))
    values = activity_row_to_tree_values(row)
    joined = " ".join(values).lower()
    for forbidden in ("[ai ", "advisory only", "readiness", "intelligence score"):
        assert forbidden not in joined


# --- structural: no forbidden import or callback ------------------------------


_FORBIDDEN_IMPORT_NAMES = {
    "CommandRouter",
    "ToolExecutor",
    "ApprovalManager",
    "WorkflowEngine",
    "AIReasoningEngine",
    "AIRouter",
    "WebSearchTool",
    # Phase 39: the Quarantine tab must display only what
    # DashboardReadModel.get_quarantine_entries() already returns - it
    # must never import a quarantine tool or store directly, which
    # would open a path to restoring/deleting/mutating quarantine state
    # from a "read-only" dashboard.
    "FileRestoreTool",
    "FileDeleteTool",
    "QuarantineListTool",
    "QuarantineStore",
    # Phase 87, Batch 2: the Brain tab must render only BrainStatus -
    # never a new dependency on main.py's composition root, the tool
    # registry, the CLI tool layer, or an AI-provider prompt-building
    # path. Its Known Limits/Prompt Studio sections are static,
    # hand-maintained text, never imported from
    # tools/builtin/jarvis_brain_tool.py or ai/prompt_studio.py.
    "ToolRegistry",
    "JarvisBrainStatusTool",
    "PromptBuilder",
}
_FORBIDDEN_MODULES = {
    "subprocess",
    "webbrowser",
    "os.system",
    # Phase 87, Batch 2.
    "git",
    "main",
    "tools.registry",
    "tools.builtin.jarvis_brain_tool",
    "ai.prompt_studio",
}


def test_dashboard_app_module_imports_no_execution_component() -> None:
    """Extended Phase 87, Batch 2 to also collect each ImportFrom's own
    module path (not just the imported symbol names), so a `from main
    import ...`- or `from tools.builtin.jarvis_brain_tool import ...`-
    shaped import would also be caught, not just a bare `import main`."""
    source = inspect.getsource(dashboard_app_module)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
            if node.module:
                imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)

    assert imported_names & _FORBIDDEN_IMPORT_NAMES == set()
    assert imported_modules & _FORBIDDEN_MODULES == set()


def test_dashboard_entry_point_imports_no_execution_component() -> None:
    import dashboard as dashboard_entry_point_module

    source = inspect.getsource(dashboard_entry_point_module)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)

    assert imported_names & (
        _FORBIDDEN_IMPORT_NAMES | {"JarvisOrchestrator", "JarvisCLI"}
    ) == set()


# --- real (withdrawn) Tk widget tests ------------------------------------------
#
# A single Tk interpreter is created once for this whole module and reused
# across every test (rather than a fresh tk.Tk() per test). Tcl's global
# library-loading state is not reliably safe under rapid repeated
# interpreter create/destroy cycles within one process - empirically
# confirmed in this environment (intermittent "Can't find a usable
# init.tcl" / "invalid command name tcl_findLibrary" errors when many
# tk.Tk() instances were each created and destroyed in quick succession).
# Reusing one root and destroying only its child widgets between tests is
# the standard, reliable pattern for testing tkinter code, and sidesteps
# that flakiness entirely. No test in this module calls mainloop() or
# update(), so a previous test's scheduled .after() callback is inert and
# never fires against a later test's (destroyed) widgets.


@pytest.fixture(scope="module")
def shared_root():
    if not _TK_AVAILABLE:
        pytest.skip("no Tk display available")
    root = _create_tk_root_with_retry()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture()
def root(shared_root: tk.Tk):
    for child in shared_root.winfo_children():
        child.destroy()
    yield shared_root


def _build_app(root: tk.Tk, read_model) -> DashboardApp:
    return DashboardApp(root, read_model)


class TestDashboardAppWithRealTk:
    def test_window_title_discloses_read_only(self, root: tk.Tk) -> None:
        read_model, *_ = _make_real_stack()
        _build_app(root, read_model)
        assert root.title() == WINDOW_TITLE
        assert "read-only" in WINDOW_TITLE.lower()

    def test_eight_tabs_exist(self, root: tk.Tk) -> None:
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)
        tab_texts = [
            app._notebook.tab(tab_id, "text") for tab_id in app._notebook.tabs()
        ]
        assert tab_texts == [
            "Overview",
            "Memories",
            "Approval History",
            "Workflow History",
            "Inbox",
            "Schedules",
            "Quarantine",
            "Brain",
        ]

    def test_memory_rows_render_real_data(self, root: tk.Tk) -> None:
        read_model, memory, _, _, _, _, _ = _make_real_stack()
        memory.save("first memory", category="project")
        app = _build_app(root, read_model)
        children = app._memory_tree.get_children()
        assert len(children) == 1
        values = app._memory_tree.item(children[0], "values")
        assert values[1] == "project"
        assert values[2] == "first memory"

    def test_empty_states_render_honest_messages(self, root: tk.Tk) -> None:
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)
        memory_values = app._memory_tree.item(
            app._memory_tree.get_children()[0], "values"
        )
        approval_values = app._approval_tree.item(
            app._approval_tree.get_children()[0], "values"
        )
        workflow_values = app._workflow_tree.item(
            app._workflow_tree.get_children()[0], "values"
        )
        inbox_values = app._inbox_tree.item(app._inbox_tree.get_children()[0], "values")
        schedules_values = app._schedules_tree.item(
            app._schedules_tree.get_children()[0], "values"
        )
        quarantine_values = app._quarantine_tree.item(
            app._quarantine_tree.get_children()[0], "values"
        )
        assert memory_values[0] == "No memories stored yet."
        assert approval_values[0] == "No approval decisions recorded yet."
        assert workflow_values[0] == "No workflow activity recorded yet."
        assert inbox_values[0] == "No inbox entries yet."
        assert schedules_values[0] == "No schedules configured yet."
        assert quarantine_values[0] == "No files currently in quarantine."

    def test_approval_history_wording_does_not_claim_live_pending_state(self) -> None:
        from ui.dashboard_app import APPROVAL_HISTORY_CAPTION

        lowered = APPROVAL_HISTORY_CAPTION.lower()
        for forbidden in (
            "active pending approvals",
            "awaiting your approval",
            "pending now",
        ):
            assert forbidden not in lowered
        assert "not a live list" in lowered

    def test_workflow_history_wording_does_not_imply_resumability(self) -> None:
        from ui.dashboard_app import WORKFLOW_HISTORY_CAPTION

        assert "not resumable" in WORKFLOW_HISTORY_CAPTION.lower()
        assert "not executable" in WORKFLOW_HISTORY_CAPTION.lower()

    def test_refresh_replaces_stale_state(self, root: tk.Tk) -> None:
        read_model, memory, _, _, _, _, _ = _make_real_stack()
        app = _build_app(root, read_model)
        assert (
            app._memory_tree.item(app._memory_tree.get_children()[0], "values")[0]
            == "No memories stored yet."
        )
        memory.save("newly added")
        app.refresh_all()
        children = app._memory_tree.get_children()
        assert len(children) == 1
        values = app._memory_tree.item(children[0], "values")
        assert values[2] == "newly added"

    def test_error_state_renders_without_crashing(self, root: tk.Tk) -> None:
        app = _build_app(root, _RaisingReadModel())
        assert "Could not read overview" in app._overview_error_var.get()
        assert "Could not read memories" in app._memory_error_var.get()
        assert "Could not read approval history" in app._approval_error_var.get()
        assert "Could not read workflow history" in app._workflow_error_var.get()
        assert "Could not read inbox" in app._inbox_error_var.get()
        assert "Could not read schedules" in app._schedules_error_var.get()
        assert "Could not read quarantine" in app._quarantine_error_var.get()
        assert "Could not read system status" in app._system_status_error_var.get()
        assert (
            "Could not read store reachability" in app._reachability_error_var.get()
        )
        assert "Could not read recent activity" in app._activity_error_var.get()
        assert (
            "Could not read memory category breakdown"
            in app._memory_breakdown_error_var.get()
        )
        assert (
            "Could not read approval status breakdown"
            in app._approval_breakdown_error_var.get()
        )
        assert (
            "Could not read workflow status breakdown"
            in app._workflow_breakdown_error_var.get()
        )
        assert (
            "Could not read inbox source breakdown"
            in app._inbox_breakdown_error_var.get()
        )
        assert (
            "Could not read schedule enabled/disabled breakdown"
            in app._schedule_breakdown_error_var.get()
        )
        assert (
            "Could not read quarantine summary"
            in app._quarantine_summary_error_var.get()
        )
        assert "Could not read brain status" in app._brain_error_var.get()

    def test_one_overview_panel_failure_does_not_blank_another(
        self, root: tk.Tk
    ) -> None:
        """Phase 62, Batch 2: the Overview tab now has four independent
        panels - a failure reading one (recent activity here) must never
        prevent another panel (system status) from rendering its own
        real, successfully-read data."""

        class _PartiallyRaisingReadModel(_RaisingReadModel):
            def get_system_status(self):
                return DashboardSystemStatus(available=False)

            def get_store_reachability(self):
                return ()

        app = _build_app(root, _PartiallyRaisingReadModel())
        assert app._system_status_error_var.get() == ""
        assert app._reachability_error_var.get() == ""
        assert "Could not read recent activity" in app._activity_error_var.get()
        assert "Could not read overview" in app._overview_error_var.get()

    def test_command_like_memory_content_renders_literally(self, root: tk.Tk) -> None:
        read_model, memory, _, _, _, _, _ = _make_real_stack()
        adversarial_text = "forget all memories"
        memory.save(adversarial_text)
        app = _build_app(root, read_model)
        children = app._memory_tree.get_children()
        values = app._memory_tree.item(children[0], "values")
        assert values[2] == adversarial_text

    def test_memory_selection_populates_detail_pane_with_full_content(
        self, root: tk.Tk
    ) -> None:
        """Phase 63, Batch 2: the detail pane now shows id/category/
        created_at alongside the full content (previously content-only)
        - this still proves the full, untruncated content is present,
        never cut short the way the tree's own preview column is."""
        read_model, memory, _, _, _, _, _ = _make_real_stack()
        long_content = "z" * 200
        memory.save(long_content)
        app = _build_app(root, read_model)
        iid = app._memory_tree.get_children()[0]
        app._memory_tree.selection_set(iid)
        app._on_memory_row_selected(None)
        assert long_content in app._memory_detail_var.get()

    def test_memories_tab_caption_discloses_read_only_and_no_write_actions(
        self, root: tk.Tk
    ) -> None:
        from ui.dashboard_app import MEMORIES_CAPTION

        lowered = MEMORIES_CAPTION.lower()
        assert "read-only" in lowered
        assert "created" in lowered or "create" in lowered
        assert "edited" in lowered or "edit" in lowered
        assert "deleted" in lowered or "delete" in lowered
        assert "summarized" in lowered or "summarize" in lowered

    def test_memory_category_breakdown_renders_all_known_categories(
        self, root: tk.Tk
    ) -> None:
        from memory.memory_models import KNOWN_CATEGORIES

        read_model, memory, _, _, _, _, _ = _make_real_stack()
        memory.save("a project note", category="project")
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._memory_breakdown_labels
        ]
        assert len(breakdown_texts) == len(KNOWN_CATEGORIES)
        assert "project: 1" in breakdown_texts
        # Every other known category is shown too, honestly at zero.
        for category in KNOWN_CATEGORIES:
            if category != "project":
                assert f"{category}: 0" in breakdown_texts

    def test_memory_category_breakdown_order_matches_known_categories_not_sorted_by_count(
        self, root: tk.Tk
    ) -> None:
        from memory.memory_models import KNOWN_CATEGORIES

        read_model, memory, _, _, _, _, _ = _make_real_stack()
        # Give the LAST known category the highest count, to prove the
        # rendered order is never resorted by count.
        for _ in range(5):
            memory.save("x", category=KNOWN_CATEGORIES[-1])
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._memory_breakdown_labels
        ]
        rendered_categories = [text.split(":")[0] for text in breakdown_texts]
        assert rendered_categories == list(KNOWN_CATEGORIES)

    def test_memory_category_breakdown_empty_store_shows_every_category_at_zero(
        self, root: tk.Tk
    ) -> None:
        from memory.memory_models import KNOWN_CATEGORIES

        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._memory_breakdown_labels
        ]
        for category in KNOWN_CATEGORIES:
            assert f"{category}: 0" in breakdown_texts
        assert app._memory_breakdown_error_var.get() == ""

    def test_approval_status_breakdown_renders_all_known_statuses(
        self, root: tk.Tk
    ) -> None:
        from approval.approval_history_store import KNOWN_APPROVAL_STATUSES

        read_model, _, approvals, _, _, _, _ = _make_real_stack()
        approvals.record_request(
            request_id="req-1", action="a", reason="r", security_tier="yellow"
        )
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._approval_breakdown_labels
        ]
        assert len(breakdown_texts) == len(KNOWN_APPROVAL_STATUSES)
        assert "pending: 1" in breakdown_texts

    def test_approval_status_breakdown_empty_store_shows_every_status_at_zero(
        self, root: tk.Tk
    ) -> None:
        from approval.approval_history_store import KNOWN_APPROVAL_STATUSES

        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._approval_breakdown_labels
        ]
        for status in KNOWN_APPROVAL_STATUSES:
            assert f"{status}: 0" in breakdown_texts
        assert app._approval_breakdown_error_var.get() == ""

    def test_approval_status_breakdown_order_not_sorted_by_count(
        self, root: tk.Tk
    ) -> None:
        from approval.approval_history_store import KNOWN_APPROVAL_STATUSES

        read_model, _, approvals, _, _, _, _ = _make_real_stack()
        for i in range(5):
            approvals.record_request(
                request_id=f"req-{i}", action="a", reason="r", security_tier="yellow"
            )
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._approval_breakdown_labels
        ]
        rendered_statuses = [text.split(":")[0] for text in breakdown_texts]
        assert rendered_statuses == list(KNOWN_APPROVAL_STATUSES)

    def test_approval_detail_placeholder_before_selection(self, root: tk.Tk) -> None:
        from ui.dashboard_app import APPROVAL_DETAIL_PLACEHOLDER

        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)
        assert app._approval_detail_var.get() == APPROVAL_DETAIL_PLACEHOLDER

    def test_approval_row_selection_populates_detail_pane(self, root: tk.Tk) -> None:
        read_model, _, approvals, _, _, _, _ = _make_real_stack()
        approvals.record_request(
            request_id="req-1",
            action="delete file",
            reason="Deleting a file changes state and should be confirmed.",
            security_tier="yellow",
        )
        app = _build_app(root, read_model)
        app._approval_tree.selection_set("req-1")
        app._on_approval_row_selected(None)
        detail = app._approval_detail_var.get()
        assert "Request ID: req-1" in detail
        assert (
            "Reason: Deleting a file changes state and should be confirmed."
            in detail
        )

    def test_workflow_status_breakdown_renders_all_known_statuses(
        self, root: tk.Tk
    ) -> None:
        from workflow.workflow_history_store import KNOWN_WORKFLOW_STATUSES

        read_model, _, _, workflows, _, _, _ = _make_real_stack()
        workflows.record_transition(workflow_id="wf-1", status="workflow_started")
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._workflow_breakdown_labels
        ]
        assert len(breakdown_texts) == len(KNOWN_WORKFLOW_STATUSES)
        assert "workflow_started: 1" in breakdown_texts

    def test_workflow_status_breakdown_empty_store_shows_every_status_at_zero(
        self, root: tk.Tk
    ) -> None:
        from workflow.workflow_history_store import KNOWN_WORKFLOW_STATUSES

        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._workflow_breakdown_labels
        ]
        for status in KNOWN_WORKFLOW_STATUSES:
            assert f"{status}: 0" in breakdown_texts
        assert app._workflow_breakdown_error_var.get() == ""

    def test_workflow_status_breakdown_order_not_sorted_by_count(
        self, root: tk.Tk
    ) -> None:
        from workflow.workflow_history_store import KNOWN_WORKFLOW_STATUSES

        read_model, _, _, workflows, _, _, _ = _make_real_stack()
        last_status = KNOWN_WORKFLOW_STATUSES[-1]
        for i in range(5):
            workflows.record_transition(workflow_id=f"wf-{i}", status=last_status)
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._workflow_breakdown_labels
        ]
        rendered_statuses = [text.split(":")[0] for text in breakdown_texts]
        assert rendered_statuses == list(KNOWN_WORKFLOW_STATUSES)

    def test_workflow_status_breakdown_discloses_recent_activity_scope(
        self, root: tk.Tk
    ) -> None:
        from ui.dashboard_app import WORKFLOW_STATUS_BREAKDOWN_SCOPE_NOTE

        lowered = WORKFLOW_STATUS_BREAKDOWN_SCOPE_NOTE.lower()
        assert "not an all-time total" in lowered
        assert "most recently active" in lowered

    def test_workflow_transitions_display_approval_request_id_when_present(
        self, root: tk.Tk
    ) -> None:
        read_model, _, _, workflows, _, _, _ = _make_real_stack()
        workflows.record_transition(
            workflow_id="wf-1",
            status="workflow_step_waiting",
            approval_request_id="req-1",
        )
        app = _build_app(root, read_model)
        app._workflow_tree.selection_set("wf-1")
        app._on_workflow_row_selected(None)
        children = app._transitions_tree.get_children()
        values = app._transitions_tree.item(children[0], "values")
        assert values[-1] == "req-1"

    def test_workflow_transitions_show_placeholder_when_no_approval_request_id(
        self, root: tk.Tk
    ) -> None:
        read_model, _, _, workflows, _, _, _ = _make_real_stack()
        workflows.record_transition(workflow_id="wf-1", status="workflow_started")
        app = _build_app(root, read_model)
        app._workflow_tree.selection_set("wf-1")
        app._on_workflow_row_selected(None)
        children = app._transitions_tree.get_children()
        values = app._transitions_tree.item(children[0], "values")
        assert values[-1] == "—"

    def test_workflow_selection_loads_transitions(self, root: tk.Tk) -> None:
        read_model, _, _, workflows, _, _, _ = _make_real_stack()
        workflows.record_transition(workflow_id="wf-1", status="workflow_started")
        workflows.record_transition(workflow_id="wf-1", status="workflow_completed")
        app = _build_app(root, read_model)
        app._workflow_tree.selection_set("wf-1")
        app._on_workflow_row_selected(None)
        children = app._transitions_tree.get_children()
        statuses = [app._transitions_tree.item(c, "values")[0] for c in children]
        assert statuses == ["workflow_started", "workflow_completed"]

    def test_category_filter_is_read_only_and_requeries(self, root: tk.Tk) -> None:
        read_model, memory, _, _, _, _, _ = _make_real_stack()
        memory.save("in project", category="project")
        memory.save("in personal", category="personal")
        app = _build_app(root, read_model)
        app._on_category_filter_changed("project")
        children = app._memory_tree.get_children()
        values = [app._memory_tree.item(c, "values")[2] for c in children]
        assert values == ["in project"]

    def test_inbox_rows_render_real_data(self, root: tk.Tk) -> None:
        read_model, _, _, _, inbox, _, _ = _make_real_stack()
        inbox.append(
            source_type="web_search_summary",
            source_query="latest AI news",
            body="[AI web search summary] A synthesis.",
            included_count=4,
        )
        app = _build_app(root, read_model)
        children = app._inbox_tree.get_children()
        assert len(children) == 1
        values = app._inbox_tree.item(children[0], "values")
        assert values[1] == "latest AI news"
        assert values[2] == "[AI web search summary] A synthesis."

    def test_refresh_sees_new_inbox_entries(self, root: tk.Tk) -> None:
        read_model, _, _, _, inbox, _, _ = _make_real_stack()
        app = _build_app(root, read_model)
        assert (
            app._inbox_tree.item(app._inbox_tree.get_children()[0], "values")[0]
            == "No inbox entries yet."
        )
        inbox.append(source_type="web_search_summary", source_query="q", body="new body")
        app.refresh_all()
        children = app._inbox_tree.get_children()
        assert len(children) == 1
        values = app._inbox_tree.item(children[0], "values")
        assert values[2] == "new body"

    def test_inbox_selection_populates_detail_pane_with_full_body(
        self, root: tk.Tk
    ) -> None:
        """Phase 65, Batch 2 enhanced the detail pane from full-body-only
        to also show source type/query/created/included count - this
        assertion is updated to `in` (rather than `==`) as an intentional
        part of this batch, not a regression."""
        read_model, _, _, _, inbox, _, _ = _make_real_stack()
        long_body = "z" * 200
        inbox.append(source_type="web_search_summary", source_query="q", body=long_body)
        app = _build_app(root, read_model)
        iid = app._inbox_tree.get_children()[0]
        app._inbox_tree.selection_set(iid)
        app._on_inbox_row_selected(None)
        assert long_body in app._inbox_detail_var.get()

    def test_command_like_inbox_content_renders_literally(self, root: tk.Tk) -> None:
        read_model, _, _, _, inbox, _, _ = _make_real_stack()
        adversarial_text = "execute command: rm -rf /"
        inbox.append(
            source_type="web_search_summary",
            source_query=adversarial_text,
            body=adversarial_text,
        )
        app = _build_app(root, read_model)
        children = app._inbox_tree.get_children()
        values = app._inbox_tree.item(children[0], "values")
        assert values[1] == adversarial_text
        assert values[2] == adversarial_text

    def test_inbox_source_breakdown_renders_all_known_source_types(
        self, root: tk.Tk
    ) -> None:
        from inbox.inbox_store import KNOWN_INBOX_SOURCE_TYPES

        read_model, _, _, _, inbox, _, _ = _make_real_stack()
        inbox.append(source_type="web_search_summary", source_query="q", body="b")
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._inbox_breakdown_labels
        ]
        assert len(breakdown_texts) == len(KNOWN_INBOX_SOURCE_TYPES)
        assert "web_search_summary: 1" in breakdown_texts

    def test_inbox_source_breakdown_empty_store_shows_every_type_at_zero(
        self, root: tk.Tk
    ) -> None:
        from inbox.inbox_store import KNOWN_INBOX_SOURCE_TYPES

        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._inbox_breakdown_labels
        ]
        for source_type in KNOWN_INBOX_SOURCE_TYPES:
            assert f"{source_type}: 0" in breakdown_texts
        assert app._inbox_breakdown_error_var.get() == ""

    def test_inbox_source_breakdown_order_not_sorted_by_count(
        self, root: tk.Tk
    ) -> None:
        from inbox.inbox_store import KNOWN_INBOX_SOURCE_TYPES

        read_model, _, _, _, inbox, _, _ = _make_real_stack()
        last_source_type = KNOWN_INBOX_SOURCE_TYPES[-1]
        for i in range(5):
            inbox.append(source_type=last_source_type, source_query=f"q{i}", body="b")
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._inbox_breakdown_labels
        ]
        rendered_source_types = [text.split(":")[0] for text in breakdown_texts]
        assert rendered_source_types == list(KNOWN_INBOX_SOURCE_TYPES)

    def test_inbox_detail_pane_shows_source_type_and_included_count(
        self, root: tk.Tk
    ) -> None:
        read_model, _, _, _, inbox, _, _ = _make_real_stack()
        inbox.append(
            source_type="scheduled_web_search_summary",
            source_query="jarvis news",
            body="[AI web search summary] A synthesis.",
            included_count=3,
        )
        app = _build_app(root, read_model)
        iid = app._inbox_tree.get_children()[0]
        app._inbox_tree.selection_set(iid)
        app._on_inbox_row_selected(None)
        detail = app._inbox_detail_var.get()
        assert "Source type: scheduled_web_search_summary" in detail
        assert "Source query: jarvis news" in detail
        assert "Included count: 3" in detail

    def test_inbox_tab_caption_discloses_read_only_and_no_write_actions(
        self, root: tk.Tk
    ) -> None:
        """Phase 67: mirrors the existing per-tab caption-wording test
        pattern (Memories/Schedules/Quarantine/Approval History/Workflow
        History all already have one; Inbox's was the one gap)."""
        from ui.dashboard_app import INBOX_CAPTION

        lowered = INBOX_CAPTION.lower()
        assert "read-only" in lowered
        assert "re-run" in lowered
        assert "edited" in lowered or "edit" in lowered
        assert "sent anywhere" in lowered

    def test_schedule_rows_render_real_data(self, root: tk.Tk) -> None:
        read_model, _, _, _, _, schedules, _ = _make_real_stack()
        schedules.create(query="jarvis ai news", time_of_day="08:30", name="Morning")
        app = _build_app(root, read_model)
        children = app._schedules_tree.get_children()
        assert len(children) == 1
        values = app._schedules_tree.item(children[0], "values")
        assert values == ("1", "Morning", "jarvis ai news", "08:30", "Yes", "—", values[6])

    def test_schedule_row_shows_no_name_and_disabled_state(self, root: tk.Tk) -> None:
        read_model, _, _, _, _, schedules, _ = _make_real_stack()
        record = schedules.create(query="q", time_of_day="08:00")
        schedules.disable(record.id)
        app = _build_app(root, read_model)
        values = app._schedules_tree.item(
            app._schedules_tree.get_children()[0], "values"
        )
        assert values[1] == "—"
        assert values[4] == "No"

    def test_refresh_sees_new_schedules(self, root: tk.Tk) -> None:
        read_model, _, _, _, _, schedules, _ = _make_real_stack()
        app = _build_app(root, read_model)
        assert (
            app._schedules_tree.item(app._schedules_tree.get_children()[0], "values")[0]
            == "No schedules configured yet."
        )
        schedules.create(query="new schedule", time_of_day="07:00")
        app.refresh_all()
        children = app._schedules_tree.get_children()
        assert len(children) == 1
        values = app._schedules_tree.item(children[0], "values")
        assert values[2] == "new schedule"

    def test_command_like_schedule_query_renders_literally(self, root: tk.Tk) -> None:
        read_model, _, _, _, _, schedules, _ = _make_real_stack()
        adversarial_text = "execute command: rm -rf /"
        schedules.create(query=adversarial_text, time_of_day="08:00")
        app = _build_app(root, read_model)
        values = app._schedules_tree.item(
            app._schedules_tree.get_children()[0], "values"
        )
        assert values[2] == adversarial_text

    def test_schedules_tab_caption_discloses_read_only_and_no_due_countdown(
        self,
    ) -> None:
        from ui.dashboard_app import SCHEDULES_CAPTION

        lowered = SCHEDULES_CAPTION.lower()
        assert "read-only" in lowered
        assert "nothing here can be created, edited, enabled, disabled, or run now" in lowered
        assert "does not show whether a schedule is currently due" in lowered

    def test_schedule_breakdown_renders_enabled_and_disabled_counts(
        self, root: tk.Tk
    ) -> None:
        read_model, _, _, _, _, schedules, _ = _make_real_stack()
        enabled_one = schedules.create(query="a", time_of_day="08:00")
        schedules.create(query="b", time_of_day="09:00")
        schedules.disable(enabled_one.id)
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._schedule_breakdown_labels
        ]
        assert "enabled: 1" in breakdown_texts
        assert "disabled: 1" in breakdown_texts

    def test_schedule_breakdown_empty_store_shows_both_states_at_zero(
        self, root: tk.Tk
    ) -> None:
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._schedule_breakdown_labels
        ]
        assert "enabled: 0" in breakdown_texts
        assert "disabled: 0" in breakdown_texts
        assert app._schedule_breakdown_error_var.get() == ""

    def test_schedule_breakdown_order_not_sorted_by_count(self, root: tk.Tk) -> None:
        """"enabled" must always render before "disabled" - even when
        disabled schedules outnumber enabled ones."""
        read_model, _, _, _, _, schedules, _ = _make_real_stack()
        for i in range(5):
            record = schedules.create(query=f"q{i}", time_of_day="08:00")
            schedules.disable(record.id)
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._schedule_breakdown_labels
        ]
        rendered_states = [text.split(":")[0] for text in breakdown_texts]
        assert rendered_states == ["enabled", "disabled"]

    def test_quarantine_rows_render_real_data(self, root: tk.Tk) -> None:
        read_model, _, _, _, _, _, quarantine = _make_real_stack()
        quarantine.record_quarantine(
            original_path="/home/nathan/notes.txt",
            quarantine_path="/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt",
        )
        app = _build_app(root, read_model)
        children = app._quarantine_tree.get_children()
        assert len(children) == 1
        values = app._quarantine_tree.item(children[0], "values")
        assert values[0] == "notes__a1b2c3d4.txt"
        assert values[1] == "/home/nathan/notes.txt"
        assert values[2] == "/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt"

    def test_quarantine_row_shows_no_session_placeholder(self, root: tk.Tk) -> None:
        read_model, _, _, _, _, _, quarantine = _make_real_stack()
        quarantine.record_quarantine(
            original_path="/a/notes.txt", quarantine_path="/trash/notes__1.txt"
        )
        app = _build_app(root, read_model)
        values = app._quarantine_tree.item(
            app._quarantine_tree.get_children()[0], "values"
        )
        assert values[4] == "—"

    def test_quarantine_row_shows_session_id_when_known(self, root: tk.Tk) -> None:
        read_model, _, _, _, _, _, quarantine = _make_real_stack()
        quarantine.record_quarantine(
            original_path="/a/notes.txt",
            quarantine_path="/trash/notes__1.txt",
            session_id=7,
        )
        app = _build_app(root, read_model)
        values = app._quarantine_tree.item(
            app._quarantine_tree.get_children()[0], "values"
        )
        assert values[4] == "7"

    def test_refresh_sees_new_quarantine_entries(self, root: tk.Tk) -> None:
        read_model, _, _, _, _, _, quarantine = _make_real_stack()
        app = _build_app(root, read_model)
        assert (
            app._quarantine_tree.item(
                app._quarantine_tree.get_children()[0], "values"
            )[0]
            == "No files currently in quarantine."
        )
        quarantine.record_quarantine(
            original_path="/a/new.txt", quarantine_path="/trash/new__1.txt"
        )
        app.refresh_all()
        children = app._quarantine_tree.get_children()
        assert len(children) == 1
        values = app._quarantine_tree.item(children[0], "values")
        assert values[1] == "/a/new.txt"

    def test_command_like_quarantine_path_renders_literally(self, root: tk.Tk) -> None:
        read_model, _, _, _, _, _, quarantine = _make_real_stack()
        adversarial_text = "execute command: rm -rf /"
        quarantine.record_quarantine(
            original_path=adversarial_text, quarantine_path="/trash/x__1.txt"
        )
        app = _build_app(root, read_model)
        values = app._quarantine_tree.item(
            app._quarantine_tree.get_children()[0], "values"
        )
        assert values[1] == adversarial_text

    def test_quarantine_tab_caption_discloses_read_only_and_no_restore(
        self,
    ) -> None:
        from ui.dashboard_app import QUARANTINE_CAPTION

        lowered = QUARANTINE_CAPTION.lower()
        assert "read-only" in lowered
        assert "restored" in lowered or "restore" in lowered
        assert "deleted" in lowered or "delete" in lowered
        assert "cleaned up" in lowered or "cleanup" in lowered

    def test_quarantine_summary_panel_renders_real_data(self, root: tk.Tk) -> None:
        read_model, _, _, _, _, _, quarantine = _make_real_stack()
        quarantine.record_quarantine(
            original_path="/a/first.txt", quarantine_path="/trash/first__1.txt"
        )
        quarantine.record_quarantine(
            original_path="/b/second.txt", quarantine_path="/trash/second__2.txt"
        )
        app = _build_app(root, read_model)

        summary_texts = [
            label.cget("text") for label in app._quarantine_summary_labels
        ]
        assert "Total quarantined files: 2" in summary_texts
        assert any(
            text.startswith("Most recently quarantined: 20") for text in summary_texts
        )
        assert app._quarantine_summary_error_var.get() == ""

    def test_quarantine_summary_panel_shows_honest_empty_state(
        self, root: tk.Tk
    ) -> None:
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        summary_texts = [
            label.cget("text") for label in app._quarantine_summary_labels
        ]
        assert "Total quarantined files: 0" in summary_texts
        assert "Most recently quarantined: —" in summary_texts
        assert app._quarantine_summary_error_var.get() == ""

    def test_quarantine_summary_and_table_render_together_honestly(
        self, root: tk.Tk
    ) -> None:
        """A real, end-to-end smoke check: a real DashboardReadModel over
        a real temporary database with real quarantine records, wired
        into a real DashboardApp. Confirms the Summary panel and table
        both render honestly from that real data (Phase 66, Batch 2)."""
        read_model, _, _, _, _, _, quarantine = _make_real_stack()
        quarantine.record_quarantine(
            original_path="/home/nathan/notes.txt",
            quarantine_path="/home/nathan/.jarvis_trash/notes__a1b2c3d4.txt",
            session_id=7,
        )
        app = _build_app(root, read_model)

        summary_texts = [
            label.cget("text") for label in app._quarantine_summary_labels
        ]
        assert "Total quarantined files: 1" in summary_texts

        children = app._quarantine_tree.get_children()
        assert len(children) == 1
        values = app._quarantine_tree.item(children[0], "values")
        assert values[0] == "notes__a1b2c3d4.txt"

        assert app._quarantine_summary_error_var.get() == ""
        assert app._quarantine_error_var.get() == ""

    def test_quarantine_tab_no_write_widget_introduced(self, root: tk.Tk) -> None:
        """Structural, behavioral proof that Batch 1/2's new Summary
        panel never introduced a button or other write-triggering widget
        anywhere in the Quarantine tab specifically (Phase 66, Batch 2)
        - no restore, delete, empty-trash, or permanent-delete control of
        any kind."""
        read_model, _, _, _, _, _, quarantine = _make_real_stack()
        quarantine.record_quarantine(
            original_path="/a/notes.txt", quarantine_path="/trash/notes__1.txt"
        )
        app = _build_app(root, read_model)

        def _collect_buttons(widget: tk.Widget) -> list[tk.Widget]:
            found = []
            if widget.winfo_class() == "TButton":
                found.append(widget)
            for child in widget.winfo_children():
                found.extend(_collect_buttons(child))
            return found

        quarantine_tab_frame = app._quarantine_tree.master
        assert _collect_buttons(quarantine_tab_frame) == []

    def test_no_widget_has_a_write_or_execute_command_bound(self, root: tk.Tk) -> None:
        """Every ttk.Button's `command` must resolve to one of this
        class's own read-only, local methods - never anything that
        could construct a ToolRequest or call an execution component."""
        read_model, *_ = _make_real_stack()
        _build_app(root, read_model)

        # Structural guarantee is enforced by construction and by the
        # import-absence test above; this walk additionally confirms the
        # only Button in the entire window is "Refresh now" - no
        # approve/deny/edit/delete/save/run/retry/resume/cancel/open-
        # URL/browse-web/ask-AI button exists anywhere.
        buttons = []

        def collect_buttons(widget: tk.Widget) -> None:
            if widget.winfo_class() == "TButton":
                buttons.append(widget)
            for child in widget.winfo_children():
                collect_buttons(child)

        collect_buttons(root)
        assert len(buttons) == 1
        assert buttons[0].cget("text") == "Refresh now"

    # --- Phase 62, Batch 3: end-to-end Overview smoke verification -------------

    def test_overview_header_says_jarvis_online(self, root: tk.Tk) -> None:
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        texts = []
        for child in app._overview_frame.winfo_children():
            try:
                texts.append(str(child.cget("text")))
            except tk.TclError:
                continue
        assert OVERVIEW_HEADER in texts

    def test_overview_renders_all_panels_honestly_with_real_data_across_domains(
        self, root: tk.Tk
    ) -> None:
        """A real, end-to-end smoke check: a real DashboardReadModel over
        a real temporary database, a real Settings object, and one real
        row seeded in every domain, wired into a real DashboardApp.
        Confirms every one of the four redesigned Overview panels
        renders honestly from that real data - never a fabricated
        value, and never the configured API key's own value."""
        settings = _test_settings(
            ai_model="claude-test-model",
            ai_reasoning_enabled=True,
            anthropic_api_key="sk-should-never-appear-in-any-widget",
        )
        read_model, memory, approvals, workflows, inbox, _, quarantine = (
            _make_real_stack_with_settings(settings)
        )
        memory.save("buy milk")
        approvals.record_request(
            request_id="req-1",
            action="delete file",
            reason="Deleting a file changes state and should be confirmed.",
            security_tier="yellow",
        )
        workflows.record_transition(workflow_id="wf-1", status="workflow_started")
        inbox.append(source_type="web_search_summary", source_query="q", body="b")
        quarantine.record_quarantine(
            original_path="/a/notes.txt", quarantine_path="/trash/notes__1.txt"
        )

        app = _build_app(root, read_model)

        status_texts = " ".join(
            label.cget("text") for label in app._system_status_labels
        )
        assert "AI model: claude-test-model" in status_texts
        assert "Anthropic API key: configured" in status_texts
        assert "sk-should-never-appear-in-any-widget" not in status_texts

        reachability_texts = " ".join(
            label.cget("text") for label in app._reachability_labels
        )
        assert "memory: reachable" in reachability_texts
        assert "quarantine: reachable" in reachability_texts

        counts_texts = " ".join(label.cget("text") for label in app._overview_labels)
        assert "Total memories stored: 1" in counts_texts

        activity_children = app._activity_tree.get_children()
        activity_domains = {
            app._activity_tree.item(child, "values")[1] for child in activity_children
        }
        assert activity_domains == {
            "memory",
            "approval",
            "workflow",
            "inbox",
            "quarantine",
        }

        assert app._system_status_error_var.get() == ""
        assert app._reachability_error_var.get() == ""
        assert app._overview_error_var.get() == ""
        assert app._activity_error_var.get() == ""

    def test_overview_system_status_honest_when_no_settings_configured(
        self, root: tk.Tk
    ) -> None:
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        status_texts = " ".join(
            label.cget("text") for label in app._system_status_labels
        )
        assert "unavailable" in status_texts.lower()

    def test_overview_activity_empty_state_is_honest(self, root: tk.Tk) -> None:
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        children = app._activity_tree.get_children()
        assert len(children) == 1
        assert app._activity_tree.item(children[0], "values")[0] == (
            dashboard_app_module._ACTIVITY_EMPTY_STATE
        )

    def test_overview_reachability_reports_quarantine_reachable_with_real_store(
        self, root: tk.Tk
    ) -> None:
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        reachability_texts = " ".join(
            label.cget("text") for label in app._reachability_labels
        )
        assert "quarantine: reachable" in reachability_texts

    # --- Phase 64, Batch 3: end-to-end Approval/Workflow History smoke checks -

    def test_approval_history_renders_all_panels_honestly_with_real_data(
        self, root: tk.Tk
    ) -> None:
        """A real, end-to-end smoke check: a real DashboardReadModel over
        a real temporary database with real approval requests across
        multiple statuses, wired into a real DashboardApp. Confirms the
        Status Breakdown, table, and selected-row detail pane all
        render honestly from that real data."""
        from datetime import datetime, timezone

        read_model, _, approvals, _, _, _, _ = _make_real_stack()
        approvals.record_request(
            request_id="req-1",
            action="delete file",
            reason="Deleting a file changes state and should be confirmed.",
            security_tier="yellow",
        )
        approvals.record_request(
            request_id="req-2", action="update memory", reason="r", security_tier="yellow"
        )
        approvals.record_decision(
            request_id="req-2",
            approved=True,
            decided_by="user",
            decided_at=datetime.now(timezone.utc),
            reason="looks safe",
        )
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._approval_breakdown_labels
        ]
        assert "pending: 1" in breakdown_texts
        assert "approved: 1" in breakdown_texts
        assert "declined: 0" in breakdown_texts
        assert "expired: 0" in breakdown_texts

        children = app._approval_tree.get_children()
        assert len(children) == 2

        app._approval_tree.selection_set("req-1")
        app._on_approval_row_selected(None)
        pending_detail = app._approval_detail_var.get()
        assert "Status: pending" in pending_detail
        assert "Decision reason: —" in pending_detail

        app._approval_tree.selection_set("req-2")
        app._on_approval_row_selected(None)
        decided_detail = app._approval_detail_var.get()
        assert "Status: approved" in decided_detail
        assert "Decision reason: looks safe" in decided_detail

        assert app._approval_error_var.get() == ""
        assert app._approval_breakdown_error_var.get() == ""

    def test_workflow_history_renders_all_panels_honestly_with_real_data(
        self, root: tk.Tk
    ) -> None:
        """A real, end-to-end smoke check across the Workflow History tab:
        Status Breakdown (recent-activity-scoped), table, transition
        drill-down, and the Approval Request ID column all render
        honestly from real, seeded workflow history data."""
        read_model, _, _, workflows, _, _, _ = _make_real_stack()
        workflows.record_transition(workflow_id="wf-1", status="workflow_started")
        workflows.record_transition(
            workflow_id="wf-1",
            status="workflow_step_waiting",
            approval_request_id="req-1",
        )
        workflows.record_transition(workflow_id="wf-1", status="workflow_completed")
        workflows.record_transition(workflow_id="wf-2", status="workflow_started")
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._workflow_breakdown_labels
        ]
        assert "workflow_completed: 1" in breakdown_texts
        assert "workflow_started: 1" in breakdown_texts
        assert "workflow_stopped: 0" in breakdown_texts

        workflow_children = app._workflow_tree.get_children()
        assert len(workflow_children) == 2

        app._workflow_tree.selection_set("wf-1")
        app._on_workflow_row_selected(None)
        transition_children = app._transitions_tree.get_children()
        values_by_status = {
            app._transitions_tree.item(c, "values")[0]: app._transitions_tree.item(
                c, "values"
            )[-1]
            for c in transition_children
        }
        assert values_by_status["workflow_started"] == "—"
        assert values_by_status["workflow_step_waiting"] == "req-1"
        assert values_by_status["workflow_completed"] == "—"

        assert app._workflow_error_var.get() == ""
        assert app._workflow_breakdown_error_var.get() == ""

    def test_approval_and_workflow_history_no_write_widget_introduced(
        self, root: tk.Tk
    ) -> None:
        """Structural, behavioral proof that Batch 1/2's new panels never
        introduced a button or other write-triggering widget anywhere
        in the Approval History or Workflow History tabs specifically."""
        read_model, _, approvals, workflows, _, _, _ = _make_real_stack()
        approvals.record_request(
            request_id="req-1", action="a", reason="r", security_tier="yellow"
        )
        workflows.record_transition(workflow_id="wf-1", status="workflow_started")
        app = _build_app(root, read_model)

        def _collect_buttons(widget: tk.Widget) -> list[tk.Widget]:
            found = []
            if widget.winfo_class() == "TButton":
                found.append(widget)
            for child in widget.winfo_children():
                found.extend(_collect_buttons(child))
            return found

        approval_tab_frame = app._approval_tree.master
        workflow_tab_frame = app._workflow_tree.master
        assert _collect_buttons(approval_tab_frame) == []
        assert _collect_buttons(workflow_tab_frame) == []

    def test_inbox_renders_all_panels_honestly_with_real_data(
        self, root: tk.Tk
    ) -> None:
        """A real, end-to-end smoke check: a real DashboardReadModel over
        a real temporary database with real inbox entries across
        multiple source types, wired into a real DashboardApp. Confirms
        the Source Breakdown, table, and selected-row detail pane
        (including its honest missing-field states) all render honestly
        from that real data (Phase 65, Batch 3)."""
        from inbox.inbox_store import KNOWN_INBOX_SOURCE_TYPES

        read_model, _, _, _, inbox, _, _ = _make_real_stack()
        inbox.append(
            source_type="web_search_summary",
            source_query="jarvis news",
            body="[AI web search summary] A synthesis.",
            included_count=3,
        )
        inbox.append(
            source_type="scheduled_web_search_summary",
            source_query="daily digest",
            body="[AI web search summary] A scheduled synthesis.",
        )
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._inbox_breakdown_labels
        ]
        assert len(breakdown_texts) == len(KNOWN_INBOX_SOURCE_TYPES)
        assert "web_search_summary: 1" in breakdown_texts
        assert "scheduled_web_search_summary: 1" in breakdown_texts
        assert "webpage_summary: 0" in breakdown_texts

        children = app._inbox_tree.get_children()
        assert len(children) == 2

        with_count_iid = next(
            iid
            for iid, row in app._inbox_rows_by_id.items()
            if row.source_query == "jarvis news"
        )
        app._inbox_tree.selection_set(with_count_iid)
        app._on_inbox_row_selected(None)
        detail_with_count = app._inbox_detail_var.get()
        assert "Source type: web_search_summary" in detail_with_count
        assert "Source query: jarvis news" in detail_with_count
        assert "Included count: 3" in detail_with_count
        assert "[AI web search summary] A synthesis." in detail_with_count

        without_count_iid = next(
            iid
            for iid, row in app._inbox_rows_by_id.items()
            if row.source_query == "daily digest"
        )
        app._inbox_tree.selection_set(without_count_iid)
        app._on_inbox_row_selected(None)
        detail_without_count = app._inbox_detail_var.get()
        assert "Source type: scheduled_web_search_summary" in detail_without_count
        assert "Included count: —" in detail_without_count

        assert app._inbox_error_var.get() == ""
        assert app._inbox_breakdown_error_var.get() == ""

    def test_schedules_renders_all_panels_honestly_with_real_data(
        self, root: tk.Tk
    ) -> None:
        """A real, end-to-end smoke check across the Schedules tab: the
        Enabled/Disabled Breakdown and table both render honestly from
        real, seeded schedule data covering both enabled and disabled
        schedules (Phase 65, Batch 3)."""
        read_model, _, _, _, _, schedules, _ = _make_real_stack()
        schedules.create(query="morning news", time_of_day="08:00", name="Morning")
        to_disable = schedules.create(query="evening news", time_of_day="18:00")
        schedules.disable(to_disable.id)
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._schedule_breakdown_labels
        ]
        assert "enabled: 1" in breakdown_texts
        assert "disabled: 1" in breakdown_texts

        children = app._schedules_tree.get_children()
        assert len(children) == 2
        enabled_values = {
            app._schedules_tree.item(c, "values")[1]: app._schedules_tree.item(
                c, "values"
            )[4]
            for c in children
        }
        assert enabled_values["Morning"] == "Yes"
        assert enabled_values["—"] == "No"

        assert app._schedules_error_var.get() == ""
        assert app._schedule_breakdown_error_var.get() == ""

    def test_schedules_breakdown_honest_zero_states_on_empty_store(
        self, root: tk.Tk
    ) -> None:
        """The Schedules Enabled/Disabled Breakdown must show honest
        zeros for both states, and the table its own empty-state
        message, when no schedules are configured at all (Phase 65,
        Batch 3)."""
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        breakdown_texts = [
            label.cget("text") for label in app._schedule_breakdown_labels
        ]
        assert "enabled: 0" in breakdown_texts
        assert "disabled: 0" in breakdown_texts
        assert (
            app._schedules_tree.item(app._schedules_tree.get_children()[0], "values")[0]
            == "No schedules configured yet."
        )

    def test_inbox_and_schedules_no_write_widget_introduced(
        self, root: tk.Tk
    ) -> None:
        """Structural, behavioral proof that Batch 1/2's new panels never
        introduced a button or other write-triggering widget anywhere in
        the Inbox or Schedules tabs specifically (Phase 65, Batch 3)."""
        read_model, _, _, _, inbox, schedules, _ = _make_real_stack()
        inbox.append(source_type="web_search_summary", source_query="q", body="b")
        schedules.create(query="q", time_of_day="08:00")
        app = _build_app(root, read_model)

        def _collect_buttons(widget: tk.Widget) -> list[tk.Widget]:
            found = []
            if widget.winfo_class() == "TButton":
                found.append(widget)
            for child in widget.winfo_children():
                found.extend(_collect_buttons(child))
            return found

        inbox_tab_frame = app._inbox_tree.master
        schedules_tab_frame = app._schedules_tree.master
        assert _collect_buttons(inbox_tab_frame) == []
        assert _collect_buttons(schedules_tab_frame) == []

    # --- Brain tab (Phase 87, Batch 2) ------------------------------------------

    @staticmethod
    def _collect_label_texts(widget: tk.Widget) -> list[str]:
        found: list[str] = []
        if widget.winfo_class() == "TLabel":
            found.append(widget.cget("text"))
        for child in widget.winfo_children():
            found.extend(TestDashboardAppWithRealTk._collect_label_texts(child))
        return found

    def test_brain_sections_use_titled_label_frames(self, root: tk.Tk) -> None:
        """Phase 88, Batch 2: each of the Brain tab's six sections is
        now a real ttk.LabelFrame with its own titled border, replacing
        the previous bare bold Label floating above a plain Frame -
        the same helper Batch 1 already applied to Overview."""
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        section_titles = {
            child.cget("text")
            for child in app._brain_frame.winfo_children()
            if child.winfo_class() == "TLabelframe"
        }
        assert section_titles == {
            "AI / Reasoning",
            "Memory",
            "Approval Status Breakdown",
            "Workflow Status Breakdown",
            "Known Limits",
            "Claude Prompt Studio",
        }

    def test_brain_content_frames_nested_inside_their_titled_section(
        self, root: tk.Tk
    ) -> None:
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        assert app._brain_system_status_frame.master.winfo_class() == "TLabelframe"
        assert app._brain_system_status_frame.master.cget("text") == "AI / Reasoning"
        assert app._brain_memory_frame.master.winfo_class() == "TLabelframe"
        assert app._brain_memory_frame.master.cget("text") == "Memory"
        assert (
            app._brain_approval_breakdown_frame.master.winfo_class() == "TLabelframe"
        )
        assert (
            app._brain_approval_breakdown_frame.master.cget("text")
            == "Approval Status Breakdown"
        )
        assert (
            app._brain_workflow_breakdown_frame.master.winfo_class() == "TLabelframe"
        )
        assert (
            app._brain_workflow_breakdown_frame.master.cget("text")
            == "Workflow Status Breakdown"
        )

    def test_brain_tab_renders_ai_reasoning_information_from_read_model(
        self, root: tk.Tk
    ) -> None:
        settings = _test_settings(
            ai_model="claude-test-model", ai_reasoning_enabled=True
        )
        read_model, *_ = _make_real_stack_with_settings(settings)
        app = _build_app(root, read_model)

        texts = "\n".join(
            label.cget("text") for label in app._brain_system_status_labels
        )
        assert "AI reasoning enabled: True" in texts
        assert "AI model: claude-test-model" in texts
        assert app._brain_error_var.get() == ""

    def test_brain_tab_ai_reasoning_information_honest_when_unavailable(
        self, root: tk.Tk
    ) -> None:
        read_model, *_ = _make_real_stack()  # no Settings supplied
        app = _build_app(root, read_model)

        texts = [label.cget("text") for label in app._brain_system_status_labels]
        assert len(texts) == 1
        assert "unavailable" in texts[0].lower()

    def test_brain_tab_renders_memory_count(self, root: tk.Tk) -> None:
        read_model, memory, *_ = _make_real_stack()
        memory.save("buy milk")
        memory.save("call dentist")
        app = _build_app(root, read_model)

        texts = [label.cget("text") for label in app._brain_memory_labels]
        assert "Total memories stored: 2" in texts

    def test_brain_tab_renders_memory_count_honest_zero(self, root: tk.Tk) -> None:
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        texts = [label.cget("text") for label in app._brain_memory_labels]
        assert "Total memories stored: 0" in texts

    def test_brain_tab_renders_approval_breakdown(self, root: tk.Tk) -> None:
        from approval.approval_history_store import KNOWN_APPROVAL_STATUSES

        read_model, _, approvals, *_ = _make_real_stack()
        approvals.record_request(
            request_id="req-1",
            action="delete file",
            reason="r",
            security_tier="yellow",
        )
        app = _build_app(root, read_model)

        texts = [label.cget("text") for label in app._brain_approval_breakdown_labels]
        assert len(texts) == len(KNOWN_APPROVAL_STATUSES)
        assert "pending: 1" in texts

    def test_brain_tab_renders_workflow_breakdown(self, root: tk.Tk) -> None:
        from workflow.workflow_history_store import KNOWN_WORKFLOW_STATUSES

        read_model, _, _, workflows, *_ = _make_real_stack()
        workflows.record_transition(workflow_id="wf-1", status="workflow_started")
        app = _build_app(root, read_model)

        texts = [label.cget("text") for label in app._brain_workflow_breakdown_labels]
        assert len(texts) == len(KNOWN_WORKFLOW_STATUSES)
        assert "workflow_started: 1" in texts

    def test_brain_tab_renders_known_limits_section(self, root: tk.Tk) -> None:
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        brain_tab_frame = app._brain_frame
        all_texts = "\n".join(self._collect_label_texts(brain_tab_frame))
        for limit in BRAIN_KNOWN_LIMITS:
            assert limit in all_texts

    def test_brain_tab_renders_prompt_studio_discoverability_commands(
        self, root: tk.Tk
    ) -> None:
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        brain_tab_frame = app._brain_frame
        all_texts = "\n".join(self._collect_label_texts(brain_tab_frame))
        for command in BRAIN_PROMPT_STUDIO_COMMANDS:
            assert command in all_texts
        assert "never calls the Claude API" in all_texts

    def test_brain_tab_refresh_updates_with_fresh_data(self, root: tk.Tk) -> None:
        read_model, memory, *_ = _make_real_stack()
        app = _build_app(root, read_model)
        assert "Total memories stored: 0" in [
            label.cget("text") for label in app._brain_memory_labels
        ]

        memory.save("new memory")
        app.refresh_all()

        assert "Total memories stored: 1" in [
            label.cget("text") for label in app._brain_memory_labels
        ]

    def test_brain_tab_no_write_widget_introduced(self, root: tk.Tk) -> None:
        """Structural, behavioral proof that the Brain tab never
        introduced a button or other write-triggering widget - the
        Prompt Studio section is plain informational text only."""
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        def _collect_buttons(widget: tk.Widget) -> list[tk.Widget]:
            found = []
            if widget.winfo_class() == "TButton":
                found.append(widget)
            for child in widget.winfo_children():
                found.extend(_collect_buttons(child))
            return found

        brain_tab_frame = app._brain_frame
        assert _collect_buttons(brain_tab_frame) == []

    def test_brain_status_failure_isolated_from_other_tabs(self, root: tk.Tk) -> None:
        """A failure reading brain status must never blank another
        tab's own most recent successful state, mirroring this module's
        established per-panel isolation convention (Phase 62, Batch 2's
        own test_one_overview_panel_failure_does_not_blank_another)."""

        class _PartiallyRaisingReadModel(_RaisingReadModel):
            def get_overview(self):
                return DashboardOverview(
                    total_memory_count=0,
                    recent_approvals=[],
                    recent_workflows=[],
                    total_inbox_count=0,
                    recent_inbox_entries=[],
                    total_scheduled_inbox_count=0,
                    latest_scheduled_inbox_created_at=None,
                )

        app = _build_app(root, _PartiallyRaisingReadModel())
        assert "Could not read brain status" in app._brain_error_var.get()
        assert app._overview_error_var.get() == ""

    def test_brain_caption_discloses_no_tool_registry_or_git_state(self) -> None:
        lowered = BRAIN_CAPTION.lower()
        assert "tool registry size" in lowered
        assert "git branch, commit, phase, or test-suite result" in lowered

    def test_brain_header_is_jarvis_brain(self) -> None:
        assert BRAIN_HEADER == "Jarvis Brain"

    def test_brain_prompt_studio_caption_discloses_no_api_call(self) -> None:
        lowered = BRAIN_PROMPT_STUDIO_CAPTION.lower()
        assert "never calls the claude api" in lowered

    # --- Overview titled-section styling (Phase 88, Batch 1) --------------------

    def test_build_titled_section_creates_a_label_frame_with_title_and_caption(
        self, root: tk.Tk
    ) -> None:
        section, error_var = DashboardApp._build_titled_section(
            root, "Example Section", caption="An example caption."
        )
        assert section.winfo_class() == "TLabelframe"
        assert section.cget("text") == "Example Section"
        assert isinstance(error_var, tk.StringVar)
        assert error_var.get() == ""

        texts = [
            child.cget("text")
            for child in section.winfo_children()
            if child.winfo_class() == "TLabel"
        ]
        assert "An example caption." in texts

    def test_build_titled_section_without_caption_omits_caption_label(
        self, root: tk.Tk
    ) -> None:
        section, _ = DashboardApp._build_titled_section(root, "No Caption Section")
        texts = [
            child.cget("text")
            for child in section.winfo_children()
            if child.winfo_class() == "TLabel"
        ]
        # Only the (empty) error label should exist - no caption line.
        assert texts == [""]

    def test_overview_sections_use_titled_label_frames(self, root: tk.Tk) -> None:
        """Phase 88, Batch 1: each of the Overview tab's four panels is
        now a real ttk.LabelFrame with its own titled border, replacing
        the previous bare bold Label floating above a plain Frame."""
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        section_titles = {
            child.cget("text")
            for child in app._overview_frame.winfo_children()
            if child.winfo_class() == "TLabelframe"
        }
        assert section_titles == {
            "System Status",
            "Store Reachability",
            "Summary Counts",
            "Recent Activity",
        }

    def test_overview_content_frames_nested_inside_their_titled_section(
        self, root: tk.Tk
    ) -> None:
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        assert app._system_status_frame.master.winfo_class() == "TLabelframe"
        assert app._system_status_frame.master.cget("text") == "System Status"
        assert app._reachability_frame.master.winfo_class() == "TLabelframe"
        assert app._reachability_frame.master.cget("text") == "Store Reachability"
        assert app._overview_counts_frame.master.winfo_class() == "TLabelframe"
        assert app._overview_counts_frame.master.cget("text") == "Summary Counts"
        assert app._activity_tree.master.winfo_class() == "TLabelframe"
        assert app._activity_tree.master.cget("text") == "Recent Activity"

    def test_overview_refresh_updates_titled_sections_with_fresh_data(
        self, root: tk.Tk
    ) -> None:
        """Confirms refresh_all() still works exactly as before for the
        Overview tab now that its panels are built via
        _build_titled_section() - purely a presentational change, no
        data path affected."""
        read_model, memory, *_ = _make_real_stack()
        app = _build_app(root, read_model)
        assert "Total memories stored: 0" in [
            label.cget("text") for label in app._overview_labels
        ]

        memory.save("new memory")
        app.refresh_all()

        assert "Total memories stored: 1" in [
            label.cget("text") for label in app._overview_labels
        ]

    def test_overview_tab_no_write_widget_introduced(self, root: tk.Tk) -> None:
        """Structural, behavioral proof that Batch 1's new titled
        sections never introduced a button or other write-triggering
        widget anywhere in the Overview tab."""
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        def _collect_buttons(widget: tk.Widget) -> list[tk.Widget]:
            found = []
            if widget.winfo_class() == "TButton":
                found.append(widget)
            for child in widget.winfo_children():
                found.extend(_collect_buttons(child))
            return found

        assert _collect_buttons(app._overview_frame) == []

    def test_non_overview_non_brain_tabs_frames_remain_plain_frames(
        self, root: tk.Tk
    ) -> None:
        """Phase 88 scoped the new titled-section helper to the
        Overview tab (Batch 1) and the Brain tab (Batch 2) only - every
        other tab's existing panel frames must remain plain ttk.Frame
        widgets, proving no other tab was structurally touched by
        either batch. (Brain's own content frames are checked
        separately below - they are still plain ttk.Frame too, just
        now nested one level deeper inside a titled ttk.LabelFrame
        section, exactly like Overview's own content frames.)"""
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        other_tab_frames = [
            app._memory_breakdown_frame,
            app._approval_breakdown_frame,
            app._workflow_breakdown_frame,
            app._inbox_breakdown_frame,
            app._schedule_breakdown_frame,
            app._quarantine_summary_frame,
        ]
        for frame in other_tab_frames:
            assert frame.winfo_class() == "TFrame"

    def test_non_overview_non_brain_tabs_have_no_label_frame_sections(
        self, root: tk.Tk
    ) -> None:
        """Structural proof that Memories, Approval History, Workflow
        History, Inbox, Schedules, and Quarantine have no
        ttk.LabelFrame anywhere - the titled-section helper was never
        applied to any of them in either Phase 88 batch."""
        read_model, *_ = _make_real_stack()
        app = _build_app(root, read_model)

        def _collect_label_frames(widget: tk.Widget) -> list[tk.Widget]:
            found = []
            if widget.winfo_class() == "TLabelframe":
                found.append(widget)
            for child in widget.winfo_children():
                found.extend(_collect_label_frames(child))
            return found

        untouched_tab_frames = [
            app._memory_tree.master,
            app._approval_tree.master,
            app._workflow_tree.master,
            app._inbox_tree.master,
            app._schedules_tree.master,
            app._quarantine_tree.master,
        ]
        for tab_frame in untouched_tab_frames:
            assert _collect_label_frames(tab_frame) == []

    def test_window_title_and_overview_header_wording_unchanged(
        self, root: tk.Tk
    ) -> None:
        """Phase 88, Batch 1 did not change WINDOW_TITLE or
        OVERVIEW_HEADER - neither was directly connected to the
        titled-section visual shell in a way that warranted a wording
        change, and the existing read-only disclosure stays intact."""
        assert WINDOW_TITLE == "Jarvis — Dashboard (read-only)"
        assert OVERVIEW_HEADER == "Jarvis Online"
        assert "read-only" in WINDOW_TITLE.lower()
