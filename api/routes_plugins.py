"""
routes_plugins.py

Plugin endpoints for the Jarvis API.

Responsibilities:
    - GET  /api/plugins — list installed plugins.
    - POST /api/plugins/{id}/enable — enable a plugin.
    - POST /api/plugins/{id}/disable — disable a plugin.

Does NOT:
    - Implement plugin loading (delegates to PluginRegistry).
    - Manage authentication (handled by auth.py dependency).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


def _get_plugin_registry() -> Any:
    """Lazy-import and return the global PluginRegistry."""
    from api.app import get_plugin_registry

    return get_plugin_registry()


@router.get("")
async def list_plugins(
    user: dict[str, Any] = Depends(get_current_user),
    plugin_registry: Any = Depends(_get_plugin_registry),
) -> dict[str, Any]:
    """List all installed plugins."""
    if plugin_registry is None:
        return {"plugins": [], "total": 0}

    try:
        plugins = plugin_registry.list_plugins()
        return {
            "plugins": [p.to_dict() for p in plugins],
            "total": len(plugins),
        }
    except Exception as exc:
        logger.error("Failed to list plugins: %s", exc)
        return {"plugins": [], "total": 0, "error": str(exc)}


@router.post("/{plugin_id}/enable")
async def enable_plugin(
    plugin_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    plugin_registry: Any = Depends(_get_plugin_registry),
) -> dict[str, Any]:
    """Enable a plugin."""
    if plugin_registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plugin registry not available",
        )

    try:
        success = plugin_registry.enable(plugin_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plugin '{plugin_id}' not found",
            )
        return {"status": "enabled", "plugin_id": plugin_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to enable plugin: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enable plugin: {exc}",
        )


@router.post("/{plugin_id}/disable")
async def disable_plugin(
    plugin_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    plugin_registry: Any = Depends(_get_plugin_registry),
) -> dict[str, Any]:
    """Disable a plugin."""
    if plugin_registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plugin registry not available",
        )

    try:
        success = plugin_registry.disable(plugin_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plugin '{plugin_id}' not found",
            )
        return {"status": "disabled", "plugin_id": plugin_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to disable plugin: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disable plugin: {exc}",
        )
