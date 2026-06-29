"""
audit_log.py

Append-only persistence for security and action events in the Jarvis
AI Operating System.

Responsibilities:
    - Write structured events into the audit_log database table.
    - Guarantee append-only behaviour: entries are only ever inserted, never
      updated or deleted through this module.
    - Provide read-only retrieval helpers for inspecting recorded events.

Does NOT:
    - Implement Security Manager logic (risk classification, approvals).
    - Implement AI logic.
    - Implement Memory logic.
    - Build or format events (see observability/logger.py).

This module is the only sanctioned path for writing to the audit_log table.
It exposes no update or delete operation, which keeps the audit trail
trustworthy: once an action is recorded, it cannot be silently altered.
"""

from __future__ import annotations

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from storage.database import session_scope
from storage.models import AuditLogEntry


class AuditLog:
    """Append-only writer and reader for the audit_log table.

    A single AuditLog instance is created with a session factory and shared by
    the subsystems that need to record actions. It deliberately provides no
    method to modify or remove existing entries.

    Attributes:
        _session_factory: Factory used to open database sessions for each
            write or read operation.
    """

    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        """Initialise the audit log with a database session factory.

        Args:
            session_factory: The factory used to create database sessions,
                typically produced by storage.database.create_session_factory.
        """
        self._session_factory = session_factory

    def record(
        self,
        *,
        action_type: str,
        outcome: str,
        security_tier: str | None = None,
        detail: str | None = None,
        duration_ms: int | None = None,
        session_id: int | None = None,
    ) -> int:
        """Insert a single event into the audit log.

        This is the only way to write to the audit trail. The entry is
        committed immediately so that the record survives even if a later step
        in the calling operation fails.

        Args:
            action_type: The category of action being recorded
                (e.g. "tool_call", "ai_call", "security_decision").
            outcome: The result of the action (e.g. "success", "blocked").
            security_tier: The risk tier of the action, if applicable
                (e.g. "green", "yellow", "red"). Defaults to None.
            detail: Optional sanitised detail describing the action. Must not
                contain secrets or sensitive data. Defaults to None.
            duration_ms: Optional duration of the action in milliseconds.
                Defaults to None.
            session_id: Optional identifier of the session the action belongs
                to. Defaults to None.

        Returns:
            The auto-generated primary key of the newly inserted entry.
        """
        with session_scope(self._session_factory) as db:
            entry = AuditLogEntry(
                session_id=session_id,
                action_type=action_type,
                security_tier=security_tier,
                outcome=outcome,
                detail=detail,
                duration_ms=duration_ms,
            )
            db.add(entry)
            db.flush()  # populate entry.id before the scope commits
            return entry.id

    def get_recent(self, limit: int = 50) -> list[AuditLogEntry]:
        """Return the most recent audit log entries, newest first.

        This is a read-only convenience for inspection and debugging. It does
        not modify the audit trail in any way.

        Args:
            limit: Maximum number of entries to return. Defaults to 50.

        Returns:
            A list of AuditLogEntry objects ordered from newest to oldest.
        """
        with session_scope(self._session_factory) as db:
            return list(
                db.query(AuditLogEntry)
                .order_by(AuditLogEntry.created_at.desc(), AuditLogEntry.id.desc())
                .limit(limit)
                .all()
            )

    def count(self) -> int:
        """Return the total number of entries in the audit log.

        Returns:
            The total count of recorded audit log entries.
        """
        with session_scope(self._session_factory) as db:
            return db.query(AuditLogEntry).count() 