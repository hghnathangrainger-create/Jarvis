"""
routes_security.py

Security endpoints for the Jarvis API.

Responsibilities:
    - GET /api/security/approvals — list pending approvals (authenticated)
    - POST /api/security/approve/{request_id} — approve a request
    - POST /api/security/deny/{request_id} — deny a request
    - GET /api/security/events — recent security events
    - GET /api/security/stats — injection detection stats
    - POST /api/security/check — test a string for injection

Does NOT:
    - Implement security logic (delegates to SecurityManagerV2).
    - Require no authentication (all endpoints are protected).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from api.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/security", tags=["security"])

# Global reference to the security manager (set during startup)
_security_manager: Any = None


def set_security_manager(mgr: Any) -> None:
    """Set the global security manager reference."""
    global _security_manager  # noqa: PLW0603
    _security_manager = mgr


def get_security_manager() -> Any:
    """Return the global security manager reference."""
    return _security_manager


@router.get("/approvals")
async def list_approvals(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """List pending approval requests."""
    if _security_manager is None:
        return {"error": "Security manager not available"}

    pending = _security_manager.get_pending_approvals()
    return {
        "approvals": [req.to_dict() for req in pending],
        "count": len(pending),
    }


@router.post("/approve/{request_id}")
async def approve_request(
    request_id: str,
    response: str | None = None,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Approve a pending security request."""
    if _security_manager is None:
        return {"error": "Security manager not available"}

    success = _security_manager.approve(request_id, response)
    if success:
        return {"status": "approved", "request_id": request_id}
    return {"error": "Request not found or not pending"}


@router.post("/deny/{request_id}")
async def deny_request(
    request_id: str,
    reason: str = "Denied via API",
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Deny a pending security request."""
    if _security_manager is None:
        return {"error": "Security manager not available"}

    success = _security_manager.deny(request_id, reason)
    if success:
        return {"status": "denied", "request_id": request_id, "reason": reason}
    return {"error": "Request not found or not pending"}


@router.get("/events")
async def list_events(
    limit: int = 50,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """List recent security events."""
    if _security_manager is None:
        return {"error": "Security manager not available"}

    events = _security_manager.get_security_events(limit=limit)
    return {
        "events": [event.to_dict() for event in events],
        "count": len(events),
    }


@router.get("/stats")
async def injection_stats(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Get injection detection statistics."""
    if _security_manager is None:
        return {"error": "Security manager not available"}

    return _security_manager.get_injection_stats()


@router.post("/check")
async def check_injection(
    text: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Test a string for prompt injection."""
    if _security_manager is None:
        return {"error": "Security manager not available"}

    result = _security_manager.check_input(text)
    return result.to_dict()
