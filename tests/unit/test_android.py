"""
test_android.py

Unit tests for the Jarvis Android Client backend.

Covers:
    - Device registration, listing, unregistration
    - Notification payload creation (mocked Firebase)
    - Command queue enqueue, poll, complete, expire
    - Remote command routing (chat → orchestrator, approve → workflow engine)
    - Manager integration (broadcast approval, task completion)
    - TTL expiration of old commands
    - Android API endpoints

Run with:
    pytest tests/unit/test_android.py -v
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from android.device_store import clear_all
from android.models import (
    CommandResponse,
    CommandStatus,
    DeviceRegistration,
    NotificationPayload,
    NotificationPriority,
    RemoteCommand,
    RemoteCommandType,
)
from android.notifications import PushNotificationService
from android.remote_commands import RemoteCommandQueue, COMMAND_TTL_SECONDS
from android.manager import AndroidManager
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_device_store():
    """Clear the device store before each test."""
    clear_all()
    yield
    clear_all()


@pytest.fixture()
def mock_orchestrator():
    """Create a mock JarvisOrchestrator."""
    from core.request_models import JarvisResponse

    orchestrator = MagicMock()
    orchestrator.handle_request.return_value = JarvisResponse(
        success=True,
        message="Test response",
    )
    mock_approvals = MagicMock()
    orchestrator.approvals = mock_approvals
    return orchestrator


@pytest.fixture()
def android_manager(mock_orchestrator):
    """Create an AndroidManager with mocked orchestrator."""
    return AndroidManager(orchestrator=mock_orchestrator)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    """Tests for Android data models."""

    def test_device_registration_defaults(self):
        """DeviceRegistration has sensible defaults."""
        reg = DeviceRegistration(device_id="d1", fcm_token="tok1")
        assert reg.device_id == "d1"
        assert reg.fcm_token == "tok1"
        assert reg.platform == "android"
        assert reg.registered_at is not None
        assert reg.last_seen is not None

    def test_device_registration_to_dict(self):
        """DeviceRegistration serialises correctly."""
        reg = DeviceRegistration(device_id="d1", fcm_token="tok1")
        d = reg.to_dict()
        assert d["device_id"] == "d1"
        assert d["fcm_token"] == "tok1"
        assert "registered_at" in d

    def test_notification_payload(self):
        """NotificationPayload creates correctly."""
        payload = NotificationPayload(
            title="Test",
            body="Hello",
            data={"key": "value"},
            priority=NotificationPriority.HIGH,
        )
        assert payload.title == "Test"
        assert payload.priority == NotificationPriority.HIGH
        d = payload.to_dict()
        assert d["title"] == "Test"
        assert d["data"]["key"] == "value"

    def test_remote_command(self):
        """RemoteCommand creates correctly."""
        cmd = RemoteCommand(
            command_id="c1",
            command_type=RemoteCommandType.CHAT,
            payload={"message": "hello"},
        )
        assert cmd.command_id == "c1"
        assert cmd.command_type == RemoteCommandType.CHAT
        d = cmd.to_dict()
        assert d["command_type"] == "chat"

    def test_command_response(self):
        """CommandResponse creates correctly."""
        resp = CommandResponse(
            command_id="c1",
            status=CommandStatus.COMPLETED,
            result={"ok": True},
        )
        assert resp.status == CommandStatus.COMPLETED
        d = resp.to_dict()
        assert d["status"] == "completed"
        assert d["result"]["ok"] is True


# ---------------------------------------------------------------------------
# Device store tests
# ---------------------------------------------------------------------------


class TestDeviceStore:
    """Tests for device registration store."""

    def test_register_device(self):
        """Registering a device returns a registration."""
        from android.device_store import register_device

        reg = register_device("d1", "token1", user_id="user1")
        assert reg.device_id == "d1"
        assert reg.fcm_token == "token1"
        assert reg.user_id == "user1"

    def test_register_updates_existing(self):
        """Re-registering updates the FCM token."""
        from android.device_store import register_device, get_device

        register_device("d1", "old_token")
        register_device("d1", "new_token")
        device = get_device("d1")
        assert device is not None
        assert device.fcm_token == "new_token"

    def test_unregister_device(self):
        """Unregistering removes the device."""
        from android.device_store import register_device, unregister_device, get_device

        register_device("d1", "token1")
        assert unregister_device("d1") is True
        assert get_device("d1") is None

    def test_unregister_nonexistent(self):
        """Unregistering a nonexistent device returns False."""
        from android.device_store import unregister_device

        assert unregister_device("nonexistent") is False

    def test_list_devices(self):
        """Listing devices returns all registered devices."""
        from android.device_store import register_device, list_devices

        register_device("d1", "token1")
        register_device("d2", "token2")
        devices = list_devices()
        assert len(devices) == 2

    def test_list_devices_by_user(self):
        """Listing devices filters by user_id."""
        from android.device_store import register_device, list_devices

        register_device("d1", "token1", user_id="alice")
        register_device("d2", "token2", user_id="bob")
        devices = list_devices(user_id="alice")
        assert len(devices) == 1
        assert devices[0].user_id == "alice"

    def test_get_device(self):
        """Getting a device by ID returns it."""
        from android.device_store import register_device, get_device

        register_device("d1", "token1")
        device = get_device("d1")
        assert device is not None
        assert device.device_id == "d1"

    def test_get_active_devices(self):
        """Active devices are those seen within 7 days."""
        from android.device_store import register_device, get_active_devices

        register_device("d1", "token1")
        active = get_active_devices()
        assert len(active) == 1

    def test_update_last_seen(self):
        """Updating last_seen refreshes the timestamp."""
        from android.device_store import register_device, update_last_seen, get_device

        register_device("d1", "token1")
        old_seen = get_device("d1").last_seen
        time.sleep(0.01)
        update_last_seen("d1")
        new_seen = get_device("d1").last_seen
        assert new_seen >= old_seen


# ---------------------------------------------------------------------------
# Notification tests
# ---------------------------------------------------------------------------


class TestNotifications:
    """Tests for push notification service."""

    def test_service_initialization(self):
        """PushNotificationService initializes without Firebase."""
        svc = PushNotificationService()
        # Without Firebase configured, available should be False.
        assert svc.available is False

    def test_send_notification_without_firebase(self):
        """Sending without Firebase logs and returns gracefully."""
        svc = PushNotificationService()
        payload = NotificationPayload(title="Test", body="Hello")
        result = svc.send_notification(["token1"], payload)
        assert result["sent"] == 0
        assert "firebase not configured" in result.get("reason", "")

    def test_send_approval_request_without_firebase(self):
        """Approval request without Firebase returns gracefully."""
        svc = PushNotificationService()
        result = svc.send_approval_request(
            "token1", "req-1", "delete file", "Delete report.txt", "yellow"
        )
        assert result["sent"] == 0

    def test_send_task_completion_without_firebase(self):
        """Task completion without Firebase returns gracefully."""
        svc = PushNotificationService()
        result = svc.send_task_completion("token1", "Build", "completed")
        assert result["sent"] == 0

    def test_send_alert_without_firebase(self):
        """Alert without Firebase returns gracefully."""
        svc = PushNotificationService()
        result = svc.send_alert("token1", "Alert", "Something happened")
        assert result["sent"] == 0

    def test_send_empty_device_list(self):
        """Sending to empty device list returns sent=0."""
        svc = PushNotificationService()
        payload = NotificationPayload(title="Test", body="Hello")
        result = svc.send_notification([], payload)
        assert result["sent"] == 0


# ---------------------------------------------------------------------------
# Command queue tests
# ---------------------------------------------------------------------------


class TestCommandQueue:
    """Tests for remote command queue."""

    def test_enqueue_command(self):
        """Enqueueing a command returns a RemoteCommand."""
        queue = RemoteCommandQueue()
        cmd = queue.enqueue_command("d1", "chat", {"message": "hello"})
        assert cmd.command_type == RemoteCommandType.CHAT
        assert cmd.payload["message"] == "hello"

    def test_get_pending_commands(self):
        """Pending commands are returned for the device."""
        queue = RemoteCommandQueue()
        queue.enqueue_command("d1", "chat")
        queue.enqueue_command("d1", "status_query")
        commands = queue.get_pending_commands("d1")
        assert len(commands) == 2

    def test_get_pending_empty(self):
        """No pending commands returns empty list."""
        queue = RemoteCommandQueue()
        commands = queue.get_pending_commands("d1")
        assert commands == []

    def test_mark_completed(self):
        """Marking a command completed removes it from pending."""
        queue = RemoteCommandQueue()
        cmd = queue.enqueue_command("d1", "chat")
        queue.mark_completed(cmd.command_id, {"response": "ok"})
        pending = queue.get_pending_commands("d1")
        assert len(pending) == 0
        resp = queue.get_response(cmd.command_id)
        assert resp is not None
        assert resp.status == CommandStatus.COMPLETED

    def test_mark_failed(self):
        """Marking a command failed records the error."""
        queue = RemoteCommandQueue()
        cmd = queue.enqueue_command("d1", "chat")
        queue.mark_failed(cmd.command_id, "Something went wrong")
        resp = queue.get_response(cmd.command_id)
        assert resp is not None
        assert resp.status == CommandStatus.FAILED
        assert "Something went wrong" in resp.error

    def test_ttl_expiration(self):
        """Commands expire after COMMAND_TTL_SECONDS."""
        queue = RemoteCommandQueue()
        cmd = queue.enqueue_command("d1", "chat")

        # Manually age the command.
        cmd.created_at = datetime.now(timezone.utc) - timedelta(
            seconds=COMMAND_TTL_SECONDS + 10
        )

        pending = queue.get_pending_commands("d1")
        assert len(pending) == 0
        # The expired command should be recorded as failed.
        resp = queue.get_response(cmd.command_id)
        assert resp is not None
        assert resp.status == CommandStatus.FAILED

    def test_clear(self):
        """Clearing removes all commands."""
        queue = RemoteCommandQueue()
        queue.enqueue_command("d1", "chat")
        queue.enqueue_command("d2", "status_query")
        queue.clear()
        assert queue.get_pending_commands("d1") == []
        assert queue.get_pending_commands("d2") == []


# ---------------------------------------------------------------------------
# Manager integration tests
# ---------------------------------------------------------------------------


class TestAndroidManager:
    """Tests for AndroidManager integration."""

    def test_handle_registration(self, android_manager):
        """Device registration returns registration details."""
        result = android_manager.handle_device_registration(
            "d1", "fcm_token_1", platform="android"
        )
        assert result["device_id"] == "d1"
        assert result["fcm_token"] == "fcm_token_1"

    def test_handle_unregistration(self, android_manager):
        """Unregistering a device returns True."""
        android_manager.handle_device_registration("d1", "token1")
        assert android_manager.handle_device_unregisteration("d1") is True

    def test_broadcast_approval_request(self, android_manager):
        """Broadcasting approval request returns device count."""
        android_manager.handle_device_registration("d1", "token1")
        result = android_manager.broadcast_approval_request(
            "req-1", "delete file", "Delete report.txt", "yellow"
        )
        # Firebase not configured, so sent=0 but devices=1.
        assert result["devices"] == 1

    def test_broadcast_task_completion(self, android_manager):
        """Broadcasting task completion returns device count."""
        android_manager.handle_device_registration("d1", "token1")
        result = android_manager.broadcast_task_completion("Build", "completed")
        assert result["devices"] == 1

    def test_process_status_query(self, android_manager):
        """Status query returns system status."""
        response = android_manager.process_remote_command(
            "d1", "status_query", {}
        )
        assert response.status == CommandStatus.COMPLETED
        assert "timestamp" in response.result

    def test_process_chat_command(self, android_manager):
        """Chat command routes to orchestrator."""
        response = android_manager.process_remote_command(
            "d1", "chat", {"message": "Hello Jarvis"}
        )
        assert response.status == CommandStatus.COMPLETED
        assert response.result["success"] is True

    def test_process_chat_no_message(self, android_manager):
        """Chat command without message fails."""
        response = android_manager.process_remote_command(
            "d1", "chat", {}
        )
        assert response.status == CommandStatus.FAILED
        assert "No message" in response.error

    def test_process_workflow_approve(self, android_manager):
        """Workflow approve routes to approval manager."""
        response = android_manager.process_remote_command(
            "d1", "workflow_approve", {"request_id": "req-1"}
        )
        assert response.status == CommandStatus.COMPLETED
        android_manager._orchestrator.approvals.approve.assert_called_once()

    def test_process_workflow_cancel(self, android_manager):
        """Workflow cancel routes to approval manager."""
        response = android_manager.process_remote_command(
            "d1", "workflow_cancel", {"request_id": "req-1"}
        )
        assert response.status == CommandStatus.COMPLETED
        android_manager._orchestrator.approvals.decline.assert_called_once()

    def test_process_unknown_command(self, android_manager):
        """Unknown command type fails."""
        response = android_manager.process_remote_command(
            "d1", "unknown_type", {}
        )
        assert response.status == CommandStatus.FAILED

    def test_get_connection_status(self, android_manager):
        """Connection status returns device info."""
        android_manager.handle_device_registration("d1", "token1")
        status = android_manager.get_connection_status()
        assert status["total_devices"] == 1
        assert status["active_devices"] == 1

    def test_acknowledge_command(self, android_manager):
        """Acknowledging a command records the result."""
        result = android_manager.acknowledge_command(
            "cmd-1", status="completed", result={"ok": True}
        )
        assert result["acknowledged"] is True

    def test_acknowledge_failure(self, android_manager):
        """Acknowledging a failure records the error."""
        result = android_manager.acknowledge_command(
            "cmd-1", status="failed", error="Something broke"
        )
        assert result["acknowledged"] is True


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def app(android_manager):
    """Create a test FastAPI app with Android manager."""
    import os
    os.environ["API_USERNAME"] = "testuser"
    os.environ["API_PASSWORD"] = "testpass"

    from api.app import create_app
    app = create_app(orchestrator=android_manager._orchestrator, android_manager=android_manager)
    return app


@pytest.fixture()
def client(app):
    """Create a TestClient."""
    return TestClient(app)


@pytest.fixture()
def auth_headers():
    """Return valid auth headers."""
    from api.auth import create_access_token
    token = create_access_token(data={"sub": "testuser"})
    return {"Authorization": f"Bearer {token}"}


class TestAndroidAPI:
    """Tests for Android API endpoints."""

    def test_register_device(self, client, auth_headers):
        """POST /api/android/register registers a device."""
        response = client.post(
            "/api/android/register",
            json={"device_id": "d1", "fcm_token": "token1"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "registered"

    def test_register_requires_auth(self, client):
        """Registration requires authentication."""
        response = client.post(
            "/api/android/register",
            json={"device_id": "d1", "fcm_token": "token1"},
        )
        assert response.status_code == 401

    def test_unregister_device(self, client, auth_headers, android_manager):
        """POST /api/android/unregister removes a device."""
        android_manager.handle_device_registration("d1", "token1")
        response = client.post(
            "/api/android/unregister",
            json={"device_id": "d1"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "unregistered"

    def test_unregister_not_found(self, client, auth_headers):
        """Unregistering nonexistent device returns 404."""
        response = client.post(
            "/api/android/unregister",
            json={"device_id": "nonexistent"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_list_devices(self, client, auth_headers, android_manager):
        """GET /api/android/devices lists devices."""
        android_manager.handle_device_registration("d1", "token1")
        response = client.get("/api/android/devices", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total_devices"] == 1

    def test_send_command(self, client, auth_headers):
        """POST /api/android/command sends a command."""
        response = client.post(
            "/api/android/command",
            json={"command_type": "status_query", "payload": {}},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"

    def test_poll_commands(self, client, auth_headers):
        """GET /api/android/poll returns pending commands."""
        response = client.get("/api/android/poll", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "commands" in data

    def test_ack_command(self, client, auth_headers):
        """POST /api/android/ack acknowledges a command."""
        response = client.post(
            "/api/android/ack",
            json={"command_id": "cmd-1", "status": "completed"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["acknowledged"] is True
