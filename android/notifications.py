"""
notifications.py

Push notification service for the Jarvis Android Client.

Responsibilities:
    - Send FCM push notifications to registered devices.
    - Provide specialised methods for approval requests and task completions.
    - Gracefully degrade when Firebase is not configured.

Does NOT:
    - Manage device registrations (see device_store.py).
    - Process remote commands (see remote_commands.py).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from android.models import NotificationPayload, NotificationPriority

logger = logging.getLogger(__name__)

# Firebase Admin SDK — imported lazily so it's optional.
_firebase_app: Any = None
_firebase_checked = False


def _get_firebase_app() -> Any:
    """Lazy-load and return the Firebase Admin app.

    Returns the Firebase app if configured, or None if Firebase is not
    available or not configured.
    """
    global _firebase_app, _firebase_checked

    if _firebase_checked:
        return _firebase_app

    _firebase_checked = True

    credentials_path = os.environ.get("GOOGLE_FIREBASE_CREDENTIALS", "")
    if not credentials_path:
        logger.warning(
            "Firebase not configured (GOOGLE_FIREBASE_CREDENTIALS not set). "
            "Push notifications will be logged but not sent."
        )
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials

        cred = credentials.Certificate(credentials_path)
        _firebase_app = firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initialized successfully")
        return _firebase_app
    except Exception as exc:
        logger.error("Failed to initialize Firebase: %s", exc)
        _firebase_app = None
        return None


class PushNotificationService:
    """Sends push notifications via Firebase Cloud Messaging.

    Falls back to logging when Firebase is not configured.

    Attributes:
        _available: Whether Firebase is configured and initialized.
    """

    def __init__(self) -> None:
        """Initialise the notification service."""
        self._available = _get_firebase_app() is not None

    @property
    def available(self) -> bool:
        """Whether Firebase push notifications are available."""
        return self._available

    def send_notification(
        self,
        device_ids: list[str],
        payload: NotificationPayload,
    ) -> dict[str, Any]:
        """Send a push notification to multiple devices.

        Args:
            device_ids: List of device FCM tokens to send to.
            payload: The notification content.

        Returns:
            A dict with success/failure counts.
        """
        if not device_ids:
            return {"sent": 0, "failed": 0, "reason": "no devices"}

        if not self._available:
            logger.info(
                "Push notification (Firebase not configured): title=%s body=%s devices=%d",
                payload.title,
                payload.body,
                len(device_ids),
            )
            return {"sent": 0, "failed": 0, "reason": "firebase not configured"}

        try:
            from firebase_admin import messaging

            messages = []
            for token in device_ids:
                message = messaging.Message(
                    notification=messaging.Notification(
                        title=payload.title,
                        body=payload.body,
                    ),
                    data=payload.data or {},
                    token=token,
                    android=messaging.AndroidConfig(
                        priority=payload.priority.value,
                    ),
                )
                messages.append(message)

            # Send in batches of 500 (FCM limit).
            sent = 0
            failed = 0
            for i in range(0, len(messages), 500):
                batch = messages[i:i + 500]
                response = messaging.send_each(batch)
                sent += response.success_count
                failed += response.failure_count

            logger.info("Push notifications sent: %d success, %d failed", sent, failed)
            return {"sent": sent, "failed": failed}

        except Exception as exc:
            logger.error("Failed to send push notifications: %s", exc)
            return {"sent": 0, "failed": len(device_ids), "error": str(exc)}

    def send_approval_request(
        self,
        device_id: str,
        request_id: str,
        action: str,
        details: str,
        tier: str,
    ) -> dict[str, Any]:
        """Send an approval request notification to a device.

        The notification includes action buttons for approve/decline.

        Args:
            device_id: The FCM token to send to.
            request_id: The approval request ID.
            action: The action requiring approval.
            details: Human-readable details.
            tier: The security tier (yellow/red).

        Returns:
            The send result.
        """
        payload = NotificationPayload(
            title=f"Approval Required ({tier.upper()})",
            body=f"{action}: {details}",
            data={
                "type": "approval_request",
                "request_id": request_id,
                "action": action,
                "tier": tier,
            },
            priority=NotificationPriority.HIGH,
        )
        return self.send_notification([device_id], payload)

    def send_task_completion(
        self,
        device_id: str,
        task_name: str,
        status: str,
    ) -> dict[str, Any]:
        """Notify when a task or workflow completes.

        Args:
            device_id: The FCM token to send to.
            task_name: Name of the completed task.
            status: The outcome (completed, failed, etc.).

        Returns:
            The send result.
        """
        payload = NotificationPayload(
            title=f"Task {status.title()}",
            body=f"{task_name} — {status}",
            data={
                "type": "task_completion",
                "task_name": task_name,
                "status": status,
            },
            priority=NotificationPriority.NORMAL,
        )
        return self.send_notification([device_id], payload)

    def send_alert(
        self,
        device_id: str,
        title: str,
        body: str,
    ) -> dict[str, Any]:
        """Send a generic proactive alert.

        Args:
            device_id: The FCM token to send to.
            title: Alert title.
            body: Alert body text.

        Returns:
            The send result.
        """
        payload = NotificationPayload(
            title=title,
            body=body,
            priority=NotificationPriority.HIGH,
        )
        return self.send_notification([device_id], payload)
