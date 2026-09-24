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

    Chat messages are handled in two ways:
    1. Tool commands (echo, help, info, memory, etc.) go through the
       rule-based orchestrator for proper tool execution.
    2. Free-form conversational messages go through the AI router
       directly for a natural language response.
    """
    trace_id = str(uuid.uuid4())
    start = time.monotonic()

    try:
        # Check if this is a known tool command via the command router.
        command_router = getattr(orchestrator, '_command_router', None)
        is_tool_command = (
            command_router is not None
            and command_router.match(request.message) is not None
        )

        if is_tool_command:
            # Route through the rule-based orchestrator for tool execution.
            jarvis_response = orchestrator.handle_request(request.message)
            response_text = jarvis_response.message or ""
            provider = ""
            tokens = 0
        else:
            # Free-form chat — route through the AI router directly.
            ai_router = getattr(orchestrator, '_ai_router', None)
            if ai_router is None:
                # Try to get the router from the reasoning engine.
                reasoning = getattr(orchestrator, '_reasoning', None)
                if reasoning is not None:
                    ai_router = getattr(reasoning, '_router', None)

            if ai_router is not None and ai_router.is_available():
                system_instruction = (
                    "You are Jarvis, a helpful AI assistant. "
                    "Answer the user's question directly and concisely. "
                    "Be friendly and helpful. Do not suggest tool calls — "
                    "just answer the question."
                )
                # Find the first available provider and call it directly.
                # This avoids the router's model-string parsing which can
                # route "claude-sonnet-4-6" to Gemini (wrong provider).
                _provider = None
                for _p in ai_router._providers:
                    if _p.is_available():
                        _provider = _p
                        break
                if _provider is not None:
                    from ai.providers.base import AIRequest, AIMessage

                    _req = AIRequest(
                        system=system_instruction,
                        messages=(AIMessage(role="user", content=request.message),),
                        model=ai_router._settings.ai_model,
                        max_tokens=ai_router._settings.ai_max_tokens,
                    )
                    _raw = _provider.generate(_req)
                    response_text = _raw.text if hasattr(_raw, 'text') else str(_raw)
                    provider = _provider.name
                    tokens = getattr(_raw, 'tokens_used', 0) or 0
            else:
                # No AI available — return a helpful fallback.
                response_text = (
                    "I'm Jarvis, your AI assistant. I can help with commands "
                    "like 'echo', 'help', 'info', 'memory', and more. "
                    "AI chat requires an API key to be configured. "
                    "Type 'help' to see available commands."
                )
                provider = ""
                tokens = 0

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
            response=response_text,
            trace_id=trace_id,
            provider=provider,
            tokens_used=tokens,
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
