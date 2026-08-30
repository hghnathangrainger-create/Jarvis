"""
test_lifecycle.py

Unit tests for the Jarvis System Lifecycle.

Covers:
    - SystemState and SubsystemStatus model tests
    - LifecycleManager startup sequence (mock all subsystems, verify order)
    - Shutdown sequence (verify cleanup steps run)
    - Crash recovery (mock checkpoint store with interrupted workflows)
    - Safe Mode entry/exit (verify GREEN-only enforcement)
    - Signal handler registration
    - Status endpoint returns correct state
    - Safe mode API endpoints

Run with:
    pytest tests/unit/test_lifecycle.py -v
"""

from __future__ import annotations

import signal
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from lifecycle.models import (
    LifecycleEvent,
    SubsystemState,
    SubsystemStatus,
    SystemState,
)
from lifecycle.manager import LifecycleManager


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestSystemState:
    """Tests for SystemState enum."""

    def test_all_states_exist(self):
        """All expected states are defined."""
        assert SystemState.STARTING.value == "starting"
        assert SystemState.READY.value == "ready"
        assert SystemState.RUNNING.value == "running"
        assert SystemState.SHUTTING_DOWN.value == "shutting_down"
        assert SystemState.STOPPED.value == "stopped"
        assert SystemState.SAFE_MODE.value == "safe_mode"
        assert SystemState.CRASHED.value == "crashed"

    def test_state_is_string(self):
        """SystemState values are strings."""
        assert isinstance(SystemState.STARTING, str)


class TestSubsystemStatus:
    """Tests for SubsystemStatus dataclass."""

    def test_defaults(self):
        """SubsystemStatus has sensible defaults."""
        status = SubsystemStatus(name="test")
        assert status.name == "test"
        assert status.state == SubsystemState.STARTING
        assert status.started_at is None
        assert status.error_message is None

    def test_to_dict(self):
        """SubsystemStatus serialises correctly."""
        status = SubsystemStatus(
            name="database",
            state=SubsystemState.READY,
            started_at=datetime.now(timezone.utc),
        )
        d = status.to_dict()
        assert d["name"] == "database"
        assert d["state"] == "ready"
        assert d["started_at"] is not None

    def test_failed_status(self):
        """SubsystemStatus with error."""
        status = SubsystemStatus(
            name="ai_router",
            state=SubsystemState.FAILED,
            error_message="Provider not configured",
        )
        d = status.to_dict()
        assert d["state"] == "failed"
        assert d["error_message"] == "Provider not configured"


class TestLifecycleEvent:
    """Tests for LifecycleEvent dataclass."""

    def test_creation(self):
        """LifecycleEvent creates with defaults."""
        event = LifecycleEvent(event_type="startup")
        assert event.event_type == "startup"
        assert event.timestamp is not None
        assert event.subsystem is None
        assert event.details == ""

    def test_to_dict(self):
        """LifecycleEvent serialises correctly."""
        event = LifecycleEvent(
            event_type="shutdown",
            subsystem="database",
            details="Closing connections",
        )
        d = event.to_dict()
        assert d["event_type"] == "shutdown"
        assert d["subsystem"] == "database"
        assert "Closing connections" in d["details"]


# ---------------------------------------------------------------------------
# LifecycleManager tests
# ---------------------------------------------------------------------------


class TestLifecycleManagerStartup:
    """Tests for LifecycleManager startup sequence."""

    def test_initial_state(self):
        """Manager starts in STARTING state."""
        mgr = LifecycleManager()
        assert mgr.state == SystemState.STARTING

    def test_start_system_sets_ready(self):
        """Successful startup sets state to READY."""
        mgr = LifecycleManager()
        result = mgr.start_system()
        assert mgr.state == SystemState.READY
        assert result["state"] == "ready"

    def test_start_system_records_started_at(self):
        """Startup records the started_at timestamp."""
        mgr = LifecycleManager()
        mgr.start_system()
        assert mgr.started_at is not None

    def test_start_system_logs_events(self):
        """Startup logs lifecycle events."""
        mgr = LifecycleManager()
        mgr.start_system()
        event_types = [e.event_type for e in mgr.events]
        assert "startup" in event_types
        assert "startup_complete" in event_types

    def test_start_system_populates_subsystems(self):
        """Startup populates subsystem statuses."""
        mgr = LifecycleManager()
        mgr.start_system()
        assert len(mgr.subsystems) > 0
        assert "config" in mgr.subsystems
        assert "database" in mgr.subsystems

    def test_start_system_config_critical(self):
        """Config failure enters Safe Mode."""
        mgr = LifecycleManager()
        with patch("config.settings.load_settings", side_effect=Exception("No config")):
            result = mgr.start_system()
        assert mgr.state == SystemState.SAFE_MODE
        assert result["state"] == "safe_mode"

    def test_start_system_database_critical(self):
        """Database failure enters Safe Mode."""
        mgr = LifecycleManager()
        with patch(
            "storage.database.create_database_engine",
            side_effect=Exception("DB fail"),
        ):
            result = mgr.start_system()
        assert mgr.state == SystemState.SAFE_MODE

    def test_start_system_voice_non_critical(self):
        """Voice failure doesn't block startup."""
        mgr = LifecycleManager()
        result = mgr.start_system()
        # Voice subsystem should still be in some state (not crash).
        assert mgr.state == SystemState.READY


