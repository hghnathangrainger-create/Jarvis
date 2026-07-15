"""
read_model.py

Narrow, read-only composition layer over Jarvis's durable stores, for the
local dashboard (Phase 19; extended Phase 20 with the inbox; extended
Phase 21 with schedules; extended Phase 39, Batch 1 with quarantine
visibility; extended Phase 62, Batch 1 with system status, store
reachability, and a merged recent-activity feed).

Responsibilities:
    - Define small, frozen view-model dataclasses shaped for dashboard
      display (MemoryRow, ApprovalRow, WorkflowRow, WorkflowTransitionRow,
      InboxRow, ScheduleRow, QuarantineRow, DashboardOverview,
      DashboardSystemStatus, StoreReachability, ActivityRow).
    - Define DashboardReadModel, which composes MemoryManager,
      ApprovalHistoryStore, WorkflowHistoryStore, InboxStore,
      ScheduleStore, (optionally) QuarantineStore's, and (optionally) an
      already-loaded Settings object's existing public read
      methods/fields into those view models.

Does NOT:
    - Call any write/mutating method on any store (save, update_content,
      update_category, forget, record_request, record_decision,
      record_timeout, record_transition, append, create, enable, disable,
      claim_due, record_quarantine).
    - Parse CLI output, tool output, or any formatted display string.
    - Import CommandRouter, ToolExecutor, the live ApprovalManager,
      WorkflowEngine, AIReasoningEngine, AIRouter, or WebSearchTool.
    - Implement a generic CQRS, event-sourcing, or reporting framework.
      This module exists only to compose the approved dashboard domains;
      it has exactly as many methods as the dashboard's views need, no
      more.
    - Truncate, summarise, or otherwise rewrite memory or inbox content
      using AI. Preview truncation here is a fixed, deterministic
      character cut, never a semantic rewrite.
    - Inspect .jarvis_trash/'s actual filesystem contents for quarantine
      visibility. get_quarantine_entries() reads only QuarantineStore's
      own durable database records (Phase 39, Batch 1) - reconciling
      those records against the live filesystem, if ever needed, is a
      distinct, separately-reviewed future decision, not part of this
      narrow read model.
    - Call load_settings() itself, or read .env/os.environ directly
      (Phase 62, Batch 1): get_system_status() only ever reads the
      already-loaded Settings object dashboard.py's own composition root
      passes in at construction time - mirroring ConfigTool's own
      established "never load settings a second time" discipline.
    - Show the API key's value, a masked form, its length, or a
      hash/fingerprint of it anywhere - only "configured"/"not
      configured", exactly like ConfigTool.
    - Open a new database connection, construct a new store, or create a
      file or row to check store reachability (Phase 62, Batch 1):
      get_store_reachability() only ever calls an already-existing,
      already-proven-safe read method on the same store instances this
      class was already constructed with.
    - Use AI, infer missing data, or fabricate a metric/score of any kind
      to build the recent-activity feed (Phase 62, Batch 1):
      get_recent_activity() only ever recombines rows this class's own
      existing get_recent_*() methods already return, using each row's
      own real, already-stored timestamp.
    - Sort, rank, or score categories by memory count (Phase 63, Batch
      1): get_memory_category_breakdown() always returns categories in
      memory.memory_models.KNOWN_CATEGORIES's own fixed, declared order
      - never reordered by count - so the display can never imply a
      category is more "important" than another.
    - Sort, rank, or score approval/workflow statuses by their own
      counts (Phase 64, Batch 1): get_approval_status_breakdown() and
      get_workflow_status_breakdown() always return statuses in
      KNOWN_APPROVAL_STATUSES's/KNOWN_WORKFLOW_STATUSES's own fixed,
      declared order - never reordered by count. The approval breakdown
      is a true, unbounded, all-time total per status
      (ApprovalHistoryStore.count_by_status()); the workflow breakdown
      is honestly scoped to only the most recently active workflows
      already returned by get_recent_workflows() - it is never
      presented, or claimed, as an all-time total, since no all-time
      per-status aggregation exists for workflows (a workflow's
      "status" is its own latest transition, not a fixed column).

This is the sole persistence-facing layer the dashboard UI depends on -
the UI never imports a store directly.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from approval.approval_history_store import (
    KNOWN_APPROVAL_STATUSES,
    ApprovalHistoryStore,
)
from config.settings import Settings
from inbox.inbox_store import InboxStore
from memory.memory_manager import MemoryManager
from memory.memory_models import KNOWN_CATEGORIES
from quarantine.quarantine_store import QuarantineStore
from scheduling.schedule_store import ScheduleStore
from scheduling.scheduled_summary_runner import SCHEDULED_SOURCE_TYPE
from workflow.workflow_history_store import (
    KNOWN_WORKFLOW_STATUSES,
    WorkflowHistoryStore,
)

#: Maximum length of a memory content preview shown in list views. Full,
#: untruncated content is still carried on MemoryRow.full_content, for an
#: explicit detail view only - see the module docstring on privacy intent
#: in docs/phase_19_implementation_plan.md, section 11.
_PREVIEW_MAX_CHARS = 120

#: Default number of rows shown in the Overview panel's small previews.
_OVERVIEW_PREVIEW_LIMIT = 5

#: Default number of entries returned by get_recent_activity() (Phase 62,
#: Batch 1).
_ACTIVITY_LIMIT_DEFAULT = 20

#: The two honest, non-secret API key statuses get_system_status() ever
#: reports - mirroring ConfigTool's own "set"/"not set" wording exactly,
#: just phrased for a status panel ("configured"/"not configured").
#: Never a value, a masked form, a length, or a hash/fingerprint.
_API_KEY_CONFIGURED = "configured"
_API_KEY_NOT_CONFIGURED = "not configured"


def _truncate_preview(content: str, max_chars: int = _PREVIEW_MAX_CHARS) -> str:
    """Deterministically truncate memory content for a list-view preview.

    A plain character cut, never a semantic rewrite or AI summarisation.
    Content at or under the limit is returned unchanged; longer content is
    cut to max_chars and has "..." appended so a truncated preview is
    visibly distinguishable from a short memory that just happens to fit.

    Args:
        content: The full memory content.
        max_chars: The maximum number of content characters to keep
            before appending the truncation marker.

    Returns:
        The original content, or a truncated-and-marked preview.
    """
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "..."


@dataclass(frozen=True, slots=True)
class MemoryRow:
    """A single memory, shaped for dashboard display.

    Attributes:
        id: The memory's primary key.
        category: The memory's normalised category.
        preview: A deterministically truncated preview of the content,
            for list-view display.
        full_content: The untruncated content, for a detail view shown
            only after explicit row selection - never rendered in bulk.
        created_at: UTC-in-substance timestamp (see read_model module
            note and docs/phase_19_implementation_plan.md section 12 for
            why this is naive once reloaded from SQLite).
    """

    id: int
    category: str
    preview: str
    full_content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryCategoryCount:
    """One known memory category's real, current count (Phase 63, Batch
    1).

    Produced only by calling MemoryManager.count_by_category() - never a
    fabricated, estimated, or inferred value, and never a ranking:
    get_memory_category_breakdown() always returns these in
    memory.memory_models.KNOWN_CATEGORIES's own fixed order, never
    sorted by count, so nothing here implies one category is more
    important than another.

    Attributes:
        category: The known category name (one of
            memory.memory_models.KNOWN_CATEGORIES).
        count: The real, current number of memories stored in this
            category - zero is a valid, honestly-reported value, never
            omitted.
    """

    category: str
    count: int


@dataclass(frozen=True, slots=True)
class ApprovalRow:
    """A single approval history entry, shaped for dashboard display.

    This describes durable approval *history* only. It is never a live,
    currently-actionable pending approval: ApprovalManager's own pending
    requests live in memory and are not readable from this row. A
    "pending" status here means only that, as of this row's last update,
    no decision or timeout had been recorded - it may describe a request
    from a prior process run that can no longer actually be approved or
    declined (see docs/phase_19_implementation_plan.md section 17, the
    "ghost pending" caveat).

    Attributes:
        request_id: The approval request id this entry describes.
        action: The action string that required approval.
        security_tier: The tier of the action, as a string.
        status: One of "pending", "approved", "declined", "expired" -
            rendered literally, exactly as stored.
        created_at: UTC-in-substance timestamp the request was created.
        decided_at: UTC-in-substance timestamp the request was decided or
            timed out, or None while its history row is still "pending".
        decided_by: Who or what decided it ("user", "timeout"), or None.
        reason: The human-readable explanation of why approval was
            needed, exactly as recorded at request time (Phase 64,
            Batch 1). Defaults to "" only for backward compatibility
            with call sites predating this field - get_recent_approvals()
            always populates it from the real, already-fetched record.
        decision_reason: An optional explanation supplied with the
            decision, or None if none was given or the request is still
            "pending" (Phase 64, Batch 1).
    """

    request_id: str
    action: str
    security_tier: str
    status: str
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    reason: str = ""
    decision_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ApprovalStatusCount:
    """One known approval-history status's real, all-time count (Phase
    64, Batch 1).

    Produced only by calling ApprovalHistoryStore.count_by_status() -
    never a fabricated, estimated, or inferred value, and never a
    ranking: get_approval_status_breakdown() always returns these in
    approval.approval_history_store.KNOWN_APPROVAL_STATUSES's own fixed
    order, never sorted by count, so nothing here implies one status is
    more significant than another.

    Attributes:
        status: The known status name (one of KNOWN_APPROVAL_STATUSES).
        count: The real, current, all-time number of approval history
            entries with this exact status - zero is a valid, honestly
            reported value, never omitted.
    """

    status: str
    count: int


@dataclass(frozen=True, slots=True)
class WorkflowTransitionRow:
    """A single workflow lifecycle transition, shaped for dashboard display.

    This describes durable history only - one row in the append-only
    transition log. It is never resumable executable state: there is no
    tool_input, no resolved step input, and no serialised Plan behind any
    row here, so nothing shown can be used to reconstruct or resume a
    workflow (see docs/phase_19_implementation_plan.md section 16).

    Attributes:
        status: The lifecycle transition name (one of WorkflowEngine's
            own seven event names), rendered literally.
        step_number: The 1-based step this transition concerns, or None
            for a workflow-level transition.
        step_total: The total number of steps in the plan, or None.
        tool_name: The step's tool name, or None.
        detail: Optional short, content-free human-readable text.
        created_at: UTC-in-substance timestamp of this transition.
        approval_request_id: The correlated approval request id, set
            only for a "workflow_step_waiting" row (Phase 64, Batch 1) -
            None otherwise. Defaults to None only for backward
            compatibility with call sites predating this field;
            get_workflow_transitions() always populates it from the
            real, already-fetched record.
    """

    status: str
    step_number: int | None
    step_total: int | None
    tool_name: str | None
    detail: str | None
    created_at: datetime
    approval_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowStatusCount:
    """One known workflow lifecycle status's count among the most
    recently active workflows (Phase 64, Batch 1).

    Honestly scoped: this is a tally of get_recent_workflows()'s own
    already-fetched WorkflowRow.latest_status values - never an
    all-time total across every workflow ever, since no all-time
    per-status aggregation exists for workflows (a workflow's "status"
    is its own latest transition, not a fixed column that could be
    counted directly). get_workflow_status_breakdown() always returns
    these in workflow.workflow_history_store.KNOWN_WORKFLOW_STATUSES's
    own fixed order, never sorted by count.

    Attributes:
        status: The known lifecycle transition name (one of
            KNOWN_WORKFLOW_STATUSES).
        count: How many of the most recently active workflows
            (get_recent_workflows()'s own result) currently have this
            status as their latest recorded transition - zero is a
            valid, honestly reported value, never omitted.
    """

    status: str
    count: int


@dataclass(frozen=True, slots=True)
class WorkflowRow:
    """One workflow's most recent durable status, shaped for dashboard display.

    This is derived entirely from the transition log's own most recent
    row for this workflow_id (via WorkflowHistoryStore.latest_status_for)
    - it is a durable-history summary, not a live runtime status. A
    "workflow_step_waiting" status here does not guarantee an in-memory
    paused workflow still exists after a restart (see
    docs/phase_19_implementation_plan.md section 16).

    Attributes:
        workflow_id: The workflow this row describes.
        latest_status: The most recent transition name recorded for this
            workflow.
        latest_step_number: That transition's step number, or None.
        latest_step_total: That transition's step total, or None.
        latest_created_at: UTC-in-substance timestamp of that transition.
    """

    workflow_id: str
    latest_status: str
    latest_step_number: int | None
    latest_step_total: int | None
    latest_created_at: datetime


@dataclass(frozen=True, slots=True)
class InboxRow:
    """A single saved inbox entry, shaped for dashboard display.

    This describes a durably saved copy of an AI-generated output that
    was already shown to Nathan once (Phase 20) - today, exactly one
    producer: a "summarise web search for <query>" advisory summary.
    `full_body` already includes its fixed disclosure label, stored
    verbatim from the original response - this row never re-derives or
    reconstructs anything.

    Attributes:
        id: The entry's primary key.
        source_query: The literal query this entry is about.
        preview: A deterministically truncated preview of the body, for
            list-view display (same convention as MemoryRow.preview).
        full_body: The untruncated, exact final text Nathan was shown,
            for a detail view shown only after explicit row selection.
        included_count: The number of search results the summary was
            based on, if known.
        created_at: UTC-in-substance timestamp of when this entry was
            saved.
    """

    id: int
    source_query: str
    preview: str
    full_body: str
    included_count: int | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ScheduleRow:
    """A single configured schedule, shaped for dashboard display.

    This describes durable schedule configuration only - it is never a
    live "next run in N minutes" countdown (no such value is computed or
    stored anywhere; see docs/phase_21_implementation_plan.md section
    15). Whether a schedule is currently due is decided solely by
    scheduler.py's own poll cycle, never by this row.

    Attributes:
        id: The schedule's primary key.
        name: The optional user-supplied label, or None.
        query_preview: A deterministically truncated preview of the
            query (same 120-character truncation convention as
            MemoryRow/InboxRow).
        time_of_day: The scheduled time, as "HH:MM" in host local time.
        enabled: Whether the schedule is currently active.
        last_run_at: UTC-in-substance timestamp of the most recent
            claimed run, or None if it has never run.
        created_at: UTC-in-substance timestamp of when the schedule was
            created.
    """

    id: int
    name: str | None
    query_preview: str
    time_of_day: str
    enabled: bool
    last_run_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class QuarantineRow:
    """A single quarantined file's durable metadata, shaped for dashboard
    display (Phase 39).

    This describes a durable QuarantineRecord (Phase 37) only - it does
    not confirm the file still physically exists at quarantine_path
    (for example, it may have already been restored, Phase 38, which
    never deletes or updates the record). It is never a live filesystem
    listing; QuarantineListTool's own CLI command remains the only thing
    that reads .jarvis_trash/'s actual current contents.

    Attributes:
        quarantine_path: The absolute, resolved path the file was moved
            to inside the quarantine directory.
        quarantine_name: Just the filename portion of quarantine_path,
            for a shorter list-view display (derived here, not stored -
            QuarantineRecord itself has no separate name column).
        original_path: The absolute, resolved path the file was
            quarantined from.
        quarantined_at: UTC-in-substance timestamp of when the file was
            quarantined.
        session_id: The session the quarantine happened under, if any.
    """

    quarantine_path: str
    quarantine_name: str
    original_path: str
    quarantined_at: datetime
    session_id: int | None


@dataclass(frozen=True, slots=True)
class DashboardOverview:
    """The small, at-a-glance summary shown on the Overview tab.

    Every field here traces to a real, already-persisted query - nothing
    is estimated, simulated, or fabricated (docs/phase_19_implementation_plan.md
    section 21 / the authorizing instructions' item 21).

    Attributes:
        total_memory_count: The total number of stored memories.
        recent_approvals: The most recent approval history rows (durable
            history, not live pending state - see ApprovalRow).
        recent_workflows: The most recently active distinct workflows
            (durable history, not live runtime state - see WorkflowRow).
        total_inbox_count: The total number of saved inbox entries.
        recent_inbox_entries: The most recent saved inbox entries.
        total_scheduled_inbox_count: The total number of saved inbox
            entries produced by the scheduler specifically (source_type
            "scheduled_web_search_summary"), a subset of
            total_inbox_count. Deliberately independent of the CLI's own
            last-seen marker (Phase 22) - this is a plain, real total,
            never framed as "since you last checked", so the dashboard
            never depends on, or implies ownership of, the CLI's marker.
        latest_scheduled_inbox_created_at: The most recent scheduled
            inbox entry's timestamp, or None if none exist yet.
    """

    total_memory_count: int
    recent_approvals: tuple[ApprovalRow, ...]
    recent_workflows: tuple[WorkflowRow, ...]
    total_inbox_count: int
    recent_inbox_entries: tuple[InboxRow, ...]
    total_scheduled_inbox_count: int
    latest_scheduled_inbox_created_at: datetime | None


@dataclass(frozen=True, slots=True)
class DashboardSystemStatus:
    """Jarvis's current configuration status, shaped for dashboard display
    (Phase 62, Batch 1).

    Reads only an already-loaded Settings object - never calls
    load_settings() itself, never reads .env/os.environ directly - using
    the same field selection and secret-handling discipline
    tools/builtin/config_tool.py's ConfigTool already established for the
    CLI's own "show config" command. The API key's own value is never
    included here in any form: not the value, not a masked/partial value,
    not its length, and not a hash/fingerprint - only whether it is
    configured at all.

    Attributes:
        available: False only when no Settings object was supplied to
            DashboardReadModel at construction time - every other field
            is then None, an honest "unavailable" state, never a
            fabricated default.
        ai_reasoning_enabled: Whether live AI reasoning is switched on.
        ai_model: The configured Claude model identifier.
        voice_enabled: Whether the voice output subsystem is switched on.
        voice_provider: Which TextToSpeechProvider is configured ("none"
            or "fake" - no real TTS engine exists yet).
        voice_input_enabled: Whether the voice input subsystem is
            switched on.
        voice_input_provider: Which SpeechToTextProvider is configured
            ("none" or "fake" - no real STT engine or microphone exists
            yet).
        log_level: The configured logging verbosity.
        database_path: The configured SQLite database file path, as text.
        approval_timeout_seconds: The configured YELLOW approval window.
        api_key_status: Either "configured" or "not configured" - never
            the key's value, a masked form, its length, or a hash.
    """

    available: bool
    ai_reasoning_enabled: bool | None = None
    ai_model: str | None = None
    voice_enabled: bool | None = None
    voice_provider: str | None = None
    voice_input_enabled: bool | None = None
    voice_input_provider: str | None = None
    log_level: str | None = None
    database_path: str | None = None
    approval_timeout_seconds: int | None = None
    api_key_status: str | None = None


@dataclass(frozen=True, slots=True)
class StoreReachability:
    """One durable store's honest reachability status, shaped for
    dashboard display (Phase 62, Batch 1).

    Produced only by calling an already-existing, already-proven-safe
    read method on a store DashboardReadModel was already constructed
    with - never a new database connection, never a new store instance,
    never a write of any kind. A raising read call is caught and
    reported here, never re-raised - one store's failure never prevents
    another store's check from running.

    Attributes:
        name: A short, fixed label for the store this describes (for
            example, "memory", "inbox", "quarantine").
        reachable: True only if the read call completed without raising.
            False for a genuine failure, or for the optional quarantine
            store when none was supplied at construction time (an honest
            "not configured" state, never conflated with a fabricated
            success).
        detail: None when reachable is True. Otherwise, a short,
            human-readable reason - either the caught exception's own
            message, or "not configured" for the optional quarantine
            store when absent.
    """

    name: str
    reachable: bool
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ActivityRow:
    """One entry in the merged, cross-domain recent-activity feed
    (Phase 62, Batch 1).

    Built entirely from rows DashboardReadModel's own existing
    get_recent_*() methods already return - never a new query, never AI,
    never an inferred or fabricated value. `summary` is a short,
    deterministic string assembled only from fields already present on
    the source row.

    Attributes:
        domain: A short, fixed label naming which existing domain this
            entry came from ("memory", "approval", "workflow", "inbox",
            or "quarantine").
        summary: A short, deterministic, non-AI description built from
            the source row's own already-real fields.
        created_at: The source row's own real timestamp - for an
            ApprovalRow, its decided_at when present, otherwise its
            created_at, since a decided approval's most notable moment
            is when it was decided, not when it was first requested.
    """

    domain: str
    summary: str
    created_at: datetime


class DashboardReadModel:
    """Composes the approved durable stores into dashboard view models.

    This is the only object the dashboard UI depends on for data. It
    holds no write path of any kind - every method here calls only an
    existing read method already present on MemoryManager,
    ApprovalHistoryStore, WorkflowHistoryStore, InboxStore, ScheduleStore,
    or QuarantineStore, or reads an already-loaded Settings object's own
    fields (Phase 62, Batch 1).

    Attributes:
        _memory: The memory manager to read from.
        _approvals: The approval history store to read from.
        _workflows: The workflow history store to read from.
        _inbox: The inbox store to read from.
        _schedules: The schedule store to read from.
        _quarantine: The quarantine store to read from, or None. Optional
            (Phase 39, Batch 1) - unlike the other five stores, which
            have always been mandatory here, a caller that has not yet
            wired one in simply sees an empty quarantine list rather
            than being forced to construct one just to keep working,
            matching FileDeleteTool/QuarantineListTool/FileRestoreTool's
            own established optional-store pattern (Phase 37/38).
        _settings: The already-loaded Settings object to read from, or
            None. Optional (Phase 62, Batch 1), mirroring _quarantine's
            own established optional-collaborator pattern - a caller
            that has not wired one in simply sees an honest
            "unavailable" DashboardSystemStatus rather than being forced
            to construct one just to keep working. Never used to call
            load_settings() or read .env/os.environ - this class only
            ever reads fields off the object it was given.
    """

    def __init__(
        self,
        memory: MemoryManager,
        approvals: ApprovalHistoryStore,
        workflows: WorkflowHistoryStore,
        inbox: InboxStore,
        schedules: ScheduleStore,
        quarantine: QuarantineStore | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Initialise the read model with the approved durable stores.

        Args:
            memory: The memory manager to read from.
            approvals: The approval history store to read from.
            workflows: The workflow history store to read from.
            inbox: The inbox store to read from.
            schedules: The schedule store to read from.
            quarantine: Optional quarantine store to read from. Defaults
                to None, in which case get_quarantine_entries() safely
                returns an empty list rather than failing.
            settings: Optional, already-loaded Settings object to read
                from (Phase 62, Batch 1). Defaults to None, in which case
                get_system_status() safely returns an "unavailable"
                status rather than failing. This class never calls
                load_settings() itself.
        """
        self._memory = memory
        self._approvals = approvals
        self._workflows = workflows
        self._inbox = inbox
        self._schedules = schedules
        self._quarantine = quarantine
        self._settings = settings

    def get_overview(self) -> DashboardOverview:
        """Return the small, real-data-only Overview summary.

        Returns:
            A DashboardOverview built from the total memory count, the
            most recent approval history rows, the most recently active
            distinct workflows, the total inbox count, the most recent
            inbox entries, and the scheduled-inbox-specific total/latest
            timestamp (Phase 22) - the latter computed via
            InboxStore.count_since(after_id=None), never via the CLI's
            own last-seen marker, so this read model never depends on or
            implies ownership of that marker.
        """
        scheduled_count, _, scheduled_latest_created_at = self._inbox.count_since(
            source_type=SCHEDULED_SOURCE_TYPE, after_id=None
        )
        return DashboardOverview(
            total_memory_count=self._memory.count(),
            recent_approvals=tuple(
                self.get_recent_approvals(limit=_OVERVIEW_PREVIEW_LIMIT)
            ),
            recent_workflows=tuple(
                self.get_recent_workflows(limit=_OVERVIEW_PREVIEW_LIMIT)
            ),
            total_inbox_count=self._inbox.count(),
            recent_inbox_entries=tuple(
                self.get_recent_inbox_entries(limit=_OVERVIEW_PREVIEW_LIMIT)
            ),
            total_scheduled_inbox_count=scheduled_count,
            latest_scheduled_inbox_created_at=scheduled_latest_created_at,
        )

    def get_recent_memories(
        self, limit: int = 20, *, category: str | None = None
    ) -> list[MemoryRow]:
        """Return the most recent memories, newest first, as MemoryRows.

        Args:
            limit: Maximum number of memories to return.
            category: Optional category to filter by. When None, all
                categories are returned.

        Returns:
            A list of MemoryRow objects, newest first.
        """
        records = self._memory.list_recent(limit=limit, category=category)
        return [
            MemoryRow(
                id=record.id,
                category=record.category,
                preview=_truncate_preview(record.content),
                full_content=record.content,
                created_at=record.created_at,
            )
            for record in records
        ]

    def get_memory_category_breakdown(self) -> tuple[MemoryCategoryCount, ...]:
        """Return a real, per-category memory count for every known
        category (Phase 63, Batch 1).

        Each count comes from one call to
        MemoryManager.count_by_category() - never a fabricated,
        estimated, or inferred value. Every category in
        memory.memory_models.KNOWN_CATEGORIES is included, even one with
        zero memories - an honest zero is reported, never omitted, so
        the breakdown can never look shorter than the real number of
        known categories. Categories are returned in KNOWN_CATEGORIES's
        own fixed, declared order - never sorted by count - so nothing
        here implies one category is more important than another.

        Returns:
            A tuple of MemoryCategoryCount, one per known category, in
            KNOWN_CATEGORIES's own fixed order.
        """
        return tuple(
            MemoryCategoryCount(
                category=category,
                count=self._memory.count_by_category(category),
            )
            for category in KNOWN_CATEGORIES
        )

    def get_recent_approvals(self, limit: int = 20) -> list[ApprovalRow]:
        """Return the most recent approval history entries as ApprovalRows.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            A list of ApprovalRow objects, newest first.
        """
        records = self._approvals.list_recent(limit=limit)
        return [
            ApprovalRow(
                request_id=record.request_id,
                action=record.action,
                security_tier=record.security_tier,
                status=record.status,
                created_at=record.created_at,
                decided_at=record.decided_at,
                decided_by=record.decided_by,
                reason=record.reason,
                decision_reason=record.decision_reason,
            )
            for record in records
        ]

    def get_approval_status_breakdown(self) -> tuple[ApprovalStatusCount, ...]:
        """Return a real, all-time approval-history count for every
        known status (Phase 64, Batch 1).

        Each count comes from one call to
        ApprovalHistoryStore.count_by_status() - a true, unbounded
        total, never a fabricated, estimated, or inferred value. Every
        status in KNOWN_APPROVAL_STATUSES is included, even one with
        zero entries - an honest zero is reported, never omitted.
        Statuses are returned in KNOWN_APPROVAL_STATUSES's own fixed,
        declared order - never sorted by count - so nothing here
        implies one status is more significant than another.

        Returns:
            A tuple of ApprovalStatusCount, one per known status, in
            KNOWN_APPROVAL_STATUSES's own fixed order.
        """
        return tuple(
            ApprovalStatusCount(
                status=status,
                count=self._approvals.count_by_status(status),
            )
            for status in KNOWN_APPROVAL_STATUSES
        )

    def get_recent_workflows(self, limit: int = 10) -> list[WorkflowRow]:
        """Return the most recently active distinct workflows as WorkflowRows.

        Uses WorkflowHistoryStore.list_recent_workflow_ids so a single
        transition-heavy workflow cannot crowd other, older workflows out
        of the result, then reads each one's latest status via the
        existing latest_status_for - no lifecycle logic is duplicated
        here.

        Args:
            limit: Maximum number of distinct workflows to return.

        Returns:
            A list of WorkflowRow objects, most recently active first.
        """
        workflow_ids = self._workflows.list_recent_workflow_ids(limit=limit)
        rows: list[WorkflowRow] = []
        for workflow_id in workflow_ids:
            latest = self._workflows.latest_status_for(workflow_id)
            if latest is None:
                continue  # pragma: no cover - defensive; ids come from real rows
            rows.append(
                WorkflowRow(
                    workflow_id=latest.workflow_id,
                    latest_status=latest.status,
                    latest_step_number=latest.step_number,
                    latest_step_total=latest.step_total,
                    latest_created_at=latest.created_at,
                )
            )
        return rows

    def get_workflow_status_breakdown(
        self, limit: int = 10
    ) -> tuple[WorkflowStatusCount, ...]:
        """Return a count, per known lifecycle status, of the most
        recently active workflows' current status (Phase 64, Batch 1).

        Honestly scoped to recent activity, never presented as an
        all-time total: this tallies get_recent_workflows()'s own
        already-fetched WorkflowRow.latest_status values - the exact
        same "most recently active" data the Workflow History tab
        already shows, never a new or wider query. No all-time
        per-status total exists for workflows, since a workflow's
        "status" is its own latest transition, not a fixed column that
        could be counted directly the way an approval's status can.

        Every status in KNOWN_WORKFLOW_STATUSES is included, even one
        with zero matches among the recently active workflows
        considered - an honest zero is reported, never omitted.
        Statuses are returned in KNOWN_WORKFLOW_STATUSES's own fixed,
        declared order - never sorted by count.

        Args:
            limit: Maximum number of most-recently-active workflows to
                consider - passed straight through to
                get_recent_workflows(). Defaults to the same value
                get_recent_workflows() itself defaults to.

        Returns:
            A tuple of WorkflowStatusCount, one per known status, in
            KNOWN_WORKFLOW_STATUSES's own fixed order.
        """
        recent = self.get_recent_workflows(limit=limit)
        tally = Counter(row.latest_status for row in recent)
        return tuple(
            WorkflowStatusCount(status=status, count=tally.get(status, 0))
            for status in KNOWN_WORKFLOW_STATUSES
        )

    def get_workflow_transitions(
        self, workflow_id: str, limit: int = 50
    ) -> list[WorkflowTransitionRow]:
        """Return one workflow's full transition history, oldest first.

        Args:
            workflow_id: The workflow to look up.
            limit: Maximum number of transitions to return.

        Returns:
            A list of WorkflowTransitionRow objects, oldest first. An
            unknown workflow_id simply returns an empty list.
        """
        records = self._workflows.list_for_workflow(workflow_id, limit=limit)
        return [
            WorkflowTransitionRow(
                status=record.status,
                step_number=record.step_number,
                step_total=record.step_total,
                tool_name=record.tool_name,
                detail=record.detail,
                created_at=record.created_at,
                approval_request_id=record.approval_request_id,
            )
            for record in records
        ]

    def get_schedules(self, limit: int = 50) -> list[ScheduleRow]:
        """Return configured schedules, in ScheduleStore's own stable order.

        Reuses ScheduleStore.list_all() unchanged - no new store API
        surface is added specifically for the dashboard. Ordering
        (id ascending, a small stable configuration list rather than a
        "most recent history" view) is ScheduleStore's own decision, not
        re-derived here.

        Args:
            limit: Maximum number of schedules to return.

        Returns:
            A list of ScheduleRow objects.
        """
        records = self._schedules.list_all(limit=limit)
        return [
            ScheduleRow(
                id=record.id,
                name=record.name,
                query_preview=_truncate_preview(record.query),
                time_of_day=record.time_of_day,
                enabled=record.enabled,
                last_run_at=record.last_run_at,
                created_at=record.created_at,
            )
            for record in records
        ]

    def get_recent_inbox_entries(self, limit: int = 20) -> list[InboxRow]:
        """Return the most recent saved inbox entries as InboxRows.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            A list of InboxRow objects, newest first.
        """
        records = self._inbox.list_recent(limit=limit)
        return [
            InboxRow(
                id=record.id,
                source_query=record.source_query,
                preview=_truncate_preview(record.body),
                full_body=record.body,
                included_count=record.included_count,
                created_at=record.created_at,
            )
            for record in records
        ]

    def get_quarantine_entries(self, limit: int = 50) -> list[QuarantineRow]:
        """Return recorded quarantine metadata as QuarantineRows, newest first.

        Reuses QuarantineStore.list_recent() unchanged - no new store API
        surface is added specifically for the dashboard beyond that one
        narrow read method (Phase 39, Batch 1). Returns an empty list
        when no QuarantineStore was supplied (backward compatible with
        any caller predating Phase 39) or when no quarantine records
        exist yet - never an error either way.

        This describes durable, database-recorded quarantine metadata
        only. It does not inspect .jarvis_trash/'s actual filesystem
        contents, so a row here does not guarantee the file still
        physically exists at its quarantine_path (for example, if it
        was already restored, Phase 38, which never deletes or updates
        the underlying record). Reconciling database records against
        the live filesystem, if ever needed, is a distinct, separately-
        reviewed future decision - see the module/class docstrings.

        Args:
            limit: Maximum number of records to return.

        Returns:
            A list of QuarantineRow objects, newest first.
        """
        if self._quarantine is None:
            return []
        records = self._quarantine.list_recent(limit=limit)
        return [
            QuarantineRow(
                quarantine_path=record.quarantine_path,
                quarantine_name=Path(record.quarantine_path).name,
                original_path=record.original_path,
                quarantined_at=record.quarantined_at,
                session_id=record.session_id,
            )
            for record in records
        ]

    def get_system_status(self) -> DashboardSystemStatus:
        """Return Jarvis's current configuration status, or an honest
        "unavailable" state (Phase 62, Batch 1).

        Reads only the already-loaded Settings object this class was
        constructed with - never calls load_settings() itself, never
        reads .env/os.environ directly, and never exposes the API key's
        value in any form, mirroring ConfigTool's own established
        secret-handling discipline exactly.

        Returns:
            A DashboardSystemStatus with available=False and every other
            field None if no Settings object was supplied at
            construction time. Otherwise, available=True with every
            allowed field populated from that Settings object, and
            api_key_status set to "configured" or "not configured" -
            never the key's value, a masked form, its length, or a hash.
        """
        if self._settings is None:
            return DashboardSystemStatus(available=False)

        settings = self._settings
        api_key_status = (
            _API_KEY_CONFIGURED
            if settings.anthropic_api_key.strip()
            else _API_KEY_NOT_CONFIGURED
        )
        return DashboardSystemStatus(
            available=True,
            ai_reasoning_enabled=settings.ai_reasoning_enabled,
            ai_model=settings.ai_model,
            voice_enabled=settings.voice_enabled,
            voice_provider=settings.voice_provider,
            voice_input_enabled=settings.voice_input_enabled,
            voice_input_provider=settings.voice_input_provider,
            log_level=settings.log_level,
            database_path=str(settings.database_path),
            approval_timeout_seconds=settings.approval_timeout_seconds,
            api_key_status=api_key_status,
        )

    def get_store_reachability(self) -> tuple[StoreReachability, ...]:
        """Return an honest reachability status for each durable store
        this read model depends on (Phase 62, Batch 1).

        Each check calls one already-existing, already-proven-safe read
        method on a store this class was already constructed with -
        never a new database connection, never a new store instance,
        never a write of any kind. A raising read call is caught here
        and reported as not reachable, never re-raised and never allowed
        to prevent another store's own check from running.

        Returns:
            A fixed-order tuple of six StoreReachability entries: memory,
            approvals, workflow_history, inbox, schedules, and
            quarantine. The quarantine entry reports reachable=False,
            detail="not configured" when no QuarantineStore was supplied
            at construction time - an honest, distinct state from a
            genuine read failure.
        """
        checks = [
            self._check_store_reachability("memory", lambda: self._memory.count()),
            self._check_store_reachability(
                "approvals", lambda: self._approvals.list_recent(limit=1)
            ),
            self._check_store_reachability(
                "workflow_history",
                lambda: self._workflows.list_recent_workflow_ids(limit=1),
            ),
            self._check_store_reachability("inbox", lambda: self._inbox.count()),
            self._check_store_reachability(
                "schedules", lambda: self._schedules.list_all(limit=1)
            ),
        ]
        if self._quarantine is None:
            checks.append(
                StoreReachability(
                    name="quarantine", reachable=False, detail="not configured"
                )
            )
        else:
            quarantine = self._quarantine
            checks.append(
                self._check_store_reachability(
                    "quarantine", lambda: quarantine.list_recent(limit=1)
                )
            )
        return tuple(checks)

    @staticmethod
    def _check_store_reachability(
        name: str, read_call: Callable[[], object]
    ) -> StoreReachability:
        """Run one store's read call and report its honest outcome.

        Args:
            name: The fixed label to attach to this check.
            read_call: A zero-argument callable performing one
                already-existing read method call. Never a write.

        Returns:
            A StoreReachability with reachable=True and detail=None if
            read_call completed without raising. Otherwise,
            reachable=False with the caught exception's own message as
            detail - the exception itself is never re-raised.
        """
        try:
            read_call()
        except Exception as exc:  # noqa: BLE001 - isolate one store's failure from the rest
            return StoreReachability(name=name, reachable=False, detail=str(exc))
        return StoreReachability(name=name, reachable=True, detail=None)

    def get_recent_activity(self, limit: int = _ACTIVITY_LIMIT_DEFAULT) -> list[ActivityRow]:
        """Return a merged, timestamp-sorted, capped recent-activity feed
        (Phase 62, Batch 1).

        Built entirely from rows this class's own existing
        get_recent_memories()/get_recent_approvals()/get_recent_workflows()/
        get_recent_inbox_entries()/get_quarantine_entries() already
        return - never a new query, never AI, never an inferred or
        fabricated value. Each source domain is read up to `limit`
        entries deep (so a domain with many more recent events than
        another is never starved out of the merged result before
        sorting), then every domain's rows are merged, sorted by their
        own real timestamp newest-first, and the combined list is capped
        at `limit`.

        A source with no data simply contributes no rows - there is no
        placeholder or fabricated "no activity" entry for an empty
        domain; the overall list is empty only if every domain is empty.

        Args:
            limit: Maximum number of entries to return, and the maximum
                depth read from each individual source domain.

        Returns:
            A list of ActivityRow objects, newest first, capped at
            `limit`.
        """
        entries: list[ActivityRow] = []

        for memory_row in self.get_recent_memories(limit=limit):
            entries.append(
                ActivityRow(
                    domain="memory",
                    summary=f"Saved memory ({memory_row.category}): {memory_row.preview}",
                    created_at=memory_row.created_at,
                )
            )

        for approval_row in self.get_recent_approvals(limit=limit):
            entries.append(
                ActivityRow(
                    domain="approval",
                    summary=f"{approval_row.status}: {approval_row.action}",
                    created_at=approval_row.decided_at or approval_row.created_at,
                )
            )

        for workflow_row in self.get_recent_workflows(limit=limit):
            entries.append(
                ActivityRow(
                    domain="workflow",
                    summary=(
                        f"Workflow {workflow_row.workflow_id}: "
                        f"{workflow_row.latest_status}"
                    ),
                    created_at=workflow_row.latest_created_at,
                )
            )

        for inbox_row in self.get_recent_inbox_entries(limit=limit):
            entries.append(
                ActivityRow(
                    domain="inbox",
                    summary=f"Saved inbox entry: {inbox_row.source_query}",
                    created_at=inbox_row.created_at,
                )
            )

        for quarantine_row in self.get_quarantine_entries(limit=limit):
            entries.append(
                ActivityRow(
                    domain="quarantine",
                    summary=f"Quarantined file: {quarantine_row.quarantine_name}",
                    created_at=quarantine_row.quarantined_at,
                )
            )

        entries.sort(key=lambda entry: entry.created_at, reverse=True)
        return entries[:limit]
