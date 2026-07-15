"""
dashboard_app.py

tkinter/ttk presentation layer for the local, read-only Jarvis dashboard
(Phase 19; extended Phase 20, Batch 2 with the Inbox tab; extended Phase
21, Batch 3 with the Schedules tab; extended Phase 39, Batch 2 with the
Quarantine tab).

Responsibilities:
    - Render DashboardReadModel's view models (MemoryRow, ApprovalRow,
      WorkflowRow, WorkflowTransitionRow, InboxRow, ScheduleRow,
      QuarantineRow, DashboardOverview) into a seven-tab ttk.Notebook
      window: Overview, Memories, Approval History, Workflow History,
      Inbox, Schedules, Quarantine.
    - Refresh displayed state manually (a button) and periodically (a
      fixed-interval Tk `.after()` tick calling the same refresh code) -
      never claimed as "live" or "real-time".
    - Present honest empty states and isolate a read-model query failure
      to that one panel, never crashing the window or any other tab.

Does NOT:
    - Import or call CommandRouter, ToolExecutor, the live ApprovalManager,
      WorkflowEngine, AIReasoningEngine, AIRouter, WebSearchTool,
      FileRestoreTool, FileDeleteTool, QuarantineListTool, or
      QuarantineStore directly - the Quarantine tab displays only what
      DashboardReadModel.get_quarantine_entries() already returns.
    - Wire any widget to approve, deny, edit, delete, save, run, retry,
      resume, cancel, open-URL, browse-web, or ask-AI behaviour. No
      command input box exists. No double-click is executable. In
      particular, the Schedules tab has no create/edit/delete/enable/
      disable/run-now/retry control of any kind, and the Quarantine tab
      has no restore/delete/empty-trash/cleanup control of any kind.
    - Open a socket, HTTP listener, or any network connection of any
      kind.
    - Treat a durable "pending" approval-history row as a live,
      currently-actionable approval, a workflow history row as
      resumable/executable state, a schedule row as a live "next run"
      countdown, or a quarantine row as proof the file still physically
      exists in .jarvis_trash/ (it may have already been restored) -
      see the wording used on each tab.
    - Inspect .jarvis_trash/'s actual filesystem contents. The
      Quarantine tab reads only DashboardReadModel's own durable
      database records - it never duplicates QuarantineListTool's own
      filesystem-listing logic.

The pure formatting/mapping functions in this module (format_timestamp,
*_to_tree_values, empty/error-state text) do not touch Tk at all, so they
are testable without constructing any widget. DashboardApp is the only
part of this module that touches real tkinter objects.
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime, timezone
from tkinter import ttk

from dashboard.read_model import (
    ActivityRow,
    ApprovalRow,
    ApprovalStatusCount,
    DashboardOverview,
    DashboardReadModel,
    DashboardSystemStatus,
    InboxRow,
    MemoryCategoryCount,
    MemoryRow,
    QuarantineRow,
    ScheduleRow,
    StoreReachability,
    WorkflowRow,
    WorkflowStatusCount,
    WorkflowTransitionRow,
)

#: Window title. "(read-only)" is part of the title itself, not just
#: documentation, so the authority boundary is visible at a glance.
WINDOW_TITLE = "Jarvis — Dashboard (read-only)"

#: Default periodic requery interval. Honest wording only: this is
#: polling, described in the UI as "current as of last refresh", never
#: "live" or "real-time".
DEFAULT_REFRESH_INTERVAL_MS = 5000

_MEMORY_EMPTY_STATE = "No memories stored yet."
_APPROVAL_EMPTY_STATE = "No approval decisions recorded yet."
_WORKFLOW_EMPTY_STATE = "No workflow activity recorded yet."
_TRANSITIONS_EMPTY_STATE = "Select a workflow above to see its recorded history."
_INBOX_EMPTY_STATE = "No inbox entries yet."
_SCHEDULES_EMPTY_STATE = "No schedules configured yet."
_QUARANTINE_EMPTY_STATE = "No files currently in quarantine."
_ACTIVITY_EMPTY_STATE = "No recent activity recorded yet."

#: Read-only wording for the redesigned Overview tab (Phase 62, Batch 2):
#: a clear, honest header - "Online" describes only that the dashboard
#: process itself is running and has read the database, never a claim
#: about the CLI, scheduler, or any AI capability being active.
OVERVIEW_HEADER = "Jarvis Online"
SYSTEM_STATUS_CAPTION = (
    "Configuration read directly from Jarvis's own Settings object - "
    "never a second load, never the API key's actual value."
)
STORE_REACHABILITY_CAPTION = (
    "Whether each durable store this dashboard depends on could be read "
    "just now - a plain reachability check, never a write, never a new "
    "database connection."
)
ACTIVITY_CAPTION = (
    "A merged, real-timestamp view across memories, approvals, "
    "workflows, inbox, and quarantine - deterministic text only, never "
    "AI-generated, never a score of any kind."
)

#: Careful, durable-history-only wording (authorizing instructions, items
#: 15-16): never implies a durable "pending" row is a live, currently
#: actionable approval, and never implies workflow history is resumable.
APPROVAL_HISTORY_CAPTION = (
    "Durable history of past approval requests and decisions - not a live "
    "list of approvals currently awaiting your response. A \"pending\" row "
    "may describe a request from a previous run that can no longer "
    "actually be approved or declined."
)
WORKFLOW_HISTORY_CAPTION = (
    "Durable lifecycle history only - not resumable, not executable state, "
    "and not a guarantee that an in-memory paused workflow still exists "
    "after a restart."
)
MEMORY_DETAIL_PLACEHOLDER = "Select a memory above to see its full content."

#: Read-only wording for the Approval History detail pane (Phase 64,
#: Batch 2): mirrors MEMORY_DETAIL_PLACEHOLDER's own established
#: convention.
APPROVAL_DETAIL_PLACEHOLDER = (
    "Select an approval request above to see its full recorded detail."
)

#: Honest scope disclosure for the Workflow History Status Breakdown
#: panel (Phase 64, Batch 2): this tallies only the most recently
#: active workflows already shown in the table above - never an
#: all-time total across every workflow ever recorded, since no
#: all-time per-status aggregation exists for workflows (see
#: dashboard/read_model.py's own get_workflow_status_breakdown()
#: docstring for why).
WORKFLOW_STATUS_BREAKDOWN_SCOPE_NOTE = (
    "Based on the most recently active workflows shown in the table "
    "above - not an all-time total across every workflow ever recorded."
)

#: Read-only wording for the Memories tab (Phase 63): a durable copy of
#: what Jarvis was explicitly asked to remember - never created, edited,
#: deleted, moved to another category, or AI-summarized from here.
MEMORIES_CAPTION = (
    "Durable memories Jarvis was explicitly asked to remember - "
    "read-only. Nothing here can be created, edited, deleted, "
    "re-categorized, or AI-summarized; use the CLI memory commands, "
    "each of which still requires approval for any change."
)

#: Read-only wording for the Inbox tab (Phase 20): a saved entry is a
#: durable copy of something already shown once - never a live queue,
#: never re-runnable, never editable.
INBOX_CAPTION = (
    "Saved advisory summaries - durable copies of what Jarvis already "
    "showed you once. Read-only: nothing here can be re-run, edited, or "
    "sent anywhere."
)
INBOX_DETAIL_PLACEHOLDER = "Select an inbox entry above to see its full saved text."

#: Read-only wording for the Schedules tab (Phase 21): configuration
#: display only - no create/edit/delete/enable/disable/run-now control
#: exists here, and no "next due" countdown is computed or implied.
SCHEDULES_CAPTION = (
    "Configured daily web-search-summary schedules - read-only. Nothing "
    "here can be created, edited, enabled, disabled, or run now; use the "
    "CLI commands to manage schedules. This list does not show whether a "
    "schedule is currently due - only scheduler.py's own poll cycle "
    "decides that."
)

#: Read-only wording for the Quarantine tab (Phase 39): durable metadata
#: display only - no restore/delete/empty-trash/cleanup control exists
#: here, and a row is never proof the file still physically exists in
#: .jarvis_trash/ (it may have already been restored via the CLI).
QUARANTINE_CAPTION = (
    "Files recorded in Jarvis's quarantine directory (.jarvis_trash/) - "
    "read-only. Nothing here can be restored, deleted, or cleaned up; "
    "use the CLI 'restore file'/'delete file' commands, both of which "
    "still require approval. A row here does not guarantee the file is "
    "still physically in quarantine - it may have already been restored."
)


def format_timestamp(value: datetime) -> str:
    """Format a stored timestamp for honest display.

    Every timestamp in the three approved data domains is produced from
    UTC-oriented repository code (datetime.now(timezone.utc)), but comes
    back naive (no tzinfo) once reloaded from SQLite - a confirmed,
    evidence-based fact (docs/phase_19_implementation_plan.md, section
    8/12), not an assumption. This function therefore appends the "UTC"
    label literally, itself - it never reads value.tzinfo, never calls
    .astimezone(), and never attaches a timezone object merely to make
    formatting easier.

    Args:
        value: The stored datetime to format.

    Returns:
        A string of the form "YYYY-MM-DD HH:MM:SS UTC".
    """
    return f"{value.strftime('%Y-%m-%d %H:%M:%S')} UTC"


def format_error_state(domain: str, error: Exception) -> str:
    """Build the honest, isolated error message shown for one panel.

    Args:
        domain: A short label for the panel that failed (for example,
            "memories").
        error: The exception the read model raised.

    Returns:
        A one-line, panel-scoped error message. Never raises.
    """
    return f"Could not read {domain}: {error}"


def memory_row_to_tree_values(row: MemoryRow) -> tuple[str, str, str, str]:
    """Map a MemoryRow to the exact tuple shown in the Memories Treeview."""
    return (str(row.id), row.category, row.preview, format_timestamp(row.created_at))


def approval_row_to_tree_values(
    row: ApprovalRow,
) -> tuple[str, str, str, str, str, str, str]:
    """Map an ApprovalRow to the exact tuple shown in the Approval History Treeview."""
    decided_at = format_timestamp(row.decided_at) if row.decided_at else "—"
    decided_by = row.decided_by if row.decided_by else "—"
    return (
        row.request_id,
        row.action,
        row.security_tier,
        row.status,
        format_timestamp(row.created_at),
        decided_at,
        decided_by,
    )


def workflow_row_to_tree_values(row: WorkflowRow) -> tuple[str, str, str, str]:
    """Map a WorkflowRow to the exact tuple shown in the Workflow History Treeview."""
    if row.latest_step_number is not None and row.latest_step_total is not None:
        step = f"{row.latest_step_number}/{row.latest_step_total}"
    else:
        step = "—"
    return (
        row.workflow_id,
        row.latest_status,
        step,
        format_timestamp(row.latest_created_at),
    )


def workflow_transition_row_to_tree_values(
    row: WorkflowTransitionRow,
) -> tuple[str, str, str, str, str]:
    """Map a WorkflowTransitionRow to the exact tuple shown in the
    drill-down Treeview.

    The fifth value, approval_request_id, is "—" for any transition
    with none recorded (every transition except a
    "workflow_step_waiting" row) - never fabricated or guessed (Phase
    64, Batch 2).
    """
    if row.step_number is not None and row.step_total is not None:
        step = f"{row.step_number}/{row.step_total}"
    else:
        step = "—"
    tool_name = row.tool_name if row.tool_name else "—"
    approval_request_id = (
        row.approval_request_id if row.approval_request_id else "—"
    )
    return (
        row.status,
        step,
        tool_name,
        format_timestamp(row.created_at),
        approval_request_id,
    )


def inbox_row_to_tree_values(row: InboxRow) -> tuple[str, str, str]:
    """Map an InboxRow to the exact tuple shown in the Inbox Treeview."""
    return (format_timestamp(row.created_at), row.source_query, row.preview)


def schedule_row_to_tree_values(
    row: ScheduleRow,
) -> tuple[str, str, str, str, str, str, str]:
    """Map a ScheduleRow to the exact tuple shown in the Schedules Treeview."""
    name = row.name if row.name else "—"
    enabled = "Yes" if row.enabled else "No"
    last_run_at = format_timestamp(row.last_run_at) if row.last_run_at else "—"
    return (
        str(row.id),
        name,
        row.query_preview,
        row.time_of_day,
        enabled,
        last_run_at,
        format_timestamp(row.created_at),
    )


def quarantine_row_to_tree_values(
    row: QuarantineRow,
) -> tuple[str, str, str, str, str]:
    """Map a QuarantineRow to the exact tuple shown in the Quarantine Treeview."""
    session_id = str(row.session_id) if row.session_id is not None else "—"
    return (
        row.quarantine_name,
        row.original_path,
        row.quarantine_path,
        format_timestamp(row.quarantined_at),
        session_id,
    )


def overview_summary_lines(overview: DashboardOverview) -> list[str]:
    """Build the small set of real-data-only summary lines for the Overview tab.

    Every value here traces to a real query on DashboardReadModel - no
    estimated, simulated, or fabricated metric is ever included (no
    "intelligence percentage", "readiness score", or similar). The
    scheduled-inbox line (Phase 22) is a plain total and latest
    timestamp - never framed as "since you last checked", never an
    unread badge, and never dependent on the CLI's own last-seen marker
    (see notice/scheduled_inbox_notice_store.py), which this module
    never reads or writes.

    Args:
        overview: The overview view model to summarise.

    Returns:
        A short list of plain-text summary lines.
    """
    if overview.latest_scheduled_inbox_created_at is not None:
        latest_scheduled = format_timestamp(overview.latest_scheduled_inbox_created_at)
    else:
        latest_scheduled = "none yet"
    return [
        f"Total memories stored: {overview.total_memory_count}",
        f"Recent approval decisions shown below: {len(overview.recent_approvals)}",
        f"Recently active workflows shown below: {len(overview.recent_workflows)}",
        f"Total inbox entries: {overview.total_inbox_count}",
        f"Scheduled inbox entries: {overview.total_scheduled_inbox_count} "
        f"(most recent: {latest_scheduled})",
    ]


def system_status_lines(status: DashboardSystemStatus) -> list[str]:
    """Build honest, real-data-only summary lines for the System Status panel
    (Phase 62, Batch 2).

    Every value here traces directly to a field on the already-loaded
    Settings object DashboardReadModel was constructed with - nothing is
    estimated, simulated, or fabricated, and the API key's own value,
    a masked form, its length, or a hash is never included, only whether
    it is configured at all.

    Args:
        status: The system status view model to summarise.

    Returns:
        A short list of plain-text summary lines. If status.available is
        False (no Settings object was supplied), a single honest
        "unavailable" line is returned instead of fabricating any field.
    """
    if not status.available:
        return ["System status: unavailable (no configuration loaded)."]
    return [
        f"AI reasoning enabled: {status.ai_reasoning_enabled}",
        f"AI model: {status.ai_model}",
        f"Voice enabled: {status.voice_enabled} (provider: {status.voice_provider})",
        f"Voice input enabled: {status.voice_input_enabled} "
        f"(provider: {status.voice_input_provider})",
        f"Log level: {status.log_level}",
        f"Database path: {status.database_path}",
        f"Approval timeout (seconds): {status.approval_timeout_seconds}",
        f"Anthropic API key: {status.api_key_status}",
    ]


def store_reachability_line(row: StoreReachability) -> str:
    """Format one StoreReachability row as a single honest status line
    (Phase 62, Batch 2).

    Never fabricates success: a store that failed its read call, or the
    optional quarantine store when none was configured, is always
    labelled "not reachable", with the honest reason shown alongside it.

    Args:
        row: The store reachability view model to format.

    Returns:
        A single plain-text line naming the store and its status.
    """
    label = row.name.replace("_", " ")
    if row.reachable:
        return f"{label}: reachable"
    detail = f" ({row.detail})" if row.detail else ""
    return f"{label}: not reachable{detail}"


def activity_row_to_tree_values(row: ActivityRow) -> tuple[str, str, str]:
    """Map an ActivityRow to the exact tuple shown in the Recent Activity
    Treeview (Phase 62, Batch 2)."""
    return (format_timestamp(row.created_at), row.domain, row.summary)


def memory_category_breakdown_line(row: MemoryCategoryCount) -> str:
    """Format one MemoryCategoryCount as a single honest status line
    (Phase 63, Batch 2).

    Never fabricates, estimates, or infers anything: the count shown is
    exactly what MemoryManager.count_by_category() returned, including
    an honest zero for a category with no memories.

    Args:
        row: The memory category count view model to format.

    Returns:
        A single plain-text line naming the category and its real count.
    """
    return f"{row.category}: {row.count}"


def memory_detail_text(row: MemoryRow) -> str:
    """Build the enhanced selected-memory detail text (Phase 63, Batch 2).

    Uses only fields already present on the already-fetched MemoryRow -
    never a new query, never a fabricated field. Replaces the previous
    content-only detail pane with one that also shows the memory's id,
    category, and creation time, for a clearer, more identifiable detail
    view.

    Args:
        row: The selected memory row to describe.

    Returns:
        A short, multi-line, plain-text description followed by the
        memory's full, untruncated content.
    """
    return (
        f"ID: {row.id}  |  Category: {row.category}  |  "
        f"Created: {format_timestamp(row.created_at)}\n\n{row.full_content}"
    )


def approval_status_breakdown_line(row: ApprovalStatusCount) -> str:
    """Format one ApprovalStatusCount as a single honest status line
    (Phase 64, Batch 2).

    Never fabricates, estimates, or infers anything: the count shown is
    exactly what ApprovalHistoryStore.count_by_status() returned - a
    true, unbounded, all-time total - including an honest zero for a
    status with no matching entries.

    Args:
        row: The approval status count view model to format.

    Returns:
        A single plain-text line naming the status and its real count.
    """
    return f"{row.status}: {row.count}"


def workflow_status_breakdown_line(row: WorkflowStatusCount) -> str:
    """Format one WorkflowStatusCount as a single honest status line
    (Phase 64, Batch 2).

    Never fabricates, estimates, or infers anything: the count shown is
    a tally of the most recently active workflows already displayed in
    the table above - never an all-time total (see
    WORKFLOW_STATUS_BREAKDOWN_SCOPE_NOTE) - including an honest zero for
    a status matched by none of them.

    Args:
        row: The workflow status count view model to format.

    Returns:
        A single plain-text line naming the status and its real count.
    """
    return f"{row.status}: {row.count}"


def approval_detail_text(row: ApprovalRow) -> str:
    """Build the selected-approval detail text (Phase 64, Batch 2).

    Uses only fields already present on the already-fetched ApprovalRow
    - never a new query, never a fabricated field. This is the Approval
    History tab's first selection-based detail view; previously the
    tab had no drill-down of any kind.

    Args:
        row: The selected approval history row to describe.

    Returns:
        A short, multi-line, plain-text description covering the
        request id, action, tier, status, reason, decision reason (if
        present), and both timestamps.
    """
    decided_at = format_timestamp(row.decided_at) if row.decided_at else "—"
    decided_by = row.decided_by if row.decided_by else "—"
    decision_reason = row.decision_reason if row.decision_reason else "—"
    return (
        f"Request ID: {row.request_id}\n"
        f"Action: {row.action}\n"
        f"Tier: {row.security_tier}\n"
        f"Status: {row.status}\n"
        f"Reason: {row.reason}\n"
        f"Decision reason: {decision_reason}\n"
        f"Created: {format_timestamp(row.created_at)}\n"
        f"Decided: {decided_at}  |  Decided by: {decided_by}"
    )


class DashboardApp:
    """The tkinter/ttk read-only dashboard window.

    Attributes:
        _root: The Tk root window this app renders into. The caller
            constructs and owns it (and calls mainloop()) - this class
            never constructs its own root, so tests can pass in a
            withdrawn one.
        _read_model: The sole source of data. No other persistence
            object is ever touched by this class.
        _refresh_interval_ms: The fixed periodic requery interval.
    """

    def __init__(
        self,
        root: tk.Tk,
        read_model: DashboardReadModel,
        *,
        refresh_interval_ms: int = DEFAULT_REFRESH_INTERVAL_MS,
    ) -> None:
        """Build the dashboard window's widgets and load initial state.

        Args:
            root: The Tk root window to render into.
            read_model: The read-only data source.
            refresh_interval_ms: The periodic requery interval, in
                milliseconds.
        """
        self._root = root
        self._read_model = read_model
        self._refresh_interval_ms = refresh_interval_ms
        self._memory_category_filter: str | None = None
        self._selected_workflow_id: str | None = None

        root.title(WINDOW_TITLE)

        self._notebook = ttk.Notebook(root, padding=(6, 6))
        self._notebook.pack(fill="both", expand=True)

        self._last_refreshed_var = tk.StringVar(value="Last refreshed: never")
        self._build_overview_tab()
        self._build_memories_tab()
        self._build_approval_history_tab()
        self._build_workflow_history_tab()
        self._build_inbox_tab()
        self._build_schedules_tab()
        self._build_quarantine_tab()

        refresh_bar = ttk.Frame(root, padding=(6, 4))
        refresh_bar.pack(fill="x")
        ttk.Button(refresh_bar, text="Refresh now", command=self.refresh_all).pack(
            side="left"
        )
        ttk.Label(refresh_bar, textvariable=self._last_refreshed_var).pack(
            side="left", padx=8
        )

        self.refresh_all()
        self._schedule_next_refresh()

    # --- tab construction ----------------------------------------------------

    def _build_overview_tab(self) -> None:
        """Build the redesigned Overview tab (Phase 62, Batch 2): a clear
        "Jarvis Online" header, then four honest, real-data-only panels -
        System Status, Store Reachability, Summary Counts (the original
        Phase 19-22 overview lines, unchanged), and Recent Activity. Each
        panel has its own error variable so a failure reading one never
        blanks out another panel's own last-good state, mirroring this
        module's own established per-tab isolation convention, now
        applied within this one tab's four sub-panels."""
        frame = ttk.Frame(self._notebook, padding=(8, 8))
        self._notebook.add(frame, text="Overview")
        self._overview_frame = frame

        ttk.Label(
            frame, text=OVERVIEW_HEADER, font=("TkDefaultFont", 14, "bold")
        ).pack(anchor="w", pady=(0, 6))

        # --- System Status ---------------------------------------------------
        ttk.Label(frame, text="System Status", font=("TkDefaultFont", 10, "bold")).pack(
            anchor="w"
        )
        ttk.Label(frame, text=SYSTEM_STATUS_CAPTION, wraplength=480).pack(anchor="w")
        self._system_status_error_var = tk.StringVar(value="")
        ttk.Label(
            frame, textvariable=self._system_status_error_var, foreground="red"
        ).pack(anchor="w")
        self._system_status_frame = ttk.Frame(frame)
        self._system_status_frame.pack(fill="x", anchor="w", pady=(0, 6))
        self._system_status_labels: list[ttk.Label] = []

        # --- Store Reachability -----------------------------------------------
        ttk.Label(
            frame, text="Store Reachability", font=("TkDefaultFont", 10, "bold")
        ).pack(anchor="w")
        ttk.Label(frame, text=STORE_REACHABILITY_CAPTION, wraplength=480).pack(
            anchor="w"
        )
        self._reachability_error_var = tk.StringVar(value="")
        ttk.Label(
            frame, textvariable=self._reachability_error_var, foreground="red"
        ).pack(anchor="w")
        self._reachability_frame = ttk.Frame(frame)
        self._reachability_frame.pack(fill="x", anchor="w", pady=(0, 6))
        self._reachability_labels: list[ttk.Label] = []

        # --- Summary Counts (Phase 19-22, unchanged content) -------------------
        ttk.Label(frame, text="Summary Counts", font=("TkDefaultFont", 10, "bold")).pack(
            anchor="w"
        )
        self._overview_error_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self._overview_error_var, foreground="red").pack(
            anchor="w"
        )
        self._overview_counts_frame = ttk.Frame(frame)
        self._overview_counts_frame.pack(fill="x", anchor="w", pady=(0, 6))
        self._overview_labels: list[ttk.Label] = []

        # --- Recent Activity ----------------------------------------------------
        ttk.Label(
            frame, text="Recent Activity", font=("TkDefaultFont", 10, "bold")
        ).pack(anchor="w")
        ttk.Label(frame, text=ACTIVITY_CAPTION, wraplength=480).pack(anchor="w")
        self._activity_error_var = tk.StringVar(value="")
        ttk.Label(
            frame, textvariable=self._activity_error_var, foreground="red"
        ).pack(anchor="w")

        activity_columns = ("created_at", "domain", "summary")
        activity_tree = ttk.Treeview(
            frame, columns=activity_columns, show="headings", height=8
        )
        for column, heading in zip(activity_columns, ("Time", "Domain", "Summary")):
            activity_tree.heading(column, text=heading)
        activity_tree.column("created_at", width=170, stretch=False)
        activity_tree.column("domain", width=90, stretch=False)
        activity_tree.column("summary", width=360)
        activity_tree.pack(fill="both", expand=True, pady=(4, 4))
        self._activity_tree = activity_tree

    @staticmethod
    def _render_label_lines(
        container: ttk.Frame, existing_labels: list[ttk.Label], lines: list[str]
    ) -> list[ttk.Label]:
        """Replace a panel's plain-text label lines with a fresh set.

        Mirrors the destroy-and-recreate approach the original Overview
        tab already used for its own summary lines (Phase 19-22) - each
        refresh tears down the previous labels and rebuilds new ones from
        the latest data, so no label is ever left showing stale text.

        Args:
            container: The frame these labels are packed into.
            existing_labels: The previous refresh's own labels, to
                destroy before rebuilding.
            lines: The new plain-text lines to render, one label each.

        Returns:
            The newly created list of labels, replacing existing_labels.
        """
        for label in existing_labels:
            label.destroy()
        new_labels: list[ttk.Label] = []
        for line in lines:
            label = ttk.Label(container, text=line)
            label.pack(anchor="w")
            new_labels.append(label)
        return new_labels

    def _build_memories_tab(self) -> None:
        frame = ttk.Frame(self._notebook, padding=(8, 8))
        self._notebook.add(frame, text="Memories")

        ttk.Label(frame, text=MEMORIES_CAPTION, wraplength=480).pack(anchor="w")

        # --- Category Breakdown (Phase 63, Batch 2) ---------------------------
        ttk.Label(
            frame, text="Category Breakdown", font=("TkDefaultFont", 10, "bold")
        ).pack(anchor="w", pady=(6, 0))
        self._memory_breakdown_error_var = tk.StringVar(value="")
        ttk.Label(
            frame, textvariable=self._memory_breakdown_error_var, foreground="red"
        ).pack(anchor="w")
        self._memory_breakdown_frame = ttk.Frame(frame)
        self._memory_breakdown_frame.pack(fill="x", anchor="w", pady=(0, 6))
        self._memory_breakdown_labels: list[ttk.Label] = []

        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        ttk.Label(controls, text="Category:").pack(side="left")
        self._category_var = tk.StringVar(value="All")
        category_choices = ["All", "general", "personal", "project", "preference", "note"]
        category_menu = ttk.OptionMenu(
            controls,
            self._category_var,
            category_choices[0],
            *category_choices,
            command=self._on_category_filter_changed,
        )
        category_menu.pack(side="left", padx=4)

        self._memory_error_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self._memory_error_var, foreground="red").pack(
            anchor="w"
        )

        columns = ("id", "category", "preview", "created_at")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for column, heading in zip(
            columns, ("ID", "Category", "Preview", "Created At")
        ):
            tree.heading(column, text=heading)
        tree.pack(fill="both", expand=True)
        tree.bind("<<TreeviewSelect>>", self._on_memory_row_selected)
        self._memory_tree = tree
        self._memory_rows_by_id: dict[str, MemoryRow] = {}

        self._memory_detail_var = tk.StringVar(value=MEMORY_DETAIL_PLACEHOLDER)
        ttk.Label(
            frame, textvariable=self._memory_detail_var, wraplength=480, justify="left"
        ).pack(fill="x", anchor="w")

    def _build_approval_history_tab(self) -> None:
        frame = ttk.Frame(self._notebook, padding=(8, 8))
        self._notebook.add(frame, text="Approval History")

        ttk.Label(frame, text=APPROVAL_HISTORY_CAPTION, wraplength=480).pack(
            anchor="w"
        )

        # --- Status Breakdown (Phase 64, Batch 2) ------------------------------
        ttk.Label(
            frame, text="Status Breakdown", font=("TkDefaultFont", 10, "bold")
        ).pack(anchor="w", pady=(6, 0))
        self._approval_breakdown_error_var = tk.StringVar(value="")
        ttk.Label(
            frame, textvariable=self._approval_breakdown_error_var, foreground="red"
        ).pack(anchor="w")
        self._approval_breakdown_frame = ttk.Frame(frame)
        self._approval_breakdown_frame.pack(fill="x", anchor="w", pady=(0, 6))
        self._approval_breakdown_labels: list[ttk.Label] = []

        self._approval_error_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self._approval_error_var, foreground="red").pack(
            anchor="w"
        )

        columns = (
            "request_id",
            "action",
            "tier",
            "status",
            "created_at",
            "decided_at",
            "decided_by",
        )
        headings = (
            "Request ID",
            "Action",
            "Tier",
            "Status",
            "Created At",
            "Decided At",
            "Decided By",
        )
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for column, heading in zip(columns, headings):
            tree.heading(column, text=heading)
        tree.pack(fill="both", expand=True)
        tree.bind("<<TreeviewSelect>>", self._on_approval_row_selected)
        self._approval_tree = tree
        self._approval_rows_by_id: dict[str, ApprovalRow] = {}

        self._approval_detail_var = tk.StringVar(value=APPROVAL_DETAIL_PLACEHOLDER)
        ttk.Label(
            frame,
            textvariable=self._approval_detail_var,
            wraplength=480,
            justify="left",
        ).pack(fill="x", anchor="w")

    def _build_workflow_history_tab(self) -> None:
        frame = ttk.Frame(self._notebook, padding=(8, 8))
        self._notebook.add(frame, text="Workflow History")

        ttk.Label(frame, text=WORKFLOW_HISTORY_CAPTION, wraplength=480).pack(
            anchor="w"
        )

        # --- Status Breakdown (Phase 64, Batch 2) ------------------------------
        ttk.Label(
            frame, text="Status Breakdown", font=("TkDefaultFont", 10, "bold")
        ).pack(anchor="w", pady=(6, 0))
        ttk.Label(
            frame, text=WORKFLOW_STATUS_BREAKDOWN_SCOPE_NOTE, wraplength=480
        ).pack(anchor="w")
        self._workflow_breakdown_error_var = tk.StringVar(value="")
        ttk.Label(
            frame, textvariable=self._workflow_breakdown_error_var, foreground="red"
        ).pack(anchor="w")
        self._workflow_breakdown_frame = ttk.Frame(frame)
        self._workflow_breakdown_frame.pack(fill="x", anchor="w", pady=(0, 6))
        self._workflow_breakdown_labels: list[ttk.Label] = []

        self._workflow_error_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self._workflow_error_var, foreground="red").pack(
            anchor="w"
        )

        columns = ("workflow_id", "latest_status", "step", "latest_created_at")
        headings = ("Workflow ID", "Latest Recorded Status", "Step", "Last Activity")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for column, heading in zip(columns, headings):
            tree.heading(column, text=heading)
        tree.pack(fill="both", expand=True)
        tree.bind("<<TreeviewSelect>>", self._on_workflow_row_selected)
        self._workflow_tree = tree

        ttk.Label(frame, text="Recorded transitions for the selected workflow:").pack(
            anchor="w"
        )
        transition_columns = (
            "status",
            "step",
            "tool_name",
            "created_at",
            "approval_request_id",
        )
        transition_headings = (
            "Status",
            "Step",
            "Tool",
            "Recorded At",
            "Approval Request ID",
        )
        transitions_tree = ttk.Treeview(
            frame, columns=transition_columns, show="headings"
        )
        for column, heading in zip(transition_columns, transition_headings):
            transitions_tree.heading(column, text=heading)
        transitions_tree.pack(fill="both", expand=True)
        self._transitions_tree = transitions_tree

    def _build_inbox_tab(self) -> None:
        frame = ttk.Frame(self._notebook, padding=(8, 8))
        self._notebook.add(frame, text="Inbox")

        ttk.Label(frame, text=INBOX_CAPTION, wraplength=480).pack(anchor="w")
        self._inbox_error_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self._inbox_error_var, foreground="red").pack(
            anchor="w"
        )

        columns = ("created_at", "query", "preview")
        headings = ("Created At", "Query", "Preview")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for column, heading in zip(columns, headings):
            tree.heading(column, text=heading)
        tree.column("created_at", width=170, stretch=False)
        tree.column("query", width=220)
        tree.column("preview", width=320)
        tree.pack(fill="both", expand=True, pady=(4, 4))
        tree.bind("<<TreeviewSelect>>", self._on_inbox_row_selected)
        self._inbox_tree = tree
        self._inbox_rows_by_id: dict[str, InboxRow] = {}

        self._inbox_detail_var = tk.StringVar(value=INBOX_DETAIL_PLACEHOLDER)
        ttk.Label(
            frame, textvariable=self._inbox_detail_var, wraplength=480, justify="left"
        ).pack(fill="x", anchor="w")

    def _build_schedules_tab(self) -> None:
        frame = ttk.Frame(self._notebook, padding=(8, 8))
        self._notebook.add(frame, text="Schedules")

        ttk.Label(frame, text=SCHEDULES_CAPTION, wraplength=480).pack(anchor="w")
        self._schedules_error_var = tk.StringVar(value="")
        ttk.Label(
            frame, textvariable=self._schedules_error_var, foreground="red"
        ).pack(anchor="w")

        columns = (
            "id",
            "name",
            "query",
            "time_of_day",
            "enabled",
            "last_run_at",
            "created_at",
        )
        headings = (
            "ID",
            "Name",
            "Query",
            "Time Of Day",
            "Enabled",
            "Last Run At",
            "Created At",
        )
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for column, heading in zip(columns, headings):
            tree.heading(column, text=heading)
        tree.pack(fill="both", expand=True, pady=(4, 4))
        self._schedules_tree = tree

    def _build_quarantine_tab(self) -> None:
        frame = ttk.Frame(self._notebook, padding=(8, 8))
        self._notebook.add(frame, text="Quarantine")

        ttk.Label(frame, text=QUARANTINE_CAPTION, wraplength=480).pack(anchor="w")
        self._quarantine_error_var = tk.StringVar(value="")
        ttk.Label(
            frame, textvariable=self._quarantine_error_var, foreground="red"
        ).pack(anchor="w")

        columns = (
            "name",
            "original_path",
            "quarantine_path",
            "quarantined_at",
            "session_id",
        )
        headings = (
            "Name",
            "Original Path",
            "Quarantine Path",
            "Quarantined At",
            "Session",
        )
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for column, heading in zip(columns, headings):
            tree.heading(column, text=heading)
        tree.pack(fill="both", expand=True, pady=(4, 4))
        self._quarantine_tree = tree

    # --- refresh ---------------------------------------------------------------

    def refresh_all(self) -> None:
        """Requery all panels and update their displayed state.

        Each panel's query is isolated: a failure in one (a transient
        SQLite lock, a malformed row) renders that panel's own error
        state and leaves the other panels' most recent successful state
        untouched. This method never raises - it is safe to call from a
        button press or a periodic timer tick.
        """
        self._refresh_overview()
        self._refresh_memory_breakdown()
        self._refresh_memories()
        self._refresh_approval_breakdown()
        self._refresh_approval_history()
        self._refresh_workflow_breakdown()
        self._refresh_workflow_history()
        self._refresh_inbox()
        self._refresh_schedules()
        self._refresh_quarantine()
        self._last_refreshed_var.set(
            f"Last refreshed: {format_timestamp(datetime.now(timezone.utc))}"
        )

    def _refresh_overview(self) -> None:
        """Refresh all four Overview panels independently (Phase 62,
        Batch 2): a failure reading one panel's data sets only that
        panel's own error message and leaves the other three panels'
        most recent successful state untouched, exactly as every other
        tab in this module already isolates its own single query."""
        self._refresh_system_status()
        self._refresh_store_reachability()
        self._refresh_overview_counts()
        self._refresh_recent_activity()

    def _refresh_system_status(self) -> None:
        try:
            status = self._read_model.get_system_status()
        except Exception as exc:  # noqa: BLE001 - isolate any read failure
            self._system_status_error_var.set(format_error_state("system status", exc))
            return
        self._system_status_error_var.set("")
        self._system_status_labels = self._render_label_lines(
            self._system_status_frame,
            self._system_status_labels,
            system_status_lines(status),
        )

    def _refresh_store_reachability(self) -> None:
        try:
            rows = self._read_model.get_store_reachability()
        except Exception as exc:  # noqa: BLE001 - isolate any read failure
            self._reachability_error_var.set(
                format_error_state("store reachability", exc)
            )
            return
        self._reachability_error_var.set("")
        self._reachability_labels = self._render_label_lines(
            self._reachability_frame,
            self._reachability_labels,
            [store_reachability_line(row) for row in rows],
        )

    def _refresh_overview_counts(self) -> None:
        try:
            overview = self._read_model.get_overview()
        except Exception as exc:  # noqa: BLE001 - isolate any read failure
            self._overview_error_var.set(format_error_state("overview", exc))
            return
        self._overview_error_var.set("")
        self._overview_labels = self._render_label_lines(
            self._overview_counts_frame,
            self._overview_labels,
            overview_summary_lines(overview),
        )

    def _refresh_recent_activity(self) -> None:
        try:
            rows = self._read_model.get_recent_activity()
        except Exception as exc:  # noqa: BLE001 - isolate any read failure
            self._activity_error_var.set(format_error_state("recent activity", exc))
            return
        self._activity_error_var.set("")
        tree = self._activity_tree
        tree.delete(*tree.get_children())
        if not rows:
            tree.insert("", "end", values=(_ACTIVITY_EMPTY_STATE, "", ""))
            return
        for row in rows:
            tree.insert("", "end", values=activity_row_to_tree_values(row))

    def _refresh_memory_breakdown(self) -> None:
        """Refresh the Category Breakdown panel (Phase 63, Batch 2).

        Isolated from _refresh_memories's own error state - a failure
        reading the breakdown never blanks the memory list, and vice
        versa, mirroring this module's established per-panel isolation
        convention.
        """
        try:
            rows = self._read_model.get_memory_category_breakdown()
        except Exception as exc:  # noqa: BLE001 - isolate any read failure
            self._memory_breakdown_error_var.set(
                format_error_state("memory category breakdown", exc)
            )
            return
        self._memory_breakdown_error_var.set("")
        self._memory_breakdown_labels = self._render_label_lines(
            self._memory_breakdown_frame,
            self._memory_breakdown_labels,
            [memory_category_breakdown_line(row) for row in rows],
        )

    def _refresh_memories(self) -> None:
        try:
            rows = self._read_model.get_recent_memories(
                category=self._memory_category_filter
            )
        except Exception as exc:  # noqa: BLE001 - isolate any read failure
            self._memory_error_var.set(format_error_state("memories", exc))
            return
        self._memory_error_var.set("")
        tree = self._memory_tree
        tree.delete(*tree.get_children())
        self._memory_rows_by_id.clear()
        if not rows:
            tree.insert("", "end", values=(_MEMORY_EMPTY_STATE, "", "", ""))
            return
        for row in rows:
            iid = str(row.id)
            tree.insert("", "end", iid=iid, values=memory_row_to_tree_values(row))
            self._memory_rows_by_id[iid] = row

    def _refresh_approval_breakdown(self) -> None:
        """Refresh the Approval History Status Breakdown panel (Phase
        64, Batch 2), isolated from _refresh_approval_history's own
        error state, mirroring this module's established per-panel
        isolation convention."""
        try:
            rows = self._read_model.get_approval_status_breakdown()
        except Exception as exc:  # noqa: BLE001 - isolate any read failure
            self._approval_breakdown_error_var.set(
                format_error_state("approval status breakdown", exc)
            )
            return
        self._approval_breakdown_error_var.set("")
        self._approval_breakdown_labels = self._render_label_lines(
            self._approval_breakdown_frame,
            self._approval_breakdown_labels,
            [approval_status_breakdown_line(row) for row in rows],
        )

    def _refresh_approval_history(self) -> None:
        try:
            rows = self._read_model.get_recent_approvals()
        except Exception as exc:  # noqa: BLE001 - isolate any read failure
            self._approval_error_var.set(format_error_state("approval history", exc))
            return
        self._approval_error_var.set("")
        tree = self._approval_tree
        tree.delete(*tree.get_children())
        self._approval_rows_by_id.clear()
        if not rows:
            tree.insert("", "end", values=(_APPROVAL_EMPTY_STATE,) + ("",) * 6)
            return
        for row in rows:
            iid = row.request_id
            tree.insert("", "end", iid=iid, values=approval_row_to_tree_values(row))
            self._approval_rows_by_id[iid] = row

    def _refresh_workflow_breakdown(self) -> None:
        """Refresh the Workflow History Status Breakdown panel (Phase
        64, Batch 2), isolated from _refresh_workflow_history's own
        error state. Honestly scoped to the most recently active
        workflows only - see WORKFLOW_STATUS_BREAKDOWN_SCOPE_NOTE.
        """
        try:
            rows = self._read_model.get_workflow_status_breakdown()
        except Exception as exc:  # noqa: BLE001 - isolate any read failure
            self._workflow_breakdown_error_var.set(
                format_error_state("workflow status breakdown", exc)
            )
            return
        self._workflow_breakdown_error_var.set("")
        self._workflow_breakdown_labels = self._render_label_lines(
            self._workflow_breakdown_frame,
            self._workflow_breakdown_labels,
            [workflow_status_breakdown_line(row) for row in rows],
        )

    def _refresh_workflow_history(self) -> None:
        try:
            rows = self._read_model.get_recent_workflows()
        except Exception as exc:  # noqa: BLE001 - isolate any read failure
            self._workflow_error_var.set(format_error_state("workflow history", exc))
            return
        self._workflow_error_var.set("")
        tree = self._workflow_tree
        tree.delete(*tree.get_children())
        if not rows:
            tree.insert("", "end", values=(_WORKFLOW_EMPTY_STATE, "", "", ""))
        else:
            for row in rows:
                tree.insert(
                    "", "end", iid=row.workflow_id, values=workflow_row_to_tree_values(row)
                )

        self._refresh_transitions_for_selected_workflow()

    def _refresh_transitions_for_selected_workflow(self) -> None:
        tree = self._transitions_tree
        tree.delete(*tree.get_children())
        if self._selected_workflow_id is None:
            tree.insert("", "end", values=(_TRANSITIONS_EMPTY_STATE, "", "", "", ""))
            return
        try:
            transitions = self._read_model.get_workflow_transitions(
                self._selected_workflow_id
            )
        except Exception as exc:  # noqa: BLE001 - isolate any read failure
            self._workflow_error_var.set(format_error_state("workflow transitions", exc))
            return
        if not transitions:
            tree.insert("", "end", values=(_TRANSITIONS_EMPTY_STATE, "", "", "", ""))
            return
        for transition in transitions:
            tree.insert(
                "", "end", values=workflow_transition_row_to_tree_values(transition)
            )

    def _refresh_inbox(self) -> None:
        try:
            rows = self._read_model.get_recent_inbox_entries()
        except Exception as exc:  # noqa: BLE001 - isolate any read failure
            self._inbox_error_var.set(format_error_state("inbox", exc))
            return
        self._inbox_error_var.set("")
        tree = self._inbox_tree
        tree.delete(*tree.get_children())
        self._inbox_rows_by_id.clear()
        if not rows:
            tree.insert("", "end", values=(_INBOX_EMPTY_STATE, "", ""))
            return
        for row in rows:
            iid = str(row.id)
            tree.insert("", "end", iid=iid, values=inbox_row_to_tree_values(row))
            self._inbox_rows_by_id[iid] = row

    def _refresh_schedules(self) -> None:
        try:
            rows = self._read_model.get_schedules()
        except Exception as exc:  # noqa: BLE001 - isolate any read failure
            self._schedules_error_var.set(format_error_state("schedules", exc))
            return
        self._schedules_error_var.set("")
        tree = self._schedules_tree
        tree.delete(*tree.get_children())
        if not rows:
            tree.insert("", "end", values=(_SCHEDULES_EMPTY_STATE,) + ("",) * 6)
            return
        for row in rows:
            tree.insert("", "end", iid=str(row.id), values=schedule_row_to_tree_values(row))

    def _refresh_quarantine(self) -> None:
        try:
            rows = self._read_model.get_quarantine_entries()
        except Exception as exc:  # noqa: BLE001 - isolate any read failure
            self._quarantine_error_var.set(format_error_state("quarantine", exc))
            return
        self._quarantine_error_var.set("")
        tree = self._quarantine_tree
        tree.delete(*tree.get_children())
        if not rows:
            tree.insert("", "end", values=(_QUARANTINE_EMPTY_STATE,) + ("",) * 4)
            return
        for row in rows:
            tree.insert("", "end", values=quarantine_row_to_tree_values(row))

    def _schedule_next_refresh(self) -> None:
        """Schedule the next periodic requery via Tk's own `.after()`.

        This runs on the Tk main loop thread - never a background
        thread - so there is no cross-thread SQLAlchemy session sharing
        and no new concurrency class introduced by the UI layer. This is
        polling, not an event-driven or real-time mechanism, and is never
        described as either in the UI.
        """
        self._root.after(self._refresh_interval_ms, self._on_refresh_tick)

    def _on_refresh_tick(self) -> None:
        self.refresh_all()
        self._schedule_next_refresh()

    # --- local, read-only interactions -----------------------------------------

    def _on_category_filter_changed(self, selected: str) -> None:
        """Update the local category filter and requery (read-only)."""
        self._memory_category_filter = None if selected == "All" else selected
        self._refresh_memories()

    def _on_memory_row_selected(self, _event: object) -> None:
        """Populate the detail pane with one memory's id, category,
        creation time, and full content (Phase 63, Batch 2: enhanced
        from content-only).

        Selecting a row only reads already-loaded local state (the same
        MemoryRow already fetched by the last _refresh_memories() call)
        - it never triggers a new database query, a tool call, or any
        external action.
        """
        selection = self._memory_tree.selection()
        if not selection:
            return
        row = self._memory_rows_by_id.get(selection[0])
        if row is None:
            return
        self._memory_detail_var.set(memory_detail_text(row))

    def _on_approval_row_selected(self, _event: object) -> None:
        """Populate the detail pane with one approval request's full
        recorded detail (Phase 64, Batch 2).

        Selecting a row only reads already-loaded local state (the same
        ApprovalRow already fetched by the last
        _refresh_approval_history() call) - it never triggers a new
        database query, a tool call, or any external action.
        """
        selection = self._approval_tree.selection()
        if not selection:
            return
        row = self._approval_rows_by_id.get(selection[0])
        if row is None:
            return
        self._approval_detail_var.set(approval_detail_text(row))

    def _on_workflow_row_selected(self, _event: object) -> None:
        """Select a workflow to drill into its recorded transitions."""
        selection = self._workflow_tree.selection()
        if not selection:
            return
        self._selected_workflow_id = selection[0]
        self._refresh_transitions_for_selected_workflow()

    def _on_inbox_row_selected(self, _event: object) -> None:
        """Populate the detail pane with one inbox entry's full saved text.

        Selecting a row only reads already-loaded local state - it never
        triggers a database query, a tool call, or any external action.
        """
        selection = self._inbox_tree.selection()
        if not selection:
            return
        row = self._inbox_rows_by_id.get(selection[0])
        if row is None:
            return
        self._inbox_detail_var.set(row.full_body)
