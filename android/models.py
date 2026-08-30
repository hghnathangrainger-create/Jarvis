"""
models.py

Data models for the Jarvis Android Client backend.

Responsibilities:
    - Define DeviceRegistration for device tracking.
    - Define NotificationPayload for push notifications.
    - Define RemoteCommand and CommandResponse for remote control.

Does NOT:
    - Implement storage or notification logic.
    - Access Firebase or the database directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


@dataclass(frozen=True, slots=True)
class DeviceRegistration:
    """A registered Android device.

    Attributes:
        device_id: Unique device identifier (e.g. Android device ID).
        fcm_token: Firebase Cloud Messaging token for push notifications.
        user_id: The Jarvis user this device belongs to.
        platform: Device platform (e.g. "android", "ios").
        registered_at: When the device was registered (UTC).
        last_seen: When the device last communicated (UTC).
    """

    device_id: str
    fcm_token: str
    user_id: str = "default"
    platform: str = "android"
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Serialise to a plain dict."""
        return {
            "device_id": self.device_id,
            "fcm_token": self.fcm_token,
            "user_id": self.user_id,
            "platform": self.platform,
            "registered_at": self.registered_at.isoformat(),
            "last_seen": self.last_seen.isoformat(),
        }


class NotificationPriority(str, Enum):
    """Push notification priority."""

    HIGH = "high"
    NORMAL = "normal"


@dataclass(frozen=True, slots=True)
class NotificationPayload:
    """A push notification to send to Android devices.

    Attributes:
        title: Notification title.
        body: Notification body text.
        data: Optional key-value data payload.
        priority: Notification priority (high/normal).
        created_at: When the notification was created (UTC).
    """

    title: str
    body: str
    data: dict | None = None
    priority: NotificationPriority = NotificationPriority.NORMAL
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Serialise to a plain dict."""
        return {
            "title": self.title,
            "body": self.body,
            "data": self.data or {},
            "priority": self.priority.value,
            "created_at": self.created_at.isoformat(),
        }


class RemoteCommandType(str, Enum):
    """Types of remote commands the Android app can send."""

    CHAT = "chat"
    WORKFLOW_APPROVE = "workflow_approve"
    WORKFLOW_CANCEL = "workflow_cancel"
    STATUS_QUERY = "status_query"


class CommandStatus(str, Enum):
    """Status of a remote command."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class RemoteCommand:
    """A command sent from an Android device to Jarvis.

    Attributes:
        command_id: Unique command identifier.
        command_type: The type of command.
        payload: Command-specific payload data.
        created_at: When the command was created (UTC).
    """

    command_id: str
    command_type: RemoteCommandType
    payload: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Serialise to a plain dict."""
        return {
            "command_id": self.command_id,
            "command_type": self.command_type.value,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(slots=True)
class CommandResponse:
    """The result of processing a remote command.

    Attributes:
        command_id: The command this response is for.
        status: Whether the command completed, failed, or is still pending.
        result: Command-specific result data.
        error: Error message if the command failed.
    """

    command_id: str
    status: CommandStatus = CommandStatus.PENDING
    result: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        """Serialise to a plain dict."""
        return {
            "command_id": self.command_id,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
        }
