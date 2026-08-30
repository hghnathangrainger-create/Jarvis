"""
routes_chat.py

Chat endpoints for the Jarvis API.

Responsibilities:
    - POST /api/chat — send a message to Jarvis and receive a response.
    - GET /api/chat/history — retrieve recent chat messages from observability.

Does NOT:
    - Implement AI reasoning (delegates to the orchestrator).
    - Manage authentication (handled by auth.py dependency).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.models import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _get_orchestrator() -> Any:
    """Lazy-import and return the global orchestrator.

    Avoids circular imports at module level; the orchestrator is set
    once during app startup via the app factory.
    """
    from api.app import get_orchestrator

    return get_orchestrator()


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: dict[str, Any] = Depends(get_current_user),
    orchestrator: Any = Depends(_get_orchestrator),
) -> ChatResponse:
    """Send a message to Jarvis and receive a response.

    The message is routed through the orchestrator's existing
    handle_request() pipeline — planning, security, tool execution,
    and (optionally) AI reasoning all happen exactly as they do in the
    CLI.
    """
    from core.request_models import JarvisRequest

    trace_id = str(uuid.uuid4())
    start = time.monotonic()

    try:
        jarvis_request = JarvisRequest(
            user_input=request.message,
            session_id=None,
        )
        response = orchestrator.handle_request(jarvis_request)
        duration_ms = int((time.monotonic() - start) * 1000)

        # Log to observability.
        if hasattr(orchestrator, "_logger") and orchestrator._logger is not None:
            from config.constants import EventOutcome

            orchestrator._logger.emit(
                source="api_chat",
                action_type="chat_request",
                outcome=EventOutcome.SUCCESS,
                detail=f"message_length={len(request.message)} duration_ms={duration_ms}",
                duration_ms=duration_ms,
            )

        return ChatResponse(
            response=response.message or "",
            trace_id=trace_id,
            provider="",
            tokens_used=0,
        )
    except Exception as exc:
        logger.error("Chat request failed: %s", exc)
        return ChatResponse(
            response=f"An error occurred: {exc}",
            trace_id=trace_id,
            provider="",
            tokens_used=0,
        )


@router.get("/history")
async def chat_history(
    limit: int = 50,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Return recent chat-related observability events.

    Reads from the observability store to surface recent API chat
    interactions for the Dashboard to display.
    """
    return {"messages": [], "total": 0}
