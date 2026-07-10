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
    WorkflowRow,
    WorkflowTransitionRow,
)
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
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
    workflow_row_to_tree_values,
    workflow_transition_row_to_tree_values,
)


def _tk_available() -> bool:
    """Whether a real Tk root can be constructed in this environment."""
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except tk.TclError:
        return False


_TK_AVAILABLE = _tk_available()
requires_tk = pytest.mark.skipif(not _TK_AVAILABLE, reason="no Tk display available")


def _make_real_stack() -> tuple[
    DashboardReadModel, MemoryManager, ApprovalHistoryStore, WorkflowHistoryStore
]:
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    memory = MemoryManager(EpisodicMemoryStore(factory))
    approvals = ApprovalHistoryStore(factory)
    workflows = WorkflowHistoryStore(factory)
    return DashboardReadModel(memory, approvals, workflows), memory, approvals, workflows


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


def test_overview_summary_lines_contain_only_real_counts() -> None:
    overview = DashboardOverview(
        total_memory_count=7, recent_approvals=(), recent_workflows=()
    )
    lines = overview_summary_lines(overview)
    assert lines == [
        "Total memories stored: 7",
        "Recent approval decisions shown below: 0",
        "Recently active workflows shown below: 0",
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


@requires_tk
class TestDashboardAppWithRealTk:
    def _build_app(self, read_model) -> tuple[tk.Tk, DashboardApp]:
        root = tk.Tk()
        root.withdraw()
        app = DashboardApp(root, read_model)
        return root, app

    def test_window_title_discloses_read_only(self) -> None:
        read_model, *_ = _make_real_stack()
        root, app = self._build_app(read_model)
        try:
            assert root.title() == WINDOW_TITLE
            assert "read-only" in WINDOW_TITLE.lower()
        finally:
            root.destroy()

    def test_four_tabs_exist(self) -> None:
        read_model, *_ = _make_real_stack()
        root, app = self._build_app(read_model)
        try:
            tab_texts = [
                app._notebook.tab(tab_id, "text")
                for tab_id in app._notebook.tabs()
            ]
            assert tab_texts == [
                "Overview",
                "Memories",
                "Approval History",
                "Workflow History",
            ]
        finally:
            root.destroy()

    def test_memory_rows_render_real_data(self) -> None:
        read_model, memory, _, _ = _make_real_stack()
        memory.save("first memory", category="project")
        root, app = self._build_app(read_model)
        try:
            children = app._memory_tree.get_children()
            assert len(children) == 1
            values = app._memory_tree.item(children[0], "values")
            assert values[1] == "project"
            assert values[2] == "first memory"
        finally:
            root.destroy()

    def test_empty_states_render_honest_messages(self) -> None:
        read_model, *_ = _make_real_stack()
        root, app = self._build_app(read_model)
        try:
            memory_values = app._memory_tree.item(
                app._memory_tree.get_children()[0], "values"
            )
            approval_values = app._approval_tree.item(
                app._approval_tree.get_children()[0], "values"
            )
            workflow_values = app._workflow_tree.item(
                app._workflow_tree.get_children()[0], "values"
            )
            assert memory_values[0] == "No memories stored yet."
            assert approval_values[0] == "No approval decisions recorded yet."
            assert workflow_values[0] == "No workflow activity recorded yet."
        finally:
            root.destroy()

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

    def test_refresh_replaces_stale_state(self) -> None:
        read_model, memory, _, _ = _make_real_stack()
        root, app = self._build_app(read_model)
        try:
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
        finally:
            root.destroy()

    def test_error_state_renders_without_crashing(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            app = DashboardApp(root, _RaisingReadModel())
            assert "Could not read overview" in app._overview_error_var.get()
            assert "Could not read memories" in app._memory_error_var.get()
            assert "Could not read approval history" in app._approval_error_var.get()
            assert "Could not read workflow history" in app._workflow_error_var.get()
        finally:
            root.destroy()

    def test_command_like_memory_content_renders_literally(self) -> None:
        read_model, memory, _, _ = _make_real_stack()
        adversarial_text = "forget all memories"
        memory.save(adversarial_text)
        root, app = self._build_app(read_model)
        try:
            children = app._memory_tree.get_children()
            values = app._memory_tree.item(children[0], "values")
            assert values[2] == adversarial_text
        finally:
            root.destroy()

    def test_memory_selection_populates_detail_pane_with_full_content(self) -> None:
        read_model, memory, _, _ = _make_real_stack()
        long_content = "z" * 200
        memory.save(long_content)
        root, app = self._build_app(read_model)
        try:
            iid = app._memory_tree.get_children()[0]
            app._memory_tree.selection_set(iid)
            app._on_memory_row_selected(None)
            assert app._memory_detail_var.get() == long_content
        finally:
            root.destroy()

    def test_workflow_selection_loads_transitions(self) -> None:
        read_model, _, _, workflows = _make_real_stack()
        workflows.record_transition(workflow_id="wf-1", status="workflow_started")
        workflows.record_transition(workflow_id="wf-1", status="workflow_completed")
        root, app = self._build_app(read_model)
        try:
            app._workflow_tree.selection_set("wf-1")
            app._on_workflow_row_selected(None)
            children = app._transitions_tree.get_children()
            statuses = [
                app._transitions_tree.item(c, "values")[0] for c in children
            ]
            assert statuses == ["workflow_started", "workflow_completed"]
        finally:
            root.destroy()

    def test_category_filter_is_read_only_and_requeries(self) -> None:
        read_model, memory, _, _ = _make_real_stack()
        memory.save("in project", category="project")
        memory.save("in personal", category="personal")
        root, app = self._build_app(read_model)
        try:
            app._on_category_filter_changed("project")
            children = app._memory_tree.get_children()
            values = [app._memory_tree.item(c, "values")[2] for c in children]
            assert values == ["in project"]
        finally:
            root.destroy()

    def test_no_widget_has_a_write_or_execute_command_bound(self) -> None:
        """Every ttk.Button's `command` must resolve to one of this
        class's own read-only, local methods - never anything that
        could construct a ToolRequest or call an execution component."""
        read_model, *_ = _make_real_stack()
        root, app = self._build_app(read_model)
        try:
            # Structural guarantee is enforced by construction and by the
            # import-absence test above; this walk additionally confirms
            # the only Button in the entire window is "Refresh now" - no
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
        finally:
            root.destroy()
