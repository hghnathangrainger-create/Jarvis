"""
websocket.py

WebSocket hub for real-time event broadcasting in the Jarvis API.

Responsibilities:
    - Manage WebSocket connections from Dashboard and Android clients.
    - Broadcast events (workflow status changes, memory updates, etc.)
      to all connected clients.
    - Buffer the last 50 events so new connections can catch up.

Does NOT:
    - Implement business logic (events are broadcast from route handlers).
    - Manage authentication beyond the initial token query parameter.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# Maximum number of events to buffer for catch-up.
_MAX_BUFFER = 50


class ConnectionManager:
    """Manages WebSocket connections and broadcasts events.

    Tracks all connected clients, buffers recent events, and provides
    a broadcast method that sends events to every connected client.

    Attributes:
        _connections: Active WebSocket connections.
        _event_buffer: Ring buffer of recent events for catch-up.
    """

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._event_buffer: deque[dict[str, Any]] = deque(maxlen=_MAX_BUFFER)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection.

        Sends the buffered event history so the client can catch up.

        Args:
            websocket: The WebSocket connection to accept.
        """
        await websocket.accept()
        self._connections.append(websocket)
        logger.info("WebSocket client connected (%d total)", len(self._connections))

        # Send buffered events for catch-up.
        for event in self._event_buffer:
            try:
                await websocket.send_json(event)
            except Exception:
                break

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a disconnected WebSocket.

        Args:
            websocket: The WebSocket connection that disconnected.
        """
        if websocket in self._connections:
            self._connections.remove(websocket)
        logger.info("WebSocket client disconnected (%d total)", len(self._connections))

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Broadcast an event to all connected clients.

        The event is added to the ring buffer for future catch-up,
        then sent to every connected client. Failed sends silently
        remove the client.

        Additionally, if the event is an approval request, it is
        automatically pushed to all registered Android devices via FCM.

        Args:
            event: The event dict to broadcast. Should include at
                minimum "type", "timestamp", and "data" keys.
        """
        # Ensure timestamp is set.
        if "timestamp" not in event:
            event["timestamp"] = datetime.now(timezone.utc).isoformat()

        self._event_buffer.append(event)

        disconnected: list[WebSocket] = []
        for connection in self._connections:
            try:
                await connection.send_json(event)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)

        # Push approval requests to Android devices via FCM.
        event_type = event.get("type", "")
        if event_type in ("approval_request", "workflow_step_complete"):
            self._push_to_android(event)

    @property
    def active_connections(self) -> int:
        """Return the number of active connections."""
        return len(self._connections)

    @property
    def buffered_events(self) -> int:
        """Return the number of buffered events."""
        return len(self._event_buffer)

    def _push_to_android(self, event: dict[str, Any]) -> None:
        """Push an event to registered Android devices via FCM.

        This is a non-blocking, best-effort operation. If the Android
        manager is not available or Firebase is not configured, the
        push is silently skipped.

        Args:
            event: The event to push.
        """
        try:
            from api.app import get_android_manager

            android_mgr = get_android_manager()
            if android_mgr is None:
                return

            event_type = event.get("type", "")
            if event_type == "approval_request":
                data = event.get("data", {})
                android_mgr.broadcast_approval_request(
                    request_id=data.get("request_id", ""),
                    action=data.get("action", ""),
                    details=data.get("details", ""),
                    tier=data.get("tier", "yellow"),
                )
            elif event_type == "workflow_step_complete":
                data = event.get("data", {})
                android_mgr.broadcast_task_completion(
                    task_name=data.get("task_name", "workflow"),
                    status=data.get("status", "completed"),
                )
        except Exception as exc:
            logger.debug("Android push failed (non-critical): %s", exc)

    async def broadcast_system_event(self, event: dict[str, Any]) -> None:
        """Broadcast a system lifecycle event (shutdown, safe-mode, etc.).

        This is a convenience method for lifecycle manager to broadcast
        SYSTEM_SHUTDOWN and SAFE_MODE_ACTIVATED events.

        Args:
            event: The lifecycle event to broadcast.
        """
        await self.broadcast(event)


# Module-level singleton — created once at import time.
manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint handler.

    Authenticates via the 'token' query parameter, then enters a
    receive loop that keeps the connection alive. Clients can send
    ping messages; the server responds with pong.

    Args:
        websocket: The WebSocket connection from FastAPI.
    """
    # Optional: validate token from query params.
    token = websocket.query_params.get("token")
    if token:
        try:
            from api.auth import verify_token
            verify_token(token)
        except Exception:
            await websocket.close(code=4001, reason="Invalid token")
            return

    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo back pings.
            try:
                parsed = json.loads(data)
                if parsed.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except (json.JSONDecodeError, TypeError):
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
        manager.disconnect(websocket)
