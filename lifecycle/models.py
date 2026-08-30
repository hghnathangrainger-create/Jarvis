"""
models.py

Data models for the Jarvis System Lifecycle.

Responsibilities:
    - Define SystemState enum for system lifecycle states.
    - Define SubsystemStatus for tracking individual subsystem health.
    - Define LifecycleEvent for audit trail of lifecycle transitions.

Does NOT:
    - Implement lifecycle logic (see manager.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SystemState(str, Enum):
    """The current state of the Jarvis system."""

    STARTING = "starting"
    READY = "ready"
    RUNNING = "running"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"
    SAFE_MODE = "safe_mode"
    CRASHED = "crashed"


class SubsystemState(str, Enum):
    """The state of an individual subsystem."""

    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"
    DISABLED = "disabled"


@dataclass(slots=True)
class SubsystemStatus:
    """Status of a single subsystem.

    Attributes:
        name: The subsystem name (e.g. "database", "ai_router").
        state: Current state of the subsystem.
        started_at: When the subsystem was started (UTC), or None.
        error_message: Error message if the subsystem failed, or None.
    """

    name: str
    state: SubsystemState = SubsystemState.STARTING
    started_at: datetime | None = None
    error_message: str | None = None

    def to_dict(self) -> dict:
        """Serialise to a plain dict."""
        return {
            "name": self.name,
            "state": self.state.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "error_message": self.error_message,
        }


@dataclass(slots=True)
class LifecycleEvent:
    """A single lifecycle event for the audit trail.

    Attributes:
        event_type: The type of event (e.g. "startup", "shutdown", "safe_mode").
        timestamp: When the event occurred (UTC).
        subsystem: The subsystem involved, or None for system-wide events.
        details: Human-readable details.
    """

    event_type: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    subsystem: str | None = None
    details: str = ""

    def to_dict(self) -> dict:
        """Serialise to a plain dict."""
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat(),
            "subsystem": self.subsystem,
            "details": self.details,
        }
