"""
android_tool.py

A GREEN tool for Android Client management in the Jarvis system.

Actions: devices, notify, broadcast.
All actions are read-only or notification-only (GREEN tier).
"""

from __future__ import annotations

from typing import Any

from tools.base_tool import BaseTool, ToolRequest, ToolResult


class AndroidTool(BaseTool):
    """Manages Android Client devices and notifications.

    Attributes:
        _android_manager: The AndroidManager providing device operations.
    """

    def __init__(self, android_manager: Any) -> None:
        """Initialise the tool.

        Args:
            android_manager: An AndroidManager instance.
        """
        self._android_manager = android_manager

    @property
    def name(self) -> str:
        return "android_client"

    @property
    def description(self) -> str:
        return "Manage Android devices: list devices, send notifications, broadcast messages."

    def run(self, request: ToolRequest) -> ToolResult:
        """Handle an Android Client request.

        Args:
            request: The request with input_data containing:
                - action (str): The operation to perform.
                - Other fields depend on the action.

        Returns:
            A ToolResult with the outcome.
        """
        action = str(request.input_data.get("action", "devices")).strip().lower()

        dispatch = {
            "devices": self._devices,
            "notify": self._notify,
            "broadcast": self._broadcast,
        }

        handler = dispatch.get(action)
        if handler is None:
            return self.fail(
                f"Unknown action '{action}'. "
                "Use: devices, notify, broadcast."
            )
        return handler(request)

    def _devices(self, request: ToolRequest) -> ToolResult:
        """List registered Android devices."""
        if self._android_manager is None:
            return self.fail("Android manager not available.")

        status = self._android_manager.get_connection_status()
        total = status.get("total_devices", 0)
        active = status.get("active_devices", 0)
        devices = status.get("devices", [])

        if not devices:
            return self.ok("No Android devices registered.")

        lines = [f"Android Devices ({active}/{total} active):", ""]
        for d in devices:
            status_cls = "●" if d.get("last_seen") else "○"
            lines.append(
                f"  {status_cls} {d['device_id']} ({d['platform']}) "
                f"— registered {d.get('registered_at', '?')[:10]}"
            )

        return self.ok("\n".join(lines))

    def _notify(self, request: ToolRequest) -> ToolResult:
        """Send a push notification to a specific device or all devices."""
        if self._android_manager is None:
            return self.fail("Android manager not available.")

        title = str(request.input_data.get("title", "")).strip()
        body = str(request.input_data.get("body", "")).strip()
        device_id = str(request.input_data.get("device_id", "")).strip()

        if not title or not body:
            return self.fail("Both 'title' and 'body' are required.")

        from android.models import NotificationPayload, NotificationPriority

        payload = NotificationPayload(
            title=title,
            body=body,
            priority=NotificationPriority.HIGH,
        )

        if device_id:
            result = self._android_manager.notifications.send_notification(
                [device_id], payload
            )
        else:
            # Broadcast to all active devices.
            result = self._android_manager.broadcast_task_completion(
                task_name=title,
                status=body,
            )

        sent = result.get("sent", 0)
        return self.ok(f"Notification sent to {sent} device(s).")

    def _broadcast(self, request: ToolRequest) -> ToolResult:
        """Broadcast a message to all registered devices."""
        if self._android_manager is None:
            return self.fail("Android manager not available.")

        title = str(request.input_data.get("title", "Jarvis Alert")).strip()
        body = str(request.input_data.get("body", "")).strip()

        if not body:
            return self.fail("'body' is required for broadcast.")

        result = self._android_manager.broadcast_task_completion(
            task_name=title,
            status=body,
        )

        sent = result.get("sent", 0)
        return self.ok(f"Broadcast sent to {sent} device(s).")
