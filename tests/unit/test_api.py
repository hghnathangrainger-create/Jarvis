"""
test_api.py

Unit tests for the Jarvis FastAPI API server.

Covers:
    - Login flow (valid/invalid credentials, token generation, token expiry)
    - All endpoints return 401 without valid token (except health + login)
    - Chat endpoint with mocked orchestrator
    - Memory endpoints with mocked memory manager
    - Workflow approval endpoint
    - System status endpoint
    - WebSocket connection and event broadcasting
    - CORS headers
    - Error handling (bad request body, missing resources, permission denied)

Run with:
    pytest tests/unit/test_api.py -v
"""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_orchestrator():
    """Create a mock JarvisOrchestrator for API tests."""
    from core.request_models import JarvisRequest, JarvisResponse

    orchestrator = MagicMock()
    orchestrator.handle_request.return_value = JarvisResponse(
        success=True,
        message="Test response from Jarvis.",
    )

    # Mock approvals.
    mock_approvals = MagicMock()
    mock_approvals.list_pending.return_value = []
    orchestrator.approvals = mock_approvals

    # Mock logger.
    mock_logger = MagicMock()
    mock_logger.emit.return_value = "event-123"
    orchestrator._logger = mock_logger

    # Mock memory manager.
    mock_memory = MagicMock()
    orchestrator._memory_manager = mock_memory

    # Mock goal manager.
    mock_goals = MagicMock()
    orchestrator._goal_manager = mock_goals

    # Mock tracer.
    mock_tracer = MagicMock()
    orchestrator._tracer = mock_tracer

    return orchestrator


@pytest.fixture()
def mock_memory_manager():
    """Create a mock MemoryManager."""
    from memory.episodic_memory import MemoryRecord
    from datetime import datetime, timezone

    manager = MagicMock()

    record = MemoryRecord(
        id=1,
        content="Test memory content",
        source="api",
        session_id=None,
        category="general",
        created_at=datetime.now(timezone.utc),
    )
    manager.list_recent.return_value = [record]
    manager.list_by_category.return_value = [record]
    manager.search.return_value = [record]
    manager.save.return_value = record
    manager.forget.return_value = True
    manager.get.return_value = record

    return manager


@pytest.fixture()
def app(mock_orchestrator, mock_memory_manager):
    """Create a test FastAPI app with mocked dependencies."""
    import os
    os.environ["API_USERNAME"] = "testuser"
    os.environ["API_PASSWORD"] = "testpass"

    from api.app import create_app
    from api.routes_system import set_lifecycle_manager

    # Clear any lifecycle manager set by other test modules.
    set_lifecycle_manager(None)

    mock_orchestrator._memory_manager = mock_memory_manager
    app = create_app(orchestrator=mock_orchestrator)
    app.state.test_client = True
    return app


@pytest.fixture()
def client(app):
    """Create a TestClient from the app."""
    return TestClient(app)


@pytest.fixture()
def auth_headers():
    """Return valid auth headers with a fresh token."""
    from api.auth import create_access_token

    token = create_access_token(data={"sub": "testuser"})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestLogin:
    """Tests for the login endpoint."""

    def test_login_valid_credentials(self, client):
        """Valid credentials return a JWT token."""
        response = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "testpass"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_invalid_credentials(self, client):
        """Invalid credentials return 401."""
        response = client.post(
            "/api/auth/login",
            json={"username": "wrong", "password": "wrong"},
        )
        assert response.status_code == 401

    def test_login_missing_body(self, client):
        """Missing required fields return 422."""
        response = client.post("/api/auth/login", json={})
        assert response.status_code == 422

    def test_token_expiry(self):
        """Expired tokens are rejected."""
        from api.auth import create_access_token, verify_token

        token = create_access_token(
            data={"sub": "testuser"},
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(Exception):
            verify_token(token)


class TestAuth:
    """Tests for authentication enforcement on protected endpoints."""

    def test_protected_endpoint_no_token(self, client):
        """Endpoints return 401 without a token."""
        response = client.get("/api/memory")
        assert response.status_code == 401

    def test_protected_endpoint_invalid_token(self, client):
        """Endpoints return 401 with an invalid token."""
        headers = {"Authorization": "Bearer invalid-token-12345"}
        response = client.get("/api/memory", headers=headers)
        assert response.status_code == 401

    def test_protected_endpoint_valid_token(self, client, auth_headers):
        """Endpoints work with a valid token."""
        response = client.get("/api/memory", headers=auth_headers)
        assert response.status_code == 200

    def test_health_check_no_auth(self, client):
        """System status endpoint does NOT require authentication."""
        response = client.get("/api/system/status")
        assert response.status_code == 200

    def test_login_no_auth_required(self, client):
        """Login endpoint does NOT require authentication."""
        response = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "testpass"},
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Chat tests
# ---------------------------------------------------------------------------


