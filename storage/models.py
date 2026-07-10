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

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
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