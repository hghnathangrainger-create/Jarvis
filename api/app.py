"""
app.py

FastAPI application factory for the Jarvis API.

Responsibilities:
    - Create the FastAPI app with all routers and middleware.
    - Hold references to the Jarvis subsystems needed by routes.
    - Provide dependency-injection accessors for the orchestrator,
      memory manager, goal manager, project manager, etc.

Does NOT:
    - Start the server (that's done via uvicorn in main.py).
    - Implement any business logic.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global subsystem references (set during startup, read by route deps).
# ---------------------------------------------------------------------------

_orchestrator: Any = None
_memory_manager: Any = None
_goal_manager: Any = None
_project_manager: Any = None
_plugin_registry: Any = None
_metrics_collector: Any = None
_android_manager: Any = None


def get_orchestrator() -> Any:
    """Return the global orchestrator instance."""
    return _orchestrator


def get_memory_manager() -> Any:
    """Return the MemoryManager, reading lazily from the orchestrator."""
    if _orchestrator is not None:
        return getattr(_orchestrator, "_memory_manager", None)
    return _memory_manager


def get_goal_manager() -> Any:
    """Return the GoalManager, reading lazily from the orchestrator."""
    if _orchestrator is not None:
        return getattr(_orchestrator, "_goal_manager", None)
    return _goal_manager


def get_project_manager() -> Any:
    """Return the ProjectManager, reading lazily from the orchestrator."""
    if _orchestrator is not None:
        return getattr(_orchestrator, "_project_manager", None)
    return _project_manager


def get_plugin_registry() -> Any:
    """Return the PluginRegistry, reading lazily from the orchestrator."""
    if _orchestrator is not None:
        return getattr(_orchestrator, "_plugin_registry", None)
    return _plugin_registry


def get_metrics_collector() -> Any:
    """Return the global MetricsCollector instance."""
    return _metrics_collector


def get_android_manager() -> Any:
    """Return the AndroidManager instance."""
    return _android_manager


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(orchestrator: Any = None, android_manager: Any = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        orchestrator: A fully-wired JarvisOrchestrator. When None, the
            app starts in degraded mode (subsystem endpoints return 503).
        android_manager: Optional AndroidManager for Android Client support.

    Returns:
        A configured FastAPI application ready to serve.
    """
    global _orchestrator, _android_manager  # noqa: PLW0603
    _orchestrator = orchestrator
    _android_manager = android_manager

    # Subsystem references are read lazily from the orchestrator,
    # not cached at app creation time. This lets tests modify
    # orchestrator attributes after create_app() and have routes
    # pick up the changes.

    app = FastAPI(
        title="Jarvis API",
        description="HTTP/WebSocket API for the Jarvis AI Operating System",
        version="0.1.0",
    )

    # CORS middleware — allow all origins for dev.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging middleware.
    @app.middleware("http")
    async def log_requests(request: Request, call_next: Any) -> Any:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        # Log to the observability system.
        if _orchestrator is not None and hasattr(_orchestrator, "_logger"):
            logger_obj = _orchestrator._logger
            if logger_obj is not None and hasattr(logger_obj, "emit"):
                try:
                    from config.constants import EventOutcome

                    logger_obj.emit(
                        source="api",
                        action_type="http_request",
                        outcome=EventOutcome.SUCCESS,
                        detail=f"{request.method} {request.url.path} -> {response.status_code} {duration_ms}ms",
                        duration_ms=duration_ms,
                    )
                except Exception:
                    pass

        logger.info(
            "%s %s -> %d (%dms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    # Global exception handler.
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error", "code": "error"},
        )

    # Register routers.
    from api.routes_chat import router as chat_router
    from api.routes_memory import router as memory_router
    from api.routes_workflow import router as workflow_router
    from api.routes_goals import router as goals_router
    from api.routes_plugins import router as plugins_router
    from api.routes_system import router as system_router

    app.include_router(chat_router)
    app.include_router(memory_router)
    app.include_router(workflow_router)
    app.include_router(goals_router)
    app.include_router(plugins_router)
    app.include_router(system_router)

    # WebSocket endpoint.
    from api.websocket import websocket_endpoint

    app.websocket("/api/ws")(websocket_endpoint)

    # Auth routes.
    from api.routes_auth import router as auth_router

    app.include_router(auth_router)

    # Android Client routes.
    from api.routes_android import router as android_router

    app.include_router(android_router)

    # Dashboard routes.
    from dashboard.routes import mount_dashboard

    mount_dashboard(app)

    return app
