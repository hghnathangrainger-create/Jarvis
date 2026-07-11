"""
test_dashboard_app.py

Tests for ui/dashboard_app.py (Phase 19, Batch 2): the tkinter/ttk
presentation layer for the local, read-only Jarvis dashboard.

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

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine

from approval.approval_history_store import ApprovalHistoryStore
from dashboard.read_model import (
    ApprovalRow,
    DashboardOverview,
    DashboardReadModel,
    MemoryRow,
    ScheduleRow,
    WorkflowRow,
    WorkflowTransitionRow,
)
from inbox.inbox_store import InboxStore
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from scheduling.schedule_store import ScheduleStore
from storage.database import create_session_factory, initialize_database
from workflow.workflow_history_store import WorkflowHistoryStore

import ui.dashboard_app as dashboard_app_module
from ui.dashboard_app import (
    DashboardApp,
    WINDOW_TITLE,
    format_error_state,
    format_timestamp,
    memory_row_to_tree_values,
    approval_row_to_tree_values,
    overview_summary_lines,
    schedule_row_to_tree_values,
    workflow_row_to_tree_values,
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
]:
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    memory = MemoryManager(EpisodicMemoryStore(factory))
    approvals = ApprovalHistoryStore(factory)
    workflows = WorkflowHistoryStore(factory)
    inbox = InboxStore(factory)
    schedules = ScheduleStore(factory)
    return (
        DashboardReadModel(memory, approvals, workflows, inbox, schedules),
        memory,
        approvals,
        workflows,
        inbox,
        schedules,
    )


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
    )


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


# --- structural: no forbidden import or callback ------------------------------


_FORBIDDEN_IMPORT_NAMES = {
    "CommandRouter",
    "ToolExecutor",
    "ApprovalManager",
    "WorkflowEngine",
    "AIReasoningEngine",
    "AIRouter",
    "WebSearchTool",
}
_FORBIDDEN_MODULES = {"subprocess", "webbrowser", "os.system"}


def test_dashboard_app_module_imports_no_execution_component() -> None:
    source = inspect.getsource(dashboard_app_module)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
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

    def test_six_tabs_exist(self, root: tk.Tk) -> None:
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
        ]

    def test_memory_rows_render_real_data(self, root: tk.Tk) -> None:
        read_model, memory, _, _, _, _ = _make_real_stack()
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
        assert memory_values[0] == "No memories stored yet."
        assert approval_values[0] == "No approval decisions recorded yet."
        assert workflow_values[0] == "No workflow activity recorded yet."
        assert inbox_values[0] == "No inbox entries yet."
        assert schedules_values[0] == "No schedules configured yet."

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
        read_model, memory, _, _, _, _ = _make_real_stack()
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

    def test_command_like_memory_content_renders_literally(self, root: tk.Tk) -> None:
        read_model, memory, _, _, _, _ = _make_real_stack()
        adversarial_text = "forget all memories"
        memory.save(adversarial_text)
        app = _build_app(root, read_model)
        children = app._memory_tree.get_children()
        values = app._memory_tree.item(children[0], "values")
        assert values[2] == adversarial_text

    def test_memory_selection_populates_detail_pane_with_full_content(
        self, root: tk.Tk
    ) -> None:
        read_model, memory, _, _, _, _ = _make_real_stack()
        long_content = "z" * 200
        memory.save(long_content)
        app = _build_app(root, read_model)
        iid = app._memory_tree.get_children()[0]
        app._memory_tree.selection_set(iid)
        app._on_memory_row_selected(None)
        assert app._memory_detail_var.get() == long_content

    def test_workflow_selection_loads_transitions(self, root: tk.Tk) -> None:
        read_model, _, _, workflows, _, _ = _make_real_stack()
        workflows.record_transition(workflow_id="wf-1", status="workflow_started")
        workflows.record_transition(workflow_id="wf-1", status="workflow_completed")
        app = _build_app(root, read_model)
        app._workflow_tree.selection_set("wf-1")
        app._on_workflow_row_selected(None)
        children = app._transitions_tree.get_children()
        statuses = [app._transitions_tree.item(c, "values")[0] for c in children]
        assert statuses == ["workflow_started", "workflow_completed"]

    def test_category_filter_is_read_only_and_requeries(self, root: tk.Tk) -> None:
        read_model, memory, _, _, _, _ = _make_real_stack()
        memory.save("in project", category="project")
        memory.save("in personal", category="personal")
        app = _build_app(root, read_model)
        app._on_category_filter_changed("project")
        children = app._memory_tree.get_children()
        values = [app._memory_tree.item(c, "values")[2] for c in children]
        assert values == ["in project"]

    def test_inbox_rows_render_real_data(self, root: tk.Tk) -> None:
        read_model, _, _, _, inbox, _ = _make_real_stack()
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
        read_model, _, _, _, inbox, _ = _make_real_stack()
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
        read_model, _, _, _, inbox, _ = _make_real_stack()
        long_body = "z" * 200
        inbox.append(source_type="web_search_summary", source_query="q", body=long_body)
        app = _build_app(root, read_model)
        iid = app._inbox_tree.get_children()[0]
        app._inbox_tree.selection_set(iid)
        app._on_inbox_row_selected(None)
        assert app._inbox_detail_var.get() == long_body

    def test_command_like_inbox_content_renders_literally(self, root: tk.Tk) -> None:
        read_model, _, _, _, inbox, _ = _make_real_stack()
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

    def test_schedule_rows_render_real_data(self, root: tk.Tk) -> None:
        read_model, _, _, _, _, schedules = _make_real_stack()
        schedules.create(query="jarvis ai news", time_of_day="08:30", name="Morning")
        app = _build_app(root, read_model)
        children = app._schedules_tree.get_children()
        assert len(children) == 1
        values = app._schedules_tree.item(children[0], "values")
        assert values == ("1", "Morning", "jarvis ai news", "08:30", "Yes", "—", values[6])

    def test_schedule_row_shows_no_name_and_disabled_state(self, root: tk.Tk) -> None:
        read_model, _, _, _, _, schedules = _make_real_stack()
        record = schedules.create(query="q", time_of_day="08:00")
        schedules.disable(record.id)
        app = _build_app(root, read_model)
        values = app._schedules_tree.item(
            app._schedules_tree.get_children()[0], "values"
        )
        assert values[1] == "—"
        assert values[4] == "No"

    def test_refresh_sees_new_schedules(self, root: tk.Tk) -> None:
        read_model, _, _, _, _, schedules = _make_real_stack()
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
        read_model, _, _, _, _, schedules = _make_real_stack()
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
