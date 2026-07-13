"""
logger.py

Structured event logging for the Jarvis AI Operating System.

Responsibilities:
    - Define the structured Event record that every subsystem emits.
    - Stamp each event with a UTC timestamp and a unique identifier.
    - Route each event through Python's standard logging module (the
      intended path to console visibility) and persist it to the
      append-only audit log - the one destination that is always
      durable and complete (see the accuracy note below).
    - Provide a simple, uniform API so every subsystem logs events the same way.

Does NOT:
    - Implement Security Manager logic (it only records the tier it is given).
    - Implement AI logic.
    - Implement Memory logic.
    - Persist events itself (persistence is delegated to security.audit_log).
    - Configure any logging handler or level (Phase 48; see
      docs/phase_47_logging_console_visibility_plan.md for the full
      investigation). No production entry point (main.py, scheduler.py)
      attaches a handler or sets a level today, so console visibility is
      not fully configured: WARNING/ERROR-level events (BLOCKED/TIMEOUT/
      FAILURE outcomes) may still appear via Python's own
      logging.lastResort fallback handler, but INFO-level events (every
      GREEN/successful outcome - the majority of what Jarvis does) are
      not guaranteed to appear on the console at all without a future
      handler-configuration phase.

This module is the single entry point for structured logging. No subsystem
should write to the console or the audit log directly; all events flow
through the EventLogger so that format and destinations stay consistent.
The append-only audit log (security.audit_log.AuditLog) is unaffected by any
of the above and remains the durable, permanent record regardless of console
configuration - every existing history command ("show approval history",
"show workflow history") and the dashboard's read-only tabs read from it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from config.constants import APP_NAME, EventOutcome, SecurityTier
from security.audit_log import AuditLog


def _utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Returns:
        The current moment in UTC, as a timezone-aware datetime.
    """
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Event:
    """A single structured event produced by a Jarvis subsystem.

    Events are immutable once created. They capture what happened, where it
    happened, the result, and the context needed to trace it later.

    Attributes:
        source: The subsystem that produced the event (e.g. "tool_manager").
        action_type: The category of action (e.g. "tool_call", "ai_call").
        outcome: The result of the action.
        detail: Optional sanitised human-readable detail. Must not contain
            secrets or sensitive data.
        duration_ms: Optional duration of the action in milliseconds.
        security_tier: Optional risk tier of the action, if applicable.
        session_id: Optional identifier of the session the event belongs to.
        timestamp: UTC timestamp marking when the event was created. Set
            automatically.
        event_id: Unique identifier for this event. Set automatically.
    """

    source: str
    action_type: str
    outcome: EventOutcome
    detail: str | None = None
    duration_ms: int | None = None
    security_tier: SecurityTier | None = None
    session_id: int | None = None
    timestamp: datetime = field(default_factory=_utc_now)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_console_line(self) -> str:
        """Render the event as a single human-readable console line.

        Returns:
            A compact, fixed-order string suitable for console output.
        """
        parts = [
            self.timestamp.isoformat(),
            f"[{self.source}]",
            self.action_type,
            f"-> {self.outcome.value}",
        ]
        if self.security_tier is not None:
            parts.append(f"tier={self.security_tier.value}")
        if self.duration_ms is not None:
            parts.append(f"{self.duration_ms}ms")
        if self.session_id is not None:
            parts.append(f"session={self.session_id}")
        if self.detail:
            parts.append(f"| {self.detail}")
        return " ".join(parts)


class EventLogger:
    """Builds, emits, and persists structured events.

    The EventLogger is the uniform logging API for every subsystem. It routes
    each event through the standard-library logging module and persists it to
    the append-only audit log for the permanent record. The audit log write
    always succeeds regardless of logging configuration; console visibility
    depends on handler/level configuration that no production entry point
    currently sets up (see module docstring above for the full accuracy note).

    Attributes:
        _audit_log: The append-only audit log events are persisted to -
            always durable, regardless of console logging configuration.
        _logger: The standard-library logger events are routed through.
            Not guaranteed to produce visible console output for INFO-level
            (GREEN/successful) events today - see module docstring above.
    """

    def __init__(self, audit_log: AuditLog) -> None:
        """Initialise the event logger.

        Args:
            audit_log: The append-only audit log used to persist events,
                produced by security.audit_log.AuditLog.
        """
        self._audit_log = audit_log
        self._logger = logging.getLogger(APP_NAME)

    def log(self, event: Event) -> str:
        """Emit a fully constructed event to all destinations.

        The event is routed to the standard-library logger at a level
        derived from its outcome, then persisted to the append-only audit
        log. The audit log write always durably succeeds. The logging call
        does not guarantee visible console output today: no production
        entry point configures a handler or level, so WARNING/ERROR-level
        events (BLOCKED/TIMEOUT/FAILURE) may appear via Python's own
        logging.lastResort fallback, while INFO-level events (GREEN/
        successful outcomes) are not guaranteed to appear on the console at
        all (see the module docstring's accuracy note).

        Args:
            event: The event to emit.

        Returns:
            The primary key of the persisted audit log entry, as a string,
            allowing the caller to correlate the in-memory event with its
            stored record.
        """
        self._logger.log(self._level_for(event.outcome), event.to_console_line())

        entry_id = self._audit_log.record(
            action_type=event.action_type,
            outcome=event.outcome.value,
            security_tier=(
                event.security_tier.value if event.security_tier is not None else None
            ),
            detail=event.detail,
            duration_ms=event.duration_ms,
            session_id=event.session_id,
        )
        return str(entry_id)

    def emit(
        self,
        *,
        source: str,
        action_type: str,
        outcome: EventOutcome,
        detail: str | None = None,
        duration_ms: int | None = None,
        security_tier: SecurityTier | None = None,
        session_id: int | None = None,
    ) -> str:
        """Construct and emit an event in a single call.

        This is the convenience method most callers use. It builds an Event
        (stamping the timestamp and id automatically) and emits it.

        Args:
            source: The subsystem producing the event.
            action_type: The category of action.
            outcome: The result of the action.
            detail: Optional sanitised detail. Must not contain secrets.
            duration_ms: Optional duration in milliseconds.
            security_tier: Optional risk tier, if applicable.
            session_id: Optional session identifier.

        Returns:
            The primary key of the persisted audit log entry, as a string.
        """
        event = Event(
            source=source,
            action_type=action_type,
            outcome=outcome,
            detail=detail,
            duration_ms=duration_ms,
            security_tier=security_tier,
            session_id=session_id,
        )
        return self.log(event)

    @staticmethod
    def _level_for(outcome: EventOutcome) -> int:
        """Map an event outcome to a standard logging level.

        Args:
            outcome: The outcome of the event.

        Returns:
            The standard-library logging level integer for the outcome.
        """
        if outcome is EventOutcome.FAILURE:
            return logging.ERROR
        if outcome in (EventOutcome.BLOCKED, EventOutcome.TIMEOUT):
            return logging.WARNING
        return logging.INFO 