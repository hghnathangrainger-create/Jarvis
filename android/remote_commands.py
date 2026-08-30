"""
remote_commands.py

Command queue for remote Android device control.

Responsibilities:
    - Queue commands from Android devices.
    - Poll for pending commands.
    - Track command completion/failure.
    - Expire commands after a TTL (5 minutes).

Does NOT:
    - Execute commands (see manager.py).
    - Manage device registrations (see device_store.py).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from android.models import (
    CommandResponse,
    CommandStatus,
    RemoteCommand,
    RemoteCommandType,
)

logger = logging.getLogger(__name__)

# Commands expire after 5 minutes if not processed.
COMMAND_TTL_SECONDS = 300


class RemoteCommandQueue:
    """In-memory command queue for remote device commands.

    Commands are stored per-device and expire after COMMAND_TTL_SECONDS.

    Attributes:
        _queues: Per-device command queues.
        _completed: Completed/failed command results.
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[RemoteCommand]] = {}
        self._completed: dict[str, CommandResponse] = {}

    def enqueue_command(
        self,
        device_id: str,
        command_type: RemoteCommandType | str,
        payload: dict | None = None,
    ) -> RemoteCommand:
        """Queue a command from an Android device.

        Args:
            device_id: The device sending the command.
            command_type: The type of command.
            payload: Command-specific payload data.

        Returns:
            The created RemoteCommand.
        """
        if isinstance(command_type, str):
            try:
                command_type = RemoteCommandType(command_type)
            except ValueError:
                # Store as a raw string; the manager will reject it later.
                pass

        command = RemoteCommand(
            command_id=str(uuid.uuid4()),
            command_type=command_type,
            payload=payload or {},
        )

        if device_id not in self._queues:
            self._queues[device_id] = []
        self._queues[device_id].append(command)

        logger.info(
            "Enqueued command %s from device %s: %s",
            command.command_id,
            device_id,
            command_type.value if hasattr(command_type, 'value') else command_type,
        )
        return command

    def get_pending_commands(self, device_id: str) -> list[RemoteCommand]:
        """Return pending (non-expired) commands for a device.

        Expired commands are automatically removed.

        Args:
            device_id: The device to check for commands.

        Returns:
            A list of pending RemoteCommand objects.
        """
        commands = self._queues.get(device_id, [])
        now = datetime.now(timezone.utc)

        # Filter out expired commands.
        valid = []
        expired = 0
        for cmd in commands:
            age = (now - cmd.created_at).total_seconds()
            if age > COMMAND_TTL_SECONDS:
                expired += 1
                # Record as failed due to timeout.
                self._completed[cmd.command_id] = CommandResponse(
                    command_id=cmd.command_id,
                    status=CommandStatus.FAILED,
                    error="Command expired (TTL exceeded)",
                )
            else:
                valid.append(cmd)

        if expired > 0:
            self._queues[device_id] = valid
            logger.info("Expired %d old commands for device %s", expired, device_id)

        return valid

    def mark_completed(
        self,
        command_id: str,
        result: dict | None = None,
    ) -> bool:
        """Mark a command as completed.

        Args:
            command_id: The command to complete.
            result: Optional result data.

        Returns:
            True if the command was found.
        """
        response = CommandResponse(
            command_id=command_id,
            status=CommandStatus.COMPLETED,
            result=result or {},
        )
        self._completed[command_id] = response
        self._remove_from_queues(command_id)
        logger.info("Command %s completed", command_id)
        return True

    def mark_failed(self, command_id: str, error: str) -> bool:
        """Mark a command as failed.

        Args:
            command_id: The command that failed.
            error: The error description.

        Returns:
            True if the command was found.
        """
        response = CommandResponse(
            command_id=command_id,
            status=CommandStatus.FAILED,
            error=error,
        )
        self._completed[command_id] = response
        self._remove_from_queues(command_id)
        logger.info("Command %s failed: %s", command_id, error)
        return True

    def get_response(self, command_id: str) -> CommandResponse | None:
        """Return the response for a completed/failed command.

        Args:
            command_id: The command to look up.

        Returns:
            The CommandResponse, or None if not found.
        """
        return self._completed.get(command_id)

    def _remove_from_queues(self, command_id: str) -> None:
        """Remove a command from all device queues."""
        for device_id, commands in self._queues.items():
            self._queues[device_id] = [
                c for c in commands if c.command_id != command_id
            ]

    def clear(self) -> None:
        """Clear all queues. Used for testing."""
        self._queues.clear()
        self._completed.clear()
