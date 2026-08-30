"""
device_store.py

SQLite-backed store for Android device registrations.

Responsibilities:
    - Register and unregister devices.
    - List devices by user or active status.
    - Track last_seen timestamps.

Does NOT:
    - Send push notifications (see notifications.py).
    - Process remote commands (see remote_commands.py).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from android.models import DeviceRegistration

logger = logging.getLogger(__name__)

# In-memory store — simple and sufficient for the device registry.
# Devices are a small, transient set; SQLite would be overkill.
_devices: dict[str, DeviceRegistration] = {}


def register_device(
    device_id: str,
    fcm_token: str,
    user_id: str = "default",
    platform: str = "android",
) -> DeviceRegistration:
    """Register or update a device.

    If the device already exists, its FCM token and last_seen are updated.

    Args:
        device_id: Unique device identifier.
        fcm_token: Firebase Cloud Messaging token.
        user_id: The Jarvis user this device belongs to.
        platform: Device platform.

    Returns:
        The DeviceRegistration record.
    """
    now = datetime.now(timezone.utc)
    existing = _devices.get(device_id)
    if existing is not None:
        # Update token and last_seen.
        updated = DeviceRegistration(
            device_id=device_id,
            fcm_token=fcm_token,
            user_id=user_id,
            platform=platform,
            registered_at=existing.registered_at,
            last_seen=now,
        )
        _devices[device_id] = updated
        logger.info("Updated device: %s", device_id)
        return updated

    registration = DeviceRegistration(
        device_id=device_id,
        fcm_token=fcm_token,
        user_id=user_id,
        platform=platform,
        registered_at=now,
        last_seen=now,
    )
    _devices[device_id] = registration
    logger.info("Registered device: %s (platform=%s)", device_id, platform)
    return registration


def unregister_device(device_id: str) -> bool:
    """Remove a device registration.

    Args:
        device_id: The device to unregister.

    Returns:
        True if the device was found and removed.
    """
    if device_id in _devices:
        del _devices[device_id]
        logger.info("Unregistered device: %s", device_id)
        return True
    return False


def list_devices(user_id: str | None = None) -> list[DeviceRegistration]:
    """Return all registered devices, optionally filtered by user.

    Args:
        user_id: If provided, only return devices for this user.

    Returns:
        A list of DeviceRegistration records.
    """
    devices = list(_devices.values())
    if user_id is not None:
        devices = [d for d in devices if d.user_id == user_id]
    return sorted(devices, key=lambda d: d.registered_at, reverse=True)


def get_device(device_id: str) -> DeviceRegistration | None:
    """Return a single device by ID.

    Args:
        device_id: The device to look up.

    Returns:
        The DeviceRegistration, or None if not found.
    """
    return _devices.get(device_id)


def update_last_seen(device_id: str) -> bool:
    """Update the last_seen timestamp for a device.

    Args:
        device_id: The device to update.

    Returns:
        True if the device was found and updated.
    """
    device = _devices.get(device_id)
    if device is None:
        return False

    updated = DeviceRegistration(
        device_id=device.device_id,
        fcm_token=device.fcm_token,
        user_id=device.user_id,
        platform=device.platform,
        registered_at=device.registered_at,
        last_seen=datetime.now(timezone.utc),
    )
    _devices[device_id] = updated
    return True


def get_active_devices() -> list[DeviceRegistration]:
    """Return devices seen within the last 7 days.

    Returns:
        A list of recently active DeviceRegistration records.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    return [
        d for d in _devices.values()
        if d.last_seen >= cutoff
    ]


def clear_all() -> None:
    """Remove all devices. Used for testing."""
    _devices.clear()