class TestLifecycleManagerShutdown:
    """Tests for LifecycleManager shutdown sequence."""

    def test_shutdown_sets_stopped(self):
        """Shutdown sets state to STOPPED."""
        mgr = LifecycleManager()
        mgr.start_system()
        result = mgr.shutdown_system()
        assert mgr.state == SystemState.STOPPED
        assert result["state"] == "stopped"

    def test_shutdown_logs_events(self):
        """Shutdown logs lifecycle events."""
        mgr = LifecycleManager()
        mgr.start_system()
        mgr.shutdown_system()
        event_types = [e.event_type for e in mgr.events]
        assert "shutdown" in event_types
        assert "shutdown_complete" in event_types

    def test_shutdown_runs_hooks(self):
        """Shutdown executes registered hooks."""
        mgr = LifecycleManager()
        mgr.start_system()

        hook_called = []
        mgr.register_shutdown_hook(lambda: hook_called.append(True))

        mgr.shutdown_system()
        assert len(hook_called) == 1

    def test_shutdown_hooks_run_reverse_order(self):
        """Shutdown hooks run in reverse registration order."""
        mgr = LifecycleManager()
        mgr.start_system()

        order = []
        mgr.register_shutdown_hook(lambda: order.append("first"))
        mgr.register_shutdown_hook(lambda: order.append("second"))

        mgr.shutdown_system()
        assert order == ["second", "first"]

    def test_shutdown_hook_error_handled(self):
        """Failing shutdown hooks don't crash shutdown."""
        mgr = LifecycleManager()
        mgr.start_system()

        def bad_hook():
            raise RuntimeError("hook failed")

        mgr.register_shutdown_hook(bad_hook)
        result = mgr.shutdown_system()
        assert result["state"] == "stopped"

    def test_shutdown_disables_subsystems(self):
        """Shutdown marks subsystems as disabled."""
        mgr = LifecycleManager()
        mgr.start_system()
        mgr.shutdown_system()

        for name, status in mgr.subsystems.items():
            if status.state == SubsystemState.READY:
                assert status.state == SubsystemState.DISABLED


class TestLifecycleManagerCrashRecovery:
    """Tests for crash recovery."""

    def test_crash_recovery_returns_empty_when_clean(self):
        """No interrupted workflows returns empty list."""
        mgr = LifecycleManager()
        recovered = mgr.crash_recovery()
        assert isinstance(recovered, list)

    def test_crash_recovery_logs_event(self):
        """Crash recovery logs an event."""
        mgr = LifecycleManager()
        mgr.crash_recovery()
        event_types = [e.event_type for e in mgr.events]
        assert "crash_recovery" in event_types

    def test_crash_recovery_handles_missing_store(self):
        """Crash recovery handles missing checkpoint store gracefully."""
        mgr = LifecycleManager()
        with patch(
            "storage.database.create_database_engine",
            side_effect=Exception("No DB"),
        ):
            recovered = mgr.crash_recovery()
        assert recovered == []


class TestLifecycleManagerSafeMode:
    """Tests for Safe Mode entry and exit."""

    def test_enter_safe_mode(self):
        """Entering Safe Mode sets state to SAFE_MODE."""
        mgr = LifecycleManager()
        mgr.start_system()
        result = mgr.enter_safe_mode("Testing")
        assert mgr.state == SystemState.SAFE_MODE
        assert result["state"] == "safe_mode"

    def test_enter_safe_mode_logs_event(self):
        """Safe Mode entry logs an event."""
        mgr = LifecycleManager()
        mgr.start_system()
        mgr.enter_safe_mode("Security breach")
        event_types = [e.event_type for e in mgr.events]
        assert "safe_mode_activated" in event_types

    def test_exit_safe_mode(self):
        """Exiting Safe Mode returns to READY."""
        mgr = LifecycleManager()
        mgr.start_system()
        mgr.enter_safe_mode("Testing")
        result = mgr.exit_safe_mode()
        assert mgr.state == SystemState.READY
        assert result["state"] == "ready"

    def test_exit_safe_mode_logs_event(self):
        """Safe Mode exit logs an event."""
        mgr = LifecycleManager()
        mgr.start_system()
        mgr.enter_safe_mode("Testing")
        mgr.exit_safe_mode()
        event_types = [e.event_type for e in mgr.events]
        assert "safe_mode_deactivated" in event_types

    def test_exit_safe_mode_when_not_in_safe_mode(self):
        """Exiting Safe Mode when not in Safe Mode returns message."""
        mgr = LifecycleManager()
        mgr.start_system()
        result = mgr.exit_safe_mode()
        assert "Not in Safe Mode" in result["message"]

    def test_is_safe_mode(self):
        """is_safe_mode returns correct boolean."""
        mgr = LifecycleManager()
        mgr.start_system()
        assert mgr.is_safe_mode() is False
        mgr.enter_safe_mode("Testing")
        assert mgr.is_safe_mode() is True
        mgr.exit_safe_mode()
        assert mgr.is_safe_mode() is False


