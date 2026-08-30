"""
routes_system.py

System endpoints for the Jarvis API.

Responsibilities:
    - GET /api/system/status — system health (NO auth required).
    - GET /api/system/providers — AI provider status.
    - GET /api/system/metrics — observability metrics summary.

Does NOT:
    - Implement system health logic (delegates to existing subsystems).
    - Require authentication for the health check endpoint.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from api.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])

_start_time = time.time()


@router.get("/status")
async def system_status() -> dict[str, Any]:
    """System health check — NO authentication required.

    Returns subsystem availability, uptime, and version.
    """
    orchestrator = _safe_get_orchestrator()
    status_dict: dict[str, Any] = {
        "status": "ok",
        "version": "0.1.0",
        "uptime_seconds": round(time.time() - _start_time, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "subsystems": {},
    }

    # Check subsystem availability.
    if orchestrator is not None:
        status_dict["subsystems"] = {
            "ai_router": _has_attr(orchestrator, "_reasoning"),
            "memory": _has_attr(orchestrator, "_memory_manager"),
            "knowledge": _has_attr(orchestrator, "_knowledge_manager"),
            "goals": _has_attr(orchestrator, "_goal_manager"),
            "plugins": True,  # Always loaded at startup.
            "voice": False,  # Checked via settings.
            "computer_control": True,  # Always loaded.
            "observability": _has_attr(orchestrator, "_tracer"),
        }
    else:
        status_dict["status"] = "degraded"
        status_dict["subsystems"] = {k: False for k in [
            "ai_router", "memory", "knowledge", "goals",
            "plugins", "voice", "computer_control", "observability",
        ]}

    return status_dict


@router.get("/providers")
async def system_providers(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Return AI provider status."""
    orchestrator = _safe_get_orchestrator()
    providers = []

    if orchestrator is not None and hasattr(orchestrator, "_reasoning"):
        reasoning = orchestrator._reasoning
        if reasoning is not None and hasattr(reasoning, "_router"):
            router = reasoning._router
            if hasattr(router, "_providers"):
                for p in router._providers:
                    providers.append({
                        "name": type(p).__name__,
                        "available": True,
                    })

    return {
        "providers": providers,
        "ai_reasoning_enabled": (
            orchestrator is not None
            and hasattr(orchestrator, "_reasoning")
            and orchestrator._reasoning is not None
        ),
    }


@router.get("/metrics")
async def system_metrics(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Return observability metrics summary."""
    from api.app import get_metrics_collector

    metrics = get_metrics_collector()
    if metrics is None:
        return {"metrics": {}, "available": False}

    try:
        return {"metrics": metrics.get_summary(), "available": True}
    except Exception as exc:
        logger.error("Failed to get metrics: %s", exc)
        return {"metrics": {}, "available": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_get_orchestrator() -> Any:
    """Safely retrieve the orchestrator, returning None on failure."""
    try:
        from api.app import get_orchestrator
        return get_orchestrator()
    except Exception:
        return None


def _has_attr(obj: Any, attr: str) -> bool:
    """Check if an attribute exists and is not None."""
    return getattr(obj, attr, None) is not None
