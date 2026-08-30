"""
manager.py

Facade for the Jarvis Android Client backend.

Responsibilities:
    - Provide a single entry point for all Android-related operations.
    - Wrap device_store, notifications, and command_queue.
    - Route remote commands to the appropriate subsystem.
    - Broadcast approval requests and task completions.

Does NOT:
    - Implement business logic (delegates to existing managers).
    - Access the database directly.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from android.device_store import (
    get_active_devices,
    get_device,
    list_devices,
    register_device,
    unregister_device,
    update_last_seen,
)
from android.models import (
    CommandResponse,
    CommandStatus,
    NotificationPayload,
    NotificationPriority,
    RemoteCommandType,
)
from android.notifications import PushNotificationService
from android.remote_commands import RemoteCommandQueue

logger = logging.getLogger(__name__)


class AndroidManager:
    """Facade wrapping device management, notifications, and command queue.

    Attributes:
        notifications: The push notification service.
        command_queue: The remote command queue.
    """

    def __init__(self, orchestrator: Any = None) -> None:
        """Initialise the Android manager.

        Args:
            orchestrator: Optional JarvisOrchestrator for routing commands.
        """
        self.notifications = PushNotificationService()
        self.command_queue = RemoteCommandQueue()
        self._orchestrator = orchestrator

    def handle_device_registration(
        self,
        device_id: str,
        fcm_token: str,
        platform: str = "android",
        user_id: str = "default",
    ) -> dict[str, Any]:
        """Register or update a device.

        Args:
            device_id: Unique device identifier.
            fcm_token: Firebase Cloud Messaging token.
            platform: Device platform.
            user_id: The Jarvis user.

        Returns:
            The registration details.
        """
        registration = register_device(
            device_id=device_id,
            fcm_token=fcm_token,
            user_id=user_id,
            platform=platform,
        )
        return registration.to_dict()

    def handle_device_unregisteration(self, device_id: str) -> bool:
        """Unregister a device.

        Args:
            device_id: The device to remove.

        Returns:
            True if the device was found and removed.
        """
        return unregister_device(device_id)

    def broadcast_approval_request(
        self,
        request_id: str,
        action: str,
        details: str,
        tier: str,
    ) -> dict[str, Any]:
        """Send an approval request to all active devices.

        Args:
            request_id: The approval request ID.
            action: The action requiring approval.
            details: Human-readable details.
            tier: The security tier.

        Returns:
            Summary of notifications sent.
        """
        active = get_active_devices()
        if not active:
            return {"sent": 0, "reason": "no active devices"}

        total_sent = 0
        total_failed = 0
        for device in active:
            result = self.notifications.send_approval_request(
                device_id=device.fcm_token,
                request_id=request_id,
                action=action,
                details=details,
                tier=tier,
            )
            total_sent += result.get("sent", 0)
            total_failed += result.get("failed", 0)

        return {"sent": total_sent, "failed": total_failed, "devices": len(active)}

    def broadcast_task_completion(
        self,
        task_name: str,
        status: str,
    ) -> dict[str, Any]:
        """Send a task completion notification to all active devices.

        Args:
            task_name: Name of the completed task.
            status: The outcome.

        Returns:
            Summary of notifications sent.
        """
        active = get_active_devices()
        if not active:
            return {"sent": 0, "reason": "no active devices"}

        total_sent = 0
        for device in active:
            result = self.notifications.send_task_completion(
                device_id=device.fcm_token,
                task_name=task_name,
                status=status,
            )
            total_sent += result.get("sent", 0)

        return {"sent": total_sent, "devices": len(active)}

    def process_remote_command(
        self,
        device_id: str,
        command_type: str,
        payload: dict | None = None,
    ) -> CommandResponse:
        """Process a command from an Android device.

        Routes the command to the appropriate subsystem based on type.

        Args:
            device_id: The device sending the command.
            command_type: The command type (chat, workflow_approve, etc.).
            payload: Command-specific payload.

        Returns:
            The CommandResponse with the result.
        """
        # Enqueue the command.
        command = self.command_queue.enqueue_command(
            device_id=device_id,
            command_type=command_type,
            payload=payload,
        )

        # Update last_seen.
        update_last_seen(device_id)

        # Route to the appropriate subsystem.
        try:
            try:
                cmd_type = RemoteCommandType(command_type)
            except ValueError:
                self.command_queue.mark_failed(
                    command.command_id, f"Unknown command type: {command_type}"
                )
                return CommandResponse(
                    command_id=command.command_id,
                    status=CommandStatus.FAILED,
                    error=f"Unknown command type: {command_type}",
                )

            if cmd_type == RemoteCommandType.STATUS_QUERY:
                return self._handle_status_query(command.command_id)

            elif cmd_type == RemoteCommandType.CHAT:
                return self._handle_chat_command(command.command_id, payload or {})

            elif cmd_type == RemoteCommandType.WORKFLOW_APPROVE:
                return self._handle_workflow_approve(command.command_id, payload or {})

            elif cmd_type == RemoteCommandType.WORKFLOW_CANCEL:
                return self._handle_workflow_cancel(command.command_id, payload or {})

        except Exception as exc:
            self.command_queue.mark_failed(command.command_id, str(exc))
            return CommandResponse(
                command_id=command.command_id,
                status=CommandStatus.FAILED,
                error=str(exc),
            )

    def get_connection_status(self) -> dict[str, Any]:
        """Return the status of all registered devices.

        Returns:
            A dict with device counts and last-seen times.
        """
        all_devices = list_devices()
        active = get_active_devices()
        return {
            "total_devices": len(all_devices),
            "active_devices": len(active),
            "devices": [d.to_dict() for d in all_devices],
        }

    def get_pending_commands(self, device_id: str) -> list[dict]:
        """Get pending commands for a device.

        Args:
            device_id: The device to check.

        Returns:
            A list of pending command dicts.
        """
        commands = self.command_queue.get_pending_commands(device_id)
        return [c.to_dict() for c in commands]

    def acknowledge_command(
        self,
        command_id: str,
        status: str = "completed",
        result: dict | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Acknowledge command completion.

        Args:
            command_id: The command to acknowledge.
            status: "completed" or "failed".
            result: Optional result data.
            error: Optional error message.

        Returns:
            The acknowledgement result.
        """
        if status == "failed" or error:
            self.command_queue.mark_failed(command_id, error or "Failed")
        else:
            self.command_queue.mark_completed(command_id, result)

        return {"command_id": command_id, "acknowledged": True}

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _handle_status_query(self, command_id: str) -> CommandResponse:
        """Handle a status query command."""
        result = {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Include subsystem status if orchestrator is available.
        if self._orchestrator is not None:
            result["subsystems"] = {
                "memory": getattr(self._orchestrator, "_memory_manager", None) is not None,
                "ai": getattr(self._orchestrator, "_reasoning", None) is not None,
                "goals": getattr(self._orchestrator, "_goal_manager", None) is not None,
            }

        self.command_queue.mark_completed(command_id, result)
        return CommandResponse(
            command_id=command_id,
            status=CommandStatus.COMPLETED,
            result=result,
        )

    def _handle_chat_command(
        self, command_id: str, payload: dict
    ) -> CommandResponse:
        """Handle a chat command from the Android device."""
        message = payload.get("message", "")
        if not message:
            self.command_queue.mark_failed(command_id, "No message provided")
            return CommandResponse(
                command_id=command_id,
                status=CommandStatus.FAILED,
                error="No message provided",
            )

        if self._orchestrator is None:
            self.command_queue.mark_failed(command_id, "Orchestrator not available")
            return CommandResponse(
                command_id=command_id,
                status=CommandStatus.FAILED,
                error="Orchestrator not available",
            )

        try:
            from core.request_models import JarvisRequest

            request = JarvisRequest(user_input=message)
            response = self._orchestrator.handle_request(request)
            result = {"response": response.message or "", "success": response.success}
            self.command_queue.mark_completed(command_id, result)
            return CommandResponse(
                command_id=command_id,
                status=CommandStatus.COMPLETED,
                result=result,
            )
        except Exception as exc:
            self.command_queue.mark_failed(command_id, str(exc))
            return CommandResponse(
                command_id=command_id,
                status=CommandStatus.FAILED,
                error=str(exc),
            )

    def _handle_workflow_approve(
        self, command_id: str, payload: dict
    ) -> CommandResponse:
        """Handle a workflow approval command."""
        request_id = payload.get("request_id", "")
        if not request_id:
            self.command_queue.mark_failed(command_id, "No request_id provided")
            return CommandResponse(
                command_id=command_id,
                status=CommandStatus.FAILED,
                error="No request_id provided",
            )

        if self._orchestrator is None:
            self.command_queue.mark_failed(command_id, "Orchestrator not available")
            return CommandResponse(
                command_id=command_id,
                status=CommandStatus.FAILED,
                error="Orchestrator not available",
            )

        try:
            approvals = self._orchestrator.approvals
            if hasattr(approvals, "approve"):
                from approval.approval_models import ApprovalDecision

                decision = ApprovalDecision(
                    request_id=request_id,
                    approved=True,
                    decided_by="android_remote",
                )
                approvals.approve(decision)
                result = {"approved": True, "request_id": request_id}
                self.command_queue.mark_completed(command_id, result)
                return CommandResponse(
                    command_id=command_id,
                    status=CommandStatus.COMPLETED,
                    result=result,
                )

            self.command_queue.mark_failed(command_id, "Approval manager not available")
            return CommandResponse(
                command_id=command_id,
                status=CommandStatus.FAILED,
                error="Approval manager not available",
            )
        except Exception as exc:
            self.command_queue.mark_failed(command_id, str(exc))
            return CommandResponse(
                command_id=command_id,
                status=CommandStatus.FAILED,
                error=str(exc),
            )

    def _handle_workflow_cancel(
        self, command_id: str, payload: dict
    ) -> CommandResponse:
        """Handle a workflow cancel command."""
        request_id = payload.get("request_id", "")
        if not request_id:
            self.command_queue.mark_failed(command_id, "No request_id provided")
            return CommandResponse(
                command_id=command_id,
                status=CommandStatus.FAILED,
                error="No request_id provided",
            )

        if self._orchestrator is None:
            self.command_queue.mark_failed(command_id, "Orchestrator not available")
            return CommandResponse(
                command_id=command_id,
                status=CommandStatus.FAILED,
                error="Orchestrator not available",
            )

        try:
            approvals = self._orchestrator.approvals
            if hasattr(approvals, "decline"):
                from approval.approval_models import ApprovalDecision

                decision = ApprovalDecision(
                    request_id=request_id,
                    approved=False,
                    decided_by="android_remote",
                )
                approvals.decline(decision)
                result = {"cancelled": True, "request_id": request_id}
                self.command_queue.mark_completed(command_id, result)
                return CommandResponse(
                    command_id=command_id,
                    status=CommandStatus.COMPLETED,
                    result=result,
                )

            self.command_queue.mark_failed(command_id, "Approval manager not available")
            return CommandResponse(
                command_id=command_id,
                status=CommandStatus.FAILED,
                error="Approval manager not available",
            )
        except Exception as exc:
            self.command_queue.mark_failed(command_id, str(exc))
            return CommandResponse(
                command_id=command_id,
                status=CommandStatus.FAILED,
                error=str(exc),
            )