class TestChat:
    """Tests for the chat endpoint."""

    def test_chat_success(self, client, auth_headers):
        """Chat endpoint returns a response."""
        response = client.post(
            "/api/chat",
            json={"message": "Hello Jarvis"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["response"] == "Test response from Jarvis."
        assert "trace_id" in data

    def test_chat_empty_message(self, client, auth_headers):
        """Chat endpoint rejects empty messages."""
        response = client.post(
            "/api/chat",
            json={"message": ""},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_chat_no_auth(self, client):
        """Chat endpoint requires authentication."""
        response = client.post(
            "/api/chat",
            json={"message": "Hello"},
        )
        assert response.status_code == 401

    def test_chat_orchestrator_exception(self, client, auth_headers, mock_orchestrator):
        """Chat handles orchestrator exceptions gracefully."""
        mock_orchestrator.handle_request.side_effect = RuntimeError("AI failed")
        response = client.post(
            "/api/chat",
            json={"message": "Test"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "error" in data["response"].lower() or "AI failed" in data["response"]


# ---------------------------------------------------------------------------
# Memory tests
# ---------------------------------------------------------------------------


class TestMemory:
    """Tests for the memory endpoints."""

    def test_list_memories(self, client, auth_headers):
        """List memories returns a list."""
        response = client.get("/api/memory", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "memories" in data
        assert len(data["memories"]) == 1

    def test_list_memories_with_category(self, client, auth_headers):
        """List memories with category filter."""
        response = client.get(
            "/api/memory?category=general", headers=auth_headers
        )
        assert response.status_code == 200

    def test_search_memories(self, client, auth_headers):
        """Search memories returns results."""
        response = client.get(
            "/api/memory/search?q=test", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "memories" in data

    def test_search_empty_query(self, client, auth_headers):
        """Search with empty query returns 422."""
        response = client.get("/api/memory/search?q=", headers=auth_headers)
        assert response.status_code == 422

    def test_create_memory(self, client, auth_headers):
        """Create memory returns 201."""
        response = client.post(
            "/api/memory",
            json={"content": "New memory", "category": "general"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["content"] == "Test memory content"

    def test_delete_memory(self, client, auth_headers):
        """Delete memory returns 204."""
        response = client.delete("/api/memory/1", headers=auth_headers)
        assert response.status_code == 204

    def test_delete_memory_not_found(self, client, auth_headers, mock_memory_manager):
        """Delete non-existent memory returns 404."""
        mock_memory_manager.forget.return_value = False
        response = client.delete("/api/memory/999", headers=auth_headers)
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Workflow tests
# ---------------------------------------------------------------------------


class TestWorkflow:
    """Tests for workflow endpoints."""

    def test_list_workflows(self, client, auth_headers):
        """List workflows returns a list."""
        response = client.get("/api/workflows", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data

    def test_get_workflow(self, client, auth_headers):
        """Get workflow by ID."""
        response = client.get(
            "/api/workflows/test-id", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == "test-id"


# ---------------------------------------------------------------------------
# Goals / Projects tests
# ---------------------------------------------------------------------------


class TestGoals:
    """Tests for goal and project endpoints."""

    def test_list_goals(self, client, auth_headers, mock_orchestrator):
        """List goals returns a list."""
        mock_goals = MagicMock()
        mock_goals.list_active_goals.return_value = []
        mock_orchestrator._goal_manager = mock_goals

        response = client.get("/api/goals", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "goals" in data

    def test_create_goal(self, client, auth_headers, mock_orchestrator):
        """Create a goal."""
        mock_goals = MagicMock()
        mock_goal = MagicMock()
        mock_goal.id = 1
        mock_goal.title = "Test Goal"
        mock_goal.description = ""
        mock_goal.status = "active"
        mock_goal.priority = "medium"
        mock_goals.create_goal.return_value = mock_goal
        mock_orchestrator._goal_manager = mock_goals

        response = client.post(
            "/api/goals",
            json={"title": "Test Goal", "priority": "medium"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Test Goal"

    def test_list_projects(self, client, auth_headers):
        """List projects returns a list."""
        response = client.get("/api/projects", headers=auth_headers)
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# System status tests
# ---------------------------------------------------------------------------


class TestSystemStatus:
    """Tests for system endpoints."""

    def test_health_check(self, client):
        """Health check returns 200 without auth."""
        response = client.get("/api/system/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "subsystems" in data
        assert "uptime_seconds" in data

    def test_providers(self, client, auth_headers):
        """Provider status returns a list."""
        response = client.get("/api/system/providers", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        assert "ai_reasoning_enabled" in data

    def test_metrics(self, client, auth_headers):
        """Metrics endpoint returns data."""
        response = client.get("/api/system/metrics", headers=auth_headers)
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Plugin tests
# ---------------------------------------------------------------------------


class TestPlugins:
    """Tests for plugin endpoints."""

    def test_list_plugins(self, client, auth_headers):
        """List plugins returns a list."""
        response = client.get("/api/plugins", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "plugins" in data


# ---------------------------------------------------------------------------
# CORS tests
# ---------------------------------------------------------------------------


class TestCORS:
    """Tests for CORS headers."""

    def test_cors_preflight(self, client):
        """CORS preflight returns allowed headers."""
        response = client.options(
            "/api/chat",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers


# ---------------------------------------------------------------------------
# WebSocket tests
# ---------------------------------------------------------------------------


class TestWebSocket:
    """Tests for WebSocket connection and event broadcasting."""

    def test_connection_manager_connect_disconnect(self):
        """ConnectionManager tracks connections correctly."""
        from api.websocket import ConnectionManager

        mgr = ConnectionManager()
        assert mgr.active_connections == 0

        ws = MagicMock()
        mgr._connections.append(ws)
        assert mgr.active_connections == 1

        mgr.disconnect(ws)
        assert mgr.active_connections == 0

    def test_event_buffering(self):
        """Events are buffered for catch-up."""
        import asyncio
        from api.websocket import ConnectionManager

        mgr = ConnectionManager()
        event = {"type": "test", "data": "hello"}

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(mgr.broadcast(event))
        finally:
            loop.close()
        assert mgr.buffered_events == 1

    def test_broadcast_rejects_failed_connections(self):
        """Failed connections are removed during broadcast."""
        import asyncio
        from api.websocket import ConnectionManager

        mgr = ConnectionManager()

        # Add a connection that will fail.
        good_ws = AsyncMock()
        bad_ws = AsyncMock()
        bad_ws.send_json.side_effect = Exception("disconnected")

        mgr._connections = [good_ws, bad_ws]

        event = {"type": "test"}
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(mgr.broadcast(event))
        finally:
            loop.close()

        assert bad_ws not in mgr._connections
        assert good_ws in mgr._connections


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling across endpoints."""

    def test_404_for_unknown_route(self, client):
        """Unknown routes return 404."""
        response = client.get("/api/nonexistent")
        assert response.status_code == 404

    def test_method_not_allowed(self, client, auth_headers):
        """Wrong HTTP method returns 405."""
        response = client.get("/api/chat", headers=auth_headers)
        assert response.status_code == 405

    def test_bad_json_body(self, client, auth_headers):
        """Malformed JSON returns 422."""
        response = client.post(
            "/api/chat",
            content="not json",
            headers={**auth_headers, "Content-Type": "application/json"},
        )
        assert response.status_code == 422
