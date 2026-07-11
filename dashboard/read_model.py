"""
read_model.py

Narrow, read-only composition layer over Jarvis's durable stores, for the
local dashboard (Phase 19; extended Phase 20 with the inbox).

Responsibilities:
    - Define small, frozen view-model dataclasses shaped for dashboard
      display (MemoryRow, ApprovalRow, WorkflowRow, WorkflowTransitionRow,
      InboxRow, DashboardOverview).
    - Define DashboardReadModel, which composes MemoryManager,
      ApprovalHistoryStore, WorkflowHistoryStore, and InboxStore's
      existing public read methods into those view models.

Does NOT:
    - Call any write/mutating method on any store (save, update_content,
      update_category, forget, record_request, record_decision,
      record_timeout, record_transition, append).
    - Parse CLI output, tool output, or any formatted display string.
    - Import CommandRouter, ToolExecutor, the live ApprovalManager,
      WorkflowEngine, AIReasoningEngine, AIRouter, or WebSearchTool.
    - Implement a generic CQRS, event-sourcing, or reporting framework.
      This module exists only to compose the four approved dashboard
      domains; it has exactly as many methods as the dashboard's five
      views need, no more.
    - Truncate, summarise, or otherwise rewrite memory or inbox content
      using AI. Preview truncation here is a fixed, deterministic
      character cut, never a semantic rewrite.

This is the sole persistence-facing layer the dashboard UI depends on -
the UI never imports a store directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from approval.approval_history_store import ApprovalHistoryStore
from inbox.inbox_store import InboxStore
from memory.memory_manager import MemoryManager
from workflow.workflow_history_store import WorkflowHistoryStore

#: Maximum length of a memory content preview shown in list views. Full,
#: untruncated content is still carried on MemoryRow.full_content, for an
#: explicit detail view only - see the module docstring on privacy intent
#: in docs/phase_19_implementation_plan.md, section 11.
_PREVIEW_MAX_CHARS = 120

#: Default number of rows shown in the Overview panel's small previews.
_OVERVIEW_PREVIEW_LIMIT = 5


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
    """

    request_id: str
    action: str
    security_tier: str
    status: str
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None


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
    """

    status: str
    step_number: int | None
    step_total: int | None
    tool_name: str | None
    detail: str | None
    created_at: datetime


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
    """

    total_memory_count: int
    recent_approvals: tuple[ApprovalRow, ...]
    recent_workflows: tuple[WorkflowRow, ...]
    total_inbox_count: int
    recent_inbox_entries: tuple[InboxRow, ...]


class DashboardReadModel:
    """Composes the four approved durable stores into dashboard view models.

    This is the only object the dashboard UI depends on for data. It
    holds no write path of any kind - every method here calls only an
    existing read method already present on MemoryManager,
    ApprovalHistoryStore, WorkflowHistoryStore, or InboxStore.

    Attributes:
        _memory: The memory manager to read from.
        _approvals: The approval history store to read from.
        _workflows: The workflow history store to read from.
        _inbox: The inbox store to read from.
    """

    def __init__(
        self,
        memory: MemoryManager,
        approvals: ApprovalHistoryStore,
        workflows: WorkflowHistoryStore,
        inbox: InboxStore,
    ) -> None:
        """Initialise the read model with the four approved durable stores.

        Args:
            memory: The memory manager to read from.
            approvals: The approval history store to read from.
            workflows: The workflow history store to read from.
            inbox: The inbox store to read from.
        """
        self._memory = memory
        self._approvals = approvals
        self._workflows = workflows
        self._inbox = inbox

    def get_overview(self) -> DashboardOverview:
        """Return the small, real-data-only Overview summary.

        Returns:
            A DashboardOverview built from the total memory count, the
            most recent approval history rows, the most recently active
            distinct workflows, the total inbox count, and the most
            recent inbox entries.
        """
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
            )
            for record in records
        ]

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
