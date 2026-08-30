"""
models.py

Security data models for the Jarvis AI Operating System.

Responsibilities:
    - Define SecurityLevel enum (GREEN/YELLOW/RED).
    - Define ApprovalRequest for the approval workflow.
    - Define SecurityEvent for audit logging.
    - Define InjectionResult for injection detection output.

Does NOT:
    - Implement security logic (see security_manager.py).
    - Implement injection detection (see injection_detector.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import uuid


class SecurityLevel(Enum):
    """Risk classification for actions.

    Attributes:
        GREEN: Safe, auto-approve. Read-only or reversible actions.
        YELLOW: Needs confirmation. State-changing but recoverable.
        RED: Needs explicit approval. Irreversible or high-consequence.
    """

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class ApprovalStatus(Enum):
    """Lifecycle state of an approval request.

    Attributes:
        PENDING: Awaiting user decision.
        APPROVED: User approved the request.
        DENIED: User denied the request.
        EXPIRED: Request expired without decision.
    """

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass
class ApprovalRequest:
    """A request for user approval of a sensitive action.

    Attributes:
        request_id: Unique identifier for this request.
        action: The action description.
        tool_name: The tool that would execute.
        input_data: The input the tool would receive.
        level: The security level (YELLOW or RED).
        requested_at: When the request was created.
        expires_at: When the request expires (None for RED).
        status: Current lifecycle state.
        response: User's response text, if any.
        responded_at: When the user responded.
    """

    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    action: str = ""
    tool_name: str = ""
    input_data: dict = field(default_factory=dict)
    level: SecurityLevel = SecurityLevel.YELLOW
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    response: str | None = None
    responded_at: datetime | None = None

    def is_expired(self) -> bool:
        """Check if this request has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict."""
        return {
            "request_id": self.request_id,
            "action": self.action,
            "tool_name": self.tool_name,
            "input_data": self.input_data,
            "level": self.level.value,
            "requested_at": self.requested_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "status": self.status.value,
            "response": self.response,
            "responded_at": self.responded_at.isoformat() if self.responded_at else None,
        }


@dataclass
class SecurityEvent:
    """A recorded security event for audit logging.

    Attributes:
        event_id: Unique identifier.
        timestamp: When the event occurred.
        level: The security level of the action.
        action: The action description.
        tool_name: The tool involved.
        details: Additional details about the event.
        approved: Whether the action was approved.
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    level: SecurityLevel = SecurityLevel.GREEN
    action: str = ""
    tool_name: str = ""
    details: str = ""
    approved: bool = True

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.value,
            "action": self.action,
            "tool_name": self.tool_name,
            "details": self.details,
            "approved": self.approved,
        }


@dataclass
class InjectionResult:
    """Result of a prompt injection detection scan.

    Attributes:
        is_injection: True if injection patterns were detected.
        confidence: Confidence score from 0.0 (clean) to 1.0 (certain).
        technique: Which detection technique was triggered.
        patterns: List of matched pattern labels.
        details: Human-readable explanation.
    """

    is_injection: bool = False
    confidence: float = 0.0
    technique: str = ""
    patterns: list[str] = field(default_factory=list)
    details: str = ""

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict."""
        return {
            "is_injection": self.is_injection,
            "confidence": self.confidence,
            "technique": self.technique,
            "patterns": self.patterns,
            "details": self.details,
        }
