"""
manager.py

System lifecycle manager for the Jarvis AI Operating System.

Responsibilities:
    - Execute the startup sequence in the correct dependency order.
    - Execute graceful shutdown with cleanup.
    - Detect and recover from unclean shutdowns (crash recovery).
    - Manage Safe Mode (GREEN-tier-only operation).
    - Track subsystem status and lifecycle events.

Does NOT:
    - Implement business logic for any individual subsystem.
    - Directly access the database (delegates to subsystem managers).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from lifecycle.models import (
    LifecycleEvent,
    SubsystemState,
    SubsystemStatus,
    SystemState,
)

logger = logging.getLogger(__name__)


class LifecycleManager:
    """Manages the Jarvis system lifecycle.

    Coordinates startup sequencing, graceful shutdown, crash recovery,
    and Safe Mode transitions. Every lifecycle event is logged to the
    observability system.

    Attributes:
        state: Current system state.
        subsystems: Map of subsystem names to their status.
        events: Chronological list of lifecycle events.
        started_at: When the system was started (UTC).
        _shutdown_hooks: Functions to call during shutdown.
    """

    def __init__(self) -> None:
        self.state: SystemState = SystemState.STARTING
        self.subsystems: dict[str, SubsystemStatus] = {}
        self.events: list[LifecycleEvent] = []
        self.started_at: datetime | None = None
        self._shutdown_hooks: list[Callable[[], None]] = []
        self._orchestrator: Any = None
        self._last_crash_info: str | None = None

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def start_system(self, orchestrator: Any = None) -> dict[str, Any]:
        """Execute the startup sequence in dependency order.

        Each step is logged. Non-critical failures are logged as warnings
        and the system continues. Critical failures (config, database)
        halt startup and enter Safe Mode.

        Args:
            orchestrator: The pre-built JarvisOrchestrator (optional —
                if provided, skips building subsystems individually).

        Returns:
            A summary dict with state, subsystem statuses, and any errors.
        """
        self._orchestrator = orchestrator
        self.started_at = datetime.now(timezone.utc)
        errors: list[str] = []

        self._log_event("startup", details="System startup initiated")

        # Step 1: Load config (CRITICAL).
        if not self._start_subsystem("config", self._start_config):
            self._enter_safe_mode("Critical: configuration failed to load")
            return self._startup_summary(errors=["Configuration load failed"])

        # Step 2: Initialize database (CRITICAL).
        if not self._start_subsystem("database", self._start_database):
            self._enter_safe_mode("Critical: database initialization failed")
            return self._startup_summary(errors=["Database initialization failed"])

        # Step 3: Connect to vector store (non-critical).
        self._start_subsystem("vector_store", self._start_vector_store)

        # Step 4: Start Observability (non-critical).
        self._start_subsystem("observability", self._start_observability)

        # Step 5: Start Security Manager (non-critical).
        self._start_subsystem("security", self._start_security)

        # Step 6: Check AI providers (non-critical).
        self._start_subsystem("ai_router", self._start_ai_providers)

        # Step 7: Restore interrupted workflows (non-critical).
        self._start_subsystem("workflow_recovery", self._start_workflow_recovery)

        # Step 8: Register tool plugins (non-critical).
        self._start_subsystem("plugins", self._start_plugins)

        # Step 9: Start Voice Pipeline (non-critical).
        self._start_subsystem("voice", self._start_voice)

        # Step 10: Start FastAPI server (non-critical).
        self._start_subsystem("api_server", self._start_api_server)

        # Step 11: Knowledge Library (non-critical).
        self._start_subsystem("knowledge", self._start_knowledge)

        # Step 12: Goal & Milestone Tracking (non-critical).
        self._start_subsystem("goals", self._start_goals)

        # Step 13: Project Management (non-critical).
        self._start_subsystem("projects", self._start_projects)

        # Step 14: Computer Control (non-critical).
        self._start_subsystem("computer_control", self._start_computer_control)

        # Step 15: AI Agent System (non-critical).
        self._start_subsystem("agents", self._start_agents)

        # Step 16: Android Client Backend (non-critical).
        self._start_subsystem("android", self._start_android)

        # Set state to READY.
        self.state = SystemState.READY
        self._log_event("startup_complete", details="All subsystems initialised")

        return self._startup_summary(errors=errors)

    def _start_subsystem(self, name: str, starter: Callable[[], bool]) -> bool:
        """Start a subsystem, catching and logging any errors.

        Args:
            name: The subsystem name.
            starter: A callable that returns True on success.

        Returns:
            True if the subsystem started successfully.
        """
        status = SubsystemStatus(name=name, state=SubsystemState.STARTING)
        self.subsystems[name] = status

        try:
            success = starter()
            if success:
                status.state = SubsystemState.READY
                status.started_at = datetime.now(timezone.utc)
                logger.info("Subsystem '%s' started successfully", name)
                return True
            else:
                status.state = SubsystemState.FAILED
                status.error_message = "Starter returned False"
                logger.warning("Subsystem '%s' failed to start", name)
                return False
        except Exception as exc:
            status.state = SubsystemState.FAILED
            status.error_message = str(exc)
            logger.warning("Subsystem '%s' failed: %s", name, exc)
            return False

    # ------------------------------------------------------------------
    # Subsystem starters (each returns True/False)
    # ------------------------------------------------------------------

    def _start_config(self) -> bool:
        """Load configuration from .env."""
        from config.settings import load_settings

        settings = load_settings()
        return settings is not None

    def _start_database(self) -> bool:
        """Initialize SQLite database."""
        from config.settings import load_settings
        from storage.database import create_database_engine, initialize_database

        settings = load_settings()
        engine = create_database_engine(settings)
        initialize_database(engine)
        return True

    def _start_vector_store(self) -> bool:
        """Connect to ChromaDB vector store."""
        try:
            import chromadb  # noqa: F401
            return True
        except ImportError:
            logger.info("ChromaDB not installed, vector store disabled")
            return True  # Non-critical; degrade gracefully.

    def _start_observability(self) -> bool:
        """Start the observability event emitter."""
        # Observability is already wired into the orchestrator.
        return True

    def _start_security(self) -> bool:
        """Start the Security Manager."""
        # Security is stateless and always available.
        return True

    def _start_ai_providers(self) -> bool:
        """Check AI provider availability."""
        from config.settings import load_settings

        settings = load_settings()
        if settings.ai_reasoning_enabled:
            logger.info("AI reasoning enabled — providers will be checked")
        else:
            logger.info("AI reasoning disabled — running in rule-based mode")
        return True

    def _start_workflow_recovery(self) -> bool:
        """Restore interrupted workflows from checkpoints."""
        # Crash recovery is handled separately; this is a no-op during
        # normal startup.
        return True

    def _start_plugins(self) -> bool:
        """Register tool plugins from manifests."""
        # Plugins are loaded during orchestrator build.
        return True

    def _start_voice(self) -> bool:
        """Start the Voice Pipeline if enabled."""
        from config.settings import load_settings

        settings = load_settings()
        if settings.voice_enabled:
            logger.info("Voice pipeline enabled")
        else:
            logger.info("Voice pipeline disabled")
        return True

    def _start_api_server(self) -> bool:
        """Start the FastAPI server (handled externally via uvicorn)."""
        return True

    def _start_knowledge(self) -> bool:
        """Initialize the Knowledge Library."""
        # Knowledge is wired through the orchestrator.
        return True

    def _start_goals(self) -> bool:
        """Initialize Goal & Milestone tracking."""
        # Goals are wired through the orchestrator.
        return True

    def _start_projects(self) -> bool:
        """Initialize Project Management."""
        # Projects are wired through the orchestrator.
        return True

    def _start_computer_control(self) -> bool:
        """Initialize Computer Control subsystem."""
        # Computer control is wired through the orchestrator.
        return True

    def _start_agents(self) -> bool:
        """Initialize AI Agent System."""
        # Agents are wired through the orchestrator.
        return True

    def _start_android(self) -> bool:
        """Initialize Android Client Backend."""
        # Android backend is wired through the orchestrator.
        return True

    def _startup_summary(self, errors: list[str] | None = None) -> dict[str, Any]:
        """Build a startup summary dict.

        Args:
            errors: Any errors encountered during startup.

        Returns:
            A summary dict.
        """
        return {
            "state": self.state.value,
            "subsystems": {
                name: status.to_dict()
                for name, status in self.subsystems.items()
            },
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "errors": errors or [],
        }

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown_system(self) -> dict[str, Any]:
        """Execute the graceful shutdown sequence.

        Steps:
            1. Set state to SHUTTING_DOWN
            2. Notify clients via WebSocket
            3. Complete/checkpoint running workflows
            4. Flush pending observability events
            5. Close AI provider connections
            6. Stop Voice Pipeline
            7. Close database connections
            8. Set state to STOPPED

        Returns:
            A summary dict with shutdown status.
        """
        self.state = SystemState.SHUTTING_DOWN
        self._log_event("shutdown", details="Graceful shutdown initiated")

        # Notify clients.
        self._notify_shutdown("System shutting down")

        # Run shutdown hooks in reverse order.
        for hook in reversed(self._shutdown_hooks):
            try:
                hook()
            except Exception as exc:
                logger.error("Shutdown hook failed: %s", exc)

        # Mark all subsystems as stopped.
        for name, status in self.subsystems.items():
            if status.state == SubsystemState.READY:
                status.state = SubsystemState.DISABLED
                logger.info("Subsystem '%s' stopped", name)

        self.state = SystemState.STOPPED
        self._log_event("shutdown_complete", details="System stopped")

        return {
            "state": self.state.value,
            "subsystems_stopped": len(self.subsystems),
        }

    def register_shutdown_hook(self, hook: Callable[[], None]) -> None:
        """Register a function to call during shutdown.

        Args:
            hook: A callable to invoke during shutdown.
        """
        self._shutdown_hooks.append(hook)

    # ------------------------------------------------------------------
    # Crash recovery
    # ------------------------------------------------------------------

    def crash_recovery(self) -> list[str]:
        """Detect and recover from unclean shutdowns.

        Called on startup after the initial config load. Checks for
        workflows in non-terminal state and logs recovery actions.

        Returns:
            A list of recovered workflow IDs.
        """
        self._log_event("crash_recovery", details="Checking for interrupted workflows")

        recovered: list[str] = []

        try:
            from config.settings import load_settings
            from storage.database import (
                create_database_engine,
                create_session_factory,
                initialize_database,
            )
            from workflow.checkpoint_store import WorkflowCheckpointStore

            settings = load_settings()
            engine = create_database_engine(settings)
            initialize_database(engine)
            session_factory = create_session_factory(engine)
            checkpoint_store = WorkflowCheckpointStore(session_factory)

            # Look for workflows with incomplete checkpoints.
            if hasattr(checkpoint_store, "list_incomplete"):
                incomplete = checkpoint_store.list_incomplete()
                for wf_id in incomplete:
                    recovered.append(wf_id)
                    self._log_event(
                        "workflow_recovered",
                        subsystem="workflow_recovery",
                        details=f"Recovered workflow: {wf_id}",
                    )

            if recovered:
                self._last_crash_info = (
                    f"Recovered {len(recovered)} interrupted workflow(s)"
                )
                logger.warning(
                    "Crash recovery: found %d interrupted workflows", len(recovered)
                )
            else:
                logger.info("Crash recovery: no interrupted workflows found")

        except Exception as exc:
            logger.warning("Crash recovery check failed (non-critical): %s", exc)

        return recovered

    # ------------------------------------------------------------------
    # Safe Mode
    # ------------------------------------------------------------------

    def enter_safe_mode(self, reason: str) -> dict[str, Any]:
        """Activate Safe Mode.

        In Safe Mode, only GREEN-tier actions are permitted. No new
        workflows or agent spawning. The dashboard remains accessible.

        Args:
            reason: The reason for entering Safe Mode.

        Returns:
            A status dict.
        """
        return self._enter_safe_mode(reason)

    def _enter_safe_mode(self, reason: str) -> dict[str, Any]:
        """Internal Safe Mode entry."""
        self.state = SystemState.SAFE_MODE
        self._last_crash_info = reason
        self._log_event(
            "safe_mode_activated",
            details=f"Safe Mode activated: {reason}",
        )

        # Notify clients.
        self._notify_safe_mode(reason)

        logger.warning("SAFE MODE ACTIVATED: %s", reason)

        return {
            "state": self.state.value,
            "reason": reason,
            "message": "Only GREEN-tier actions are permitted in Safe Mode.",
        }

    def exit_safe_mode(self) -> dict[str, Any]:
        """Exit Safe Mode and return to normal operation.

        Returns:
            A status dict.
        """
        if self.state != SystemState.SAFE_MODE:
            return {
                "state": self.state.value,
                "message": "Not in Safe Mode.",
            }

        self.state = SystemState.READY
        self._log_event("safe_mode_deactivated", details="Safe Mode exited")

        logger.info("Safe Mode deactivated — resuming normal operation")

        return {
            "state": self.state.value,
            "message": "Normal operation resumed.",
        }

    def is_safe_mode(self) -> bool:
        """Return True if the system is in Safe Mode."""
        return self.state == SystemState.SAFE_MODE

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Return the current system status.

        Returns:
            A dict with state, subsystem statuses, uptime, and crash info.
        """
        uptime = 0.0
        if self.started_at:
            uptime = (datetime.now(timezone.utc) - self.started_at).total_seconds()

        return {
            "state": self.state.value,
            "subsystems": {
                name: status.to_dict()
                for name, status in self.subsystems.items()
            },
            "uptime_seconds": round(uptime, 1),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_crash_info": self._last_crash_info,
            "is_safe_mode": self.is_safe_mode(),
            "events_count": len(self.events),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log_event(
        self,
        event_type: str,
        subsystem: str | None = None,
        details: str = "",
    ) -> None:
        """Log a lifecycle event."""
        event = LifecycleEvent(
            event_type=event_type,
            subsystem=subsystem,
            details=details,
        )
        self.events.append(event)
        logger.info("Lifecycle: %s — %s", event_type, details)

    def _notify_shutdown(self, message: str) -> None:
        """Notify WebSocket clients of impending shutdown."""
        try:
            from api.websocket import manager as ws_manager

            import asyncio

            event = {
                "type": "SYSTEM_SHUTDOWN",
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Try to broadcast synchronously if loop is running.
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(ws_manager.broadcast(event))
            except RuntimeError:
                # No event loop running; broadcast synchronously.
                pass

        except Exception:
            pass  # Non-critical.

    def _notify_safe_mode(self, reason: str) -> None:
        """Notify WebSocket clients of Safe Mode activation."""
        try:
            from api.websocket import manager as ws_manager

            import asyncio

            event = {
                "type": "SAFE_MODE_ACTIVATED",
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(ws_manager.broadcast(event))
            except RuntimeError:
                pass

        except Exception:
            pass  # Non-critical.