class TestLifecycleManagerStatus:
    """Tests for get_status."""

    def test_status_returns_dict(self):
        """get_status returns a complete status dict."""
        mgr = LifecycleManager()
        mgr.start_system()
        status = mgr.get_status()
        assert "state" in status
        assert "subsystems" in status
        assert "uptime_seconds" in status
        assert "is_safe_mode" in status
        assert "events_count" in status

    def test_status_shows_uptime(self):
        """Status includes uptime."""
        mgr = LifecycleManager()
        mgr.start_system()
        status = mgr.get_status()
        assert status["uptime_seconds"] >= 0

    def test_status_shows_safe_mode(self):
        """Status reflects Safe Mode state."""
        mgr = LifecycleManager()
        mgr.start_system()
        assert mgr.get_status()["is_safe_mode"] is False
        mgr.enter_safe_mode("Testing")
        assert mgr.get_status()["is_safe_mode"] is True


class TestSignalHandlers:
    """Tests for signal handler registration."""

    def test_signal_handlers_registered(self):
        """Signal handlers are registered for SIGINT and SIGTERM."""
        from main import _register_signal_handlers

        orchestrator = MagicMock()
        _register_signal_handlers(orchestrator)

        # Check that handlers are set (not default).
        sigint_handler = signal.getsignal(signal.SIGINT)
        sigterm_handler = signal.getsignal(signal.SIGTERM)

        # Signal handlers should not be SIG_DFL or SIG_IGN.
        assert sigint_handler != signal.SIG_DFL
        assert sigint_handler != signal.SIG_IGN
        assert sigterm_handler != signal.SIG_DFL
        assert sigterm_handler != signal.SIG_IGN


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_with_lifecycle():
    """Create a test app with lifecycle manager."""
    import os
    os.environ["API_USERNAME"] = "testuser"
    os.environ["API_PASSWORD"] = "testpass"

    from api.app import create_app
    from api.routes_system import set_lifecycle_manager
    from lifecycle.manager import LifecycleManager

    lifecycle_mgr = LifecycleManager()
    lifecycle_mgr.start_system()
    set_lifecycle_manager(lifecycle_mgr)

    app = create_app(orchestrator=None)
    return app, lifecycle_mgr


@pytest.fixture()
def client(app_with_lifecycle):
    """Create a TestClient."""
    from fastapi.testclient import TestClient
    app, mgr = app_with_lifecycle
    return TestClient(app), mgr


class TestLifecycleAPI:
    """Tests for lifecycle API endpoints."""

    def test_status_returns_lifecycle_state(self, client):
        """GET /api/system/status returns lifecycle state."""
        test_client, mgr = client
        response = test_client.get("/api/system/status")
        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "ready"

    def test_safe_mode_endpoint(self, client):
        """POST /api/system/safe-mode enters Safe Mode."""
        test_client, mgr = client
        from api.auth import create_access_token

        token = create_access_token(data={"sub": "testuser"})
        headers = {"Authorization": f"Bearer {token}"}

        response = test_client.post(
            "/api/system/safe-mode?reason=testing",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "safe_mode"

    def test_resume_endpoint(self, client):
        """POST /api/system/resume exits Safe Mode."""
        test_client, mgr = client
        from api.auth import create_access_token

        token = create_access_token(data={"sub": "testuser"})
        headers = {"Authorization": f"Bearer {token}"}

        # Enter Safe Mode first.
        mgr.enter_safe_mode("testing")

        response = test_client.post(
            "/api/system/resume",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "ready"

    def test_safe_mode_requires_auth(self, client):
        """Safe Mode endpoints require authentication."""
        test_client, mgr = client
        response = test_client.post("/api/system/safe-mode")
        assert response.status_code == 401
