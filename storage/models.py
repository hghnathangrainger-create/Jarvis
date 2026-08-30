"""
models.py

SQLAlchemy ORM table definitions for the Jarvis AI Operating System.

Responsibilities:
    - Define the declarative Base that all ORM models inherit from.
    - Define the initial Phase 1 tables: sessions, episodic_memories, audit_log.
    - Declare columns, types, constraints, and created_at timestamps.

Does NOT:
    - Implement Memory Manager logic (reading, writing, retrieving memories).
    - Implement Observability logic (emitting or formatting events).
    - Implement AI logic of any kind.
    - Create the engine, sessions, or initialise the database (see database.py).

This module is purely structural: it describes the shape of the data. All
behaviour that uses these tables lives in the subsystems that own them.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Used as the default factory for created_at columns so that every timestamp
    is unambiguous and comparable regardless of the host's local timezone.

    Returns:
        The current moment in UTC, as a timezone-aware datetime.
    """
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base class for all Jarvis ORM models.

    All table models inherit from this class. The shared metadata it carries
    is used by database.py to create every table in a single operation.
    """


class Session(Base):
    """A single interaction session between the user and Jarvis.

    A session groups together the conversation turns, memories, and audit
    events that belong to one continuous period of use. Other tables reference
    a session so that activity can be traced back to the context in which it
    occurred.

    Attributes:
        id: Auto-incrementing primary key.
        started_at: Timestamp marking when the session began (UTC).
        ended_at: Timestamp marking when the session ended (UTC); None while
            the session is still active.
        episodic_memories: Memories recorded during this session.
        audit_entries: Audit log entries recorded during this session.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    episodic_memories: Mapped[list["EpisodicMemory"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    audit_entries: Mapped[list["AuditLogEntry"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging.

        Returns:
            A string identifying the session by id and start time.
        """
        return f"<Session id={self.id} started_at={self.started_at!r}>"


class EpisodicMemory(Base):
    """A timestamped record of a fact, note, or event worth remembering.

    Episodic memories persist across sessions. They form the long-term memory
    that allows Jarvis to recall earlier conversations and stored information.
    The Memory Manager owns all reading and writing of this table; this class
    only defines its structure.

    Attributes:
        id: Auto-incrementing primary key.
        session_id: The session during which this memory was recorded; may be
            None for memories not tied to a specific session.
        content: The memory text itself.
        source: Where the memory originated (e.g. "conversation", "tool").
        category: An organisational label for the memory (e.g. "general",
            "personal", "project"). Defaults to "general". Purely for
            organisation; it never affects safety classification.
        created_at: Timestamp marking when the memory was stored (UTC).
        session: The session this memory belongs to, if any.
    """

    __tablename__ = "episodic_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="conversation")
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="general", server_default="general", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False, index=True
    )

    session: Mapped["Session | None"] = relationship(back_populates="episodic_memories")

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging.

        Returns:
            A string identifying the memory by id, source, and creation time.
        """
        return (
            f"<EpisodicMemory id={self.id} source={self.source!r} "
            f"created_at={self.created_at!r}>"
        )


class AuditLogEntry(Base):
    """An append-only record of a single action taken by Jarvis.

    Every significant action is recorded here for transparency, debugging, and
    security auditing. This table is written to by the Observability and
    Security subsystems; it is never modified or deleted by normal operation.
    This class only defines the table's structure, not the logic that writes
    to it.

    Attributes:
        id: Auto-incrementing primary key.
        session_id: The session during which the action occurred; may be None.
        action_type: The category of action recorded (e.g. "tool_call").
        security_tier: The risk tier of the action (e.g. "green", "red").
        outcome: The result of the action (e.g. "success", "blocked").
        detail: Optional sanitised detail describing the action.
        duration_ms: Optional duration of the action in milliseconds.
        created_at: Timestamp marking when the action occurred (UTC).
        session: The session this entry belongs to, if any.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    security_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False, index=True
    )

    session: Mapped["Session | None"] = relationship(back_populates="audit_entries")

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging.

        Returns:
            A string identifying the entry by id, action type, and outcome.
        """
        return (
            f"<AuditLogEntry id={self.id} action_type={self.action_type!r} "
            f"outcome={self.outcome!r}>"
        )


class ApprovalHistoryEntry(Base):
    """A durable, read-only record of one approval request and its outcome.

    Phase 6, Batch 1. This table exists purely so approval history survives a
    restart and can be reviewed later; it does not make anything resumable.

    Deliberately excluded, by design, not oversight: there is no tool_name
    column and no tool_input column anywhere in this table. An approval
    request's actual executable payload (which tool, with what input) lives
    only in the in-memory JarvisResponse produced during the request that is
    currently pending, and is never written here. That means a row in this
    table can describe what was asked and how it was decided, but it can
    never be used to re-run or replay the original action - there is nothing
    in the schema that a future "resume" feature could read to do so by
    accident. Making approvals resumable is an explicit, separate decision
    deferred to a later phase, with its own safety review.

    Attributes:
        id: Auto-incrementing primary key.
        request_id: The unique id of the approval request this entry
            describes (matches ApprovalRequest.request_id).
        session_id: The session the request belonged to; may be None.
        action: The action string that required approval.
        reason: A human-readable explanation of why approval was needed.
        security_tier: The tier of the action, as a string (e.g. "yellow").
            Only YELLOW actions ever have an approval request, so this is
            expected to always be "yellow", but it is stored as text rather
            than assumed.
        status: The lifecycle state - "pending", "approved", or "declined".
        created_at: Timestamp marking when the request was created (UTC).
        decided_at: Timestamp marking when the request was decided (UTC), or
            None while still pending.
        decided_by: Who decided it (for example, "user"), or None while
            pending.
        decision_reason: An optional explanation supplied with the decision.
        session: The session this entry belongs to, if any.
    """

    __tablename__ = "approval_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True, index=True
    )
    session_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    security_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False, index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging.

        Returns:
            A string identifying the entry by request_id and status.
        """
        return (
            f"<ApprovalHistoryEntry request_id={self.request_id!r} "
            f"status={self.status!r}>"
        )


class WorkflowHistoryEntry(Base):
    """A durable, append-only record of one workflow lifecycle transition.

    Durable Workflow Lifecycle Foundation (prerequisite turn, not a
    numbered phase). This table exists purely so a workflow's lifecycle
    survives a restart and can be reviewed later; it does not make any
    workflow resumable, replayable, or exactly-once. `WorkflowEngine`
    remains fully synchronous and in-memory-only for actual execution
    state - this table is a read-only history of what already happened,
    written alongside (never instead of) the existing generic audit log.

    One row is written per lifecycle transition (a single workflow_id can
    and normally does have several rows over its lifetime - start, one or
    more step transitions, and a terminal completed/failed/stopped row),
    mirroring AuditLogEntry's own append-only convention rather than
    ApprovalHistoryEntry's update-in-place convention, since a workflow's
    transition count is not fixed at exactly two like an approval's is.

    Deliberately excluded, by design, not oversight: there is no
    tool_input column and no column capable of holding a serialised Plan
    or resolved step input anywhere in this table. A row can describe
    that a transition happened, for which workflow, at which step, but it
    can never be used to reconstruct an executable resumption point -
    there is nothing in the schema a future "resume after crash" feature
    could read to do so by accident. Making workflows durably resumable
    is an explicit, separate, and larger decision deferred to a future,
    separately-authorized phase, with its own safety review.

    Attributes:
        id: Auto-incrementing primary key.
        workflow_id: The workflow this transition belongs to (matches
            WorkflowEngine's own per-run UUID). Not unique - many rows
            share one workflow_id.
        session_id: The session the workflow ran under; may be None.
        status: One of WorkflowEngine's own seven lifecycle event names
            (e.g. "workflow_started", "workflow_step_waiting"), stored
            verbatim rather than a second, separately-defined vocabulary.
        step_number: The 1-based step this transition concerns, or None
            for a workflow-level transition (started/completed/stopped).
        step_total: The total number of steps in the plan, for display
            context; None where not applicable.
        tool_name: The step's tool name only - never its input or any
            memory/file content.
        approval_request_id: Set only for a "workflow_step_waiting" row;
            correlates with ApprovalHistoryEntry.request_id so a paused
            workflow's history can be cross-referenced with its approval.
        detail: Optional short, content-free human-readable text (for
            example, the reason a workflow stopped).
        created_at: Timestamp marking when this transition was recorded
            (UTC).
    """

    __tablename__ = "workflow_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    step_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    step_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approval_request_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False, index=True
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging.

        Returns:
            A string identifying the entry by workflow_id and status.
        """
        return (
            f"<WorkflowHistoryEntry workflow_id={self.workflow_id!r} "
            f"status={self.status!r}>"
        )


class InboxEntry(Base):
    """A durable, append-only record of one saved Jarvis-produced output.

    Phase 20. This table exists so a valuable AI-generated output - today,
    exactly one producer: the "summarise web search for <query>" advisory
    summary - survives past CLI scrollback and a restart, instead of
    disappearing the moment the terminal session ends. Follows the same
    newer, non-ForeignKey session_id convention ApprovalHistoryEntry and
    WorkflowHistoryEntry already use, rather than the original
    EpisodicMemory/AuditLogEntry ForeignKey convention.

    Deliberately excluded, by design, not oversight: there is no status
    column (every row here is, by construction, a successful entry - a
    failed summary is never persisted), no error column (no failure is
    ever stored), and no read/unread or pinned/starred column (this table
    has no update method at all - see inbox/inbox_store.py - so nothing
    could set such a flag even if the column existed). A row describes a
    saved output only; it is never executable, never a ToolRequest, and
    never trusted AI context - it is stored, user-facing display text,
    nothing more.

    Attributes:
        id: Auto-incrementing primary key.
        session_id: The session the entry was produced under; may be
            None. Plain Integer, not a ForeignKey, matching
            ApprovalHistoryEntry/WorkflowHistoryEntry.
        source_type: The producer that created this entry (for example,
            "web_search_summary" - the only value Phase 20 ever writes).
        source_query: The literal query the entry is about, stored
            verbatim (an explicit, reasoned privacy decision - see
            docs/phase_20_implementation_plan.md section 6 - distinct
            from the audit log's own raw-content-avoidance policy,
            because this is a user-facing store only Nathan ever reads,
            not cross-system telemetry).
        body: The exact final text Nathan was shown for this entry,
            including its fixed disclosure label, stored verbatim - never
            re-derived or reconstructed later.
        included_count: The number of search results the summary was
            based on, if known; content-free metadata only.
        created_at: Timestamp marking when this entry was saved (UTC).
    """

    __tablename__ = "inbox_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_query: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    included_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False, index=True
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging.

        Returns:
            A string identifying the entry by id and source_type.
        """
        return f"<InboxEntry id={self.id} source_type={self.source_type!r}>"


class QuarantineRecord(Base):
    """A durable record of one file successfully moved into quarantine.

    Phase 37, Batch 1. Exists so a future restore command has
    trustworthy information about where a quarantined file originally
    came from: FileDeleteTool's own quarantine filename only preserves
    the original stem/suffix (Phase 35), never the original directory -
    this table closes that gap by recording both paths at the moment
    of quarantine.

    Deliberately excluded, by design, not oversight: no restore_status,
    restored_at, cleanup/retention, or dashboard-facing fields - none
    of that is needed until a future, separately-scoped restore phase
    actually exists. There is no update or delete method on
    QuarantineStore (see quarantine/quarantine_store.py) - once
    recorded, a row is never mutated or removed.

    Not every file inside .jarvis_trash/ has a corresponding row here:
    files quarantined by Phase 35/36, before this table existed, have
    none. Any future consumer of this table must treat a missing
    record as the ordinary, expected case for such files, never an
    error - this table does not attempt to retroactively backfill or
    migrate anything quarantined before it existed.

    Attributes:
        id: Auto-incrementing primary key.
        original_path: The absolute, resolved path the file was
            quarantined from. Stored resolved (not relative to whatever
            the working directory happened to be at quarantine time),
            so a future restore command is never ambiguous about what
            "the original location" means even if Jarvis is later run
            from a different directory.
        quarantine_path: The absolute, resolved path the file was moved
            to inside the quarantine directory. Unique: FileDeleteTool's
            own collision-safe naming scheme never reuses a quarantine
            path, and this column enforces that as a durable guarantee
            too, not just an in-process one.
        quarantined_at: Timestamp marking when the file was quarantined
            (UTC).
        session_id: The session the quarantine happened under; may be
            None. Plain Integer, not a ForeignKey, matching
            ApprovalHistoryEntry/WorkflowHistoryEntry/InboxEntry's own
            established convention.
    """

    __tablename__ = "quarantine_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    original_path: Mapped[str] = mapped_column(Text, nullable=False)
    quarantine_path: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True, index=True
    )
    quarantined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False, index=True
    )
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging.

        Returns:
            A string identifying the record by id and quarantine_path.
        """
        return (
            f"<QuarantineRecord id={self.id} "
            f"quarantine_path={self.quarantine_path!r}>"
        )


class ScheduleEntry(Base):
    """A durable, user-configured daily web-search-summary schedule.

    Phase 21. Unlike every other table in this project, this one is
    neither append-only nor write-once-then-decided-once:
    `enabled`/`last_run_at` change in place over the schedule's lifetime.
    This is a deliberate, disclosed departure from the append-only
    convention `ApprovalHistoryEntry`/`WorkflowHistoryEntry`/`InboxEntry`
    all follow - compensated for by keeping the table's own shape, and
    `scheduling/schedule_store.py`'s public API, as narrow as possible.

    Deliberately excluded, by design, not oversight: there is no
    arbitrary command-string column, no `action_type` dispatch column,
    no workflow id, no tool name, no tool input, no approval id, no
    recurrence/cron expression, no timezone column (host local time is
    used uniformly - see docs/phase_21_implementation_plan.md section
    10), and no notification/read-unread field of any kind. The only
    "what to do" data this table ever holds is the literal search query
    text - never a command, never code, never a reference to any other
    action. The single hard-coded action (search, summarise, save to
    Inbox) lives entirely in Python code added in a later batch, not in
    this schema - extending to a second action type would require a
    real code change and its own review, not a configuration change.

    Attributes:
        id: Auto-incrementing primary key.
        name: An optional, user-supplied label for the schedule; purely
            for display, never interpreted.
        query: The literal search query this schedule runs, stored
            verbatim (the same reasoned privacy decision as
            InboxEntry.source_query - this is a user-facing record only
            Nathan ever reads, not the audit log).
        time_of_day: The scheduled time, as a strict 24-hour "HH:MM"
            string, interpreted in the host machine's own local time
            (never a stored per-schedule timezone).
        enabled: Whether this schedule is currently active. Disabling a
            schedule is the only way to stop it from running - there is
            no delete method (see schedule_store.py).
        last_run_at: UTC timestamp of this schedule's most recent claimed
            run, or None if it has never run. Updated by the atomic claim
            mechanism added in a later batch - Batch 1 never writes to
            this field.
        created_at: Timestamp marking when this schedule was created (UTC).
    """

    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    time_of_day: Mapped[str] = mapped_column(String(5), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False, index=True
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging.

        Returns:
            A string identifying the schedule by id, time, and enabled state.
        """
        return (
            f"<ScheduleEntry id={self.id} time_of_day={self.time_of_day!r} "
            f"enabled={self.enabled!r}>"
        )


class ScheduledInboxNoticeState(Base):
    """A single-row, durable marker tracking the last scheduled Inbox
    entry the CLI has already reported to Nathan.

    Phase 22. Unlike every other table in this project, exactly one row
    of this table is ever expected to exist - it is neither append-only
    (InboxEntry, WorkflowHistoryEntry), write-once-then-decided-once
    (ApprovalHistoryEntry), nor per-row mutable-by-id (ScheduleEntry).
    scheduling/scheduled_inbox_notice_store.py's own store enforces this
    single-row, upsert-style shape; the model itself does not use a
    fixed/singleton primary key value, since SQLAlchemy's own autoincrement
    identity is sufficient given the store never creates a second row.

    Deliberately excluded, by design, not oversight: there is no
    key/name column (this is not a generic settings table - see
    docs/phase_22_implementation_plan.md section 4 for the considered
    and rejected alternatives), no per-entry notification record, no
    read/unread/dismiss column, and no channel/delivery column of any
    kind. This table tracks exactly one fact: the highest InboxEntry.id
    already reported in a CLI startup notice - nothing about the notice
    text itself, nothing about delivery, and nothing about any other
    Inbox entry's state.

    A timestamp-based marker (last_seen_at) was considered and rejected
    in favour of an id-based one: InboxEntry.id is a strictly monotonic,
    never-reused autoincrement primary key on an append-only table,
    making it immune to the clock-change and exact-timestamp-collision
    edge cases a timestamp comparison would need to reason about.

    Attributes:
        id: Auto-incrementing primary key. Exactly one row is ever
            written by the owning store.
        last_seen_entry_id: The highest InboxEntry.id already reported
            in a startup notice, or None if no notice has ever been
            shown (the store's own first-run state).
        created_at: Timestamp marking when this marker row was first
            created (UTC) - informational only, matching every other
            table's own created_at convention.
    """

    __tablename__ = "scheduled_inbox_notice_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    last_seen_entry_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging.

        Returns:
            A string identifying the row by id and last_seen_entry_id.
        """
        return (
            f"<ScheduledInboxNoticeState id={self.id} "
            f"last_seen_entry_id={self.last_seen_entry_id!r}>"
        )


class PendingApprovalState(Base):
    """Durable operational state for a currently-pending YELLOW approval.

    Phase 27, Batch 1. This is deliberately NOT a second approval-history
    table - `ApprovalHistoryEntry` remains completely unchanged, and its
    own long-standing discipline of never storing a tool_name or
    tool_input is preserved exactly as before. This table exists for a
    different, narrower, newly-authorized purpose: letting a pending
    approval's execution state - which tool, with what input - survive a
    process restart, so it can be independently revalidated and safely
    resumed. See approval/pending_approval_store.py's own module
    docstring, and docs/phase_27_implementation_plan.md section 4, for
    the full trust-boundary reasoning this table's design rests on.

    A row here is short-lived operational state, not history: it exists
    only while its request is genuinely pending, and is deleted the
    moment that request is decided, expires, or is found invalid on
    reload. Nothing here is ever copied into approval_history, and
    nothing in approval_history is ever read from here.

    Row existence must never be treated as approval, and loading a row
    must never, by itself, execute anything - ApprovalManager.
    reload_pending() always independently re-validates every field
    against live code (the current ToolRegistry and a fresh
    SecurityManager.classify_action() call) before treating a row as
    genuinely pending again; a row that fails that revalidation is
    removed here and recorded as an honest terminal entry in
    approval_history instead of ever being resumed.

    Attributes:
        id: Auto-incrementing primary key.
        request_id: The approval request id this row describes (matches
            ApprovalRequest.request_id). Unique - at most one row per
            request.
        session_id: The session the request belonged to, if any. Plain
            Integer, not a ForeignKey, matching every newer table's own
            convention.
        action: The action string that required approval.
        reason: A human-readable explanation of why approval was needed.
        security_tier: The tier of the action, as a string. Always
            "yellow" at write time - never trusted alone on reload; the
            action is always reclassified fresh.
        metadata_json: JSON-serialized copy of ApprovalRequest.metadata
            (a plain dict[str, str] - for example workflow_id/
            step_number, when this request is workflow-linked). Never
            anything beyond that existing, already-narrow shape.
        tool_name: The registered tool this request would run once
            approved, or None when this request has no backing tool at
            all (a plan-only confirmation with nothing to execute - see
            core.orchestrator._confirmation_response) - such a row is
            never resumable, by design, and is always invalidated on
            reload rather than executed.
        tool_input_json: JSON-serialized copy of the plain tool_input
            dict this request would run with once approved. Null exactly
            when tool_name is null. Plain, already-validated data only
            (paths, ids, text) - never code, never a pickled object.
        schema_version: The version of this row's own JSON shape. Used
            so a future change to what is stored can safely refuse to
            treat an older or newer row it no longer understands as
            resumable, rather than guessing.
        created_at: Timestamp marking when this request was first
            created (UTC) - used to evaluate staleness on reload, using
            the same timeout_seconds ceiling ApprovalManager already
            applies to a live pending request.
        handoff_status: The durable execution-handoff lifecycle state
            of this row (Approval-to-Resume Handoff Interlock, Batch 1
            - docs/phase_98_approval_handoff_plan.md), one of
            approval.approval_models.PendingApprovalHandoffStatus's own
            values, stored as text. Defaults to "pending" for every row
            - both freshly created ones and existing rows migrated by
            storage.database's own guarded
            _ensure_pending_approval_handoff_status_column() - so this
            column's addition changes no existing row's meaning. A
            wholly separate concept from this table's own `action`/
            `reason`/`security_tier` (which describe the request being
            approved) - see PendingApprovalHandoffStatus's own
            docstring for why this is not the same lifecycle as
            ApprovalStatus. No live ApprovalManager code reads or
            writes this column in Batch 1 - only the new, narrow
            compare-and-set primitives on PendingApprovalStore do,
            exercised directly by this batch's own tests.
    """

    __tablename__ = "pending_approval_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True, index=True
    )
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    security_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False, index=True
    )
    handoff_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", server_default="pending"
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging.

        Returns:
            A string identifying the row by request_id and tool_name.
        """
        return (
            f"<PendingApprovalState request_id={self.request_id!r} "
            f"tool_name={self.tool_name!r}>"
        )


class PausedWorkflowState(Base):
    """Durable operational state for a currently-paused workflow.

    Phase 27, Batch 2. This is deliberately NOT a second workflow-history
    table - `WorkflowHistoryEntry` remains completely unchanged, and its
    own long-standing discipline of never storing a serialised Plan or
    resolved step input is preserved exactly as before. This table exists
    for a different, narrower, newly-authorized purpose: letting a paused
    workflow's own resumption state - its plan, which steps already
    completed, which step is waiting, and that step's resolved input -
    survive a process restart, so it can be independently revalidated and
    safely resumed. See workflow/paused_workflow_store.py's own module
    docstring, and docs/phase_27_implementation_plan.md section 4/5, for
    the full trust-boundary reasoning this table's design rests on -
    identical in spirit to storage.models.PendingApprovalState (Phase 27,
    Batch 1), applied to a whole paused workflow instead of one pending
    tool call.

    A row here is short-lived operational state, not history: it exists
    only while its workflow is genuinely paused, and is deleted the
    moment that workflow resumes (successfully or not) or is found
    invalid on reload. Nothing here is ever copied into workflow_history,
    and nothing in workflow_history is ever read from here.

    Row existence must never be treated as approval, and loading a row
    must never, by itself, execute anything - WorkflowEngine.
    reload_paused() always independently re-validates every field
    against live code (the current ToolRegistry, a fresh
    SecurityManager.classify_action() call, and - critically - whether
    this row's own linked approval is still genuinely pending in
    ApprovalManager, reusing Batch 1's own reload_pending() outcome
    rather than re-deriving approval validity here) before treating a row
    as genuinely paused again; a row that fails that revalidation is
    removed here and recorded as an honest terminal entry in
    workflow_history instead of ever being resumed, and its own linked
    pending-approval row (if still present) is invalidated too, so its
    mere existence can never imply this workflow is still resumable.

    Attributes:
        id: Auto-incrementing primary key.
        workflow_id: The workflow this row describes (matches
            WorkflowEngine's own per-run correlation id). Unique - at
            most one row per workflow, mirroring Phase 15's own
            one-workflow-paused-at-a-time contract.
        session_id: The session the workflow ran under, if any. Plain
            Integer, not a ForeignKey, matching every newer table's own
            convention.
        request_id: The id of the pending_approval_state /
            ApprovalRequest this workflow is paused on (matches
            ApprovalRequest.request_id). A paused workflow is never
            treated as resumable unless this exact request_id is still
            genuinely pending in ApprovalManager after its own reload.
        user_request: The original Plan.user_request text this workflow
            was built from.
        plan_steps_json: JSON-serialized list of every step in the
            paused workflow's Plan (number, description, action, tier,
            reason, tool_name, tool_input, input_from_previous_step) -
            plain, already-validated data (paths, ids, text), never code
            or a pickled object. Authorized to be stored here, for this
            table only, for the same reason PendingApprovalState.
            tool_input_json is authorized (Phase 27 planning).
        completed_outcomes_json: JSON-serialized list of the steps
            already completed before the pause (step_number and a plain
            view of that step's ToolResult) - enough to display/resume
            context. Never re-executed on reload; only the waiting step
            is ever a candidate for execution, and only after a fresh
            approval decision.
        waiting_step_index: The plan.steps index of the step this
            workflow is paused on.
        resolved_tool_input_json: JSON-serialized dict of the specific
            input the waiting step would run with once resumed.
        schema_version: The version of this row's own JSON shape. Used
            so a future change to what is stored can safely refuse to
            treat an older or newer row it no longer understands as
            resumable, rather than guessing.
        created_at: Timestamp marking when this workflow first paused
            (UTC). Deliberately not used as an independent staleness
            ceiling - see reload_paused()'s own docstring for why a
            paused workflow's resumability is entirely inherited from
            its linked approval's own staleness check (Batch 1), rather
            than a second, separately-clocked ceiling that could disagree
            with it.
    """

    __tablename__ = "paused_workflow_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True, index=True
    )
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_request: Mapped[str] = mapped_column(Text, nullable=False)
    plan_steps_json: Mapped[str] = mapped_column(Text, nullable=False)
    completed_outcomes_json: Mapped[str] = mapped_column(Text, nullable=False)
    waiting_step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_tool_input_json: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False, index=True
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging.

        Returns:
            A string identifying the row by workflow_id and request_id.
        """
        return (
            f"<PausedWorkflowState workflow_id={self.workflow_id!r} "
            f"request_id={self.request_id!r}>"
        )


class ProjectState(Base):
    """A single-row, durable, manually-maintained record of Jarvis's
    project context (Phase 89, Batch 1).

    Unlike every other table in this project except
    ScheduledInboxNoticeState and PendingApprovalState, exactly one row
    of this table is ever expected to exist -
    project_state/project_state_store.py's own store enforces this
    single-row, upsert-in-place shape; the model itself does not use a
    fixed/singleton primary key value, mirroring
    ScheduledInboxNoticeState's own established reasoning (SQLAlchemy's
    autoincrement identity is sufficient given the store never creates
    a second row).

    Every field here is manually provided by Nathan through the
    "update jarvis project state: <field>=<value>" command - Jarvis
    never inspects git, a subprocess, or the filesystem to populate any
    of them, and never fabricates a value for a field that has not yet
    been recorded (None, reported honestly as "not recorded yet" by
    ProjectStateShowTool).

    Attributes:
        id: Auto-incrementing primary key. Exactly one row is ever
            written by the owning store.
        branch: The current git branch name, as manually recorded by
            Nathan, or None if never recorded.
        phase: The latest closed phase, as manually recorded, or None.
        commit: The latest closed commit hash, as manually recorded,
            or None.
        suite_result: The latest full test-suite result, as manually
            recorded, or None. Called "suite" in the CLI grammar - the
            one field name that differs between grammar and column,
            matching JarvisBrainStatusTool's/PromptContext's own
            naming for the same real-world concept.
        focus: The current focus/next goal, as manually recorded, or
            None.
        last_updated: When this stored record was last written by
            ProjectStateStore.update() (UTC) - meaning only "when
            Nathan/Jarvis last updated this stored record," never a
            live git/test-run timestamp. None if the row has never
            been written to.
    """

    __tablename__ = "project_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phase: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commit: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suite_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    focus: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_updated: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging.

        Returns:
            A string identifying the row by id and last_updated.
        """
        return f"<ProjectState id={self.id} last_updated={self.last_updated!r}>"


class CompoundWorkflowProgress(Base):
    """Durable, authoritative step-progress state for exactly one future,
    not-yet-live compound workflow template (Phase 98, Batch 1 -
    docs/phase_98_implementation_plan.md):
    PROJECT_STATE_UPDATE_PHASE -> internal phase verification ->
    PROJECT_STATE_SHOW.

    This table is deliberately narrow - scoped exclusively to this one
    trusted template, never a generic workflow-progress framework.
    `workflow.compound_workflow_progress_store.CompoundWorkflowProgressStore`
    is the sole owner of every write to this table; a row's own
    `overall_status`/`step_*_status` fields are this template's
    authoritative execution state - unlike `WorkflowHistoryEntry`, which
    remains a permanent, append-only, execution-decision-independent
    audit log, and unlike `PausedWorkflowState`, which only ever
    represents "paused awaiting approval," never "actively progressing
    after approval." No code in this phase reads or writes this table
    from any live request path - it exists only so its own dedicated
    tests can prove the mechanism correct ahead of a later, separately-
    approved batch that wires it into live execution.

    Attributes:
        id: Auto-incrementing primary key.
        workflow_id: The workflow id this row describes (matches
            WorkflowEngine's own per-run correlation id). Unique - at
            most one row per workflow.
        template_id: The trusted, static compound-template identity
            (matches
            intelligence.compound_grounding.CompoundTemplate.template_id)
            this workflow was built from. Immutable once set - never
            replaced.
        request_id: The id of the linked approval/paused-workflow this
            compound workflow began from, if any.
        approved_phase_value: The exact, already-approved phase value
            this workflow was authorized to write. Immutable once set.
        pre_execution_phase_value: The real ProjectState.phase value
            observed immediately before the write step was attempted,
            or None if never recorded. Used only for honest, bounded
            reconciliation (see
            workflow.compound_workflow_progress_store.reconcile_phase_update) -
            never to claim execution occurred by itself.
        pre_execution_last_updated: The real ProjectState.last_updated
            timestamp observed at the same moment as
            pre_execution_phase_value, or None. A change between this
            value and the real, current last_updated at reconciliation
            time is evidence that *some* write touched the row since -
            never, by itself, proof of which write.
        step_1_status: One of "pending" / "in_progress" / "completed" /
            "failed" - the phase-update write step.
        step_2_status: One of "pending" / "in_progress" / "completed" /
            "failed" - the internal phase-verification step.
        step_2_verification_outcome: One of "verified" / "failed" /
            "unavailable", or None before step 2 completes. Mirrors
            intelligence.verification.VerificationOutcome's own bounded
            vocabulary - never a raw metadata string.
        step_3_status: One of "pending" / "in_progress" / "completed" /
            "failed" - the ProjectState-show read step.
        overall_status: One of "pending" / "in_progress" /
            "needs_reconciliation" / "completed" / "failed".
        created_at: UTC timestamp this row was first written.
        updated_at: UTC timestamp this row was last written.
    """

    __tablename__ = "compound_workflow_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True, index=True
    )
    template_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    request_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    approved_phase_value: Mapped[str] = mapped_column(Text, nullable=False)
    pre_execution_phase_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    pre_execution_last_updated: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    step_1_status: Mapped[str] = mapped_column(String(16), nullable=False)
    step_2_status: Mapped[str] = mapped_column(String(16), nullable=False)
    step_2_verification_outcome: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    step_3_status: Mapped[str] = mapped_column(String(16), nullable=False)
    overall_status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
        nullable=False,
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging.

        Returns:
            A string identifying the row by workflow_id and overall_status.
        """
        return (
            f"<CompoundWorkflowProgress workflow_id={self.workflow_id!r} "
            f"overall_status={self.overall_status!r}>"
        )


class ScheduleCompoundWorkflowProgress(Base):
    """Durable, authoritative step-progress state for exactly one
    second, still-dormant compound workflow template (Phase 99, Batch 2 -
    docs/phase_99_second_compound_template_planning.md): SCHEDULE_ENABLE
    -> SCHEDULE_VERIFY_ENABLED_STATE -> SCHEDULE_SHOW_ENABLED_STATE.

    A wholly separate, parallel table to CompoundWorkflowProgress -
    never a shared or generalised progress schema. Every column here is
    specific to this one template's own three trusted steps, mirroring
    CompoundWorkflowProgress's own shape exactly, except that the
    write step's trusted, immutable payload is an integer `schedule_id`
    (never a string value), and there is no `pre_execution_*_last_updated`
    counterpart - ScheduleEntry has no updated_at/version column, so
    reconciliation here has one fewer piece of tie-breaking evidence
    than reconcile_phase_update() (see
    workflow.schedule_compound_workflow_progress_store.reconcile_schedule_enable()'s
    own docstring for the honest, narrower consequence of that).

    No code in this phase reads or writes this table from any live
    request path - it exists only so its own dedicated tests can prove
    the mechanism correct ahead of a later, separately-approved batch
    that wires it into live execution.

    Attributes:
        id: Auto-incrementing primary key.
        workflow_id: The workflow id this row describes (matches
            WorkflowEngine's own per-run correlation id). Unique - at
            most one row per workflow.
        template_id: The trusted, static compound-template identity
            this workflow was built from. Immutable once set.
        request_id: The id of the linked approval/paused-workflow this
            compound workflow began from, if any.
        schedule_id: The exact, already-approved schedule id this
            workflow was authorized to enable. Immutable once set.
        pre_execution_enabled: The real ScheduleEntry.enabled value
            observed immediately before the enable step was attempted,
            or None if never recorded. Used only for honest, bounded
            reconciliation - never to claim execution occurred by itself.
        step_1_status: One of "pending" / "in_progress" / "completed" /
            "failed" - the schedule-enable write step.
        step_2_status: One of "pending" / "in_progress" / "completed" /
            "failed" - the internal enabled-state-verification step.
        step_2_verification_outcome: One of "verified" / "failed" /
            "unavailable", or None before step 2 completes.
        step_3_status: One of "pending" / "in_progress" / "completed" /
            "failed" - the SCHEDULE_SHOW_ENABLED_STATE read step.
        overall_status: One of "pending" / "in_progress" /
            "needs_reconciliation" / "completed" / "failed" /
            "not_executed".
        created_at: UTC timestamp this row was first written.
        updated_at: UTC timestamp this row was last written.
    """

    __tablename__ = "schedule_compound_workflow_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True, index=True
    )
    template_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    request_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    schedule_id: Mapped[int] = mapped_column(Integer, nullable=False)
    pre_execution_enabled: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    step_1_status: Mapped[str] = mapped_column(String(16), nullable=False)
    step_2_status: Mapped[str] = mapped_column(String(16), nullable=False)
    step_2_verification_outcome: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    step_3_status: Mapped[str] = mapped_column(String(16), nullable=False)
    overall_status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
        nullable=False,
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging.

        Returns:
            A string identifying the row by workflow_id and overall_status.
        """
        return (
            f"<ScheduleCompoundWorkflowProgress workflow_id={self.workflow_id!r} "
            f"overall_status={self.overall_status!r}>"
        )


class WorkflowCheckpointEntry(Base):
    """Per-step checkpoint for DAG workflow crash recovery.

    One row per (workflow_id, step_id) tracking that step's progress.
    Updated in-place as the step progresses through pending -> running ->
    completed/failed/skipped.
    """

    __tablename__ = "workflow_checkpoints"
    __table_args__ = (
        UniqueConstraint("workflow_id", "step_id", name="uq_checkpoint_wf_step"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    step_id: Mapped[str] = mapped_column(String(128), nullable=False)
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    tool_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retries_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<WorkflowCheckpointEntry workflow_id={self.workflow_id!r} "
            f"step_id={self.step_id!r} status={self.status!r}>"
        )