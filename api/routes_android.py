"""
routes_android.py

Android Client endpoints for the Jarvis API.

Responsibilities:
    - POST /api/android/register — register device with FCM token.
    - POST /api/android/unregister — unregister device.
    - GET  /api/android/devices — list registered devices.
    - POST /api/android/command — send a remote command.
    - GET  /api/android/poll — poll for pending notifications/commands.
    - POST /api/android/ack — acknowledge command completion.

Does NOT:
    - Implement business logic (delegates to AndroidManager).
    - Manage authentication (handled by auth.py dependency).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/android", tags=["android"])


def _get_android_manager() -> Any:
    """Lazy-import and return the global AndroidManager."""
    from api.app import get_android_manager

    return get_android_manager()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class DeviceRegisterRequest(BaseModel):
    """Request body for POST /api/android/register."""

    device_id: str = Field(..., min_length=1)
    fcm_token: str = Field(..., min_length=1)
    platform: str = Field(default="android")


class DeviceUnregisterRequest(BaseModel):
    """Request body for POST /api/android/unregister."""

    device_id: str = Field(..., min_length=1)


class RemoteCommandRequest(BaseModel):
    """Request body for POST /api/android/command."""

    command_type: str = Field(
        ...,
        description="chat, workflow_approve, workflow_cancel, status_query",
    )
    payload: dict[str, Any] = Field(default_factory=dict)


class CommandAckRequest(BaseModel):
    """Request body for POST /api/android/ack."""

    command_id: str = Field(..., min_length=1)
    status: str = Field(default="completed")
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/register")
async def register_device(
    request: DeviceRegisterRequest,
    user: dict[str, Any] = Depends(get_current_user),
    android_manager: Any = Depends(_get_android_manager),
) -> dict[str, Any]:
    """Register an Android device with its FCM token."""
    if android_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Android manager not available",
        )

    try:
        result = android_manager.handle_device_registration(
            device_id=request.device_id,
            fcm_token=request.fcm_token,
            platform=request.platform,
            user_id=user.get("sub", "default"),
        )
        return {"status": "registered", "device": result}
    except Exception as exc:
        logger.error("Device registration failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {exc}",
        )


@router.post("/unregister")
async def unregister_device_endpoint(
    request: DeviceUnregisterRequest,
    user: dict[str, Any] = Depends(get_current_user),
    android_manager: Any = Depends(_get_android_manager),
) -> dict[str, Any]:
    """Unregister an Android device."""
    if android_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Android manager not available",
        )

    success = android_manager.handle_device_unregisteration(request.device_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device '{request.device_id}' not found",
        )
    return {"status": "unregistered", "device_id": request.device_id}


@router.get("/devices")
async def list_devices(
    user: dict[str, Any] = Depends(get_current_user),
    android_manager: Any = Depends(_get_android_manager),
) -> dict[str, Any]:
    """List all registered devices."""
    if android_manager is None:
        return {"devices": [], "total": 0}

    status_info = android_manager.get_connection_status()
    return status_info


@router.post("/command")
async def send_command(
    request: RemoteCommandRequest,
    user: dict[str, Any] = Depends(get_current_user),
    android_manager: Any = Depends(_get_android_manager),
) -> dict[str, Any]:
    """Send a remote command from an Android device.

    The device_id is extracted from the JWT token's 'sub' claim.
    """
    if android_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Android manager not available",
        )

    device_id = user.get("sub", "unknown")

    try:
        response = android_manager.process_remote_command(
            device_id=device_id,
            command_type=request.command_type,
            payload=request.payload,
        )
        return response.to_dict()
    except Exception as exc:
        logger.error("Command processing failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Command failed: {exc}",
        )


@router.get("/poll")
async def poll_commands(
    user: dict[str, Any] = Depends(get_current_user),
    android_manager: Any = Depends(_get_android_manager),
) -> dict[str, Any]:
    """Poll for pending commands for the requesting device.

    The device_id is extracted from the JWT token's 'sub' claim.
    """
    if android_manager is None:
        return {"commands": []}

    device_id = user.get("sub", "unknown")
    commands = android_manager.get_pending_commands(device_id)
    return {"commands": commands, "total": len(commands)}


@router.post("/ack")
async def acknowledge_command(
    request: CommandAckRequest,
    user: dict[str, Any] = Depends(get_current_user),
    android_manager: Any = Depends(_get_android_manager),
) -> dict[str, Any]:
    """Acknowledge command completion from an Android device."""
    if android_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Android manager not available",
        )

    try:
        result = android_manager.acknowledge_command(
            command_id=request.command_id,
            status=request.status,
            result=request.result,
            error=request.error,
        )
        return result
    except Exception as exc:
        logger.error("Command ack failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Acknowledgement failed: {exc}",
        )
