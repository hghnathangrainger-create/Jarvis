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